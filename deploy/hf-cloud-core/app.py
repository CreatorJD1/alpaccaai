"""Fail-closed supervisor for the on-demand Hugging Face cloud core.

This process is intentionally the container entrypoint.  It restores a fresh
runtime database, obtains the cross-host continuity fence, publishes the Space
endpoint, and only then starts Alpecca's existing FastAPI application.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit


REPO_ROOT = Path(
    os.environ.get("ALPECCA_SOURCE_ROOT", str(Path(__file__).resolve().parents[2]))
).expanduser().resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from alpecca.continuity_lease import (  # noqa: E402
    ContinuityLeaseError,
    ContinuityLeaseGuard,
    client_from_env,
)


MODEL_ID = "Qwen/Qwen3.5-9B"
CONTINUITY_ROLE = "cloud-standby"
APP_PORT = 7860
LEASE_RENEW_SECONDS = 10.0
LEASE_LOST_EXIT = 75
MAX_APPROVAL_SECONDS = 5 * 60
HARD_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
_NODE_CHARS = re.compile(r"[^A-Za-z0-9._:-]+")
_APPROVAL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUIRED_VALUES = (
    "ALPECCA_MINDSCAPE_VAULT_URL",
    "ALPECCA_MINDSCAPE_VAULT_TOKEN",
    "ALPECCA_MINDSCAPE_VAULT_KEY",
    "ALPECCA_CONTINUITY_LEASE_URL",
    "ALPECCA_CONTINUITY_LEASE_TOKEN",
    "ALPECCA_AUTH_SECRET",
    "ALPECCA_CREATOR_PASSWORD",
)
_TRUE_VALUES = {"1", "true", "yes", "on"}


class CloudCoreStartupError(RuntimeError):
    """A precondition failed before CoreMind was allowed to start."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RestoreReceipt:
    path: Path
    sequence: int
    created_at: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RestoreApproval:
    approval_id: str
    snapshot_digest: str
    lease_epoch: int
    issued_at: datetime
    expires_at: datetime
    evidence_id: str


def _clean_status(value: object) -> str:
    text = re.sub(r"[^a-z0-9_-]+", "-", str(value or "unknown").lower())
    return text.strip("-")[:64] or "unknown"


