from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from alpecca import holyrog_voice, tts


ROOT = Path(__file__).resolve().parents[1]
SECRET_MANAGER_PATH = ROOT / "scripts" / "manage_holyrog_voice_secret.py"
ENDPOINT = "http://jason-holyrog.tailda0108.ts.net:8790"


def _secret_manager_module():
    spec = importlib.util.spec_from_file_location(
        "holyrog_voice_secret_primary_test", SECRET_MANAGER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Remote:
    enabled = True

    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[str] = []

    def synthesize(self, text: str):
        self.calls.append(text)
        return self.result

    def status(self) -> dict[str, object]:
        return {
            "engine": "holyrog-xtts",
            "configured": True,
            "state": "ready",
            "cooldown_active": False,
        }


def test_client_reads_dedicated_credential_and_restricts_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("ALPECCA_HOLYROG_VOICE_SECRET", raising=False)
    monkeypatch.setattr(holyrog_voice, "_credential_secret", lambda: "v" * 32)
    monkeypatch.setenv("ALPECCA_HOLYROG_VOICE_URL", ENDPOINT)

    assert holyrog_voice.HolyrogVoiceClient().enabled is True

    monkeypatch.setenv(
        "ALPECCA_HOLYROG_VOICE_URL", "https://unrelated.example.test:8790"
    )
    assert holyrog_voice.HolyrogVoiceClient().enabled is False


def test_environment_secret_precedes_credential_without_exposing_it(monkeypatch) -> None:
    explicit = "e" * 32
    monkeypatch.setenv("ALPECCA_HOLYROG_VOICE_URL", ENDPOINT)
    monkeypatch.setenv("ALPECCA_HOLYROG_VOICE_SECRET", explicit)
    monkeypatch.setattr(
        holyrog_voice,
        "_credential_secret",
        lambda: (_ for _ in ()).throw(AssertionError("credential reader called")),
    )

    client = holyrog_voice.HolyrogVoiceClient()

    assert client.enabled is True
    assert explicit not in json.dumps(client.status())
    assert "tailda0108" not in json.dumps(client.status())


def test_secret_manager_decodes_windows_utf16_blob_without_nuls() -> None:
    manager = _secret_manager_module()
    value = "d" * 43

    decoded = manager._decode_credential_blob(
        memoryview((value + "\x00").encode("utf-16-le")), source="test credential"
    )

    assert decoded == value
    assert "\x00" not in decoded


def test_auto_voice_uses_holyrog_before_local(monkeypatch) -> None:
    remote = _Remote(("audio/wav", b"remote-audio"))
    monkeypatch.setattr(holyrog_voice, "_client", remote)
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(tts, "voice_state", lambda _state: {})
    monkeypatch.setattr(
        tts,
        "_synth_kokoro",
        lambda *_args: (_ for _ in ()).throw(AssertionError("local route called")),
    )
    monkeypatch.setattr(
        "alpecca.open_tts.ready", lambda: False
    )

    assert tts.synth("private words") == ("audio/wav", b"remote-audio")
    assert remote.calls == ["private words"]
    assert tts._last_engine == "holyrog-xtts"


def test_engine_status_only_labels_holyrog_primary_for_auto(monkeypatch) -> None:
    remote = _Remote(("audio/wav", b"remote-audio"))
    monkeypatch.setattr(holyrog_voice, "_client", remote)
    monkeypatch.setattr("alpecca.open_tts.status", lambda: {"ready": False})
    monkeypatch.setattr(tts, "kokoro_status", lambda: {"installed": False})
    monkeypatch.setattr(tts.importlib.util, "find_spec", lambda _name: None)

    monkeypatch.setattr(tts, "TTS_BACKEND", "kokoro")
    assert tts.engine_status()["primary"] != "holyrog-xtts"

    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    assert tts.engine_status()["primary"] == "holyrog-xtts"


def test_auto_voice_falls_back_locally_when_holyrog_is_down(monkeypatch) -> None:
    remote = _Remote(None)
    monkeypatch.setattr(holyrog_voice, "_client", remote)
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(tts, "voice_state", lambda _state: {})
    monkeypatch.setattr("alpecca.open_tts.ready", lambda: False)
    monkeypatch.setattr(
        tts, "_synth_kokoro", lambda *_args: ("audio/wav", b"local-audio")
    )

    assert tts.synth("fallback words") == ("audio/wav", b"local-audio")
    assert remote.calls == ["fallback words"]


def test_explicit_kokoro_identity_route_is_not_substituted(monkeypatch) -> None:
    remote = _Remote(("audio/wav", b"remote-audio"))
    monkeypatch.setattr(holyrog_voice, "_client", remote)
    monkeypatch.setattr(tts, "voice_state", lambda _state: {})
    monkeypatch.setattr(
        tts, "_synth_kokoro", lambda *_args: ("audio/wav", b"kokoro-audio")
    )

    result = tts.synth("discord words", backend_override="kokoro")

    assert result == ("audio/wav", b"kokoro-audio")
    assert remote.calls == []
