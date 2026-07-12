"""Void Prototype system-center and legacy-shell retirement contracts."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_void_system_center_covers_the_retired_house_internal_menu():
    source = (ROOT / "apps" / "house-hq" / "src" / "main.ts").read_text(
        encoding="utf-8"
    )

    for system_id in (
        "overview",
        "self",
        "devices",
        "senses",
        "voice",
        "studio",
        "observatory",
        "memory",
        "journal",
        "soul",
        "growth",
        "files",
        "games",
        "runtime",
    ):
        assert f'data-system-id="{system_id}"' in source

    for endpoint in (
        "/home/state",
        "/introspect",
        "/auth/status",
        "/sight",
        "/voice",
        "/studio/work",
        "/observatory",
        "/memories",
        "/journal",
        "/soul",
        "/growth",
        "/desktop",
        "/games",
        "/system/status",
        "/system/doctor",
    ):
        assert endpoint in source


def test_void_system_center_keeps_both_native_modes_and_legacy_shell_unreachable():
    source = (ROOT / "apps" / "house-hq" / "src" / "main.ts").read_text(
        encoding="utf-8"
    )

    assert "<iframe" not in source
    assert "alpeccaCoreFrame" not in source
    assert "environmentModeFromUrl" not in source
    assert 'searchParams.get("environment")' in source
    assert 'const currentEnvironmentMode: "prototype" | "hq"' in source
    assert 'id="environmentModeToggle"' in source
    assert "switchEnvironmentMode" not in source
    assert "createPrototypeVoid();" in source
    assert "new THREE.OrthographicCamera" in source
    assert 'id="viewModeToggle"' in source
    assert 'data-view-mode="orthographic"' in (
        ROOT / "apps" / "house-hq" / "src" / "styles.css"
    ).read_text(encoding="utf-8")


def test_system_navigation_is_grouped_and_emotion_state_stays_visible():
    source = (ROOT / "apps" / "house-hq" / "src" / "main.ts").read_text(
        encoding="utf-8"
    )
    for category in ("Core", "Experience", "Records", "Actions", "System"):
        assert f"<span>{category}</span>" in source
    assert 'id="alpeccaSystemsAffect"' in source
    assert "updateAlpeccaSystemsAffect" in source
    for signal in ("love", "compassion", "fear", "energy"):
        assert f'["{signal}"' in source


def test_retired_internal_shell_is_archived_and_routes_point_to_void():
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    archived = ROOT / "web" / "archive" / "house_hq_internal_legacy.html"

    assert archived.is_file()
    assert not (ROOT / "web" / "home.html").exists()
    assert 'return RedirectResponse("/house-hq", status_code=307)' in server
    assert 'WEB_DIR / "home.html"' not in server


def test_archived_internal_shell_is_not_served_by_web_asset_route():
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    headers = {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}

    archived = client.get(
        "/web/archive/house_hq_internal_legacy.html",
        headers=headers,
    )
    home = client.get("/home", headers=headers, follow_redirects=False)

    assert archived.status_code == 404
    assert home.status_code == 307
    assert home.headers["location"] == "/house-hq"