def _approval_time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CloudCoreStartupError(f"restore_approval_{field}_invalid")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise CloudCoreStartupError(f"restore_approval_{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise CloudCoreStartupError(f"restore_approval_{field}_invalid")
    return parsed.astimezone(timezone.utc)


def load_restore_approval(
    environ: Mapping[str, str],
    receipt: RestoreReceipt,
    *,
    now: datetime | None = None,
) -> RestoreApproval:
    """Validate an external CreatorJD approval against the restored archive."""
    raw = str(environ.get("ALPECCA_CLOUD_RESTORE_APPROVAL") or "").strip()
    if not raw:
        raise CloudCoreStartupError("explicit_restore_approval_required")
    if len(raw.encode("utf-8")) > 8 * 1024:
        raise CloudCoreStartupError("restore_approval_invalid")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CloudCoreStartupError("restore_approval_invalid") from exc
    expected_keys = {
        "approvalId",
        "purpose",
        "creatorPrincipal",
        "snapshotDigest",
        "leaseEpoch",
        "issuedAt",
        "expiresAt",
        "oneUse",
        "verification",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise CloudCoreStartupError("restore_approval_invalid")
    verification = value.get("verification")
    if not isinstance(verification, dict) or set(verification) != {
        "status",
        "verifier",
        "evidenceId",
    }:
        raise CloudCoreStartupError("restore_approval_invalid")

    approval_id = value.get("approvalId")
    evidence_id = verification.get("evidenceId")
    if not isinstance(approval_id, str) or not _APPROVAL_IDENTIFIER.fullmatch(approval_id):
        raise CloudCoreStartupError("restore_approval_id_invalid")
    if not isinstance(evidence_id, str) or not _APPROVAL_IDENTIFIER.fullmatch(evidence_id):
        raise CloudCoreStartupError("restore_approval_evidence_invalid")
    if value.get("purpose") != "stage-passive-restore":
        raise CloudCoreStartupError("restore_approval_purpose_mismatch")
    if value.get("creatorPrincipal") != "CreatorJD":
        raise CloudCoreStartupError("restore_approval_creator_mismatch")
    expected_digest = f"sha256:{receipt.sha256}"
    if value.get("snapshotDigest") != expected_digest:
        raise CloudCoreStartupError("restore_approval_digest_mismatch")
    lease_epoch = value.get("leaseEpoch")
    if isinstance(lease_epoch, bool) or not isinstance(lease_epoch, int) or lease_epoch < 1:
        raise CloudCoreStartupError("restore_approval_lease_epoch_invalid")
    if value.get("oneUse") is not True:
        raise CloudCoreStartupError("restore_approval_not_one_use")
    if verification.get("status") != "verified":
        raise CloudCoreStartupError("restore_approval_unverified")
    if verification.get("verifier") != "external-creator-verifier":
        raise CloudCoreStartupError("restore_approval_verifier_invalid")

    issued_at = _approval_time(value.get("issuedAt"), "issued_at")
    expires_at = _approval_time(value.get("expiresAt"), "expires_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expires_at <= issued_at or (expires_at - issued_at).total_seconds() > MAX_APPROVAL_SECONDS:
        raise CloudCoreStartupError("restore_approval_window_invalid")
    if issued_at > current:
        raise CloudCoreStartupError("restore_approval_not_yet_valid")
    if current >= expires_at:
        raise CloudCoreStartupError("restore_approval_expired")
    return RestoreApproval(
        approval_id=approval_id,
        snapshot_digest=expected_digest,
        lease_epoch=lease_epoch,
        issued_at=issued_at,
        expires_at=expires_at,
        evidence_id=evidence_id,
    )


def require_current_approval(approval: RestoreApproval) -> None:
    if datetime.now(timezone.utc) >= approval.expires_at:
        raise CloudCoreStartupError("restore_approval_expired")


def automatic_failover_authorized(environ: Mapping[str, str]) -> bool:
    """Return whether deployment policy authorizes unattended lease takeover."""
    return str(environ.get("ALPECCA_CLOUD_AUTO_FAILOVER") or "").strip().lower() in _TRUE_VALUES


def resolve_public_endpoint(environ: Mapping[str, str]) -> str:
    """Return the exact HTTPS origin that the lease authority may publish."""
    configured = str(environ.get("ALPECCA_PUBLIC_ENDPOINT") or "").strip()
    if configured:
        candidate = configured
    else:
        space_host = str(environ.get("SPACE_HOST") or "").strip()
        candidate = f"https://{space_host}" if space_host else ""
    parsed = urlsplit(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise CloudCoreStartupError("public_endpoint_invalid")
    return f"https://{parsed.netloc}"


def configure_runtime(
    environ: MutableMapping[str, str],
    runtime_home: Path,
    endpoint: str,
) -> None:
    """Pin the cloud runtime before config.py or alpecca.mind is imported."""
    forced = {
        "ALPECCA_HOME": str(runtime_home),
        "ALPECCA_LLM_BACKEND": "hf",
        "ALPECCA_HF_MODEL": MODEL_ID,
        "ALPECCA_MODEL": "qwen3.5:9b",
        "ALPECCA_FAST_MODEL": "qwen3.5:9b",
        "ALPECCA_REFLECT_MODEL": "",
        "ALPECCA_REFLECT_THINK": "0",
        "ALPECCA_DEEP_BACKEND": "local",
        "ALPECCA_CHAT_CLOUD_MODEL": "",
        "ALPECCA_OLLAMA_CLOUD_MODEL": "",
        "ALPECCA_CHAT_ZEROGPU": "0",
        "ALPECCA_REMOTE": "1",
        "ALPECCA_SERVER_HOST": "0.0.0.0",
        "ALPECCA_SERVER_PORT": str(APP_PORT),
        "ALPECCA_TUNNEL": "off",
        "ALPECCA_PUBLIC_URL": endpoint,
        "ALPECCA_CONTINUITY_ROLE": CONTINUITY_ROLE,
        # Restore is read-only until Vault writes can validate the exact fence.
        "ALPECCA_MINDSCAPE": "0",
        "ALPECCA_MINDSCAPE_VAULT": "0",
        "ALPECCA_STREAM_CHAT": "0",
        "ALPECCA_F5_WORKER": "0",
        "ALPECCA_DISCORD": "0",
        "ALPECCA_DISCORD_MEDIA": "0",
        "ALPECCA_DISCORD_VOICE": "0",
        "ALPECCA_COMPUTER_USE": "0",
        "ALPECCA_SIGHT": "0",
        "ALPECCA_FACE": "0",
        "ALPECCA_VOICE": "0",
        "ALPECCA_APPS": "",
        "PYTHONUNBUFFERED": "1",
    }
    environ.update(forced)
    environ.setdefault("ALPECCA_HF_PROVIDER", "auto")

    hf_token = str(
        environ.get("HF_TOKEN")
        or environ.get("HUGGINGFACEHUB_API_TOKEN")
        or ""
    ).strip()
    if hf_token:
        environ["HF_TOKEN"] = hf_token

    configured_node = str(environ.get("ALPECCA_CONTINUITY_NODE_ID") or "").strip()
    if not configured_node:
        identity = str(environ.get("SPACE_ID") or urlsplit(endpoint).hostname or "space")
        identity = _NODE_CHARS.sub("-", identity).strip("-._:") or "space"
        configured_node = f"hf-cloud-standby:{identity}"[:96]
        environ["ALPECCA_CONTINUITY_NODE_ID"] = configured_node


def validate_runtime_configuration(environ: Mapping[str, str]) -> None:
    missing = [name for name in _REQUIRED_VALUES if not str(environ.get(name) or "").strip()]
    if not str(environ.get("HF_TOKEN") or "").strip():
        missing.append("HF_TOKEN")
    if missing:
        raise CloudCoreStartupError("missing_configuration:" + ",".join(sorted(missing)))
    if len(str(environ["ALPECCA_AUTH_SECRET"]).encode("utf-8")) < 32:
        raise CloudCoreStartupError("authorization_secret_too_short")
    if len(str(environ["ALPECCA_CREATOR_PASSWORD"])) < 12:
        raise CloudCoreStartupError("creator_password_too_short")
    if str(environ.get("ALPECCA_CONTINUITY_ROLE")) != CONTINUITY_ROLE:
        raise CloudCoreStartupError("continuity_role_invalid")


def create_runtime_home(environ: Mapping[str, str]) -> Path:
    root = Path(
        str(environ.get("ALPECCA_CLOUD_RUNTIME_ROOT") or tempfile.gettempdir())
    ).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    runtime_home = Path(tempfile.mkdtemp(prefix="alpecca-hf-core-", dir=root))
    try:
        runtime_home.chmod(0o700)
    except OSError:
        pass
    return runtime_home


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore_latest_verified_archive(
    environ: Mapping[str, str],
    runtime_home: Path,
    *,
    vault_module: Any | None = None,
) -> RestoreReceipt:
    """Restore the latest authenticated Vault archive into a new runtime DB."""
    if vault_module is None:
        from alpecca import mindscape_vault as vault_module

    destination = (runtime_home / "alpecca.db").resolve()
    if destination.exists():
        raise CloudCoreStartupError("restore_destination_not_fresh")
    try:
        recovery_key, _key_source = vault_module.load_or_create_encryption_key(environ)
        transport_token, _token_source = vault_module.load_or_create_transport_token(environ)
    except Exception as exc:
        raise CloudCoreStartupError("vault_credentials_invalid") from exc

    try:
        timeout = float(environ.get("ALPECCA_CLOUD_RESTORE_TIMEOUT", "30"))
    except (TypeError, ValueError) as exc:
        raise CloudCoreStartupError("restore_timeout_invalid") from exc
    timeout = max(5.0, min(120.0, timeout))
    result = vault_module.fetch_latest_archive(
        str(environ["ALPECCA_MINDSCAPE_VAULT_URL"]),
        transport_token,
        recovery_key,
        destination,
        timeout=timeout,
    )
    if not isinstance(result, Mapping) or result.get("ok") is not True:
        status = result.get("status") if isinstance(result, Mapping) else "invalid_result"
        raise CloudCoreStartupError(f"vault_restore_failed:{_clean_status(status)}")
    try:
        restored_path = Path(str(result["path"])).resolve()
        sequence = int(result["sequence"])
        created_at = str(result["created_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CloudCoreStartupError("vault_restore_receipt_invalid") from exc
    if restored_path != destination or sequence < 0 or not destination.is_file():
        raise CloudCoreStartupError("vault_restore_receipt_invalid")
    return RestoreReceipt(
        path=destination,
        sequence=sequence,
        created_at=created_at,
        sha256=_file_sha256(destination),
    )


def server_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "server:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(APP_PORT),
        "--log-level",
        "warning",
        "--no-access-log",
    ]


class CloudCoreSupervisor:
    def __init__(
        self,
        *,
        environ: MutableMapping[str, str] | None = None,
        vault_module: Any | None = None,
        lease_client_factory: Callable[..., Any] = client_from_env,
        lease_guard_factory: Callable[..., Any] = ContinuityLeaseGuard,
        process_factory: Callable[..., Any] = subprocess.Popen,
        runtime_home_factory: Callable[[Mapping[str, str]], Path] = create_runtime_home,
        vrm_installer: Callable[[Path], Path] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.environ = os.environ if environ is None else environ
        self.vault_module = vault_module
        self.lease_client_factory = lease_client_factory
        self.lease_guard_factory = lease_guard_factory
        self.process_factory = process_factory
        self.runtime_home_factory = runtime_home_factory
        self.vrm_installer = vrm_installer
        self.sleep = sleep
        self._shutdown = threading.Event()
        self._lease_lost = threading.Event()
        self._child_lock = threading.Lock()
        self._child: Any | None = None

    def request_shutdown(self, *_args: object) -> None:
        self._shutdown.set()

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self.request_shutdown)
        signal.signal(signal.SIGINT, self.request_shutdown)

    def _handle_lease_loss(self, _reason: str) -> None:
        self._lease_lost.set()
        with self._child_lock:
            child = self._child
            if child is not None and child.poll() is None:
                self._signal_child(child, HARD_KILL_SIGNAL, "kill")

    def _spawn_child(self, guard: Any) -> Any:
        with self._child_lock:
            if self._lease_lost.is_set() or not guard.active:
                raise CloudCoreStartupError("lease_lost_before_start")
            child = self.process_factory(
                server_command(),
                cwd=str(REPO_ROOT),
                env=dict(self.environ),
                start_new_session=True,
            )
            self._child = child
            return child

    @staticmethod
    def _signal_child(child: Any, sig: int, fallback: str) -> None:
        pid = getattr(child, "pid", None)
        if os.name == "posix" and isinstance(pid, int) and pid > 0:
            try:
                os.killpg(pid, sig)
                return
            except (OSError, ProcessLookupError):
                pass
        getattr(child, fallback)()

    @staticmethod
    def _stop_child(child: Any, *, graceful: bool) -> None:
        if child.poll() is not None:
            return
        if graceful:
            CloudCoreSupervisor._signal_child(child, signal.SIGTERM, "terminate")
        else:
            CloudCoreSupervisor._signal_child(child, HARD_KILL_SIGNAL, "kill")
        try:
            child.wait(timeout=12.0 if graceful else 3.0)
        except subprocess.TimeoutExpired:
            CloudCoreSupervisor._signal_child(child, HARD_KILL_SIGNAL, "kill")
            child.wait(timeout=3.0)

    def run(self) -> int:
        endpoint = resolve_public_endpoint(self.environ)
        runtime_home = self.runtime_home_factory(self.environ)
        guard: Any | None = None
        child: Any | None = None
        try:
            configure_runtime(self.environ, runtime_home, endpoint)
            validate_runtime_configuration(self.environ)
            if self.vrm_installer is not None:
                installed_vrm = self.vrm_installer(runtime_home)
                if not isinstance(installed_vrm, Path) or not installed_vrm.is_file():
                    raise CloudCoreStartupError("locked_vrm_install_failed")
            receipt = restore_latest_verified_archive(
                self.environ,
                runtime_home,
                vault_module=self.vault_module,
            )
            print(
                "[hf-cloud-core] verified Vault restore "
                f"sequence={receipt.sequence} sha256={receipt.sha256}"
            )
            approval: RestoreApproval | None
            if str(self.environ.get("ALPECCA_CLOUD_RESTORE_APPROVAL") or "").strip():
                approval = load_restore_approval(self.environ, receipt)
            elif automatic_failover_authorized(self.environ):
                approval = None
                print(
                    "[hf-cloud-core] unattended promotion authorized by the "
                    "deployment failover policy"
                )
            else:
                approval = load_restore_approval(self.environ, receipt)

            client = self.lease_client_factory(role=CONTINUITY_ROLE)
            if client is None:
                raise CloudCoreStartupError("continuity_lease_not_configured")
            guard = self.lease_guard_factory(
                client,
                renew_seconds=LEASE_RENEW_SECONDS,
                endpoint="",
                on_loss=self._handle_lease_loss,
            )
            grant = guard.start()
            if self._lease_lost.is_set() or not guard.active:
                raise CloudCoreStartupError("lease_lost_before_endpoint_publication")
            if approval is not None:
                if approval.lease_epoch != grant.fencing_epoch:
                    raise CloudCoreStartupError("restore_approval_lease_epoch_mismatch")
                require_current_approval(approval)
            published = client.publish_endpoint(grant, endpoint)
            if not isinstance(published, Mapping) or published.get("ok") is not True:
                raise CloudCoreStartupError("lease_endpoint_publication_rejected")
            if self._lease_lost.is_set() or not guard.active:
                raise CloudCoreStartupError("lease_lost_before_start")
            if approval is not None:
                require_current_approval(approval)
            guard.endpoint = endpoint
            self.environ["ALPECCA_CONTINUITY_LEASE_ID"] = str(grant.lease_id)
            self.environ["ALPECCA_CONTINUITY_FENCING_EPOCH"] = str(grant.fencing_epoch)
            self.environ["ALPECCA_CONTINUITY_LEASE_HOLDER"] = str(grant.holder)
            self.environ["ALPECCA_RESTORE_APPROVAL_ID"] = (
                approval.approval_id
                if approval is not None
                else "deployment-auto-failover-v1"
            )
            self.environ.pop("ALPECCA_CLOUD_RESTORE_APPROVAL", None)

            child = self._spawn_child(guard)
            print(
                "[hf-cloud-core] cloud core started under continuity fence "
                f"epoch={grant.fencing_epoch}"
            )
            while True:
                if self._lease_lost.is_set() or not guard.active:
                    self._stop_child(child, graceful=False)
                    return LEASE_LOST_EXIT
                if self._shutdown.is_set():
                    self._stop_child(child, graceful=True)
                    return int(child.poll() or 0)
                exit_code = child.poll()
                if exit_code is not None:
                    return int(exit_code)
                self.sleep(0.25)
        finally:
            try:
                if child is not None and child.poll() is None:
                    self._stop_child(child, graceful=not self._lease_lost.is_set())
            finally:
                try:
                    if guard is not None:
                        guard.stop()
                finally:
                    with self._child_lock:
                        self._child = None
                    shutil.rmtree(runtime_home, ignore_errors=True)


def main(
    _argv: Sequence[str] | None = None,
    *,
    vrm_installer: Callable[[Path], Path] | None = None,
) -> int:
    supervisor = CloudCoreSupervisor(vrm_installer=vrm_installer)
    supervisor.install_signal_handlers()
    try:
        return supervisor.run()
    except CloudCoreStartupError as exc:
        print(f"[hf-cloud-core] startup blocked: {exc.code}", file=sys.stderr)
        return 2
    except ContinuityLeaseError:
        print("[hf-cloud-core] startup blocked: continuity_lease_unavailable", file=sys.stderr)
        return 3
    except Exception as exc:
        print(
            f"[hf-cloud-core] startup blocked: unexpected_{type(exc).__name__}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
