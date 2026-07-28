"""Manage the separate HOLYROG XTTS voice secret without echoing its value.

This helper is intentionally not the compute-worker credential manager.  The
voice endpoint has its own Windows Credential Manager record and the dedicated
service receives only a staged, ACL-restricted copy under ProgramData.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
from pathlib import Path
from typing import Sequence


TARGET = "Alpecca/Jason_HOLYROG/XTTSVoice"
COMPUTE_WORKER_TARGET = "Alpecca/Jason_HOLYROG/ComputeWorker"
MIN_SECRET_BYTES = 32
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class VoiceSecretError(RuntimeError):
    """Safe operational error that never contains secret material."""


def _win32cred() -> object:
    if os.name != "nt":
        raise VoiceSecretError("Windows Credential Manager is required")
    try:
        import win32cred
    except ImportError as exc:
        raise VoiceSecretError("Windows Credential Manager support requires pywin32") from exc
    return win32cred


def _credential_error_code(exc: Exception) -> int | None:
    for name in ("winerror", "errno"):
        value = getattr(exc, name, None)
        if isinstance(value, int):
            return value
    return None


def _validate(value: str, *, source: str) -> str:
    normalized = value.strip()
    if len(normalized.encode("utf-8")) < MIN_SECRET_BYTES:
        raise VoiceSecretError(f"{source} must be at least {MIN_SECRET_BYTES} bytes")
    return normalized


def _read_target(target: str, *, source: str) -> str | None:
    win32cred = _win32cred()
    try:
        credential = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception as exc:
        if _credential_error_code(exc) in {2, 1168}:
            return None
        raise VoiceSecretError(f"could not read {source}") from exc
    value = credential.get("CredentialBlob", b"")
    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-16-le"):
            try:
                return _validate(value.decode(encoding), source=source)
            except UnicodeDecodeError:
                continue
        raise VoiceSecretError(f"{source} is unreadable")
    if isinstance(value, str):
        return _validate(value, source=source)
    raise VoiceSecretError(f"{source} is invalid")


def _read() -> str | None:
    return _read_target(TARGET, source="the stored HOLYROG XTTS credential")


def _derive_voice_secret(compute_secret: str) -> str:
    """Domain-separate the XTTS credential without exposing the compute secret."""
    parent = _validate(compute_secret, source="the compute-worker credential")
    material = hmac.new(
        parent.encode("utf-8"),
        b"Alpecca/Jason_HOLYROG/XTTSVoice/v1",
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(material).decode("ascii").rstrip("=")


def _derive_from_compute_worker() -> str:
    stored = _read_target(
        COMPUTE_WORKER_TARGET, source="the existing compute-worker credential"
    )
    if stored is None:
        raise VoiceSecretError(
            "the existing compute-worker credential is unavailable; use --install-secret"
        )
    return _derive_voice_secret(stored)


def _write(value: str) -> None:
    win32cred = _win32cred()
    secret = _validate(value, source="the entered HOLYROG XTTS secret")
    try:
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": TARGET,
                "CredentialBlob": secret,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "AlpeccaHOLYROGXTTS",
                "Comment": "Alpecca dedicated HOLYROG XTTS voice service",
            },
            0,
        )
    except Exception as exc:
        raise VoiceSecretError("could not store the HOLYROG XTTS credential") from exc


def _stage(path: Path, value: str) -> None:
    if not path.is_absolute():
        raise VoiceSecretError("the staged secret file path must be absolute")
    resolved = path.resolve()
    if resolved == REPOSITORY_ROOT or REPOSITORY_ROOT in resolved.parents:
        raise VoiceSecretError("the staged secret file cannot be stored in the repository")
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = resolved.with_name(f".{resolved.name}.new")
        temporary.write_text(_validate(value, source="the staged HOLYROG XTTS secret"), encoding="utf-8")
        os.replace(temporary, resolved)
    except OSError as exc:
        raise VoiceSecretError("could not stage the HOLYROG XTTS secret file") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install-secret", action="store_true")
    actions.add_argument("--derive-from-compute-worker", action="store_true")
    actions.add_argument("--stage-secret-file", metavar="ABSOLUTE_PATH")
    actions.add_argument("--remove-secret", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.install_secret:
            first = getpass.getpass("HOLYROG XTTS shared secret (32+ characters): ")
            second = getpass.getpass("Confirm HOLYROG XTTS shared secret: ")
            if first != second:
                print("The secrets did not match.")
                return 2
            _write(first)
            print("HOLYROG XTTS secret stored in Windows Credential Manager without printing its value.")
            return 0
        if args.derive_from_compute_worker:
            _write(_derive_from_compute_worker())
            print("HOLYROG XTTS secret derived from the local compute-worker credential without printing either value.")
            return 0
        if args.remove_secret:
            win32cred = _win32cred()
            try:
                win32cred.CredDelete(TARGET, win32cred.CRED_TYPE_GENERIC, 0)
                print("HOLYROG XTTS Credential Manager record removed.")
            except Exception as exc:
                if _credential_error_code(exc) in {2, 1168}:
                    print("HOLYROG XTTS Credential Manager record was not present.")
                else:
                    raise VoiceSecretError("could not remove the HOLYROG XTTS credential") from exc
            return 0
        stored = _read()
        if stored is None:
            raise VoiceSecretError("HOLYROG XTTS authorization is not configured; use --install-secret")
        _stage(Path(args.stage_secret_file), stored)
        print("HOLYROG XTTS service secret staged without printing its value.")
        return 0
    except VoiceSecretError as exc:
        print(f"HOLYROG XTTS secret setup failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
