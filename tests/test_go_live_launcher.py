from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "go_live.ps1"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_go_live_uses_single_full_stack_and_shared_tunnel_manager():
    source = _source()

    assert "scripts\\run_full.py" in source
    assert "scripts\\share.py', '--tunnel" in source
    assert "Get-NetTCPConnection -LocalPort $port -State Listen" in source
    assert "data\\preview.json" in source


def test_go_live_has_no_cloudflare_only_install_gate_or_embedded_origin():
    source = _source()

    assert "cloudflared not found" not in source
    assert "ALPECCA_CORS_ORIGINS" not in source
    assert ".trycloudflare.com" not in source
    assert "LocalTunnel" in source


def test_go_live_waits_for_backend_and_published_route_before_success():
    source = _source()

    health_index = source.index("/healthz")
    share_index = source.index("scripts\\share.py', '--tunnel")
    published_index = source.index("PUBLIC LINK")
    phone_index = source.index("ALPECCA VOID ON YOUR PHONE")

    assert health_index < share_index < published_index < phone_index
