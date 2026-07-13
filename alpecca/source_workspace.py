"""Read-only repository workspace shared by House and source inspection tools."""
from __future__ import annotations

import os
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

SOURCE_ROOTS: dict[str, Path] = {
    "source": _REPOSITORY_ROOT / "alpecca",
    "house": _REPOSITORY_ROOT / "apps" / "house-hq" / "src",
    "tests": _REPOSITORY_ROOT / "tests",
    "scripts": _REPOSITORY_ROOT / "scripts",
    "docs": _REPOSITORY_ROOT / "docs",
    "project": _REPOSITORY_ROOT,
}

PROJECT_FILES = frozenset({
    "agents.md",
    "app.py",
    "claude.md",
    "config.py",
    "handoff.md",
    "package.json",
    "project.md",
    "project_context.md",
    "readme.md",
    "requirements.txt",
    "requirements-core.txt",
    "requirements-mcp.txt",
    "requirements-mindpage-optional.txt",
    "server.py",
})

BLOCKED_PARTS = frozenset({
    ".agents", ".codex", ".git", ".venv", "build", "credentials", "data",
    "dist", "node_modules", "secrets", "venv",
})

BLOCKED_NAMES = frozenset({
    ".env", ".env.local", "access_token.txt", "credentials.json",
    "id_rsa", "secrets.json", "token.json",
})

_ATTACHABLE_SUFFIXES = frozenset({
    ".cfg", ".conf", ".csv", ".css", ".html", ".ini", ".js", ".json",
    ".log", ".md", ".py", ".toml", ".ts", ".txt", ".xml", ".yaml",
    ".yml",
})
SEARCH_VISIT_LIMIT = 5000
SEARCH_DEPTH_LIMIT = 10


