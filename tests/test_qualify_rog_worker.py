from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts import qualify_rog_worker as qualify


COMMIT = "a" * 40


def _facts(**overrides: object) -> qualify.HostFacts:
    values: dict[str, object] = {
        "hostname": "Jason_HOLYROG",
        "os_name": "Windows",
        "os_release": "11",
        "os_version": "10.0.26100",
        "machine": "AMD64",
        "cpu_count": 24,
        "total_ram_bytes": 32 * 1024**3,
        "python_version": "3.12.8",
        "python_implementation": "CPython",
    }
    values.update(overrides)
    return qualify.HostFacts(**values)  # type: ignore[arg-type]


def _tool_finder(*missing: str):
    missing_set = set(missing)

    def find(candidate: str) -> str | None:
        logical_name = next(
            (
                name
                for name, candidates in qualify.TOOL_CANDIDATES.items()
                if candidate in candidates
            ),
            candidate,
        )
        if logical_name in missing_set:
            return None
        if candidate == qualify.CURRENT_PYTHON:
            return r"C:\Python\python.exe"
        return rf"C:\Tools\{candidate}"

    return find


class FakeRunner:
    def __init__(
        self,
        *,
        dirty_output: str = "",
        nvidia: qualify.CommandResult | None = None,
        powershell: qualify.CommandResult | None = None,
    ) -> None:
        self.dirty_output = dirty_output
        self.nvidia = nvidia or qualify.CommandResult(
            0, "NVIDIA GeForce RTX 4070 Laptop GPU, 8188\n"
        )
        self.powershell = powershell or qualify.CommandResult(
            0, '{"Name":"Fallback GPU","AdapterRAM":4294967296}'
        )
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, command: list[str] | tuple[str, ...], cwd: Path, timeout: float
    ) -> qualify.CommandResult:
        del cwd
        assert 0 < timeout <= qualify.COMMAND_TIMEOUT_SECONDS
        call = tuple(command)
        self.calls.append(call)
        executable = qualify._executable_key(call[0])
        args = call[1:]
        if executable == "git" and args == qualify.GIT_HEAD_ARGS:
            return qualify.CommandResult(0, COMMIT + "\n")
        if executable == "git" and args == qualify.GIT_STATUS_ARGS:
            return qualify.CommandResult(0, self.dirty_output)
        if executable == "nvidia-smi":
            return self.nvidia
        if executable in {"powershell", "pwsh"}:
            return self.powershell
        raise AssertionError(f"unexpected command: {call!r}")


def _collect(
    tmp_path: Path,
    *,
    runner: FakeRunner | None = None,
    facts: qualify.HostFacts | None = None,
    missing_tools: tuple[str, ...] = (),
    worker_bind_host: str = qualify.DEFAULT_WORKER_BIND_HOST,
    worker_port: int = qualify.DEFAULT_WORKER_PORT,
    ollama_host: str = qualify.DEFAULT_OLLAMA_HOST,
    ollama_port: int = qualify.DEFAULT_OLLAMA_PORT,
    port_probe: qualify.PortProbe = lambda _host, _port, _timeout: True,
) -> tuple[dict[str, object], FakeRunner]:
    active_runner = runner or FakeRunner()
    report = qualify.collect_qualification(
        tmp_path,
        facts_provider=lambda: facts or _facts(),
        disk_provider=lambda _path: qualify.DiskFacts(
            total_bytes=1024 * 1024**3,
            free_bytes=640 * 1024**3,
        ),
        tool_finder=_tool_finder(*missing_tools),
        command_runner=active_runner,
        worker_bind_host=worker_bind_host,
        worker_port=worker_port,
        ollama_host=ollama_host,
        ollama_port=ollama_port,
        port_probe=port_probe,
    )
    return report, active_runner


