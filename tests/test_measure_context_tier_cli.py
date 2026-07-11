"""CLI contracts for the evidence-only context-tier measurement entry point."""
from __future__ import annotations

import json

import pytest

from alpecca import context_tier_measurement as measurement
from scripts import measure_context_tier as cli


def test_cli_default_emits_a_single_json_dry_run_report(monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("ALPECCA_MODEL", raising=False)
    calls: list[dict[str, object]] = []
    expected_report = {
        "kind": "alpecca_context_tier_measurement",
        "status": "dry_run",
        "mode": "dry_run",
        "request": {"attempted": False},
    }

    def fake_run_context_tier_measurement(**kwargs):
        calls.append(kwargs)
        return expected_report

    monkeypatch.setattr(cli, "run_context_tier_measurement", fake_run_context_tier_measurement)

    assert cli.main([]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == expected_report
    assert calls == [
        {
            "tier": 8192,
            "execute": False,
            "host": measurement.DEFAULT_OLLAMA_HOST,
            "model": measurement.LOCAL_QWEN_MODEL,
        }
    ]


@pytest.mark.parametrize(
    ("argv", "error"),
    (
        (["--execute"], "execution requires --execute --tier N"),
        (["--all", "--execute", "--tier", "8192"], "--all is intentionally unsupported"),
    ),
)
def test_cli_refuses_execution_without_a_tier_or_any_all_mode(
    monkeypatch, capsys, argv: list[str], error: str
):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("ALPECCA_MODEL", raising=False)
    calls: list[dict[str, object]] = []

    def unexpected_run_context_tier_measurement(**kwargs):
        calls.append(kwargs)
        raise AssertionError("rejected CLI input must not reach the measurement harness")

    monkeypatch.setattr(cli, "run_context_tier_measurement", unexpected_run_context_tier_measurement)

    assert cli.main(argv) == 2

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert calls == []
    assert report["status"] == "rejected"
    assert report["mode"] == "dry_run"
    assert report["request"]["attempted"] is False
    assert report["request"]["http_request_count"] == 0
    assert error in report["unknowns"][0]


@pytest.mark.parametrize(
    ("argv", "error"),
    (
        (
            ["--execute", "--tier", "8192", "--model", f"{measurement.LOCAL_QWEN_MODEL}:cloud"],
            "cloud models are forbidden",
        ),
        (
            ["--execute", "--tier", "8192", "--host", "http://198.51.100.8:11434"],
            "nonloopback Ollama hosts are forbidden",
        ),
    ),
)
def test_cli_rejects_cloud_or_nonloopback_execution_before_network_or_sampling(
    monkeypatch, capsys, argv: list[str], error: str
):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("ALPECCA_MODEL", raising=False)
    opener_calls: list[tuple[object, ...]] = []
    sampler_calls: list[object] = []

    def unexpected_build_opener(*handlers):
        opener_calls.append(handlers)
        raise AssertionError("unsafe CLI input must not construct an HTTP opener")

    def unexpected_default_sampler():
        sampler_calls.append(object())
        raise AssertionError("unsafe CLI input must not create a resource sampler")

    monkeypatch.setattr(measurement, "build_opener", unexpected_build_opener)
    monkeypatch.setattr(measurement, "_default_sampler", unexpected_default_sampler)

    assert cli.main(argv) == 2

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert opener_calls == []
    assert sampler_calls == []
    assert report["status"] == "rejected"
    assert report["mode"] == "dry_run"
    assert report["request"]["attempted"] is False
    assert report["request"]["http_request_count"] == 0
    assert error in report["unknowns"][0]


def test_cli_emits_a_preflight_block_as_a_nonzero_json_result(monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("ALPECCA_MODEL", raising=False)
    calls: list[dict[str, object]] = []
    expected_report = {
        "kind": "alpecca_context_tier_measurement",
        "status": "blocked",
        "mode": "execute",
        "request": {
            "allowed": False,
            "attempted": False,
            "http_request_count": 0,
        },
    }

    def blocked_preflight(**kwargs):
        calls.append(kwargs)
        return expected_report

    monkeypatch.setattr(cli, "run_context_tier_measurement", blocked_preflight)

    assert cli.main(["--execute", "--tier", "8192"]) == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == expected_report
    assert calls == [
        {
            "tier": "8192",
            "execute": True,
            "host": measurement.DEFAULT_OLLAMA_HOST,
            "model": measurement.LOCAL_QWEN_MODEL,
        }
    ]
