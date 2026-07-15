import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "deploy" / "continuity-pages-gateway"


def test_gateway_binds_existing_authority_and_vault_without_secrets():
    config = json.loads((GATEWAY / "wrangler.jsonc").read_text(encoding="utf-8"))
    services = {row["binding"]: row["service"] for row in config["services"]}
    assert config["pages_build_output_dir"] == "./public"
    assert services == {
        "LEASE_SERVICE": "alpecca-continuity-lease",
        "VAULT_SERVICE": "alpecca-mindscape-vault",
    }
    assert "vars" not in config


def test_gateway_is_prefix_bounded_and_contains_no_direct_worker_url():
    source = (GATEWAY / "functions" / "[[path]].js").read_text(encoding="utf-8")
    assert 'pathname.startsWith("/lease/")' in source
    assert 'pathname.startsWith("/vault/")' in source
    assert 'url.pathname === "/healthz"' in source
    assert 'target.binding.fetch(new Request(' in source
    assert 'return json({ detail: "not found" }, 404);' in source
    assert "workers.dev" not in source
    assert "Authorization" not in source


def test_cloud_image_removes_deployment_surface_before_runtime():
    dockerfile = (ROOT / "deploy" / "hf-cloud-core" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "rm -rf /opt/alpecca/.git" in dockerfile
    assert "/opt/alpecca/deploy" in dockerfile
    assert "/opt/alpecca/docs" in dockerfile
    assert "/opt/alpecca/scripts" in dockerfile
