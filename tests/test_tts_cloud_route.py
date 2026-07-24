from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import config
from alpecca import auth as auth_mod
from alpecca import open_tts, tts
from alpecca.cloud_tts import (
    AUTHORIZATION_ENV,
    ENDPOINT_ENV,
    CloudTTSClient,
)


ENDPOINT = "https://voice.example.test/voice/tts"


@dataclass(frozen=True)
class FakeStatus:
    configured: bool
    reason: str = "configured_not_called"
    state: str = "unverified"

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "state": self.state,
            "reason": self.reason,
        }


class FakeCloudClient:
    def __init__(self, result, *, configured: bool = True) -> None:
        self.result = result
        self.calls: list[str] = []
        reason = "configured_not_called" if configured else "not_configured"
        state = "unverified" if configured else "unavailable"
        self._status = FakeStatus(configured, reason, state)

    def status(self) -> FakeStatus:
        return self._status

    def synthesize(self, text: str):
        self.calls.append(text)
        if self.result is None and self._status.configured:
            self._status = FakeStatus(True, "transport_error", "degraded")
        elif self.result is not None:
            self._status = FakeStatus(True, "ok", "ready")
        return self.result


def _quiet_voice_state(_state) -> dict[str, object]:
    return {}


def test_auto_uses_configured_cloud_before_local_routes(monkeypatch) -> None:
    cloud = FakeCloudClient(("audio/wav", b"cloud", {"http_status": 200}))
    local_calls = []
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(open_tts, "ready", lambda: True)
    monkeypatch.setattr(
        open_tts,
        "synth",
        lambda text, state: local_calls.append(("f5", text)) or None,
    )
    monkeypatch.setattr(
        tts,
        "_synth_kokoro",
        lambda text, state: local_calls.append(("kokoro", text)) or None,
    )
    monkeypatch.setattr(tts, "voice_state", _quiet_voice_state)

    result = tts.synth("private words")

    assert result == ("audio/wav", b"cloud")
    assert cloud.calls == ["private words"]
    assert local_calls == []
    assert tts._last_engine == "cloud"


def test_engine_status_requires_success_before_cloud_is_ready(monkeypatch) -> None:
    cloud = FakeCloudClient(("audio/wav", b"cloud", {}))
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(open_tts, "status", lambda: {"ready": False})
    monkeypatch.setattr(
        tts,
        "kokoro_status",
        lambda: {"installed": False, "state": "unavailable"},
    )

    unverified = tts.engine_status()

    assert unverified["cloud"]["state"] == "unverified"
    assert unverified["cloud"]["ready"] is None
    assert unverified["primary"] != "cloud"
    assert cloud.calls == []

    cloud.synthesize("successful words")
    ready = tts.engine_status()

    assert ready["cloud"]["state"] == "ready"
    assert ready["cloud"]["ready"] is True
    assert ready["primary"] == "cloud"


def test_engine_status_maps_cloud_failure_without_exposing_target(monkeypatch) -> None:
    cloud = FakeCloudClient(None)
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(open_tts, "status", lambda: {"ready": False})
    monkeypatch.setattr(
        tts,
        "kokoro_status",
        lambda: {"installed": False, "state": "unavailable"},
    )

    cloud.synthesize("failed words")
    status = tts.engine_status()

    assert status["cloud"]["state"] == "degraded"
    assert status["cloud"]["ready"] is False
    assert status["cloud"]["enabled"] is True
    assert status["primary"] != "cloud"
    exposed = json.dumps(status)
    assert "voice.example.test" not in exposed
    assert "/voice/tts" not in exposed
    assert "failed words" not in exposed


def test_auto_falls_back_to_f5_then_kokoro_after_cloud_failure(monkeypatch) -> None:
    cloud = FakeCloudClient(None)
    calls = []
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(open_tts, "ready", lambda: True)
    monkeypatch.setattr(tts, "_prefers_clone_voice", lambda state: True)
    monkeypatch.setattr(
        open_tts,
        "synth",
        lambda text, state: calls.append("f5") or None,
    )
    monkeypatch.setattr(
        tts,
        "_synth_kokoro",
        lambda text, state: calls.append("kokoro") or ("audio/wav", b"local"),
    )
    monkeypatch.setattr(tts, "voice_state", _quiet_voice_state)

    result = tts.synth("fallback words", state=object())

    assert result == ("audio/wav", b"local")
    assert cloud.calls == ["fallback words"]
    assert calls == ["f5", "kokoro"]


def test_explicit_local_overrides_never_call_cloud(monkeypatch) -> None:
    cloud = FakeCloudClient(("audio/wav", b"cloud", {}))
    calls = []
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(
        open_tts,
        "synth",
        lambda text, state: calls.append("f5") or ("audio/wav", b"f5"),
    )
    monkeypatch.setattr(
        tts,
        "_synth_kokoro",
        lambda text, state: calls.append("kokoro") or ("audio/wav", b"kokoro"),
    )
    monkeypatch.setattr(tts, "voice_state", _quiet_voice_state)

    assert tts.synth("one", backend_override="f5") == ("audio/wav", b"f5")
    assert tts.synth("two", backend_override="kokoro") == ("audio/wav", b"kokoro")
    assert cloud.calls == []
    assert calls == ["f5", "kokoro"]


