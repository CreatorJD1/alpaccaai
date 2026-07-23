#!/usr/bin/env python3
"""Run the isolated, non-speaking compute helper on Jason_HOLYROG.

This entry point can only load ``alpecca.rog_worker_server``.  It does not
start Alpecca's main server, Discord bridge, memory stores, tunnels, or
continuity lease.  Network widening is explicit: loopback is the default and
``ALPECCA_ROG_WORKER_LAN=1`` is required to bind the private LAN interface.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import getpass
import importlib
import os
from pathlib import Path
import socket
import ssl
import sys
from typing import Callable, Mapping, MutableMapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_HOST = "Jason_HOLYROG"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_PORT = 8788
SECRET_ENV = "ALPECCA_ROG_WORKER_SECRET"
CREDENTIAL_TARGET_ENV = "ALPECCA_ROG_WORKER_CREDENTIAL_TARGET"
DEFAULT_CREDENTIAL_TARGET = "Alpecca/Jason_HOLYROG/ComputeWorker"
LAN_ENV = "ALPECCA_ROG_WORKER_LAN"
SERVER_LAN_ENV = "ALPECCA_ROG_WORKER_ALLOW_LAN"
SERVER_BIND_ENV = "ALPECCA_ROG_WORKER_BIND"
PORT_ENV = "ALPECCA_ROG_WORKER_PORT"
MODEL_ENV = "ALPECCA_ROG_WORKER_MODEL"
ALLOWED_MODELS_ENV = "ALPECCA_ROG_WORKER_ALLOWED_MODELS"
TLS_CERT_ENV = "ALPECCA_ROG_WORKER_TLS_CERT"
TLS_KEY_ENV = "ALPECCA_ROG_WORKER_TLS_KEY"
CA_CERT_ENV = "ALPECCA_ROG_WORKER_CA_CERT"
REPLAY_DB_ENV = "ALPECCA_ROG_WORKER_REPLAY_DB"
MIN_SECRET_BYTES = 32
MAX_SECRET_BYTES = 512

# These process-local overrides make an accidental import fail inert.  The
# worker app still owns its own strict compute-only request allowlist.
INERT_CAPABILITY_ENV: dict[str, str] = {
    "ALPECCA_ROG_WORKER_ROLE": "compute-only",
    "ALPECCA_REMOTE": "0",
    "ALPECCA_TUNNEL": "",
    "ALPECCA_DISCORD": "0",
    "ALPECCA_DISCORD_VOICE": "0",
    "ALPECCA_DISCORD_VOICE_RECEIVE": "0",
    "ALPECCA_FILES": "0",
    "ALPECCA_COMPUTER_USE": "0",
    "ALPECCA_SIGHT": "0",
    "ALPECCA_FACE": "0",
    "ALPECCA_ROUTINES": "0",
    "ALPECCA_WATCH_DIRS": "",
    "ALPECCA_EMBED_BACKFILL": "0",
    "ALPECCA_MINDPAGE": "0",
    "ALPECCA_CLOUD_AUTO_FAILOVER": "0",
    "ALPECCA_CONTINUITY_LEASE_URL": "",
    "ALPECCA_CONTINUITY_OFFLINE_ISOLATED": "0",
}

SENSITIVE_INHERITED_ENV: tuple[str, ...] = (
    "DISCORD_BOT_TOKEN",
    "ALPECCA_DISCORD_BRIDGE_SECRET",
    "ALPECCA_DISCORD_ACTOR_IDENTITY_SEAL_SECRET",
    "ALPECCA_CONTINUITY_LEASE_ID",
    "ALPECCA_CONTINUITY_FENCING_EPOCH",
    "ALPECCA_CONTINUITY_LEASE_HOLDER",
    "ALPECCA_CONTINUITY_LAUNCHER_PID",
)


class WorkerStartupError(RuntimeError):
    """A content-free startup refusal safe to show in the terminal."""


@dataclass(frozen=True)
class WorkerSettings:
    bind_host: str
    port: int
    model: str
    lan_enabled: bool
    observed_host: str
    tls_cert_path: Path | None
    tls_key_path: Path | None
    replay_db_path: Path


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _worker_data_dir(environ: Mapping[str, str]) -> Path:
    local_app_data = str(environ.get("LOCALAPPDATA", "")).strip()
    if local_app_data:
        return Path(local_app_data).expanduser() / "Alpecca" / "rog-worker"
    return Path.home() / "AppData" / "Local" / "Alpecca" / "rog-worker"


def _configured_path(
    environ: Mapping[str, str],
    name: str,
    default: Path,
) -> Path:
    configured = str(environ.get(name, "")).strip()
    return Path(configured).expanduser() if configured else default


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _tls_paths(environ: Mapping[str, str]) -> tuple[Path, Path]:
    tls_dir = _worker_data_dir(environ) / "tls"
    return (
        _configured_path(environ, TLS_CERT_ENV, tls_dir / "jason-holyrog.crt"),
        _configured_path(environ, TLS_KEY_ENV, tls_dir / "jason-holyrog.key"),
    )


def _validate_tls_material(cert_path: Path, key_path: Path) -> tuple[Path, Path]:
    try:
        cert = cert_path.expanduser().resolve(strict=True)
        key = key_path.expanduser().resolve(strict=True)
    except OSError:
        raise WorkerStartupError(
            "LAN mode requires an installed ROG TLS certificate and private key"
        ) from None
    if not cert.is_file() or not key.is_file():
        raise WorkerStartupError("ROG TLS certificate paths must name files")
    if _is_within(key, ROOT.resolve()):
        raise WorkerStartupError("the ROG TLS private key cannot be stored in the repository")
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        if hasattr(ssl, "TLSVersion"):
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert), str(key))
    except (OSError, ssl.SSLError, ValueError):
        raise WorkerStartupError("the ROG TLS certificate and key are invalid") from None
    try:
        from cryptography import x509
    except ImportError:
        raise WorkerStartupError("TLS validation requires the cryptography package") from None
    try:
        certificate = x509.load_pem_x509_certificate(cert.read_bytes())
        names = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.DNSName)
    except (OSError, ValueError, x509.ExtensionNotFound):
        raise WorkerStartupError("the ROG TLS certificate is invalid") from None
    if EXPECTED_HOST.casefold() not in {name.casefold() for name in names}:
        raise WorkerStartupError(
            f"the ROG TLS certificate must contain DNS SAN {EXPECTED_HOST}"
        )
    return cert, key


def install_tls_identity(
    environ: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    """Create one self-signed server identity outside the repository."""

    active_env = os.environ if environ is None else environ
    cert_path, key_path = _tls_paths(active_env)
    cert_path = cert_path.expanduser().resolve(strict=False)
    key_path = key_path.expanduser().resolve(strict=False)
    repo_root = ROOT.resolve()
    if _is_within(cert_path, repo_root) or _is_within(key_path, repo_root):
        raise WorkerStartupError("ROG TLS material cannot be stored in the repository")
    if cert_path.exists() or key_path.exists():
        if cert_path.is_file() and key_path.is_file():
            return _validate_tls_material(cert_path, key_path)
        raise WorkerStartupError("incomplete ROG TLS material already exists")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError:
        raise WorkerStartupError("TLS setup requires the cryptography package") from None

    issued_at = now or datetime.now(timezone.utc)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, EXPECTED_HOST)]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(issued_at - timedelta(minutes=5))
        .not_valid_after(issued_at + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(EXPECTED_HOST)]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    key_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    cert_temp = cert_path.with_name(cert_path.name + ".new")
    key_temp = key_path.with_name(key_path.name + ".new")
    try:
        with key_temp.open("xb") as handle:
            handle.write(key_bytes)
        os.chmod(key_temp, 0o600)
        with cert_temp.open("xb") as handle:
            handle.write(cert_bytes)
        os.replace(key_temp, key_path)
        os.replace(cert_temp, cert_path)
    except OSError as exc:
        for temporary in (cert_temp, key_temp):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise WorkerStartupError("could not install ROG TLS material") from exc
    return _validate_tls_material(cert_path, key_path)


def _validate_secret(value: object, *, source: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerStartupError(f"{source} is missing")
    if value != value.strip():
        raise WorkerStartupError(f"{source} must not have surrounding whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise WorkerStartupError(f"{source} contains unsupported control characters")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkerStartupError(f"{source} is not valid UTF-8") from exc
    if len(encoded) < MIN_SECRET_BYTES or len(encoded) > MAX_SECRET_BYTES:
        raise WorkerStartupError(
            f"{source} must contain {MIN_SECRET_BYTES} to {MAX_SECRET_BYTES} UTF-8 bytes"
        )
    return value


def _credential_error_code(exc: BaseException) -> int | None:
    code = getattr(exc, "winerror", None)
    if isinstance(code, int):
        return code
    if exc.args and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def _decode_credential_blob(blob: object) -> str:
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if isinstance(blob, bytes):
        encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
        try:
            return blob.decode(encoding).rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise WorkerStartupError("the stored ROG worker credential is invalid") from exc
    if isinstance(blob, str):
        return blob
    raise WorkerStartupError("the stored ROG worker credential is invalid")


def _credential_target(environ: Mapping[str, str]) -> str:
    target = environ.get(CREDENTIAL_TARGET_ENV, DEFAULT_CREDENTIAL_TARGET).strip()
    if not target or len(target) > 240 or any(ord(char) < 32 for char in target):
        raise WorkerStartupError(f"{CREDENTIAL_TARGET_ENV} is invalid")
    return target


def _win32cred_module() -> object:
    if os.name != "nt":
        raise WorkerStartupError(
            f"{SECRET_ENV} is required when Windows Credential Manager is unavailable"
        )
    try:
        import win32cred
    except ImportError as exc:
        raise WorkerStartupError(
            "Windows Credential Manager support requires pywin32"
        ) from exc
    return win32cred


def _read_windows_credential(target: str, *, win32cred_module: object | None = None) -> str | None:
    win32cred = win32cred_module or _win32cred_module()
    try:
        credential = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception as exc:
        if _credential_error_code(exc) in {2, 1168}:
            return None
        raise WorkerStartupError("could not read the ROG worker credential") from exc
    if not isinstance(credential, dict):
        raise WorkerStartupError("the stored ROG worker credential is invalid")
    return _decode_credential_blob(credential.get("CredentialBlob"))


def _write_windows_credential(
    target: str,
    secret: str,
    *,
    win32cred_module: object | None = None,
) -> None:
    value = _validate_secret(secret, source="the entered ROG worker secret")
    win32cred = win32cred_module or _win32cred_module()
    try:
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": target,
                "CredentialBlob": value,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "AlpeccaROGWorker",
                "Comment": "Alpecca compute-only ROG worker shared secret",
            },
            0,
        )
    except Exception as exc:
        raise WorkerStartupError("could not store the ROG worker credential") from exc


def _delete_windows_credential(
    target: str, *, win32cred_module: object | None = None
) -> bool:
    win32cred = win32cred_module or _win32cred_module()
    try:
        win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception as exc:
        if _credential_error_code(exc) in {2, 1168}:
            return False
        raise WorkerStartupError("could not remove the ROG worker credential") from exc
    return True


CredentialReader = Callable[[str], str | None]


def load_worker_secret(
    environ: Mapping[str, str] | None = None,
    *,
    credential_reader: CredentialReader | None = None,
) -> tuple[str, str]:
    active_env = os.environ if environ is None else environ
    env_value = active_env.get(SECRET_ENV, "")
    if env_value:
        return _validate_secret(env_value, source=SECRET_ENV), "environment"

    target = _credential_target(active_env)
    reader = credential_reader or _read_windows_credential
    stored = reader(target)
    if stored is None:
        raise WorkerStartupError(
            "ROG worker authorization is not configured; use --install-secret"
        )
    return _validate_secret(stored, source="the stored ROG worker credential"), "credential-manager"


def resolve_settings(
    environ: Mapping[str, str] | None = None,
    *,
    hostname_provider: Callable[[], str] = socket.gethostname,
) -> WorkerSettings:
    active_env = os.environ if environ is None else environ
    observed_host = str(hostname_provider() or "").strip()
    if observed_host.casefold() != EXPECTED_HOST.casefold():
        raise WorkerStartupError(
            f"this helper is assigned to {EXPECTED_HOST}, not {observed_host or 'an unknown host'}"
        )

    raw_port = active_env.get(PORT_ENV, str(DEFAULT_PORT)).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise WorkerStartupError(f"{PORT_ENV} must be an integer") from exc
    if not 1024 <= port <= 65535:
        raise WorkerStartupError(f"{PORT_ENV} must be between 1024 and 65535")

    model = active_env.get(MODEL_ENV, DEFAULT_MODEL).strip()
    if not model or len(model) > 160 or any(ord(char) < 32 for char in model):
        raise WorkerStartupError(f"{MODEL_ENV} is invalid")

    lan_enabled = _truthy(active_env.get(LAN_ENV, "0"))
    worker_dir = _worker_data_dir(active_env)
    replay_db_path = _configured_path(
        active_env,
        REPLAY_DB_ENV,
        worker_dir / "worker-ops.sqlite3",
    ).resolve(strict=False)
    tls_cert_path: Path | None = None
    tls_key_path: Path | None = None
    if lan_enabled:
        configured_cert, configured_key = _tls_paths(active_env)
        tls_cert_path, tls_key_path = _validate_tls_material(
            configured_cert,
            configured_key,
        )
    return WorkerSettings(
        bind_host="0.0.0.0" if lan_enabled else "127.0.0.1",
        port=port,
        model=model,
        lan_enabled=lan_enabled,
        observed_host=observed_host,
        tls_cert_path=tls_cert_path,
        tls_key_path=tls_key_path,
        replay_db_path=replay_db_path,
    )


def apply_compute_only_environment(
    environ: MutableMapping[str, str],
    *,
    secret: str,
    model: str,
    bind_host: str = "127.0.0.1",
    lan_enabled: bool = False,
    tls_cert_path: Path | None = None,
    tls_key_path: Path | None = None,
    replay_db_path: Path | None = None,
) -> None:
    for key in SENSITIVE_INHERITED_ENV:
        environ.pop(key, None)
    environ.update(INERT_CAPABILITY_ENV)
    environ[SECRET_ENV] = secret
    environ[MODEL_ENV] = model
    environ.setdefault(ALLOWED_MODELS_ENV, model)
    environ[SERVER_LAN_ENV] = "1" if lan_enabled else "0"
    environ[SERVER_BIND_ENV] = bind_host
    if replay_db_path is not None:
        environ[REPLAY_DB_ENV] = str(replay_db_path)
    if lan_enabled:
        if tls_cert_path is None or tls_key_path is None:
            raise WorkerStartupError("LAN mode requires validated TLS material")
        environ[TLS_CERT_ENV] = str(tls_cert_path)
        environ[TLS_KEY_ENV] = str(tls_key_path)


def _load_worker_app() -> object:
    try:
        module = importlib.import_module("alpecca.rog_worker_server")
    except (ImportError, ModuleNotFoundError) as exc:
        raise WorkerStartupError(
            "the isolated ROG worker app is unavailable; synchronize the source first"
        ) from exc
    factory = getattr(module, "create_app", None)
    if not callable(factory):
        raise WorkerStartupError("the isolated ROG worker app has no create_app factory")
    # The factory reads the already-validated, process-local settings above.
    return factory()


def run_worker(
    *,
    environ: MutableMapping[str, str] | None = None,
    hostname_provider: Callable[[], str] = socket.gethostname,
    credential_reader: CredentialReader | None = None,
    app_loader: Callable[[], object] = _load_worker_app,
    uvicorn_runner: Callable[..., object] | None = None,
    check_only: bool = False,
) -> int:
    active_env = os.environ if environ is None else environ
    settings = resolve_settings(active_env, hostname_provider=hostname_provider)
    secret, secret_source = load_worker_secret(
        active_env, credential_reader=credential_reader
    )
    apply_compute_only_environment(
        active_env,
        secret=secret,
        model=settings.model,
        bind_host=settings.bind_host,
        lan_enabled=settings.lan_enabled,
        tls_cert_path=settings.tls_cert_path,
        tls_key_path=settings.tls_key_path,
        replay_db_path=settings.replay_db_path,
    )
    app = app_loader()

    if check_only:
        print(
            "ROG compute worker check passed "
            f"(host={settings.observed_host}, role=compute-only, "
            f"bind={settings.bind_host}:{settings.port}, model={settings.model}, "
            f"secret={secret_source})."
        )
        return 0

    if uvicorn_runner is None:
        try:
            import uvicorn
        except ImportError as exc:
            raise WorkerStartupError("uvicorn is not installed") from exc
        uvicorn_runner = uvicorn.run

    scope = "private LAN" if settings.lan_enabled else "loopback only"
    print(
        "Starting the ROG compute-only worker "
        f"on {settings.bind_host}:{settings.port} ({scope}, model={settings.model})."
    )
    print("CoreMind, Discord, memory writers, tunnels, and continuity ownership stay disabled.")
    uvicorn_options: dict[str, object] = {
        "host": settings.bind_host,
        "port": settings.port,
        "workers": 1,
        "access_log": False,
        "proxy_headers": False,
        "server_header": False,
        "date_header": False,
        "log_level": "warning",
    }
    if settings.lan_enabled:
        assert settings.tls_cert_path is not None
        assert settings.tls_key_path is not None
        uvicorn_options["ssl_certfile"] = str(settings.tls_cert_path)
        uvicorn_options["ssl_keyfile"] = str(settings.tls_key_path)
        uvicorn_options["ssl_version"] = ssl.PROTOCOL_TLS_SERVER
    uvicorn_runner(
        app,
        **uvicorn_options,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--install-secret",
        action="store_true",
        help="prompt silently and store the shared secret in Windows Credential Manager",
    )
    actions.add_argument(
        "--remove-secret",
        action="store_true",
        help="remove only the dedicated Windows Credential Manager record",
    )
    actions.add_argument(
        "--install-tls",
        action="store_true",
        help=(
            "create or validate a self-signed Jason_HOLYROG TLS identity "
            "under LocalAppData"
        ),
    )
    actions.add_argument(
        "--check",
        action="store_true",
        help="validate host, secret, and isolated app without opening a listener",
    )
    return parser


def _install_secret(environ: Mapping[str, str]) -> int:
    target = _credential_target(environ)
    first = getpass.getpass("ROG worker shared secret (32+ characters): ")
    second = getpass.getpass("Confirm ROG worker shared secret: ")
    if first != second:
        print("The secrets did not match.", file=sys.stderr)
        return 2
    _write_windows_credential(target, first)
    print(f"ROG worker secret stored in Windows Credential Manager at {target}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.install_secret:
            return _install_secret(os.environ)
        if args.remove_secret:
            target = _credential_target(os.environ)
            removed = _delete_windows_credential(target)
            status = "removed" if removed else "was not present"
            print(f"ROG worker Credential Manager record {status}: {target}.")
            return 0
        if args.install_tls:
            cert_path, _key_path = install_tls_identity(os.environ)
            print(f"ROG worker TLS identity ready. Copy only this public certificate: {cert_path}")
            print(f"On the primary, set {CA_CERT_ENV} to the copied certificate path.")
            return 0
        return run_worker(check_only=args.check)
    except WorkerStartupError as exc:
        print(f"ROG compute worker refused startup: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
