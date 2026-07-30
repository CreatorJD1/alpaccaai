from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy" / "hf-cloud-core" / "cloud_server.py"
SPEC = importlib.util.spec_from_file_location("alpecca_hf_cloud_server", PATH)
assert SPEC and SPEC.loader
cloud_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cloud_server)


def _environment() -> dict[str, str]:
    return {
        "ALPECCA_CONTINUITY_LEASE_ID": "lease-42",
        "ALPECCA_CONTINUITY_FENCING_EPOCH": "42",
        "ALPECCA_CONTINUITY_LEASE_HOLDER": "cloud-standby:test",
        "ALPECCA_CONTINUITY_ROLE": "cloud-standby",
        "ALPECCA_SERVER_PORT": "7860",
    }


def test_cloud_server_binds_launcher_guard_to_its_own_process() -> None:
    environ = _environment()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))

    assert cloud_server.main(
        environ=environ,
        process_id=4321,
        runner=runner,
    ) == 0
    assert environ["ALPECCA_CONTINUITY_LAUNCHER_PID"] == "4321"
    assert calls == [(('server:app',), {
        "host": "0.0.0.0",
        "port": 7860,
        "log_level": "warning",
        "access_log": False,
    })]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ALPECCA_CONTINUITY_LEASE_ID", "", "fence is incomplete"),
        ("ALPECCA_CONTINUITY_FENCING_EPOCH", "0", "fence is incomplete"),
        ("ALPECCA_CONTINUITY_LEASE_HOLDER", "", "fence is incomplete"),
        ("ALPECCA_CONTINUITY_ROLE", "local-primary", "role is invalid"),
        ("ALPECCA_SERVER_PORT", "0", "port is invalid"),
    ],
)
def test_cloud_server_fails_closed_before_importing_server(
    field: str,
    value: str,
    message: str,
) -> None:
    environ = _environment()
    environ[field] = value
    with pytest.raises(cloud_server.CloudServerStartupError, match=message):
        cloud_server.main(
            environ=environ,
            process_id=4321,
            runner=lambda *_args, **_kwargs: pytest.fail("server unexpectedly ran"),
        )


def test_cloud_supervisor_and_image_use_the_self_fencing_entrypoint() -> None:
    app_source = (ROOT / "deploy" / "hf-cloud-core" / "app.py").read_text(
        encoding="utf-8"
    )
    dockerfile = (ROOT / "deploy" / "hf-cloud-core" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert 'with_name("cloud_server.py")' in app_source
    assert "cloud_server.py" in dockerfile
