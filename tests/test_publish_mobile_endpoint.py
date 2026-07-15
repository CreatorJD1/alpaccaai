from scripts.publish_mobile_endpoint import wait_for_endpoint


def test_new_tunnel_health_is_retried_before_publication():
    outcomes = iter((False, False, True))
    probes = []
    sleeps = []

    assert wait_for_endpoint(
        "https://alpecca.example.com",
        attempts=5,
        delay_seconds=0.25,
        probe=lambda url: probes.append(url) is None and next(outcomes),
        sleeper=sleeps.append,
    )
    assert probes == ["https://alpecca.example.com"] * 3
    assert sleeps == [0.25, 0.25]


def test_new_tunnel_health_retry_is_bounded():
    probes = []
    sleeps = []

    assert not wait_for_endpoint(
        "https://alpecca.example.com",
        attempts=100,
        delay_seconds=100,
        probe=lambda url: probes.append(url) is not None,
        sleeper=sleeps.append,
    )
    assert len(probes) == 10
    assert sleeps == [5.0] * 9
