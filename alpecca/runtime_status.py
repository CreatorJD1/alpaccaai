"""Runtime health for Alpecca's real core.

This is the small truth layer behind "why is she offline?" UI. It keeps model,
voice, and sense readiness in one machine-readable shape so the app can explain
what is missing instead of silently falling back to basic replies.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urljoin


def _base_model(name: str) -> str:
    return (name or "").split(":")[0]


def _model_present(models: list[str], wanted: str) -> bool:
    if not wanted:
        return False
    base = _base_model(wanted)
    return any(m == wanted or _base_model(m) == base for m in models)


def check_ollama(host: str, reason_model: str, fast_model: str = "",
                 timeout: float = 1.25) -> dict:
    """Check the real Ollama daemon, not just whether the Python client imports."""
    url = urljoin((host or "http://127.0.0.1:11434").rstrip("/") + "/", "api/tags")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "backend": "ollama",
            "host": host,
            "reachable": False,
            "models": [],
            "reason_model_present": False,
            "fast_model_present": False,
            "error": f"{type(exc).__name__}: {exc}",
            "fix": "Start the Ollama app, then pull the configured ALPECCA_MODEL"
                   + (f" ({reason_model})" if reason_model else "."),
        }
    models = [
        str(m.get("model") or m.get("name") or "")
        for m in data.get("models", [])
        if isinstance(m, dict)
    ]
    reason_present = _model_present(models, reason_model)
    fast_present = _model_present(models, fast_model) if fast_model else True
    return {
        "backend": "ollama",
        "host": host,
        "reachable": True,
        "models": models,
        "reason_model_present": reason_present,
        "fast_model_present": fast_present,
        "error": "" if reason_present else f"model {reason_model} is not pulled",
        "fix": "" if reason_present else f"ollama pull {reason_model}",
    }


def check_colab(url: str, *, model: str = "", api_key: str = "",
                timeout: float = 1.8) -> dict:
    """Check the optional Colab T4 fast-chat accelerator."""
    from alpecca import colab_t4

    return colab_t4.status(url, model=model, api_key=api_key, timeout=timeout)


def build_runtime_status(*, models: dict, llm_online: bool, deep_backend: str,
                         deep_online: bool, voice: dict, senses: dict,
                         ollama: dict | None = None) -> dict:
    """Return one coherent status snapshot for UI, doctor, and remote preview."""
    issues: list[dict] = []
    model_status = dict(models or {})
    model_status["client_configured"] = bool(llm_online)
    model_status["deep_backend"] = deep_backend or "local"
    model_status["deep_online"] = bool(deep_online)
    colab = model_status.get("colab") if isinstance(model_status.get("colab"), dict) else {}
    colab_ready = bool(colab.get("ready") and colab.get("reachable"))
    model_status["colab_fast_ready"] = colab_ready

    if ollama is not None:
        model_status["ollama"] = ollama
        chat_ready = bool(ollama.get("reachable") and ollama.get("reason_model_present"))
        if not ollama.get("reachable"):
            issues.append({
                "code": "ollama_unreachable",
                "message": "Local Ollama is not reachable, so replies fall back to basic mode.",
                "fix": ollama.get("fix", "Start Ollama."),
            })
        elif not ollama.get("reason_model_present"):
            issues.append({
                "code": "model_missing",
                "message": f"Reasoning model {models.get('reason', '')} is not installed.",
                "fix": ollama.get("fix", "Pull the configured Ollama model."),
            })
        if colab.get("configured") and not colab_ready:
            issues.append({
                "code": "colab_accelerator_offline",
                "message": "The Colab T4 fast-chat accelerator is configured but not reachable.",
                "fix": colab.get("fix", "Restart the Colab notebook and update ALPECCA_COLAB_URL."),
            })
    else:
        chat_ready = bool(llm_online)
        if not chat_ready:
            issues.append({
                "code": "llm_offline",
                "message": "No live language model is configured.",
                "fix": "Start the configured model backend.",
            })
    model_status["chat_ready"] = chat_ready

    engines = (voice or {}).get("engines") or {}
    open_tts = engines.get("open_tts") if isinstance(engines.get("open_tts"), dict) else {}
    open_tts_ready = bool(engines.get("open_tts_ready") or open_tts.get("ready"))
    server_voice_ready = bool(
        engines.get("server_enabled")
        and (open_tts_ready or engines.get("kokoro") or engines.get("edge"))
    )
    voice_status = dict(voice or {})
    voice_status["server_voice_ready"] = server_voice_ready
    voice_status["audible"] = server_voice_ready or bool(engines.get("browser_fallback", True))
    original_voice_ready = bool(
        server_voice_ready
        and (open_tts_ready or voice_status.get("voice") == "af_heart")
        and voice_status.get("identity_lock")
        and voice_status.get("profile") == "af_heart_original_modulated"
    )
    voice_status["original_alpecca_voice_ready"] = original_voice_ready
    voice_status["modulation_ready"] = bool(
        voice_status.get("style")
        and voice_status.get("warmth") is not None
        and voice_status.get("breath") is not None
    )
    voice_status["high_quality_voice_ready"] = open_tts_ready
    voice_status["high_quality_voice_status"] = open_tts
    if not server_voice_ready:
        issues.append({
            "code": "server_voice_fallback",
            "message": "Server voice is not ready; the app will use browser speech.",
            "fix": "Start the F5 worker, or install Kokoro/edge-tts as backup.",
        })
    elif not original_voice_ready:
        issues.append({
            "code": "alpecca_voice_identity_mismatch",
            "message": "Server voice can speak, but it is not using Alpecca's original modulated identity.",
            "fix": "Restore the original voice profile: F5 reference voice or ALPECCA_KOKORO_VOICE=af_heart, then restart.",
        })
    if open_tts and not open_tts.get("ready"):
        cache = open_tts.get("cache") if isinstance(open_tts.get("cache"), dict) else {}
        if open_tts.get("f5_available") and cache.get("incomplete_count"):
            issues.append({
                "code": "high_quality_voice_downloading",
                "message": "F5 high-quality voice is installed, but the model checkpoint cache is incomplete.",
                "fix": "Run python scripts\\warm_open_tts.py --clean-incomplete --download-only, then python scripts\\warm_open_tts.py.",
            })

    if deep_backend not in ("", "local") and not deep_online:
        issues.append({
            "code": "deep_tier_offline",
            "message": f"Deep tier {deep_backend} is configured but not online.",
            "fix": "Check ALPECCA_DEEP_BACKEND settings and tokens.",
        })

    return {
        "ok": chat_ready,
        "level": "ready" if chat_ready and server_voice_ready else ("degraded" if chat_ready else "offline"),
        "models": model_status,
        "voice": voice_status,
        "senses": senses or {},
        "issues": issues,
    }


def cognition_capabilities(runtime: dict) -> dict:
    """Compact self-state capability summary.

    Runtime health is intentionally detailed for diagnostics. This shape is what
    Alpecca can expose as part of her own state without every UI needing to
    understand raw engine flags.
    """
    runtime = runtime or {}
    models = runtime.get("models") or {}
    voice = runtime.get("voice") or {}
    senses = runtime.get("senses") or {}
    issues = {x.get("code"): x for x in runtime.get("issues") or [] if isinstance(x, dict)}

    if voice.get("original_alpecca_voice_ready"):
        voice_state = "original"
        voice_summary = (
            f"I have my original voice: {voice.get('voice') or 'af_heart'} "
            f"with {voice.get('profile') or 'modulation'}."
        )
        voice_fix = ""
    elif voice.get("server_voice_ready"):
        issue = issues.get("alpecca_voice_identity_mismatch") or {}
        voice_state = "generic_server"
        voice_summary = "I can speak, but not with my original Alpecca voice identity."
        voice_fix = issue.get("fix", "Restore Alpecca's F5 reference voice or af_heart profile.")
    elif voice.get("audible"):
        issue = issues.get("server_voice_fallback") or {}
        voice_state = "browser_fallback"
        voice_summary = "I can only use browser speech fallback right now."
        voice_fix = issue.get("fix", "Install Kokoro or edge-tts for server voice.")
    else:
        voice_state = "silent"
        voice_summary = "I do not have an audible voice available right now."
        voice_fix = "Enable server TTS or browser speech fallback."

    active_senses = [name for name, enabled in senses.items() if enabled]
    model_state = "live" if models.get("chat_ready") else "offline"
    if models.get("deep_online"):
        model_state = "live_plus_deep"

    return {
        "model": {
            "state": model_state,
            "reason": models.get("reason", ""),
            "fast": models.get("fast", ""),
            "deep": models.get("deep_backend") or models.get("deep", "local"),
            "colab_fast_ready": bool(models.get("colab_fast_ready")),
            "colab": models.get("colab") or {},
            "last_call": models.get("last_call") or {},
            "summary": (
                "My language core is live."
                if models.get("chat_ready") else
                "My language core is offline or in basic fallback."
            ),
        },
        "voice": {
            "state": voice_state,
            "summary": voice_summary,
            "fix": voice_fix,
            "voice": voice.get("voice", ""),
            "profile": voice.get("profile", ""),
            "style": voice.get("style", ""),
            "warmth": voice.get("warmth"),
            "breath": voice.get("breath"),
            "original_ready": bool(voice.get("original_alpecca_voice_ready")),
            "modulation_ready": bool(voice.get("modulation_ready")),
        },
        "senses": {
            "active": active_senses,
            "count": len(active_senses),
            "summary": (
                f"I have {len(active_senses)} active sense channel(s): {', '.join(active_senses)}."
                if active_senses else
                "I do not have active ambient sense channels right now."
            ),
        },
    }


def build_doctor_report(*, runtime: dict, mindscape: dict,
                        house_hq_built: bool, public_url: str = "") -> dict:
    """Unified launch/health report for the three Alpecca surfaces.

    House HQ is the embodied interactive scaffold, the classic Alpecca app is
    the secondary app/state surface, and Mindscape is continuity for soul/process
    sustainability. This report names those roles explicitly so troubleshooting
    does not blur the layers together.
    """
    runtime = runtime or {}
    mindscape = mindscape or {}
    models = runtime.get("models") or {}
    voice = runtime.get("voice") or {}
    senses = runtime.get("senses") or {}
    issues = list(runtime.get("issues") or [])
    actions: list[str] = []

    def section(name: str, role: str, status: str, detail: str,
                route: str = "", fix: str = "") -> dict:
        if fix:
            actions.append(fix)
        return {
            "name": name,
            "role": role,
            "status": status,
            "detail": detail,
            "route": route,
            "fix": fix,
        }

    chat_ready = bool(models.get("chat_ready"))
    colab = models.get("colab") if isinstance(models.get("colab"), dict) else {}
    colab_ready = bool(models.get("colab_fast_ready") or (colab.get("ready") and colab.get("reachable")))
    voice_ready = bool(voice.get("server_voice_ready"))
    mindscape_cloud = bool(mindscape.get("cloud_configured"))
    mindscape_enabled = bool(mindscape.get("enabled"))
    public_ready = bool(public_url and "localhost" not in public_url and "127.0.0.1" not in public_url)
    sense_count = sum(1 for v in senses.values() if bool(v))

    sections = [
        section(
            "House HQ",
            "main embodied interactive scaffold",
            "ready" if house_hq_built else "needs_build",
            "3D home interface is built and can host embodied interaction."
            if house_hq_built else "House HQ build output is missing.",
            "/house-hq",
            "" if house_hq_built else "Run npm.cmd run house:build.",
        ),
        section(
            "Alpecca app",
            "secondary virtual app and state surface",
            "ready" if runtime.get("level") in {"ready", "degraded"} else "offline",
            "Conversation/state app is available; model tier may still be degraded."
            if runtime.get("level") in {"ready", "degraded"} else "Conversation app is running in basic/offline mode.",
            "/",
            "" if chat_ready else "Start Ollama and pull the configured reasoning model.",
        ),
        section(
            "Mindscape",
            "soul-process continuity and sustainability layer",
            "cloud_ready" if mindscape_enabled and mindscape_cloud else ("local_only" if mindscape_enabled else "disabled"),
            "Continuity snapshots can mirror online."
            if mindscape_enabled and mindscape_cloud else "Continuity is local only until a cloud target is configured.",
            "/mindscape",
            "" if mindscape_enabled and mindscape_cloud else "Set ALPECCA_MINDSCAPE_URL and ALPECCA_MINDSCAPE_TOKEN.",
        ),
        section(
            "Model",
            "live language core",
            "ready" if chat_ready else "offline",
            (
                f"Reason model: {models.get('reason', '')}; "
                f"fast accelerator: {'Colab T4' if colab_ready else 'local'}; "
                f"deep tier: {models.get('deep_backend') or models.get('deep') or 'local'}."
            ),
            "/system/status",
            "" if chat_ready else "Start Ollama, then pull the configured ALPECCA_MODEL.",
        ),
        section(
            "Voice",
            "spoken Alpecca voice",
            "ready" if voice.get("original_alpecca_voice_ready") else ("server_generic" if voice_ready else ("fallback" if voice.get("audible") else "offline")),
            f"Original voice {voice.get('voice') or 'unknown'} with {voice.get('profile') or 'unknown'}."
            if voice.get("original_alpecca_voice_ready") else (
                "Server voice is present, but not Alpecca's original identity."
                if voice_ready else "Browser speech fallback is available."
            ),
            "/voice",
            "" if voice.get("original_alpecca_voice_ready") else (
                "Restore Alpecca's original voice profile with ALPECCA_KOKORO_VOICE=af_heart."
                if voice_ready else "Install Kokoro or edge-tts for server-side voice."
            ),
        ),
        section(
            "Senses",
            "grounded perception inputs",
            "active" if sense_count > 1 else "minimal",
            f"{sense_count} sense channel(s) active.",
            "/sight",
            "" if sense_count > 1 else "Launch with START_HERE.bat or enable optional senses as needed.",
        ),
        section(
            "Remote preview",
            "mobile/cloud access surface",
            "ready" if public_ready else "local",
            public_url or "No public URL detected in this request.",
            "",
            "" if public_ready else "Use a Cloudflare tunnel for remote mobile preview.",
        ),
    ]

    if not chat_ready:
        actions.append("Fix model availability first; it is the main reason replies become basic/offline.")
    if mindscape_enabled and not mindscape_cloud:
        actions.append("Configure Mindscape cloud fallback so continuity survives a local device outage.")

    return {
        "ok": all(s["status"] in {"ready", "cloud_ready", "active"} for s in sections[:5]),
        "level": runtime.get("level", "unknown"),
        "sections": sections,
        "issues": issues,
        "next_actions": list(dict.fromkeys(a for a in actions if a)),
        "hierarchy": {
            "primary": "House HQ",
            "secondary": "Alpecca app",
            "continuity": "Mindscape",
        },
    }