class SourceWorkspaceRejected(ValueError):
    """A source workspace reference failed a code-owned boundary."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def inspection_roots() -> dict[str, Path]:
    """Return a copy so callers cannot mutate the shared root policy."""

    return dict(SOURCE_ROOTS)


def _relative_parts(relative_path: object, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(relative_path, str) or len(relative_path) > 512:
        raise SourceWorkspaceRejected("invalid-path")
    normalized = relative_path.replace("\\", "/").strip("/")
    if not normalized:
        if allow_empty:
            return ()
        raise SourceWorkspaceRejected("path-required")
    requested = Path(normalized)
    if requested.is_absolute() or requested.drive:
        raise SourceWorkspaceRejected("path-not-relative")
    parts = tuple(part for part in requested.parts if part not in {"", "."})
    if not parts or any(part == ".." for part in parts):
        raise SourceWorkspaceRejected("traversal")
    if any(":" in part or part.rstrip(" .") != part for part in parts):
        raise SourceWorkspaceRejected("path-alias-not-allowed")
    lowered = tuple(part.casefold() for part in parts)
    if any(part in BLOCKED_PARTS for part in lowered):
        raise SourceWorkspaceRejected("blocked-path")
    filename = lowered[-1]
    if filename in BLOCKED_NAMES or filename.startswith(".env"):
        raise SourceWorkspaceRejected("credential-path")
    return parts


def _resolve(root_id: object, relative_path: object, *, allow_empty: bool) -> tuple[Path, tuple[str, ...]]:
    if not isinstance(root_id, str) or root_id not in SOURCE_ROOTS:
        raise SourceWorkspaceRejected("root-not-allowed")
    parts = _relative_parts(relative_path, allow_empty=allow_empty)
    if root_id == "project" and parts:
        if len(parts) != 1 or parts[0].casefold() not in PROJECT_FILES:
            raise SourceWorkspaceRejected("project-file-not-allowed")
    try:
        base = SOURCE_ROOTS[root_id].resolve(strict=True)
        target = base
        for part in parts:
            target = target / part
            if target.is_symlink():
                raise SourceWorkspaceRejected("symlink-not-allowed")
        target = target.resolve(strict=True)
        canonical_relative = target.relative_to(base)
        if tuple(part.casefold() for part in canonical_relative.parts) != tuple(
            part.casefold() for part in parts
        ):
            raise SourceWorkspaceRejected("path-alias-not-allowed")
    except SourceWorkspaceRejected:
        raise
    except (OSError, RuntimeError, ValueError):
        raise SourceWorkspaceRejected("path-unavailable") from None
    return target, parts


def reference_allowed(root_id: object, relative_path: object) -> bool:
    """Validate one file reference before bounded ingress reads any bytes."""

    target, _ = _resolve(root_id, relative_path, allow_empty=False)
    if not target.is_file():
        raise SourceWorkspaceRejected("not-a-file")
    return True


def _entry(root_id: str, base: Path, path: Path) -> dict[str, object] | None:
    try:
        if path.is_symlink():
            return None
        resolved = path.resolve(strict=True)
        rel = resolved.relative_to(base)
    except (OSError, RuntimeError, ValueError):
        return None
    parts = tuple(part.casefold() for part in rel.parts)
    if any(part in BLOCKED_PARTS for part in parts):
        return None
    name_lower = path.name.casefold()
    if name_lower in BLOCKED_NAMES or name_lower.startswith(".env"):
        return None
    if root_id == "project" and (
        len(rel.parts) != 1 or name_lower not in PROJECT_FILES
    ):
        return None
    is_dir = path.is_dir()
    try:
        size = path.stat().st_size if path.is_file() else 0
    except OSError:
        size = 0
    return {
        "name": path.name,
        "rel": rel.as_posix(),
        "is_dir": is_dir,
        "size": size,
        "attachable": bool(not is_dir and path.suffix.casefold() in _ATTACHABLE_SUFFIXES),
    }


def list_entries(root_id: str, relative_path: str = "", *, limit: int = 200) -> dict[str, object]:
    """List approved repository metadata without returning file contents."""

    bounded_limit = max(1, min(200, int(limit)))
    try:
        target, parts = _resolve(root_id, relative_path, allow_empty=True)
    except SourceWorkspaceRejected as exc:
        return {"ok": False, "read_only": True, "error": exc.reason}
    if not target.is_dir():
        return {"ok": False, "read_only": True, "error": "not-a-directory"}
    base = SOURCE_ROOTS[root_id].resolve(strict=True)
    entries: list[dict[str, object]] = []
    try:
        children = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    except OSError:
        return {"ok": False, "read_only": True, "error": "directory-unavailable"}
    truncated = False
    for child in children:
        item = _entry(root_id, base, child)
        if item is None:
            continue
        if len(entries) >= bounded_limit:
            truncated = True
            break
        entries.append(item)
    return {
        "ok": True,
        "mode": "source",
        "read_only": True,
        "root": root_id,
        "rel": Path(*parts).as_posix() if parts else "",
        "entries": entries,
        "truncated": truncated,
    }


def search(query: str, *, limit: int = 80) -> dict[str, object]:
    """Search approved source names while preserving the same read-only policy."""

    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "read_only": True, "error": "query-required"}
    needle = query.strip().casefold()[:120]
    bounded_limit = max(1, min(100, int(limit)))
    matches: list[dict[str, object]] = []
    visited = 0
    truncated = False
    for root_id, configured_root in SOURCE_ROOTS.items():
        try:
            base = configured_root.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if root_id == "project":
            candidates = [base / name for name in sorted(PROJECT_FILES)]
            for candidate in candidates:
                if visited >= SEARCH_VISIT_LIMIT:
                    truncated = True
                    break
                visited += 1
                if needle not in candidate.name.casefold() or not candidate.exists():
                    continue
                item = _entry(root_id, base, candidate)
                if item is not None:
                    matches.append({"root": root_id, **item})
                if len(matches) >= bounded_limit:
                    truncated = True
                    break
        else:
            pending: list[tuple[Path, int]] = [(base, 0)]
            while pending and not truncated:
                directory, depth = pending.pop()
                try:
                    scanner = os.scandir(directory)
                except OSError:
                    continue
                with scanner:
                    for entry in scanner:
                        if visited >= SEARCH_VISIT_LIMIT:
                            truncated = True
                            break
                        visited += 1
                        lowered = entry.name.casefold()
                        candidate = Path(entry.path)
                        try:
                            if entry.is_symlink():
                                continue
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        if lowered in BLOCKED_PARTS or lowered in BLOCKED_NAMES or lowered.startswith(".env"):
                            continue
                        if is_dir and depth < SEARCH_DEPTH_LIMIT:
                            pending.append((candidate, depth + 1))
                        if needle not in lowered:
                            continue
                        item = _entry(root_id, base, candidate)
                        if item is not None:
                            matches.append({"root": root_id, **item})
                        if len(matches) >= bounded_limit:
                            truncated = True
                            break
        if truncated:
            break
    return {
        "ok": True,
        "mode": "source",
        "read_only": True,
        "query": query.strip()[:120],
        "matches": sorted(matches, key=lambda item: (str(item["root"]), str(item["rel"]))),
        "truncated": truncated,
        "visited": min(visited, SEARCH_VISIT_LIMIT),
    }


def overview() -> dict[str, object]:
    roots: list[dict[str, object]] = []
    any_truncated = False
    for root_id in SOURCE_ROOTS:
        listing = list_entries(root_id, limit=200)
        truncated = listing.get("truncated") is True
        any_truncated = any_truncated or truncated
        roots.append({
            "root": root_id,
            "count": len(listing.get("entries", [])),
            "truncated": truncated,
            "available": listing.get("ok") is True,
        })
    return {
        "ok": True,
        "mode": "source",
        "read_only": True,
        "roots": roots,
        "note": (
            "Approved Alpecca source areas are visible by metadata only. Files cannot be changed here."
            + (" Counts ending in + are capped at 200." if any_truncated else "")
        ),
    }
