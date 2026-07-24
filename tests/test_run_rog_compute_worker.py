from __future__ import annotations

import ast
from pathlib import Path
import socket
import ssl
import tempfile
import threading

import pytest

from scripts import run_rog_compute_worker as worker


ROOT = Path(__file__).resolve().parents[1]
VALID_SECRET = "r" * worker.MIN_SECRET_BYTES


@pytest.fixture(scope="module")
def tls_environment():
    with tempfile.TemporaryDirectory(prefix="alpecca-rog-runner-tls-") as folder:
        environ = {"LOCALAPPDATA": folder}
        cert_path, key_path = worker.install_tls_identity(environ)
        yield environ, cert_path, key_path


def _write_single_san_identity(folder: Path) -> tuple[Path, Path]:
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert_path = folder / "legacy-jason-holyrog.crt"
    key_path = folder / "legacy-jason-holyrog.key"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, worker.EXPECTED_HOST)]
    )
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(worker.EXPECTED_HOST)]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class MissingCredentialError(Exception):
    winerror = 1168


class FakeWin32Cred:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self, stored: object | None = None) -> None:
        self.stored = stored
        self.writes: list[tuple[dict[str, object], int]] = []
        self.deletes: list[tuple[str, int, int]] = []

    def CredRead(self, target: str, credential_type: int, flags: int) -> dict[str, object]:
        assert target == worker.DEFAULT_CREDENTIAL_TARGET
        assert credential_type == self.CRED_TYPE_GENERIC
        assert flags == 0
        if self.stored is None:
            raise MissingCredentialError()
        return {"CredentialBlob": self.stored}

    def CredWrite(self, credential: dict[str, object], flags: int) -> None:
        self.writes.append((credential, flags))

    def CredDelete(self, target: str, credential_type: int, flags: int) -> None:
        self.deletes.append((target, credential_type, flags))
        if self.stored is None:
            raise MissingCredentialError()


def test_settings_bind_loopback_by_default() -> None:
    settings = worker.resolve_settings({}, hostname_provider=lambda: "JASON_HOLYROG")

    assert settings.bind_host == "127.0.0.1"
    assert settings.port == worker.DEFAULT_PORT
    assert settings.model == "qwen3.5:9b"
    assert settings.lan_enabled is False
    assert settings.tls_cert_path is None
    assert settings.tls_key_path is None


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_private_lan_bind_requires_explicit_truthy_environment(
    value: str,
    tls_environment,
) -> None:
    tls_env, cert_path, key_path = tls_environment
    settings = worker.resolve_settings(
        {**tls_env, worker.LAN_ENV: value},
        hostname_provider=lambda: "Jason_HOLYROG",
    )

    assert settings.bind_host == "0.0.0.0"
    assert settings.lan_enabled is True
    assert settings.tls_cert_path == cert_path
    assert settings.tls_key_path == key_path


def test_private_lan_bind_refuses_missing_tls_material(tmp_path: Path) -> None:
    with pytest.raises(worker.WorkerStartupError, match="TLS"):
        worker.resolve_settings(
            {"LOCALAPPDATA": str(tmp_path), worker.LAN_ENV: "1"},
            hostname_provider=lambda: "Jason_HOLYROG",
        )


def test_wrong_hostname_refuses_worker_startup() -> None:
    with pytest.raises(worker.WorkerStartupError, match="assigned to Jason_HOLYROG"):
        worker.resolve_settings({}, hostname_provider=lambda: "RygenART")


def test_environment_secret_precedes_credential_manager() -> None:
    called = False

    def credential_reader(_target: str) -> str | None:
        nonlocal called
        called = True
        return "c" * worker.MIN_SECRET_BYTES

    secret, source = worker.load_worker_secret(
        {worker.SECRET_ENV: VALID_SECRET}, credential_reader=credential_reader
    )

    assert secret == VALID_SECRET
    assert source == "environment"
    assert called is False