def test_complete_inventory_is_worker_only_and_never_primary(tmp_path: Path) -> None:
    report, runner = _collect(tmp_path)

    qualification = report["qualification"]
    assert qualification["assigned_role"] == "worker-only"  # type: ignore[index]
    assert qualification["worker_status"] == "qualified-worker-only"  # type: ignore[index]
    assert qualification["worker_ready"] is True  # type: ignore[index]
    assert qualification["primary_status"] == "not-qualified"  # type: ignore[index]
    assert qualification["primary_qualified"] is False  # type: ignore[index]
    assert qualification["continuity_failover_evidence_in_scope"] is False  # type: ignore[index]
    assert set(qualification["continuity_failover_gates"].values()) == {  # type: ignore[index,union-attr]
        "not_evidenced"
    }
    assert report["hardware"]["gpu"]["source"] == "nvidia-smi"  # type: ignore[index]
    assert report["hardware"]["gpu"]["devices"] == [  # type: ignore[index]
        {"name": "NVIDIA GeForce RTX 4070 Laptop GPU", "vram_mib": 8188}
    ]
    assert report["source"] == {
        "status": "ready",
        "commit": COMMIT,
        "dirty": False,
        "dirty_scope": "superproject_worktree_excluding_submodules",
        "head_probe": "ok",
        "dirty_probe": "ok",
    }
    assert report["runtime"]["ollama"] == {  # type: ignore[index]
        "status": "ready",
        "ready": True,
        "executable_present": True,
        "host": qualify.DEFAULT_OLLAMA_HOST,
        "port": qualify.DEFAULT_OLLAMA_PORT,
        "loopback_only": True,
        "probe": "listening",
        "application_request_sent": False,
    }
    assert report["runtime"]["blender"] == {  # type: ignore[index]
        "status": "available",
        "executable_present": True,
        "executable_started": False,
    }
    assert report["runtime"]["compute_worker_endpoint"] == {  # type: ignore[index]
        "status": "sane",
        "sane": True,
        "bind_host": qualify.DEFAULT_WORKER_BIND_HOST,
        "port": qualify.DEFAULT_WORKER_PORT,
        "exposure": "loopback-only",
        "reasons": [],
        "listener_probed": False,
    }
    assert report["qualification"]["capability_statuses"] == {  # type: ignore[index]
        "reasoning": "ready",
        "build": "ready",
        "render": "ready",
    }
    assert all(  # type: ignore[union-attr]
        details["ready"] for details in report["capabilities"].values()
    )
    assert report["collection"]["services_started"] == []  # type: ignore[index]
    assert report["collection"]["application_requests_sent"] == 0  # type: ignore[index]
    executed = "\n".join(" ".join(call) for call in runner.calls).lower()
    assert "ollama serve" not in executed
    assert "discord" not in executed
    assert "coremind" not in executed


def test_dirty_paths_and_command_errors_never_enter_json(tmp_path: Path) -> None:
    private_name = "data/secrets/private-token.env"
    runner = FakeRunner(dirty_output=f" M {private_name}\n?? creator-password.txt\n")

    report, _ = _collect(tmp_path, runner=runner)
    serialized = json.dumps(report, sort_keys=True)

    assert report["source"]["dirty"] is True  # type: ignore[index]
    assert "source_dirty" in report["qualification"]["attention_reasons"]  # type: ignore[index]
    assert private_name not in serialized
    assert "creator-password.txt" not in serialized
    assert report["capabilities"]["build"]["status"] == "needs-attention"  # type: ignore[index]
    assert report["capabilities"]["render"]["status"] == "needs-attention"  # type: ignore[index]


def test_capabilities_fail_independently_without_starting_missing_tools(
    tmp_path: Path,
) -> None:
    report, runner = _collect(
        tmp_path,
        missing_tools=("ollama", "blender"),
        port_probe=lambda _host, _port, _timeout: False,
    )

    assert report["qualification"]["worker_ready"] is True  # type: ignore[index]
    assert report["qualification"]["capability_statuses"] == {  # type: ignore[index]
        "reasoning": "needs-attention",
        "build": "ready",
        "render": "needs-attention",
    }
    assert report["runtime"]["ollama"]["probe"] == "not-listening"  # type: ignore[index]
    assert report["runtime"]["blender"]["executable_started"] is False  # type: ignore[index]
    executed = "\n".join(" ".join(call) for call in runner.calls).lower()
    assert "ollama" not in executed
    assert "blender" not in executed


def test_nonloopback_ollama_target_is_rejected_without_network_probe(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, int, float]] = []

    def probe(host: str, port: int, timeout: float) -> bool:
        calls.append((host, port, timeout))
        return True

    report, _ = _collect(
        tmp_path,
        ollama_host="192.168.12.165",
        port_probe=probe,
    )

    ollama = report["runtime"]["ollama"]  # type: ignore[index]
    assert ollama["status"] == "needs-attention"
    assert ollama["loopback_only"] is False
    assert ollama["probe"] == "rejected-non-loopback"
    assert calls == []


@pytest.mark.parametrize(
    ("host", "port", "reason"),
    [
        ("127.0.0.1", 80, "worker_port_out_of_range"),
        ("127.0.0.1", qualify.DEFAULT_OLLAMA_PORT, "worker_port_conflict"),
        ("8.8.8.8", qualify.DEFAULT_WORKER_PORT, "public_bind_not_allowed"),
    ],
)
def test_invalid_worker_endpoint_blocks_worker_qualification(
    tmp_path: Path, host: str, port: int, reason: str
) -> None:
    report, _ = _collect(tmp_path, worker_bind_host=host, worker_port=port)

    endpoint = report["runtime"]["compute_worker_endpoint"]  # type: ignore[index]
    assert endpoint["status"] == "invalid"
    assert reason in endpoint["reasons"]
    assert report["qualification"]["worker_ready"] is False  # type: ignore[index]
    assert "worker_endpoint_invalid" in report["qualification"][  # type: ignore[index]
        "attention_reasons"
    ]


