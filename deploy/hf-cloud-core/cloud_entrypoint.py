"""Standalone Docker Space entrypoint for the fenced cloud-core supervisor."""
from __future__ import annotations

import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Any, Mapping, NamedTuple, Protocol
import urllib.error
import urllib.request


VRM_URL = (
    "https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/"
    "main/runtime-assets/assets/vrm/alpecca-v4-live.vrm"
)
VRM_SHA256 = "0b6385de90be7c2401f94f8f2450c6a0e1198942ba11083e68a6c3233fde27d3"
MAX_VRM_BYTES = 32 * 1024 * 1024
REQUIRED_SECRETS = (
    "HF_TOKEN",
    "ALPECCA_CONTINUITY_LEASE_TOKEN",
    "ALPECCA_MINDSCAPE_VAULT_TOKEN",
    "ALPECCA_MINDSCAPE_VAULT_KEY",
    "ALPECCA_AUTH_SECRET",
    "ALPECCA_CREATOR_PASSWORD",
)
REQUIRED_URLS = (
    "ALPECCA_CONTINUITY_LEASE_URL",
    "ALPECCA_MINDSCAPE_VAULT_URL",
)
_TRUE_VALUES = {"1", "true", "yes", "on"}
STANDBY_SERVICE = "alpecca-continuity-standby"
STANDBY_POLL_SECONDS = 10.0
STANDBY_STATES = frozenset({
    "disabled",
    "configuration-required",
    "lease-unavailable",
    "waiting-for-singleton-lease",
})
VOICE_AUTHORIZATION_HEADER = "X-Alpecca-Authorization"
VOICE_SERVICE = "alpecca-cloud-kokoro-voice"
VOICE_PORT = 7861
MAX_VOICE_CREDENTIAL_CHARS = 512
MAX_VOICE_BODY_BYTES = 16 * 1024
MAX_VOICE_AUDIO_BYTES = 12 * 1024 * 1024
MAX_VOICE_HEALTH_BYTES = 16 * 1024
PROMOTION_HEALTH_GRACE_SECONDS = 300.0
PROMOTION_HEALTH_MARKER = (
    Path(os.environ.get("ALPECCA_CLOUD_RUNTIME_ROOT", "/tmp/alpecca-cloud-core"))
    / "promotion-health-grace"
)