def test_windows_credential_reader_accepts_utf16_blob() -> None:
    fake = FakeWin32Cred(VALID_SECRET.encode("utf-16-le"))

    stored = worker._read_windows_credential(
        worker.DEFAULT_CREDENTIAL_TARGET, win32cred_module=fake
    )

    assert stored == VALID_SECRET


def test_missing_or_short_secret_fails_without_exposing_value() -> None:
    short = "do-not-print-this"

    with pytest.raises(worker.WorkerStartupError) as exc_info:
        worker.load_worker_secret({worker.SECRET_ENV: short})

    assert short not in str(exc_info.value)


def test_compute_environment_removes_speaker_fence_and_disables_capabilities() -> None:
    environ = {
        "DISCORD_BOT_TOKEN": "not-retained",
        "ALPECCA_CONTINUITY_LEASE_ID": "not-retained",
        "ALPECCA_DISCORD": "1",
        "ALPECCA_REMOTE": "1",
    }

    worker.apply_compute_only_environment(
        environ, secret=VALID_SECRET, model="qwen3.5:9b"
    )

    assert "DISCORD_BOT_TOKEN" not in environ
    assert "ALPECCA_CONTINUITY_LEASE_ID" not in environ
    assert environ["ALPECCA_ROG_WORKER_ROLE"] == "compute-only"
    assert environ["ALPECCA_DISCORD"] == "0"
    assert environ["ALPECCA_REMOTE"] == "0"
    assert environ["ALPECCA_CONTINUITY_LEASE_URL"] == ""
    assert environ[worker.MODEL_ENV] == "qwen3.5:9b"
    assert environ[worker.ALLOWED_MODELS_ENV] == "qwen3.5:9b"
    assert environ[worker.SERVER_LAN_ENV] == "0"
    assert environ[worker.SERVER_BIND_ENV] == "127.0.0.1"
    assert environ[worker.SECRET_ENV] == VALID_SECRET


def test_worker_runs_one_quiet_uvicorn_process_without_logging_secret(
    capsys: pytest.CaptureFixture[str],
    tls_environment,
) -> None:
    tls_env, cert_path, key_path = tls_environment
    environ = {
        **tls_env,
        worker.SECRET_ENV: VALID_SECRET,
        worker.LAN_ENV: "1",
    }
    app = object()
    observed: dict[str, object] = {}
    loaded: list[bool] = []

    def app_loader() -> object:
        assert environ[worker.SECRET_ENV] == VALID_SECRET
        loaded.append(True)
        return app

    def uvicorn_runner(received_app: object, **kwargs: object) -> None:
        observed["app"] = received_app
        observed.update(kwargs)

    result = worker.run_worker(
        environ=environ,
        hostname_provider=lambda: "Jason_HOLYROG",
        app_loader=app_loader,
        uvicorn_runner=uvicorn_runner,
    )
    output = capsys.readouterr()

    assert result == 0
    assert loaded == [True]
    assert observed == {
        "app": app,
        "host": "0.0.0.0",
        "port": worker.DEFAULT_PORT,
        "workers": 1,
        "access_log": False,
        "proxy_headers": False,
        "server_header": False,
        "date_header": False,
        "log_level": "warning",
        "ssl_certfile": str(cert_path),
        "ssl_keyfile": str(key_path),
        "ssl_version": ssl.PROTOCOL_TLS_SERVER,
    }
    assert VALID_SECRET not in output.out
    assert VALID_SECRET not in output.err


def test_check_only_loads_app_but_never_opens_listener() -> None:
    environ = {worker.SECRET_ENV: VALID_SECRET}
    loaded: list[bool] = []

    result = worker.run_worker(
        environ=environ,
        hostname_provider=lambda: "Jason_HOLYROG",
        app_loader=lambda: loaded.append(True) or object(),
        uvicorn_runner=lambda *_args, **_kwargs: pytest.fail("listener was opened"),
        check_only=True,
    )

    assert result == 0
    assert loaded == [True]