def test_unconfigured_cloud_is_skipped_in_auto(monkeypatch) -> None:
    cloud = FakeCloudClient(None, configured=False)
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(open_tts, "ready", lambda: False)
    monkeypatch.setattr(tts, "_synth_kokoro", lambda text, state: ("audio/wav", b"local"))
    monkeypatch.setattr(tts, "voice_state", _quiet_voice_state)

    assert tts.synth("stays local") == ("audio/wav", b"local")
    assert cloud.calls == []


def test_explicit_cloud_falls_back_to_local_when_unconfigured(monkeypatch) -> None:
    cloud = FakeCloudClient(None, configured=False)
    calls = []
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(tts, "TTS_BACKEND", "cloud")
    monkeypatch.setattr(open_tts, "ready", lambda: True)
    monkeypatch.setattr(
        open_tts,
        "synth",
        lambda text, state: calls.append("f5") or ("audio/wav", b"f5"),
    )
    monkeypatch.setattr(
        tts,
        "_synth_kokoro",
        lambda text, state: calls.append("kokoro") or ("audio/wav", b"local"),
    )
    monkeypatch.setattr(tts, "voice_state", _quiet_voice_state)

    assert tts.synth("must still speak") == ("audio/wav", b"f5")
    assert cloud.calls == []
    assert calls == ["f5"]
    assert tts._last_error == ""


def test_config_reuses_protected_auth_only_when_endpoint_is_configured(
    monkeypatch,
) -> None:
    secret = "shared-protected-secret"
    calls = []
    monkeypatch.setattr(
        auth_mod,
        "load_or_create_authorization_secret",
        lambda home: calls.append(home) or secret,
    )

    assert config._cloud_tts_authorization(ENDPOINT, "") == secret
    assert calls == [config.HOME]
    assert config._cloud_tts_authorization("", "") == ""
    assert calls == [config.HOME]


def test_explicit_cloud_auth_wins_without_loading_shared_secret(monkeypatch) -> None:
    explicit = "explicit-cloud-secret"
    monkeypatch.setattr(
        auth_mod,
        "load_or_create_authorization_secret",
        lambda home: (_ for _ in ()).throw(AssertionError("loader called")),
    )

    assert config._cloud_tts_authorization(ENDPOINT, explicit) == explicit


def test_loader_failure_leaves_cloud_unconfigured_and_falls_back_locally(
    monkeypatch,
) -> None:
    network_calls = []
    monkeypatch.setattr(
        auth_mod,
        "load_or_create_authorization_secret",
        lambda home: (_ for _ in ()).throw(RuntimeError("credential unavailable")),
    )
    authorization = config._cloud_tts_authorization(ENDPOINT, "")
    cloud = CloudTTSClient.from_env(
        {ENDPOINT_ENV: ENDPOINT, AUTHORIZATION_ENV: authorization},
        opener=lambda *args, **kwargs: network_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(open_tts, "ready", lambda: False)
    monkeypatch.setattr(
        tts,
        "_synth_kokoro",
        lambda text, state: ("audio/wav", b"local"),
    )
    monkeypatch.setattr(tts, "voice_state", _quiet_voice_state)

    assert tts.synth("local-only words") == ("audio/wav", b"local")
    assert cloud.status().reason == "configuration_invalid"
    assert network_calls == []


def test_cloud_status_and_errors_never_expose_loaded_secret(
    monkeypatch,
    capsys,
) -> None:
    secret = "status-must-not-contain-this-secret"
    private_text = "status-must-not-contain-this-text"
    monkeypatch.setattr(
        auth_mod,
        "load_or_create_authorization_secret",
        lambda home: secret,
    )
    authorization = config._cloud_tts_authorization(ENDPOINT, "")

    def fail_with_secret(*args, **kwargs):
        raise RuntimeError(secret)

    cloud = CloudTTSClient.from_env(
        {ENDPOINT_ENV: ENDPOINT, AUTHORIZATION_ENV: authorization},
        opener=fail_with_secret,
    )
    monkeypatch.setattr(tts, "_cloud_tts_client", cloud)
    monkeypatch.setattr(tts, "TTS_BACKEND", "cloud")
    monkeypatch.setattr(open_tts, "ready", lambda: False)
    monkeypatch.setattr(tts, "_synth_kokoro", lambda text, state: None)

    assert tts.synth(private_text) is None
    exposed = (
        repr(cloud.status())
        + json.dumps(cloud.status().as_dict())
        + tts._last_error
        + capsys.readouterr().err
    )
    assert secret not in exposed
    assert private_text not in exposed
    assert cloud.status().reason == "transport_error"


def test_run_full_derives_only_cloud_endpoint_and_does_not_invent_secret() -> None:
    root = Path(__file__).resolve().parent.parent
    source = (root / "scripts" / "run_full.py").read_text(encoding="utf-8")

    assert '"ALPECCA_CLOUD_TTS_ENDPOINT"' in source
    assert 'os.environ["ALPECCA_CLOUD_STANDBY_URL"].rstrip("/")' in source
    assert '"/voice/tts"' in source
    assert "ALPECCA_CLOUD_TTS_AUTHORIZATION" not in source
