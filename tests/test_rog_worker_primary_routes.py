from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"missing function {name}")


def test_primary_worker_status_is_creator_scoped_and_content_free():
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    function = _function_source(ROOT / "server.py", "rog_worker_status")

    assert '@app.get("/system/rog-worker")' in source
    assert "_require_creator_request(req)" in function
    assert "status_snapshot(ROG_WORKER_URL)" in function
    assert 'getattr(mind.llm, "_deep_chain", ())' in function
    assert 'snapshot["deep_route_loaded"]' in function
    assert 'snapshot["restart_required"]' in function


def test_primary_render_route_is_bounded_audited_and_runs_off_event_loop():
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    function = _function_source(ROOT / "server.py", "rog_worker_render")

    assert '@app.post("/system/rog-worker/render")' in source
    assert "_require_creator_request(req)" in function
    assert "_read_bounded_json_object(req, max_bytes=4096)" in function
    assert '"rog_compute"' in function
    assert "_record_capability_use" in function
    assert "asyncio.to_thread" in function
    assert "rog_worker_runtime_mod.render_blender" in function


def test_rog_compute_is_visible_in_capability_audit_inventory():
    source = (ROOT / "alpecca" / "capabilities.py").read_text(encoding="utf-8")

    assert '"rog_compute", "ALPECCA_ROG_WORKER_URL", "network", "choice"' in source


def test_primary_render_route_matches_worker_frame_ceiling():
    path = ROOT / "server.py"
    function = _function_source(path, "rog_worker_render")

    assert "1 <= frame <= 999_999" in function
    assert "1_000_000" not in function


def test_server_refuses_compute_only_host_before_coremind_construction():
    source = (ROOT / "server.py").read_text(encoding="utf-8")

    guard = source.index("host_roles_mod.require_primary_runtime_host()")
    core_mind = source.index("mind = CoreMind(")
    assert guard < core_mind
