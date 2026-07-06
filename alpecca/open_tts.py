"""Open-source cloned/emotional TTS bridge for Alpecca.

This module is intentionally optional. F5-TTS and IndexTTS2 are heavier than
Kokoro and can have fragile Windows dependencies, so the main app should never
hard-fail if they are missing. When an open engine is installed, this becomes
Alpecca's primary voice path; when not, Kokoro remains the stable fallback.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from config import (
    F5_WORKER_ENABLED,
    F5_WORKER_HOST,
    F5_WORKER_PORT,
    F5_WORKER_TIMEOUT,
    OPEN_TTS_DEVICE,
    OPEN_TTS_ENGINE,
    OPEN_TTS_LOCAL_MODEL_DIR,
    OPEN_TTS_NFE_STEP,
    OPEN_TTS_PYTHON,
    OPEN_TTS_REFERENCE_MANIFEST,
    OPEN_TTS_TIMEOUT,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV_PYTHON = ROOT / ".venv-f5-tts" / "Scripts" / "python.exe"
READY_SAMPLE = ROOT / "data" / "voice_references" / "generated_samples" / "alpecca_f5_open_tts_sample.wav"
LOCAL_MODEL_DIR = Path(OPEN_TTS_LOCAL_MODEL_DIR)
LOCAL_CKPT = LOCAL_MODEL_DIR / "model_1250000.safetensors"
LOCAL_VOCAB = LOCAL_MODEL_DIR / "vocab.txt"
_last_error = ""
_last_engine = ""
_last_reference: dict = {}
_last_worker: dict = {}


def _load_manifest() -> dict:
    path = Path(OPEN_TTS_REFERENCE_MANIFEST)
    if not path.is_absolute():
        path = ROOT / path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _emotion_primary(state) -> str:
    if state is None:
        return "content"
    try:
        from alpecca import affect as affect_mod

        return str(affect_mod.affect(state).primary or "content").lower()
    except Exception:
        return "content"


def select_reference(state=None, preview: str = "") -> dict:
    manifest = _load_manifest()
    refs = [r for r in manifest.get("references", []) if isinstance(r, dict) and r.get("audio")]
    if not refs:
        return {}
    wanted = (preview or _emotion_primary(state) or "content").lower()
    aliases = {
        "joyful": "curious",
        "playful": "curious",
        "content": "current",
        "affectionate": "tender",
        "wistful": "vulnerable",
        "lonely": "vulnerable",
        "withdrawn": "vulnerable",
        "worried": "worried",
        "anxious": "anxious",
        "sleepy": "tender",
    }
    wanted = aliases.get(wanted, wanted)
    for ref in refs:
        roles = [str(role).lower() for role in ref.get("roles", [])]
        if wanted in roles or wanted == str(ref.get("id", "")).lower():
            return ref
    default_id = manifest.get("default", "")
    for ref in refs:
        if ref.get("id") == default_id:
            return ref
    return refs[0]


def _f5_cli() -> list[str] | None:
    direct = shutil.which("f5-tts_infer-cli")
    if direct:
        return [direct]
    py = Path(OPEN_TTS_PYTHON) if OPEN_TTS_PYTHON else DEFAULT_VENV_PYTHON
    if py.exists():
        return [str(py), "-m", "f5_tts.infer.infer_cli"]
    return None


def _f5_model_cache_status() -> dict:
    """Cheap health readout for the Hugging Face F5 model cache.

    F5 can look "installed" while the real model weights are only half
    downloaded. In that state the CLI may sit for minutes and the app feels
    broken. We keep this check read-only and use it for status/doctor output.
    """
    cache_root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    hub = cache_root / "hub"
    model_dir = hub / "models--SWivid--F5-TTS"
    incomplete = []
    complete_bytes = 0
    largest_complete = 0
    if model_dir.exists():
        for path in model_dir.rglob("*"):
            if not path.is_file():
                continue
            size = path.stat().st_size
            if path.name.endswith(".incomplete"):
                incomplete.append({"path": str(path), "mb": round(size / 1048576, 1)})
            else:
                complete_bytes += size
                largest_complete = max(largest_complete, size)
    # The main F5 checkpoint is hundreds of MB. This is intentionally a broad
    # heuristic so status can warn about a partial cache without knowing every
    # future filename the upstream project may use.
    weights_present = largest_complete > 200 * 1024 * 1024
    local_weights_present = LOCAL_CKPT.exists() and LOCAL_CKPT.stat().st_size > 1000 * 1024 * 1024
    return {
        "cache_dir": str(model_dir),
        "exists": model_dir.exists(),
        "weights_present": weights_present or local_weights_present,
        "local_model_dir": str(LOCAL_MODEL_DIR),
        "local_checkpoint": str(LOCAL_CKPT),
        "local_checkpoint_mb": round((LOCAL_CKPT.stat().st_size if LOCAL_CKPT.exists() else 0) / 1048576, 1),
        "local_vocab": str(LOCAL_VOCAB),
        "local_vocab_present": LOCAL_VOCAB.exists(),
        "complete_mb": round(complete_bytes / 1048576, 1),
        "largest_complete_mb": round(largest_complete / 1048576, 1),
        "incomplete_count": len(incomplete),
        "incomplete": incomplete[:4],
    }


def _subprocess_env() -> dict:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("WANDB_MODE", "disabled")
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        import imageio_ffmpeg

        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        env["PATH"] = str(ffmpeg.parent) + os.pathsep + env.get("PATH", "")
        env.setdefault("FFMPEG_BINARY", str(ffmpeg))
    except Exception:
        pass
    return env


def _worker_url(path: str) -> str:
    return f"http://{F5_WORKER_HOST}:{F5_WORKER_PORT}{path}"


def _worker_health(timeout: float = 0.45) -> dict:
    if not F5_WORKER_ENABLED:
        return {"enabled": False, "ready": False}
    try:
        with urllib.request.urlopen(_worker_url("/health"), timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            payload["enabled"] = True
            payload["url"] = _worker_url("")
            return payload
    except Exception as exc:
        return {"enabled": True, "ready": False, "url": _worker_url(""), "error": f"{type(exc).__name__}: {exc}"}


def _worker_synth(text: str, ref: dict):
    global _last_error, _last_engine, _last_reference, _last_worker
    if not F5_WORKER_ENABLED:
        return None
    ref_audio = Path(str(ref.get("audio", "")))
    if not ref_audio.is_absolute():
        ref_audio = ROOT / ref_audio
    body = json.dumps({
        "text": text,
        "ref_audio": str(ref_audio),
        "ref_text": str(ref.get("text") or ""),
        "nfe_step": max(4, int(OPEN_TTS_NFE_STEP)),
    }).encode("utf-8")
    req = urllib.request.Request(
        _worker_url("/synth"),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=max(3.0, float(F5_WORKER_TIMEOUT))) as resp:
            if resp.status != 200:
                _last_error = f"F5 worker returned HTTP {resp.status}"
                return None
            data = resp.read()
            try:
                _last_worker = json.loads(resp.headers.get("X-Alpecca-F5-Worker") or "{}")
            except Exception:
                _last_worker = {}
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        _last_error = f"F5 worker HTTPError: {detail[-400:]}"
        return None
    except Exception as exc:
        _last_error = f"F5 worker unavailable: {type(exc).__name__}: {exc}"
        return None
    if len(data) < 1024:
        _last_error = "F5 worker returned empty audio"
        return None
    _last_engine = "f5-tts-worker"
    _last_reference = {
        "id": ref.get("id", ""),
        "roles": ref.get("roles", []),
        "source": ref.get("source", ""),
    }
    _last_worker.setdefault("round_trip_seconds", round(time.perf_counter() - started, 3))
    return "audio/wav", data, {
        "engine": _last_engine,
        "reference": _last_reference,
        "profile": "alpecca_kling_reference_f5_worker",
        "worker": _last_worker,
    }


def available() -> bool:
    if OPEN_TTS_ENGINE not in ("auto", "f5", "f5-tts"):
        return False
    worker = _worker_health()
    return bool(worker.get("ready") or _f5_cli())


def ready() -> bool:
    worker = _worker_health()
    if worker.get("ready"):
        return True
    if os.environ.get("ALPECCA_OPEN_TTS_READY", "") in ("1", "true", "True", "yes"):
        return available()
    cache = _f5_model_cache_status()
    if cache.get("local_checkpoint_mb", 0) > 1000 and cache.get("local_vocab_present"):
        return available() and READY_SAMPLE.exists() and READY_SAMPLE.stat().st_size > 1024
    return (
        available()
        and READY_SAMPLE.exists()
        and READY_SAMPLE.stat().st_size > 1024
        and not cache.get("incomplete_count")
    )


def status() -> dict:
    manifest = _load_manifest()
    refs = manifest.get("references", []) if isinstance(manifest.get("references"), list) else []
    return {
        "engine": OPEN_TTS_ENGINE,
        "f5_available": bool(_f5_cli()),
        "ready": ready(),
        "ready_sample": str(READY_SAMPLE),
        "device": OPEN_TTS_DEVICE,
        "nfe_step": OPEN_TTS_NFE_STEP,
        "cache": _f5_model_cache_status(),
        "worker": _worker_health(),
        "manifest": str(Path(OPEN_TTS_REFERENCE_MANIFEST)),
        "references": len([r for r in refs if isinstance(r, dict) and r.get("audio")]),
        "default": manifest.get("default", ""),
        "last_engine": _last_engine,
        "last_error": _last_error,
        "last_reference": _last_reference,
    }


def synth(text: str, state=None, preview: str = ""):
    """Return (mime, bytes, metadata) or None.

    The first implementation uses F5-TTS CLI because it is the most practical
    open-source clone engine to install locally. IndexTTS2 can be added behind
    this same interface later without changing server/UI code.
    """
    global _last_error, _last_engine, _last_reference
    _last_error = ""
    _last_engine = ""
    _last_reference = {}
    if OPEN_TTS_ENGINE not in ("auto", "f5", "f5-tts"):
        _last_error = f"open TTS engine {OPEN_TTS_ENGINE!r} is not enabled"
        return None
    ref = select_reference(state, preview)
    if not ref:
        _last_error = "No Alpecca open TTS reference manifest is available."
        return None
    ref_audio = Path(str(ref.get("audio", "")))
    if not ref_audio.is_absolute():
        ref_audio = ROOT / ref_audio
    ref_text = str(ref.get("text") or "").strip()
    if not ref_audio.exists() or not ref_text:
        _last_error = f"Reference {ref.get('id') or '?'} is incomplete."
        return None
    cache = _f5_model_cache_status()
    if cache.get("incomplete_count") and not cache.get("weights_present"):
        _last_error = (
            "F5-TTS model download is incomplete. Run "
            "python scripts\\warm_open_tts.py to finish the model cache."
        )
        return None

    worker_status = _worker_health()
    worker = _worker_synth(text, ref) if worker_status.get("ready") else None
    if worker:
        return worker
    if worker_status.get("ready"):
        # In auto mode, return None so tts.synth can use Kokoro's fast
        # original-voice fallback. Do not fall through to the cold CLI path when
        # the warmed worker had a per-request issue.
        return None

    cli = _f5_cli()
    if not cli:
        _last_error = "F5-TTS is not installed. Run scripts\\setup_f5_tts.ps1 or set ALPECCA_OPEN_TTS_PYTHON."
        return None

    with tempfile.TemporaryDirectory(prefix="alpecca_f5_") as td:
        out = Path(td) / "alpecca_open_tts.wav"
        cmd = [
            *cli,
            "--model",
            "F5TTS_v1_Base",
            "--ref_audio",
            str(ref_audio),
            "--ref_text",
            ref_text,
            "--gen_text",
            text,
            "--output_file",
            str(out),
            "--device",
            OPEN_TTS_DEVICE,
            "--nfe_step",
            str(max(4, int(OPEN_TTS_NFE_STEP))),
        ]
        if LOCAL_CKPT.exists() and LOCAL_CKPT.stat().st_size > 1000 * 1024 * 1024:
            cmd.extend(["--ckpt_file", str(LOCAL_CKPT)])
            if LOCAL_VOCAB.exists():
                cmd.extend(["--vocab_file", str(LOCAL_VOCAB)])
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                env=_subprocess_env(),
                text=True,
                capture_output=True,
                timeout=max(5.0, float(OPEN_TTS_TIMEOUT)),
            )
        except subprocess.TimeoutExpired:
            _last_error = f"F5-TTS timed out after {OPEN_TTS_TIMEOUT:.0f}s"
            return None
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            return None
        if proc.returncode != 0:
            _last_error = (proc.stderr or proc.stdout or f"F5-TTS exited {proc.returncode}")[-800:]
            return None
        if not out.exists() or out.stat().st_size < 1024:
            _last_error = "F5-TTS completed without producing audio."
            return None
        data = out.read_bytes()
    _last_engine = "f5-tts"
    _last_reference = {
        "id": ref.get("id", ""),
        "roles": ref.get("roles", []),
        "source": ref.get("source", ""),
    }
    return "audio/wav", data, {
        "engine": _last_engine,
        "reference": _last_reference,
        "profile": "alpecca_kling_reference_f5",
        "worker": _last_worker,
    }
