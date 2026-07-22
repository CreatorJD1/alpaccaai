from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "hf-cloud-desktop"


def test_private_space_metadata_and_inert_policy_are_explicit() -> None:
    readme = (DEPLOY / "README.md").read_text(encoding="utf-8")
    policy = json.loads((DEPLOY / "policy.json").read_text(encoding="utf-8"))

    assert "sdk: docker" in readme
    assert "app_port: 7860" in readme
    assert "must remain **private**" in readme
    assert policy == {
        "schema": "alpecca.cloud-desktop-policy.v1",
        "provider": "huggingface-space",
        "visibility_required": "private",
        "desktop_only": True,
        "coremind_enabled": False,
        "conversation_egress_enabled": False,
        "public_port": 7860,
        "vnc_bind": "127.0.0.1:5901",
        "persistent_mount": "/data",
        "runtime_user_id": 1000,
        "package_execution": "image-build-only",
        "leadership_activation": "absent",
    }


def test_container_runs_non_root_and_exposes_only_the_web_desktop() -> None:
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    start = (DEPLOY / "start-desktop.sh").read_text(encoding="utf-8")

    assert "install -d -o 1000 -g 1000" in dockerfile
    assert "USER 1000" in dockerfile
    assert dockerfile.count("EXPOSE ") == 1
    assert "EXPOSE 7860" in dockerfile
    assert "ALPECCA_DESKTOP_ONLY=1" in dockerfile
    assert "-localhost yes" in start
    assert "127.0.0.1:5901" in start
    assert "0.0.0.0:7860" in start
    assert "refusing to run the desktop as root" in start


def test_cloud_desktop_contains_no_coremind_or_runtime_package_executor() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in DEPLOY.iterdir()
        if path.is_file()
    ).casefold()

    for forbidden in (
        "python server.py",
        "scripts/run_full.py",
        "ollama serve",
        "sudo ",
        "apt-get install $",
        "flatpak install $",
        "cloudflared tunnel run",
    ):
        assert forbidden not in text


def test_health_identity_is_content_free_and_desktop_only() -> None:
    health = json.loads((DEPLOY / "healthz").read_text(encoding="utf-8"))

    assert health == {
        "service": "alpecca-cloud-desktop",
        "version": 1,
        "desktop_only": True,
        "coremind": False,
    }