def test_real_worker_factory_reads_process_local_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        worker.SECRET_ENV,
        worker.MODEL_ENV,
        worker.ALLOWED_MODELS_ENV,
        worker.SERVER_LAN_ENV,
        worker.SERVER_BIND_ENV,
    ):
        monkeypatch.delenv(key, raising=False)
    worker.apply_compute_only_environment(
        worker.os.environ,
        secret=VALID_SECRET,
        model="qwen3.5:9b",
        bind_host="127.0.0.1",
        lan_enabled=False,
    )

    app = worker._load_worker_app()

    assert app.state.worker.settings.secret == VALID_SECRET.encode("utf-8")
    assert app.state.worker.settings.model_allowlist == frozenset({"qwen3.5:9b"})
    assert app.state.worker.settings.bind_host == "127.0.0.1"
    assert app.state.worker.settings.allow_lan is False


def test_credential_install_and_removal_touch_only_dedicated_target() -> None:
    fake = FakeWin32Cred(VALID_SECRET)

    worker._write_windows_credential(
        worker.DEFAULT_CREDENTIAL_TARGET,
        VALID_SECRET,
        win32cred_module=fake,
    )
    removed = worker._delete_windows_credential(
        worker.DEFAULT_CREDENTIAL_TARGET, win32cred_module=fake
    )

    assert removed is True
    assert fake.writes == [
        (
            {
                "Type": fake.CRED_TYPE_GENERIC,
                "TargetName": worker.DEFAULT_CREDENTIAL_TARGET,
                "CredentialBlob": VALID_SECRET,
                "Persist": fake.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "AlpeccaROGWorker",
                "Comment": "Alpecca compute-only ROG worker shared secret",
            },
            0,
        )
    ]
    assert fake.deletes == [
        (worker.DEFAULT_CREDENTIAL_TARGET, fake.CRED_TYPE_GENERIC, 0)
    ]


def test_generated_tls_identity_is_self_signed_for_both_worker_dns_names_and_idempotent(
    tls_environment,
) -> None:
    from cryptography import x509

    environ, cert_path, key_path = tls_environment
    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    names = certificate.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.DNSName)

    assert names == list(worker.REQUIRED_DNS_SANS)
    assert cert_path.is_file()
    assert key_path.is_file()
    assert not worker._is_within(key_path, worker.ROOT.resolve())
    assert b"PRIVATE KEY" not in cert_path.read_bytes()
    assert worker.install_tls_identity(environ) == (cert_path, key_path)


@pytest.mark.parametrize("server_hostname", worker.REQUIRED_DNS_SANS)
def test_generated_tls_identity_completes_each_required_hostname_handshake(
    tls_environment,
    server_hostname: str,
) -> None:
    _, cert_path, key_path = tls_environment
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(cert_path), str(key_path))
    client_context = ssl.create_default_context(cafile=str(cert_path))
    client_context.check_hostname = True
    client_context.verify_mode = ssl.CERT_REQUIRED
    server_socket, client_socket = socket.socketpair()
    received: list[bytes] = []
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            with server_context.wrap_socket(server_socket, server_side=True) as secure:
                received.append(secure.recv(1))
                secure.sendall(b"y")
        except BaseException as exc:  # surfaced by the assertion below
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        with client_context.wrap_socket(
            client_socket,
            server_hostname=server_hostname,
        ) as secure:
            secure.sendall(b"x")
            assert secure.recv(1) == b"y"
    finally:
        thread.join(timeout=5)

    assert errors == []
    assert received == [b"x"]


def test_existing_single_san_identity_requires_rotation() -> None:
    with tempfile.TemporaryDirectory(prefix="alpecca-rog-legacy-tls-") as folder:
        cert_path, key_path = _write_single_san_identity(Path(folder))

        with pytest.raises(
            worker.WorkerStartupError, match="needs rotation"
        ) as exc_info:
            worker._validate_tls_material(cert_path, key_path)

    assert worker.EXPECTED_FQDN in str(exc_info.value)