def test_custom_expected_host_is_a_sane_named_bind(tmp_path: Path) -> None:
    report = qualify.collect_qualification(
        tmp_path,
        expected_host="render-node",
        worker_bind_host="render-node",
        facts_provider=lambda: _facts(hostname="render-node"),
        disk_provider=lambda _path: qualify.DiskFacts(
            total_bytes=1024 * 1024**3,
            free_bytes=640 * 1024**3,
        ),
        tool_finder=_tool_finder(),
        command_runner=FakeRunner(),
        port_probe=lambda _host, _port, _timeout: True,
    )

    endpoint = report["runtime"]["compute_worker_endpoint"]  # type: ignore[index]
    assert endpoint["status"] == "sane"
    assert endpoint["exposure"] == "named-interface"


def test_powershell_gpu_fallback_is_bounded_and_content_free(tmp_path: Path) -> None:
    runner = FakeRunner(
        nvidia=qualify.CommandResult(1, "", "private diagnostic path", "failed"),
        powershell=qualify.CommandResult(
            0,
            '[{"Name":"AMD Radeon 780M","AdapterRAM":2147483648},'
            '{"Name":"NVIDIA RTX 4060","AdapterRAM":4294967296}]',
        ),
    )

    report, active_runner = _collect(tmp_path, runner=runner)
    gpu = report["hardware"]["gpu"]  # type: ignore[index]

    assert gpu["source"] == "powershell-cim"
    assert gpu["devices"] == [
        {"name": "AMD Radeon 780M", "vram_mib": 2048},
        {"name": "NVIDIA RTX 4060", "vram_mib": 4096},
    ]
    assert "private diagnostic path" not in json.dumps(report)
    powershell_call = next(
        call
        for call in active_runner.calls
        if qualify._executable_key(call[0]) in {"powershell", "pwsh"}
    )
    assert powershell_call[1:] == qualify.POWERSHELL_QUERY_ARGS


def test_missing_evidence_fails_worker_readiness_without_promoting_primary(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        nvidia=qualify.CommandResult(124, status="timeout"),
        powershell=qualify.CommandResult(124, status="timeout"),
    )
    report, _ = _collect(
        tmp_path,
        runner=runner,
        facts=_facts(hostname="different-host", total_ram_bytes=None),
        missing_tools=("node",),
    )
    qualification = report["qualification"]

    assert qualification["worker_status"] == "worker-only-needs-attention"  # type: ignore[index]
    assert qualification["worker_ready"] is False  # type: ignore[index]
    assert qualification["primary_qualified"] is False  # type: ignore[index]
    assert set(qualification["attention_reasons"]) >= {  # type: ignore[index]
        "expected_host_mismatch",
        "ram_inventory_unavailable",
        "required_tools_missing",
        "gpu_inventory_unavailable",
    }
    assert report["hardware"]["gpu"]["attempts"] == {  # type: ignore[index]
        "nvidia_smi": "timeout",
        "powershell": "timeout",
    }


@pytest.mark.parametrize(
    "command",
    [
        ("ollama.exe", "serve"),
        ("git.exe", "checkout", "main"),
        ("powershell.exe", "-Command", "Get-ChildItem Env:"),
        ("python.exe", "server.py"),
    ],
)
def test_command_runner_rejects_service_start_and_mutating_or_secret_commands(
    tmp_path: Path, command: tuple[str, ...]
) -> None:
    runner = qualify.BoundedReadOnlyCommandRunner()

    with pytest.raises(ValueError, match="read-only qualification allowlist"):
        runner(command, tmp_path, 5.0)


def test_bounded_runner_uses_no_shell_and_caps_timeout_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "x" * 40_000, "")

    monkeypatch.setattr(qualify.subprocess, "run", fake_run)
    runner = qualify.BoundedReadOnlyCommandRunner()
    result = runner(("git.exe", *qualify.GIT_HEAD_ARGS), tmp_path, 60.0)

    assert observed["shell"] is False
    assert observed["timeout"] == qualify.COMMAND_TIMEOUT_SECONDS
    assert observed["stdin"] is subprocess.DEVNULL
    assert result.truncated is True
    assert len(result.stdout) == qualify.MAX_CAPTURE_CHARS


def test_injected_collection_is_deterministic(tmp_path: Path) -> None:
    first, _ = _collect(tmp_path)
    second, _ = _collect(tmp_path)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_main_prints_json_and_does_not_create_an_output_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report, _ = _collect(tmp_path)
    monkeypatch.setattr(qualify, "collect_qualification", lambda *_args, **_kwargs: report)
    before = set(tmp_path.iterdir())

    result = qualify.main(["--repo", str(tmp_path), "--compact"])
    printed = json.loads(capsys.readouterr().out)

    assert result == 0
    assert printed == report
    assert set(tmp_path.iterdir()) == before
