"""Standalone Docker Space entrypoint for the fenced cloud-core supervisor."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import socket
import sys
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
    if not cloud_core_enabled(os.environ):
        print(
            "Cloud continuity core is installed but disabled; no restore, lease, "
            "model, or CoreMind was started.",
            flush=True,
        )
        return 0
    configure_environment(os.environ)
    missing = validate_configuration(os.environ)
    if missing:
        print("Cloud continuity configuration is incomplete: " + ", ".join(missing), flush=True)
        return 2
    return supervisor.main(vrm_installer=install_vrm)


if __name__ == "__main__":
    raise SystemExit(main())
