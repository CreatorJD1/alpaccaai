"""Optional Google Colab T4 acceleration for Alpecca.

The Colab side runs a tiny OpenAI-compatible FastAPI server. This client keeps
the integration deliberately narrow: fast chat can use it when awake, but local
Ollama remains the authoritative reasoning model and fallback.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urljoin


def _base(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _headers(api_key: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _open_json(url: str, *, api_key: str = "", payload: dict | None = None,
               timeout: float = 2.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if payload is not None else "GET",
        headers=_headers(api_key),
    )
    with urllib.request.urlopen(req, timeout=max(0.3, float(timeout))) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def status(url: str, *, model: str = "", api_key: str = "",
           timeout: float = 1.8) -> dict:
    base = _base(url)
    if not base:
        return {
            "configured": False,
            "reachable": False,
            "ready": False,
            "url": "",
            "model": model,
            "error": "",
        }
    for path in ("health", "v1/models"):
        try:
            payload = _open_json(urljoin(base + "/", path), api_key=api_key, timeout=timeout)
            models = []
            if isinstance(payload.get("data"), list):
                models = [str(x.get("id") or "") for x in payload["data"] if isinstance(x, dict)]
            return {
                "configured": True,
                "reachable": True,
                "ready": bool(payload.get("ready", True)),
                "url": base,
                "model": str(payload.get("model") or model or (models[0] if models else "")),
                "models": models,
                "backend": str(payload.get("backend") or "colab-t4"),
                "gpu": str(payload.get("gpu") or ""),
                "error": "",
            }
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return {
        "configured": True,
        "reachable": False,
        "ready": False,
        "url": base,
        "model": model,
        "error": last_error,
        "fix": "Open the Colab T4 notebook and copy its tunnel URL into ALPECCA_COLAB_URL.",
    }


def chat(system_prompt: str, user_msg: str, *, history: list[dict] | None = None,
         url: str, model: str, api_key: str = "", timeout: float = 7.0,
         max_tokens: int = 160, temperature: float = 0.72) -> str:
    base = _base(url)
    if not base:
        raise RuntimeError("ALPECCA_COLAB_URL is not configured")
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_msg})
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max(24, int(max_tokens)),
        "temperature": float(temperature),
        "stream": False,
    }
    data = _open_json(
        urljoin(base + "/", "v1/chat/completions"),
        api_key=api_key,
        payload=payload,
        timeout=timeout,
    )
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise RuntimeError("Colab returned no chat choices")
    msg = choices[0].get("message") if isinstance(choices[0], dict) else {}
    text = str((msg or {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("Colab returned an empty reply")
    return text
