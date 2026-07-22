"""Fail-closed, credential-free release secret scan for Alpecca.

The scanner reads only Git-tracked files and the built House HQ distribution.
Its JSON receipt contains aggregate evidence and deterministic path hashes; it
never serializes matched bytes, environment values, or exception text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


SCHEMA = "alpecca.release-secret-scan.v1"
DEFAULT_DIST = Path("apps/house-hq/dist")
CHUNK_BYTES = 1024 * 1024
OVERLAP_BYTES = 16 * 1024
MAX_RECEIPT_FINDINGS = 1000


@dataclass(frozen=True)
class Detector:
    name: str
    pattern: re.Pattern[bytes]
    secret_group: int = 1
    validator: Callable[[bytes], bool] | None = None
    needles: tuple[bytes, ...] = ()
    casefold_needles: bool = False


def _entropy(value: bytes) -> float:
    if not value:
        return 0.0
    counts: dict[int, int] = {}
    for item in value:
        counts[item] = counts.get(item, 0) + 1
    length = float(len(value))
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _credible_named_value(value: bytes) -> bool:
    candidate = value.strip().rstrip(b",;)}]")
    lowered = candidate.lower()
    placeholders = (
        b"example",
        b"placeholder",
        b"replace",
        b"redacted",
        b"changeme",
        b"dummy",
        b"sample",
        b"fixture",
        b"test-",
        b"test_",
        b"your-",
        b"your_",
        b"runtime-secret",
        b"generation",
    )
    if len(candidate) < 12 or any(marker in lowered for marker in placeholders):
        return False
    if re.fullmatch(rb"(?:phase|stage)\d{1,2}-[a-z0-9-]{8,}", lowered):
        return False
    if candidate.startswith((b"${", b"%", b"<")) or candidate.endswith(b">"):
        return False
    if lowered in {b"none", b"null", b"true", b"false", b"unset"}:
        return False
    classes = sum(
        (
            any(65 <= item <= 90 for item in candidate),
            any(97 <= item <= 122 for item in candidate),
            any(48 <= item <= 57 for item in candidate),
            any(not chr(item).isalnum() for item in candidate),
        )
    )
    return classes >= 3 and _entropy(candidate) >= 3.15


DETECTORS: tuple[Detector, ...] = (
    Detector(
        "hugging_face_token",
        re.compile(rb"\b(hf_[A-Za-z0-9]{20,})\b"),
        needles=(b"hf_",),
    ),
    Detector(
        "github_token",
        re.compile(rb"\b((?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}))\b"),
        needles=(b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_", b"github_pat_"),
    ),
    Detector(
        "openai_key",
        re.compile(rb"\b(sk-(?:proj-)?[A-Za-z0-9_-]{20,})\b"),
        needles=(b"sk-",),
    ),
    Detector(
        "aws_access_key",
        re.compile(rb"\b((?:AKIA|ASIA)[A-Z0-9]{16})\b"),
        needles=(b"AKIA", b"ASIA"),
    ),
    Detector(
        "jwt",
        re.compile(
            rb"\b(eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})\b"
        ),
        needles=(b"eyJ",),
    ),
    Detector(
        "discord_token",
        re.compile(
            rb"\b([A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,40})\b"
        ),
        needles=(b".",),
    ),
    Detector(
        "private_key",
        re.compile(
            rb"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\r\n]+"
            rb"[A-Za-z0-9+/=\r\n]{64,})"
        ),
        needles=(b"-----BEGIN ",),
    ),
    Detector(
        "credential_in_url",
        re.compile(rb"\b(https?://[^\s/:@]{1,128}:[^\s/@]{8,256}@)"),
        needles=(b"http://", b"https://"),
    ),
    Detector(
        "named_secret_assignment",
        re.compile(
            rb"(?i)\b([A-Z][A-Z0-9_.-]{0,64}"
            rb"(?:TOKEN|SECRET|PASSWORD|PASSPHRASE|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL)"
            rb")\b\s*(?:=|:)\s*[\"']?([^\s\"'`<>]{12,512})"
        ),
        secret_group=2,
        validator=_credible_named_value,
        needles=(
            b"token",
            b"secret",
            b"password",
            b"passphrase",
            b"api_key",
            b"api-key",
            b"private_key",
            b"private-key",
            b"credential",
        ),
        casefold_needles=True,
    ),
)


def _utc_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _path_id(scope: str, relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lstrip("./")
    return hashlib.sha256(f"{scope}\0{normalized}".encode("utf-8")).hexdigest()


def _safe_relative(root: Path, path: Path) -> str | None:
    try:
        return path.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return None


def _resolves_inside(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _error(scope: str, code: str, relative_path: str) -> dict[str, str]:
    return {
        "scope": scope,
        "code": code,
        "path_sha256": _path_id(scope, relative_path),
    }


def _git_paths(root: Path) -> tuple[list[Path], str | None, list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    try:
        listed = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files", "--cached", "-z"],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return [], None, [_error("tracked_source", "git_listing_failed", ".git")]
    if listed.returncode != 0:
        return [], None, [_error("tracked_source", "git_listing_failed", ".git")]

    paths: list[Path] = []
    for raw in listed.stdout.split(b"\0"):
        if not raw:
            continue
        relative = os.fsdecode(raw)
        candidate = root / relative
        if _safe_relative(root, candidate) is None:
            errors.append(_error("tracked_source", "tracked_path_outside_root", relative))
            continue
        paths.append(candidate)
    if not paths:
        errors.append(_error("tracked_source", "tracked_source_empty", ".git/index"))

    head: str | None = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=10,
            text=True,
            encoding="ascii",
            errors="ignore",
        )
        candidate_head = result.stdout.strip().lower()
        if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", candidate_head):
            head = candidate_head
        else:
            errors.append(_error("tracked_source", "git_head_unavailable", ".git/HEAD"))
    except (OSError, subprocess.SubprocessError):
        errors.append(_error("tracked_source", "git_head_unavailable", ".git/HEAD"))
    return sorted(set(paths), key=lambda item: item.as_posix()), head, errors


def _fixture_paths(root: Path, values: Sequence[str | Path]) -> tuple[list[Path], list[dict[str, str]]]:
    paths: list[Path] = []
    errors: list[dict[str, str]] = []
    for value in values:
        supplied = Path(value)
        candidate = supplied if supplied.is_absolute() else root / supplied
        relative = _safe_relative(root, candidate)
        if relative is None:
            errors.append(
                _error("tracked_source", "tracked_path_outside_root", supplied.name or "outside")
            )
            continue
        paths.append(candidate)
    if not paths:
        errors.append(_error("tracked_source", "tracked_source_empty", "fixture"))
    return sorted(set(paths), key=lambda item: item.as_posix()), errors


def _dist_paths(root: Path, dist: Path) -> tuple[list[Path], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    relative_dist = _safe_relative(root, dist) or "outside-dist"
    if not _resolves_inside(root, dist):
        return [], [_error("house_hq_dist", "dist_outside_root", relative_dist)]
    if not dist.is_dir() or dist.is_symlink():
        return [], [_error("house_hq_dist", "dist_absent", relative_dist)]

    paths: list[Path] = []
    for directory, directory_names, file_names in os.walk(dist, followlinks=False):
        base = Path(directory)
        for name in list(directory_names):
            candidate = base / name
            if candidate.is_symlink():
                rel = _safe_relative(root, candidate) or name
                errors.append(_error("house_hq_dist", "symlink_not_scanned", rel))
                directory_names.remove(name)
        for name in file_names:
            paths.append(base / name)

    if not paths:
        errors.append(_error("house_hq_dist", "dist_empty", relative_dist))
    index_path = dist / "index.html"
    if not index_path.is_file() or index_path.is_symlink():
        rel = _safe_relative(root, index_path) or "index.html"
        errors.append(_error("house_hq_dist", "dist_index_missing", rel))
    return sorted(set(paths), key=lambda item: item.as_posix()), errors


def _iter_matches(data: bytes, base_offset: int) -> Iterable[tuple[str, int]]:
    lowered: bytes | None = None
    for detector in DETECTORS:
        if detector.needles:
            if detector.casefold_needles:
                if lowered is None:
                    lowered = data.lower()
                haystack = lowered
            else:
                haystack = data
            if not any(needle in haystack for needle in detector.needles):
                continue
        for match in detector.pattern.finditer(data):
            secret = match.group(detector.secret_group)
            if detector.validator is not None and not detector.validator(secret):
                continue
            yield detector.name, base_offset + match.start(detector.secret_group)


def _scan_file(
    root: Path,
    path: Path,
    scope: str,
) -> tuple[int, str | None, list[tuple[str, int]], dict[str, str] | None]:
    relative = _safe_relative(root, path)
    identity = relative or path.name or "unknown"
    if relative is None or not _resolves_inside(root, path):
        return 0, None, [], _error(scope, "path_outside_root", identity)
    try:
        before = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            return 0, None, [], _error(scope, "not_regular_file", identity)
        digest = hashlib.sha256()
        matches: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        tail = b""
        consumed = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                window = tail + chunk
                base_offset = consumed - len(tail)
                for finding in _iter_matches(window, base_offset):
                    if finding not in seen:
                        seen.add(finding)
                        matches.append(finding)
                consumed += len(chunk)
                tail = window[-OVERLAP_BYTES:]
            open_stat = os.fstat(handle.fileno())
        after = path.lstat()
    except OSError:
        return 0, None, [], _error(scope, "file_read_failed", identity)

    stable = (
        before.st_size == consumed == open_stat.st_size == after.st_size
        and before.st_mtime_ns == open_stat.st_mtime_ns == after.st_mtime_ns
        and before.st_ino == open_stat.st_ino == after.st_ino
    )
    if not stable:
        return consumed, None, [], _error(scope, "file_changed_during_scan", identity)
    return consumed, digest.hexdigest(), matches, None


def _scan_scope(
    root: Path,
    scope: str,
    paths: Sequence[Path],
    initial_errors: Sequence[dict[str, str]],
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, str]]]:
    errors = list(initial_errors)
    findings: list[dict[str, object]] = []
    total_findings = 0
    file_count = 0
    byte_count = 0
    inventory = hashlib.sha256()
    overflow_recorded = False

    for path in paths:
        relative = _safe_relative(root, path) or path.name or "unknown"
        path_hash = _path_id(scope, relative)
        size, content_hash, matches, scan_error = _scan_file(root, path, scope)
        byte_count += size
        if scan_error is not None:
            errors.append(scan_error)
            continue
        file_count += 1
        inventory.update(f"{path_hash}\0{size}\0{content_hash}\n".encode("ascii"))
        total_findings += len(matches)
        for rule, offset in matches:
            if len(findings) < MAX_RECEIPT_FINDINGS:
                findings.append(
                    {
                        "scope": scope,
                        "rule": rule,
                        "path_sha256": path_hash,
                        "byte_offset": offset,
                    }
                )
            elif not overflow_recorded:
                errors.append(_error(scope, "finding_receipt_limit_exceeded", relative))
                overflow_recorded = True

    summary: dict[str, object] = {
        "file_count": file_count,
        "byte_count": byte_count,
        "finding_count": total_findings,
        "error_count": len(errors),
        "inventory_sha256": inventory.hexdigest(),
    }
    return summary, findings, errors


def scan_release(
    root: Path,
    *,
    dist_dir: Path | None = None,
    tracked_paths: Sequence[str | Path] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Scan a release tree and return a content-free receipt.

    ``tracked_paths`` is a test-fixture seam. A fixture can pass its scan, but
    can never set ``release_ready`` because Git did not define the source set.
    """

    root = Path(root).resolve(strict=False)
    mode = "fixture" if tracked_paths is not None else "git"
    if not root.is_dir():
        source_paths: list[Path] = []
        source_errors = [_error("tracked_source", "repository_absent", "repository")]
        head = None
    elif tracked_paths is not None:
        source_paths, source_errors = _fixture_paths(root, tracked_paths)
        head = None
    else:
        source_paths, head, source_errors = _git_paths(root)

    requested_dist = dist_dir or DEFAULT_DIST
    dist = requested_dist if requested_dist.is_absolute() else root / requested_dist
    if root.is_dir():
        dist_paths, dist_errors = _dist_paths(root, dist)
    else:
        dist_paths = []
        dist_errors = [_error("house_hq_dist", "repository_absent", "repository")]

    source_summary, source_findings, source_scan_errors = _scan_scope(
        root, "tracked_source", source_paths, source_errors
    )
    dist_summary, dist_findings, dist_scan_errors = _scan_scope(
        root, "house_hq_dist", dist_paths, dist_errors
    )
    findings = sorted(
        source_findings + dist_findings,
        key=lambda item: (
            str(item["scope"]),
            str(item["path_sha256"]),
            int(item["byte_offset"]),
            str(item["rule"]),
        ),
    )
    unique_errors = {
        (item["scope"], item["code"], item["path_sha256"]): item
        for item in source_scan_errors + dist_scan_errors
    }
    errors = [unique_errors[key] for key in sorted(unique_errors)]
    total_findings = int(source_summary["finding_count"]) + int(
        dist_summary["finding_count"]
    )
    passed = total_findings == 0 and not errors
    release_ready = passed and mode == "git"
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "generated_at": _utc_timestamp(now),
        "mode": mode,
        "repository_head": head,
        "path_identity": "sha256(scope + NUL + normalized repository-relative path)",
        "scopes": {
            "tracked_source": source_summary,
            "house_hq_dist": dist_summary,
        },
        "finding_count": total_findings,
        "findings": findings,
        "error_count": len(errors),
        "errors": errors,
        "result": "pass" if passed else "fail",
        "release_ready": release_ready,
        "claim": "release_secret_scan_passed" if release_ready else "not_release_ready",
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
    return receipt


