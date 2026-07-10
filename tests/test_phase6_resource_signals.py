from alpecca import resource_signals


def test_unknown_readings_are_not_converted_to_zero():
    normalized = resource_signals.normalize_readings()
    assessment = resource_signals.assess_resources()

    for resource in resource_signals.RESOURCE_ORDER:
        assert normalized[resource]["state"] == "unknown"
        assert normalized[resource]["known"] is False
        assert normalized[resource]["pressure"] is None
    assert normalized["cpu"]["percent"] is None
    assert normalized["ram"]["used_bytes"] is None
    assert normalized["disk"]["free_bytes"] is None
    assert normalized["battery"]["charging"] is None
    assert normalized["thermal"]["celsius"] is None
    assert assessment["pressure"] is None
    assert assessment["severity"] == "unknown"
    assert assessment["known_resources"] == []
    assert assessment["unknown_resources"] == list(resource_signals.RESOURCE_ORDER)
    assert assessment["reasons"] == []


def test_explicit_zero_readings_remain_known_and_preserved():
    normalized = resource_signals.normalize_readings(
        cpu_percent=0,
        ram_used_bytes=0,
        ram_total_bytes=1,
        commit_used_bytes=0,
        commit_limit_bytes=1,
        vram_used_bytes=0,
        vram_total_bytes=1,
        disk_free_bytes=0,
        disk_total_bytes=1,
        battery_percent=0,
        battery_charging=False,
        thermal_celsius=0,
    )

    assert normalized["cpu"] == {
        "state": "known",
        "known": True,
        "percent": 0.0,
        "pressure": 0.0,
    }
    for resource in ("ram", "commit", "vram"):
        assert normalized[resource]["state"] == "known"
        assert normalized[resource]["used_bytes"] == 0.0
        assert normalized[resource]["pressure"] == 0.0
    assert normalized["disk"]["free_bytes"] == 0.0
    assert normalized["disk"]["pressure"] == 1.0
    assert normalized["battery"]["percent"] == 0.0
    assert normalized["battery"]["charging"] is False
    assert normalized["battery"]["pressure"] == 1.0
    assert normalized["thermal"]["celsius"] == 0.0
    assert normalized["thermal"]["pressure"] == 0.0


def test_partial_and_invalid_readings_do_not_gain_derived_values():
    normalized = resource_signals.normalize_readings(
        cpu_percent=101,
        ram_used_bytes=0,
        ram_total_bytes=None,
        commit_used_bytes=0,
        commit_limit_bytes=0,
        vram_used_bytes=8,
        vram_total_bytes=4,
        disk_free_bytes=101,
        disk_total_bytes=100,
        battery_percent=50,
        battery_charging="yes",
        thermal_celsius=float("nan"),
    )
    assessment = resource_signals.assess_resources(
        cpu_percent=101,
        ram_used_bytes=0,
        ram_total_bytes=None,
        commit_used_bytes=0,
        commit_limit_bytes=0,
        vram_used_bytes=8,
        vram_total_bytes=4,
        disk_free_bytes=101,
        disk_total_bytes=100,
        battery_percent=50,
        battery_charging="yes",
        thermal_celsius=float("nan"),
    )

    assert normalized["ram"]["state"] == "unknown"
    assert normalized["ram"]["used_bytes"] == 0.0
    assert normalized["ram"]["total_bytes"] is None
    assert normalized["ram"]["used_fraction"] is None
    assert normalized["ram"]["pressure"] is None
    for resource in ("cpu", "commit", "vram", "disk", "thermal"):
        assert normalized[resource]["state"] == "invalid"
        assert normalized[resource]["pressure"] is None
    assert normalized["battery"]["state"] == "known"
    assert normalized["battery"]["charging"] is None
    assert normalized["battery"]["charging_state"] == "invalid"
    assert assessment["known_resources"] == ["battery"]
    assert assessment["unknown_resources"] == ["ram"]
    assert assessment["invalid_resources"] == ["cpu", "commit", "vram", "disk", "thermal"]
    assert assessment["invalid_fields"] == ["battery_charging"]


def test_assessment_is_bounded_evidence_backed_and_deterministic():
    readings = {
        "cpu_percent": 70,
        "ram_used_bytes": 85,
        "ram_total_bytes": 100,
        "commit_used_bytes": 95,
        "commit_limit_bytes": 100,
        "vram_used_bytes": 0,
        "vram_total_bytes": 100,
        "disk_free_bytes": 5,
        "disk_total_bytes": 100,
        "battery_percent": 30,
        "battery_charging": True,
        "thermal_celsius": 120,
    }

    first = resource_signals.assess_resources(**readings)
    second = resource_signals.assess_resources(**readings)

    assert first == second
    assert first["pressure"] == 1.0
    assert first["severity"] == "critical"
    assert first["complete"] is True
    assert first["unknown_resources"] == []
    assert first["invalid_resources"] == []
    assert [reason["resource"] for reason in first["reasons"]] == [
        "cpu",
        "ram",
        "commit",
        "disk",
        "battery",
        "thermal",
    ]
    assert first["readings"]["cpu"]["severity"] == "elevated"
    assert first["readings"]["ram"]["severity"] == "high"
    assert first["readings"]["commit"]["severity"] == "critical"
    assert first["readings"]["vram"]["severity"] == "normal"
    assert first["readings"]["thermal"]["pressure"] == 1.0
    for reading in first["readings"].values():
        assert reading["pressure"] is None or 0.0 <= reading["pressure"] <= 1.0
    assert first["reasons"][0]["observed"] == {"percent": 70.0}
    assert first["reasons"][-2]["observed"] == {
        "percent": 30.0,
        "charging": True,
    }
