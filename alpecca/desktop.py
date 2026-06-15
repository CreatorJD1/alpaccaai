"""Her workstation: a desktop-like view she can tidy, within hard limits.

This is the file room of her home -- the "virtual workstation" where she can see
a desktop-like layout and organize files. Every capability here is bounded by her
constitution (`charter.py`), and the bounds are enforced *in code*, not merely
described in a prompt she could talk past:

  - She can only ever touch five roots: Desktop, Pictures, Music, Video, and a
    general files folder. Anything outside is invisible and unreachable.
  - She can list, move, and rename. She **cannot delete** -- there is no delete
    function in this module at all, by design. Deletion stays with the person.
  - Every path is resolved and checked to be *inside* an allowed root before any
    filesystem call, so neither a crafted name nor a symlink can escape.

So the room is real and useful (she can reorganize her own space) while being
incapable of the destructive or out-of-bounds actions the charter forbids. The
guard (`charter.file_action_allowed`) is consulted on every operation; this
module never works around it.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from alpecca import charter
from config import Files as FilesCfg


def _default_roots() -> dict:
    """Map the five allowed root names to real folders. Defaults to the standard
    user folders; each is overridable by env (e.g. ALPECCA_ROOT_PICTURES) so this
    works the same on any machine and is trivially pointed at a sandbox in tests.
    'general' defaults to the Documents folder."""
    home = Path(os.environ.get("ALPECCA_USER_HOME", str(Path.home())))
    mapping = {
        "desktop":  home / "Desktop",
        "pictures": home / "Pictures",
        "music":    home / "Music",
        "video":    home / "Videos",
        "general":  home / "Documents",
    }
    out = {}
    for name, default in mapping.items():
        out[name] = Path(os.environ.get(f"ALPECCA_ROOT_{name.upper()}", str(default)))
    return out


# Resolved once; tests pass their own roots in explicitly.
ROOTS = _default_roots()


@dataclass
class Entry:
    name: str
    is_dir: bool
    size: int

    def as_dict(self) -> dict:
        return {"name": self.name, "is_dir": self.is_dir, "size": self.size}


def _safe_under(root: Path, rel: str) -> Path | None:
    """Resolve `rel` under `root` and return it only if it stays inside `root`.
    This is the traversal/symlink guard: we resolve to a real absolute path and
    confirm `root` is one of its parents (or it is the root itself)."""
    try:
        base = root.resolve()
        target = (base / (rel or "")).resolve()
    except Exception:
        return None
    if target == base or base in target.parents:
        return target
    return None


def list_room(root: str, rel: str = "", roots: dict | None = None) -> dict:
    """List one allowed root (optionally a subfolder). Refuses unknown roots and
    any path that escapes the root. Read access is itself gated through the
    charter ('view'), so the allow-list is the single source of truth."""
    roots = roots or ROOTS
    ok, why = charter.file_action_allowed("view", root)
    if not ok:
        return {"ok": False, "error": why}
    base = roots.get(root)
    if base is None:
        return {"ok": False, "error": f"'{root}' isn't a room I can open."}
    target = _safe_under(base, rel)
    if target is None:
        return {"ok": False, "error": "that path is outside the room."}
    if not target.exists():
        return {"ok": True, "root": root, "rel": rel, "entries": []}
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            size = p.stat().st_size if p.is_file() else 0
        except Exception:
            size = 0
        entries.append(Entry(p.name, p.is_dir(), size).as_dict())
    return {"ok": True, "root": root, "rel": rel, "entries": entries}


def move(src_root: str, src_rel: str, dst_root: str, dst_rel: str = "",
         roots: dict | None = None) -> dict:
    """Move a file/folder from one allowed location to another. Gated on both
    ends; never overwrites; both sides must stay inside their roots. Returns a
    result dict; on any guard failure nothing on disk is touched."""
    roots = roots or ROOTS
    for r in (src_root, dst_root):
        ok, why = charter.file_action_allowed("move", r)
        if not ok:
            return {"ok": False, "error": why}
    src_base, dst_base = roots.get(src_root), roots.get(dst_root)
    if src_base is None or dst_base is None:
        return {"ok": False, "error": "one of those rooms isn't one I can open."}
    src = _safe_under(src_base, src_rel)
    dst_dir = _safe_under(dst_base, dst_rel)
    if src is None or dst_dir is None:
        return {"ok": False, "error": "that path is outside the room."}
    if not src.exists():
        return {"ok": False, "error": "there's nothing there to move."}
    dst = dst_dir / src.name
    if dst.exists():
        return {"ok": False, "error": "something with that name is already there."}
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    except Exception as e:
        return {"ok": False, "error": f"couldn't move it: {e}"}
    return {"ok": True, "moved": src.name, "to": f"{dst_root}/{dst_rel}".rstrip("/")}


def rename(root: str, rel: str, new_name: str, roots: dict | None = None) -> dict:
    """Rename within an allowed root. Gated; the new name is a single path
    component (no slashes -> can't relocate via rename); never overwrites."""
    roots = roots or ROOTS
    ok, why = charter.file_action_allowed("rename", root)
    if not ok:
        return {"ok": False, "error": why}
    base = roots.get(root)
    if base is None:
        return {"ok": False, "error": f"'{root}' isn't a room I can open."}
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        return {"ok": False, "error": "that isn't a valid name."}
    src = _safe_under(base, rel)
    if src is None or not src.exists():
        return {"ok": False, "error": "there's nothing there to rename."}
    dst = src.parent / new_name
    if dst.exists():
        return {"ok": False, "error": "something with that name is already there."}
    try:
        src.rename(dst)
    except Exception as e:
        return {"ok": False, "error": f"couldn't rename it: {e}"}
    return {"ok": True, "renamed": src.name, "to": new_name}


def search(query: str, roots: dict | None = None, limit: int = 40) -> dict:
    """Find files/folders whose name contains `query` (case-insensitive) across
    her allowed rooms -- so she can actually help you find something ("where's that
    invoice?") during cowork. Read-only and charter-gated per room. It never
    follows a symlink out of a room and skips anything that resolves outside its
    root, so the same hard sandbox as the rest of this module holds. Returns
    {ok, query, matches:[{root, rel, name, is_dir, size}], truncated}."""
    roots = roots or ROOTS
    q = (query or "").strip().lower()
    if not q:
        return {"ok": False, "error": "give me something to look for."}
    matches: list[dict] = []
    truncated = False
    for name in charter.ALLOWED_FILE_ROOTS:
        ok, _ = charter.file_action_allowed("view", name)
        if not ok:
            continue
        base = roots.get(name)
        if base is None:
            continue
        try:
            base_r = base.resolve()
        except Exception:
            continue
        if not base_r.exists():
            continue
        # os.walk does NOT follow symlinked directories by default, so we can't be
        # walked out of the room; the relative_to check below also drops any entry
        # that resolves outside it (e.g. a symlinked file).
        for dirpath, dirnames, filenames in os.walk(base_r):
            for entry in list(dirnames) + list(filenames):
                if q not in entry.lower():
                    continue
                full = Path(dirpath) / entry
                try:
                    real = full.resolve()
                    rel = real.relative_to(base_r)
                except Exception:
                    continue            # escaped the room -> ignore
                is_dir = full.is_dir()
                try:
                    size = full.stat().st_size if not is_dir else 0
                except Exception:
                    size = 0
                matches.append({"root": name, "rel": str(rel).replace("\\", "/"),
                                "name": entry, "is_dir": is_dir, "size": size})
                if len(matches) >= limit:
                    truncated = True
                    break
            if truncated:
                break
        if truncated:
            break
    return {"ok": True, "query": query, "matches": matches, "truncated": truncated}


def summarize(root: str, roots: dict | None = None) -> dict:
    """A grounded readout of one room: how many files and folders it holds, the
    total size, and a count by file kind (extension) -- the honest 'what's in
    Documents' answer. Read-only and charter-gated."""
    roots = roots or ROOTS
    ok, why = charter.file_action_allowed("view", root)
    if not ok:
        return {"ok": False, "error": why}
    base = roots.get(root)
    if base is None:
        return {"ok": False, "error": f"'{root}' isn't a room I can open."}
    try:
        base_r = base.resolve()
    except Exception:
        return {"ok": False, "error": "couldn't open that room."}
    files = folders = total = 0
    by_kind: dict[str, int] = {}
    if base_r.exists():
        for dirpath, dirnames, filenames in os.walk(base_r):
            folders += len(dirnames)
            for fn in filenames:
                files += 1
                ext = Path(fn).suffix.lower().lstrip(".") or "none"
                by_kind[ext] = by_kind.get(ext, 0) + 1
                try:
                    total += (Path(dirpath) / fn).stat().st_size
                except Exception:
                    pass
    top = dict(sorted(by_kind.items(), key=lambda kv: kv[1], reverse=True)[:8])
    return {"ok": True, "root": root, "files": files, "folders": folders,
            "total_bytes": total, "by_kind": top}


def overview(roots: dict | None = None) -> dict:
    """A desktop-like snapshot: each allowed room and how many items it holds.
    What the workstation view renders. Honest about what she can and can't do."""
    roots = roots or ROOTS
    rooms = []
    for name in charter.ALLOWED_FILE_ROOTS:
        listing = list_room(name, roots=roots)
        rooms.append({"root": name,
                      "count": len(listing.get("entries", [])),
                      "available": listing.get("ok", False)})
    return {
        "enabled": FilesCfg.ENABLED,
        "rooms": rooms,
        "can": list(charter.ALLOWED_FILE_ACTIONS),
        "cannot": list(charter.FORBIDDEN_FILE_ACTIONS),
        "note": "I can tidy these folders, but I can't delete anything -- that's yours.",
    }