def write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(_canonical_json(receipt) + b"\n")
        temporary.replace(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _fatal_receipt(now: datetime | None = None) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "generated_at": _utc_timestamp(now),
        "mode": "git",
        "repository_head": None,
        "path_identity": "sha256(scope + NUL + normalized repository-relative path)",
        "scopes": {},
        "finding_count": 0,
        "findings": [],
        "error_count": 1,
        "errors": [
            {
                "scope": "scanner",
                "code": "scanner_failed_closed",
                "path_sha256": _path_id("scanner", "internal"),
            }
        ],
        "result": "fail",
        "release_ready": False,
        "claim": "not_release_ready",
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan Git-tracked source and built House HQ dist, then emit a "
            "content-free release receipt."
        )
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--dist",
        type=Path,
        default=DEFAULT_DIST,
        help="House HQ dist path, relative to --root by default",
    )
    parser.add_argument("--receipt", type=Path, help="optional JSON receipt output path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and print the receipt without writing --receipt",
    )
    parser.add_argument("--pretty", action="store_true", help="pretty-print stdout JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = scan_release(args.root, dist_dir=args.dist)
        if args.receipt is not None and not args.dry_run:
            write_receipt(args.receipt, receipt)
    except Exception:  # Receipt remains content-free even on unexpected scanner faults.
        receipt = _fatal_receipt()
    if args.pretty:
        print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(_canonical_json(receipt).decode("utf-8"))
    return 0 if receipt.get("release_ready") is True else 1


if __name__ == "__main__":
    sys.exit(main())
