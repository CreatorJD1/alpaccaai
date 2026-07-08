"""Passive directory watchers that record names/counts only."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def parse_watch_dirs(spec: str) -> list[Path]:
    out: list[Path] = []
    for raw in (spec or "").replace("\n", ";").split(";"):
        raw = raw.strip().strip('"')
        if not raw:
            continue
        p = Path(os.path.expandvars(os.path.expanduser(raw)))
        if p.exists() and p.is_dir():
            out.append(p)
    return out


def snapshot(paths: Iterable[Path], *, max_files: int = 500) -> dict[str, dict]:
    max_files = max(1, int(max_files or 500))
    seen: dict[str, dict] = {}
    count = 0
    for root in paths:
        root = Path(root)
        if not root.exists() or not root.is_dir():
            continue
        try:
            walker = os.walk(root)
            for base, dirs, files in walker:
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))[:50]
                names = sorted(files) + sorted(dirs)
                for name in names:
                    if name.startswith("."):
                        continue
                    p = Path(base) / name
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    rel = str(p.relative_to(root))
                    key = f"{root.resolve()}::{rel}"
                    seen[key] = {
                        "root": str(root),
                        "name": name[:180],
                        "rel": rel[:260],
                        "is_dir": p.is_dir(),
                        "mtime": int(st.st_mtime),
                        "size": 0 if p.is_dir() else int(st.st_size),
                    }
                    count += 1
                    if count >= max_files:
                        return seen
        except OSError:
            continue
    return seen


def diff_snapshots(old: dict[str, dict], new: dict[str, dict], *, limit: int = 12) -> dict:
    old = old or {}
    new = new or {}
    added_keys = sorted(set(new) - set(old))
    removed_keys = sorted(set(old) - set(new))
    modified_keys = sorted(
        key for key in (set(old) & set(new))
        if old[key].get("mtime") != new[key].get("mtime")
        or old[key].get("size") != new[key].get("size")
    )

    def names(keys: list[str], source: dict[str, dict]) -> list[str]:
        return [str(source[k].get("name") or source[k].get("rel") or "")[:180] for k in keys[:limit]]

    return {
        "added": len(added_keys),
        "modified": len(modified_keys),
        "removed": len(removed_keys),
        "added_names": names(added_keys, new),
        "modified_names": names(modified_keys, new),
        "removed_names": names(removed_keys, old),
    }


class DirectoryWatcher:
    def __init__(self, paths: Iterable[Path], *, max_files: int = 500) -> None:
        self.paths = [Path(p) for p in paths]
        self.max_files = max_files
        self._last: dict[str, dict] | None = None

    def poll(self) -> dict:
        current = snapshot(self.paths, max_files=self.max_files)
        if self._last is None:
            self._last = current
            return {"changed": False, "initial": True, "watched": len(self.paths), "files": len(current)}
        changes = diff_snapshots(self._last, current)
        self._last = current
        changed = bool(changes["added"] or changes["modified"] or changes["removed"])
        return {"changed": changed, "initial": False, "watched": len(self.paths), "files": len(current), **changes}