def test_install_tls_identity_refuses_to_reuse_single_san_identity() -> None:
    with tempfile.TemporaryDirectory(prefix="alpecca-rog-legacy-install-") as folder:
        environ = {"LOCALAPPDATA": folder}
        cert_path, _key_path = worker._tls_paths(environ)
        cert_path.parent.mkdir(parents=True)
        generated_cert, generated_key = _write_single_san_identity(cert_path.parent)
        generated_cert.replace(cert_path)
        generated_key.replace(worker._tls_paths(environ)[1])

        with pytest.raises(worker.WorkerStartupError, match="needs rotation"):
            worker.install_tls_identity(environ)


def test_launcher_imports_only_the_isolated_worker_app() -> None:
    path = ROOT / "scripts" / "run_rog_compute_worker.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    dynamic_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            dynamic_imports.add(node.args[0].value)

    forbidden = {
        "server",
        "alpecca.mind",
        "alpecca.memory",
        "alpecca.discord_bridge",
        "alpecca.continuity_lease",
        "scripts.run_full",
        "scripts.share",
    }
    assert imported.isdisjoint(forbidden)
    assert dynamic_imports == {"alpecca.rog_worker_server"}


def test_isolated_worker_module_does_not_import_speaker_or_memory_runtimes() -> None:
    path = ROOT / "alpecca" / "rog_worker_server.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {
        "server",
        "alpecca.mind",
        "alpecca.memory",
        "alpecca.journal",
        "alpecca.cognition",
        "alpecca.discord_bridge",
        "alpecca.continuity_lease",
        "alpecca.mindscape_vault",
    }
    assert imported.isdisjoint(forbidden)


def test_setup_and_documentation_preserve_worker_only_boundary() -> None:
    setup = (ROOT / "scripts" / "setup_rog_worker.ps1").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "ROG_COMPUTE_WORKER.md").read_text(encoding="utf-8")
    combined = (setup + "\n" + docs).lower()

    assert "jason_holyrog" in combined
    assert "qwen3.5:9b" in combined
    assert "qualify_rog_worker.py" in setup
    assert "run_rog_compute_worker.py" in setup
    assert "alpecca_rog_worker_lan" in combined
    assert "alpecca/jason_holyrog/computeworker" in combined
    retired_model = "qwen3" + ":8b"
    assert retired_model not in combined

    setup_lower = setup.lower()
    forbidden_start_paths = (
        "server.py",
        "run_full.py",
        "run_discord_bridge.py",
        "share.py",
        "cloudflared",
        "register-scheduledtask",
        "new-netfirewallrule",
        "start-process",
    )
    assert not any(path in setup_lower for path in forbidden_start_paths)


def test_dedicated_server_task_remains_compute_only_and_restartable() -> None:
    installer = (
        ROOT / "scripts" / "install_rog_compute_server.ps1"
    ).read_text(encoding="utf-8")
    lowered = installer.lower()

    assert "alpecca rog compute server" in lowered
    assert "register-scheduledtask" in lowered
    assert "new-scheduledtasktrigger -atlogon" in lowered
    assert "-restartcount 999" in lowered
    assert "setup_rog_worker.ps1" in lowered
    assert "alpecca_rog_worker_lan = '1'" in lowered
    assert "qwen3.5:9b" in lowered
    assert "enableblender" in lowered
    assert "alpecca_rog_worker_blender_exe" in lowered
    assert "alpecca_rog_worker_blend_root" in lowered
    assert "alpecca_rog_worker_output_root" in lowered
    assert "blender-enabled" in lowered
    assert "blend-input" in lowered
    assert "render-output" in lowered
    for forbidden in (
        "server.py",
        "run_full.py",
        "run_discord_bridge.py",
        "share.py",
        "cloudflared",
        "continuity_lease",
    ):
        assert forbidden not in lowered