def _load_supervisor_module():
    path = Path(__file__).with_name("app.py")
    spec = importlib.util.spec_from_file_location("alpecca_hf_cloud_supervisor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cloud supervisor module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


supervisor = _load_supervisor_module()


def configure_environment(environ: dict[str, str]) -> None:
    port = environ.get("PORT", "7860")
    public_url = environ.get("ALPECCA_PUBLIC_URL", "").strip().rstrip("/")
    if public_url:
        environ["ALPECCA_PUBLIC_ENDPOINT"] = public_url
    elif environ.get("SPACE_HOST", "").strip():
        environ["ALPECCA_PUBLIC_ENDPOINT"] = (
            "https://" + environ["SPACE_HOST"].strip()
        )
    forced = {
        "ALPECCA_SERVER_HOST": "0.0.0.0",
        "ALPECCA_SERVER_PORT": port,
        "ALPECCA_REMOTE": "1",
        "ALPECCA_PUBLIC_URL": public_url,
        "ALPECCA_LLM_BACKEND": "hf",
        "ALPECCA_HF_MODEL": "Qwen/Qwen3.5-9B",
        "ALPECCA_HF_PROVIDER": "auto",
        "ALPECCA_MODEL": "qwen3.5:9b",
        "ALPECCA_FAST_MODEL": "qwen3.5:9b",
        "ALPECCA_REFLECT_MODEL": "",
        "ALPECCA_REFLECT_THINK": "0",
        "ALPECCA_CHAT_CLOUD_MODEL": "",
        "ALPECCA_CHAT_ZEROGPU": "0",
        "ALPECCA_DEEP_BACKEND": "",
        "ALPECCA_STREAM_CHAT": "0",
        "ALPECCA_TTS_BACKEND": "kokoro",
        "ALPECCA_CLOUD_TTS_ENDPOINT": "",
        "ALPECCA_CLOUD_TTS_AUTHORIZATION": "",
        "ALPECCA_F5_WORKER": "0",
        "ALPECCA_DISCORD": "0",
        "ALPECCA_DISCORD_MEDIA": "0",
        "ALPECCA_DISCORD_VOICE": "0",
        "ALPECCA_COMPUTER_USE": "0",
        "ALPECCA_SIGHT": "0",
        "ALPECCA_FACE": "0",
        "ALPECCA_VOICE": "0",
        "ALPECCA_APPS": "",
        "ALPECCA_MINDSCAPE": "0",
        "ALPECCA_MINDSCAPE_VAULT": "0",
        "ALPECCA_CONTINUITY_ROLE": "cloud-standby",
    }
    environ.update(forced)
    environ.setdefault(
        "ALPECCA_CONTINUITY_NODE_ID",
        f"cloud-standby:{socket.gethostname()}"[:96],
    )


def validate_configuration(environ: dict[str, str]) -> list[str]:
    missing = [name for name in (*REQUIRED_SECRETS, *REQUIRED_URLS) if not environ.get(name, "").strip()]
    for name in REQUIRED_URLS:
        value = environ.get(name, "").strip()
        if value and not value.startswith("https://"):
            missing.append(f"{name}:https-required")
    return missing


def cloud_core_enabled(environ: dict[str, str]) -> bool:
    """Require an explicit deployment switch before any restore or lease work."""
    return str(environ.get("ALPECCA_CLOUD_CORE_ENABLED") or "").strip().lower() in _TRUE_VALUES


def begin_promotion_health_grace(*, now: float | None = None) -> None:
    """Allow the container probe to survive the bounded 7860 ownership gap."""
    marker = PROMOTION_HEALTH_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    staging = marker.with_suffix(".tmp")
    staging.write_text(
        f"{time.time() if now is None else float(now):.6f}",
        encoding="ascii",
    )
    os.replace(staging, marker)


def end_promotion_health_grace() -> None:
    PROMOTION_HEALTH_MARKER.unlink(missing_ok=True)


def promotion_eligible(status: object) -> bool:
    """Require positive authority evidence that no local or cloud owner exists."""
    if not isinstance(status, dict) or status.get("ok") is not True:
        return False
    if status.get("activeLeaseCount") != 0 or status.get("activeLease") is not None:
        return False
    return status.get("localPrimaryPreferred") is False


class VoiceBackendResponse(NamedTuple):
    status: int
    body: bytes
    content_type: str


class VoiceBackend(Protocol):
    def authorized(self, supplied: str | None) -> bool: ...

    def health(self) -> Mapping[str, Any]: ...

    def synthesize(self, body: bytes, authorization: str) -> VoiceBackendResponse: ...


class DisabledVoiceBackend:
    """Fail closed when standby voice authentication is unavailable."""

    def authorized(self, _supplied: str | None) -> bool:
        return False

    def health(self) -> Mapping[str, Any]:
        return {"state": "unavailable", "modelLoaded": False}

    def synthesize(self, _body: bytes, _authorization: str) -> VoiceBackendResponse:
        return VoiceBackendResponse(503, b"", "application/json")


class LoopbackVoiceBackend:
    """Bounded proxy to the isolated cloud_voice process on loopback only."""

    def __init__(
        self,
        *,
        secret: str,
        port: int = VOICE_PORT,
        opener=urllib.request.urlopen,
    ) -> None:
        if not secret or len(secret) > MAX_VOICE_CREDENTIAL_CHARS:
            raise ValueError("voice authorization secret is missing or malformed")
        if not 1 <= int(port) <= 65_535:
            raise ValueError("voice service port is invalid")
        self._expected_digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._base_url = f"http://127.0.0.1:{int(port)}"
        self._opener = opener

    def authorized(self, supplied: str | None) -> bool:
        value = supplied or ""
        if value[:7].casefold() == "bearer ":
            value = value[7:]
        malformed = not value or len(value) > MAX_VOICE_CREDENTIAL_CHARS
        candidate_value = "" if malformed else value
        candidate = hashlib.sha256(candidate_value.encode("utf-8")).digest()
        matched = hmac.compare_digest(candidate, self._expected_digest)
        return matched and not malformed

    def health(self) -> Mapping[str, Any]:
        request = urllib.request.Request(
            self._base_url + "/healthz",
            headers={"User-Agent": "Alpecca-Cloud-Standby-Voice/1"},
        )
        try:
            with self._opener(request, timeout=2.0) as response:
                body = response.read(MAX_VOICE_HEALTH_BYTES + 1)
            if len(body) > MAX_VOICE_HEALTH_BYTES:
                raise ValueError("voice health response exceeded limit")
            value = json.loads(body.decode("utf-8"))
            return value if isinstance(value, dict) else {"state": "unavailable"}
        except Exception:
            return {"state": "unavailable", "modelLoaded": False}

    def synthesize(self, body: bytes, authorization: str) -> VoiceBackendResponse:
        request = urllib.request.Request(
            self._base_url + "/v1/voice/synthesize",
            data=body,
            headers={
                "Content-Type": "application/json",
                VOICE_AUTHORIZATION_HEADER: authorization,
                "User-Agent": "Alpecca-Cloud-Standby-Voice/1",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=90.0) as response:
                result = response.read(MAX_VOICE_AUDIO_BYTES + 1)
                return VoiceBackendResponse(
                    int(getattr(response, "status", 200)),
                    result,
                    str(response.headers.get("Content-Type", "")),
                )
        except urllib.error.HTTPError as exc:
            return VoiceBackendResponse(int(exc.code), b"", "application/json")
        except Exception:
            return VoiceBackendResponse(503, b"", "application/json")


def _voice_backend_from_environment(environ: Mapping[str, str]) -> VoiceBackend:
    secret = (
        str(environ.get("ALPECCA_CLOUD_VOICE_SECRET") or "").strip()
        or str(environ.get("ALPECCA_AUTH_SECRET") or "").strip()
    )
    if not secret:
        return DisabledVoiceBackend()
    try:
        port = int(environ.get("ALPECCA_CLOUD_VOICE_PORT", str(VOICE_PORT)))
        return LoopbackVoiceBackend(secret=secret, port=port)
    except (TypeError, ValueError):
        return DisabledVoiceBackend()


def _voice_health_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a content-free allowlist and hard-code authority denials."""
    state = str(value.get("state") or "unavailable")
    if state not in {"ready", "unavailable"}:
        state = "unavailable"
    return {
        "service": VOICE_SERVICE,
        "version": 1,
        "state": state,
        "engine": "kokoro",
        "voice": "af_heart",
        "device": "cpu",
        "sampleRateHz": 24000,
        "modelLoaded": value.get("modelLoaded") is True,
        "persistence": False,
        "coreMind": False,
        "singletonAuthority": False,
        "maxBodyBytes": MAX_VOICE_BODY_BYTES,
    }


class _StandbyHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        route = self.path.split("?", 1)[0]
        if route == "/voice/health":
            backend = self.server.voice_backend  # type: ignore[attr-defined]
            self._send_json(200, _voice_health_metadata(backend.health()))
            return
        if route in {"/", "/healthz"}:
            self._send_json(200, {
                "service": STANDBY_SERVICE,
                "version": 1,
                "state": self.server.standby_state,  # type: ignore[attr-defined]
                "coreMind": False,
            })
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        route = self.path.split("?", 1)[0]
        if route != "/voice/tts":
            self._send_json(404, {"error": "not_found"})
            return
        backend = self.server.voice_backend  # type: ignore[attr-defined]
        authorization = self.headers.get(VOICE_AUTHORIZATION_HEADER)
        if not backend.authorized(authorization):
            self._send_json(401, {"error": "unauthorized"})
            return
        declared = self.headers.get("Content-Length")
        if declared is None:
            self._send_json(411, {"error": "content_length_required"})
            return
        try:
            length = int(declared)
        except ValueError:
            self._send_json(400, {"error": "invalid_content_length"})
            return
        if length < 0:
            self._send_json(400, {"error": "invalid_content_length"})
            return
        if length > MAX_VOICE_BODY_BYTES:
            self._send_json(413, {"error": "request_body_too_large"})
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._send_json(400, {"error": "incomplete_request_body"})
            return
        result = backend.synthesize(body, authorization or "")
        if result.status == 200:
            if (
                not result.body
                or len(result.body) > MAX_VOICE_AUDIO_BYTES
                or result.content_type.split(";", 1)[0].strip().lower() != "audio/wav"
            ):
                self._send_json(503, {"error": "voice_unavailable"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(result.body)))
            self.end_headers()
            self.wfile.write(result.body)
            return
        status = result.status if result.status in {400, 413, 422} else 503
        self._send_json(status, {"error": "voice_request_rejected"})

    def _send_json(self, status: int, value: Mapping[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _StandbyHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address,
        handler,
        *,
        voice_backend: VoiceBackend,
        standby_state: str,
    ) -> None:
        self.voice_backend = voice_backend
        self.standby_state = standby_state
        super().__init__(address, handler)


class StandbyServer:
    """A standby and voice-proxy listener; it never constructs CoreMind."""

    def __init__(
        self,
        port: int,
        *,
        voice_backend: VoiceBackend | None = None,
        environ: Mapping[str, str] | None = None,
        state: str = "waiting-for-singleton-lease",
    ) -> None:
        if state not in STANDBY_STATES:
            raise ValueError("invalid standby state")
        backend = voice_backend or _voice_backend_from_environment(environ or os.environ)
        self._server = _StandbyHttpServer(
            ("0.0.0.0", port),
            _StandbyHandler,
            voice_backend=backend,
            standby_state=state,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="AlpeccaCloudStandby",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=3.0)

    def set_state(self, state: str) -> None:
        if state not in STANDBY_STATES:
            raise ValueError("invalid standby state")
        self._server.standby_state = state


def standby_state(environ: dict[str, str]) -> str:
    """Describe sparse readiness without granting CoreMind authority."""
    if not cloud_core_enabled(environ):
        return "disabled"
    if validate_configuration(environ):
        return "configuration-required"
    return "waiting-for-singleton-lease"


def wait_in_sparse_standby(*, sleep=time.sleep) -> None:
    """Keep the public non-speaking health listener alive until shutdown."""
    while True:
        sleep(60.0)


def wait_until_promotion_eligible(client, *, sleep=time.sleep) -> None:
    """Poll authenticated status without restoring memory or starting a model."""
    while True:
        try:
            if promotion_eligible(client.status()):
                return
        except Exception:
            pass
        sleep(STANDBY_POLL_SECONDS)


def install_vrm(home: Path, opener=urllib.request.urlopen) -> Path:
    target = home / "avatar" / "vrm" / "alpecca.vrm"
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == VRM_SHA256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(VRM_URL, headers={"User-Agent": "Alpecca-Continuity-Core/1"})
    with opener(request, timeout=90) as response:
        data = response.read(MAX_VRM_BYTES + 1)
    if len(data) > MAX_VRM_BYTES or hashlib.sha256(data).hexdigest() != VRM_SHA256:
        raise RuntimeError("V.4 VRM integrity check failed")
    staging = target.with_suffix(".vrm.tmp")
    staging.write_bytes(data)
    os.replace(staging, target)
    return target


def main() -> int:
    configure_environment(os.environ)
    port = int(os.environ.get("PORT", "7860"))
    state = standby_state(os.environ)
    standby = StandbyServer(port, state=state)
    standby.start()
    print(
        f"Cloud continuity sparse standby is healthy ({state}); "
        "CoreMind is not active.",
        flush=True,
    )
    if state == "disabled":
        print(
            "Cloud continuity core is installed but disabled; no restore, lease, "
            "model, or CoreMind was started.",
            flush=True,
        )
        wait_in_sparse_standby()
    missing = validate_configuration(os.environ)
    if missing:
        print("Cloud continuity configuration is incomplete: " + ", ".join(missing), flush=True)
        wait_in_sparse_standby()
    while True:
        try:
            from alpecca.continuity_lease import client_from_env
            status_client = client_from_env(role="cloud-standby")
        except Exception:
            status_client = None
        if status_client is None:
            standby.set_state("lease-unavailable")
            time.sleep(STANDBY_POLL_SECONDS)
            continue
        standby.set_state("waiting-for-singleton-lease")
        wait_until_promotion_eligible(status_client)
        begin_promotion_health_grace()
        standby.stop()
        try:
            try:
                result, shutdown_requested = supervisor.run_supervisor_once(
                    vrm_installer=install_vrm,
                )
            except Exception:
                result, shutdown_requested = 1, False
        finally:
            end_promotion_health_grace()
        if shutdown_requested:
            return result
        standby = StandbyServer(port, state="waiting-for-singleton-lease")
        standby.start()
        print(
            f"Cloud promotion ended with code {result}; returning to fenced standby.",
            flush=True,
        )
        time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
