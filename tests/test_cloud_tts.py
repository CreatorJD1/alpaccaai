from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from alpecca.cloud_tts import (
    AUTHORIZATION_HEADER,
    CloudTTSClient,
    CloudTTSConfig,
    CloudTTSConfigError,
)


ENDPOINT = "https://voice.example.test/voice/tts"
SECRET = "Bearer top-secret-credential"
PRIVATE_TEXT = "The private phrase must never appear in status."


class Response:
    def __init__(
        self,
        body: bytes = b"RIFFaudio",
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        final_url: str | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = {
            "Content-Type": "audio/wav",
            **(headers or {}),
        }
        self.read_sizes: list[int] = []
        self.closed = False
        self.final_url = final_url
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        chunk = self.body[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self.final_url or ENDPOINT


class Clock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)
        self.last = values[-1] if values else 0.0

    def __call__(self) -> float:
        try:
            self.last = next(self.values)
        except StopIteration:
            pass
        return self.last


def config(**kwargs) -> CloudTTSConfig:
    return CloudTTSConfig(
        endpoint=kwargs.pop("endpoint", ENDPOINT),
        authorization=kwargs.pop("authorization", SECRET),
        **kwargs,
    )


def test_success_posts_bounded_json_with_exact_auth_and_returns_audio() -> None:
    captured = {}
    response = Response(
        headers={
            "Content-Type": "audio/wav; codec=pcm_s16le",
            "Content-Length": "9",
            "X-Alpecca-Request-Id": "request-42",
        }
    )

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return response

    client = CloudTTSClient(config(), opener=opener, clock=Clock(5.0, 5.25))
    result = client.synthesize(PRIVATE_TEXT)

    assert result == (
        "audio/wav",
        b"RIFFaudio",
        {
            "http_status": 200,
            "content_type": "audio/wav",
            "byte_count": 9,
            "elapsed_ms": 250,
            "request_id": "request-42",
        },
    )
    request = captured["request"]
    assert request.full_url == ENDPOINT
    assert request.get_method() == "POST"
    request_headers = {name.lower(): value for name, value in request.header_items()}
    assert request_headers[AUTHORIZATION_HEADER.lower()] == SECRET
    assert json.loads(request.data) == {"text": PRIVATE_TEXT}
    assert captured["timeout"] == 15.0
    assert response.read_sizes == [9, 1]
    assert response.closed
    status = client.status()
    assert status.state == "ready"
    assert status.reason == "ok"
    assert (status.calls, status.network_attempts, status.successes) == (1, 1, 1)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://voice.example.test/voice/tts",
        "https://voice.example.test/tts",
        "https://voice.example.test/voice/tts/",
        "https://voice.example.test/voice/tts?redirect=other",
        "https://user:pass@voice.example.test/voice/tts",
        "https://voice.example.test/voice/tts#fragment",
    ],
)
def test_endpoint_must_be_exact_https_host_and_path(endpoint: str) -> None:
    with pytest.raises(CloudTTSConfigError, match="exact HTTPS"):
        config(endpoint=endpoint)


def test_authorization_must_be_safe_for_an_http_header() -> None:
    invalid_values = (
        " secret",
        "secret ",
        "secret\nvalue",
        "secret\tvalue",
        "secr" + chr(0xE9) + "t",
    )
    for authorization in invalid_values:
        with pytest.raises(CloudTTSConfigError, match="bounded text"):
            config(authorization=authorization)


def test_config_repr_and_status_never_expose_authorization_or_text() -> None:
    cfg = config()
    client = CloudTTSClient(cfg, opener=lambda *args, **kwargs: Response())
    client.synthesize(PRIVATE_TEXT)

    encoded = repr(cfg) + repr(client.status()) + json.dumps(client.status().as_dict())
    assert SECRET not in encoded
    assert PRIVATE_TEXT not in encoded
    assert "voice.example.test" not in encoded
    assert "/voice/tts" not in encoded


def test_from_env_is_injectable_and_invalid_or_missing_config_is_truthful() -> None:
    calls = []
    missing = CloudTTSClient.from_env(
        {}, opener=lambda *args, **kwargs: calls.append(1)
    )
    partial = CloudTTSClient.from_env(
        {"ALPECCA_CLOUD_TTS_ENDPOINT": ENDPOINT},
        opener=lambda *args, **kwargs: calls.append(1),
    )
    valid = CloudTTSClient.from_env(
        {
            "ALPECCA_CLOUD_TTS_ENDPOINT": ENDPOINT,
            "ALPECCA_CLOUD_TTS_AUTHORIZATION": SECRET,
            "ALPECCA_CLOUD_TTS_TIMEOUT_SECONDS": "3.5",
            "ALPECCA_CLOUD_TTS_MAX_RESPONSE_BYTES": "64",
            "ALPECCA_CLOUD_TTS_MAX_TEXT_BYTES": "32",
        },
        opener=lambda request, timeout: Response(),
    )

    assert missing.status().reason == "not_configured"
    assert partial.status().reason == "configuration_invalid"
    assert missing.synthesize("hello") is None
    assert partial.synthesize("hello") is None
    assert calls == []
    assert valid.status().configured
    assert valid.status().state == "unverified"
    assert valid.status().reason == "configured_not_called"


def test_configured_status_is_unverified_without_a_network_probe() -> None:
    calls = []
    client = CloudTTSClient(
        config(),
        opener=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    status = client.status()

    assert status.configured is True
    assert status.state == "unverified"
    assert status.reason == "configured_not_called"
    assert status.network_attempts == 0
    assert calls == []
    exposed = repr(status) + json.dumps(status.as_dict())
    assert "voice.example.test" not in exposed
    assert "/voice/tts" not in exposed
    assert "endpoint_host" not in status.as_dict()
    assert "endpoint_path" not in status.as_dict()


def test_failed_configured_route_is_degraded_but_missing_route_is_unavailable() -> None:
    configured = CloudTTSClient(
        config(),
        opener=lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )
    missing = CloudTTSClient.from_env({})

    assert configured.synthesize("hello") is None
    assert configured.status().state == "degraded"
    assert missing.synthesize("hello") is None
    assert missing.status().state == "unavailable"


def test_oversized_or_empty_text_fails_before_network() -> None:
    calls = []
    client = CloudTTSClient(
        config(max_text_bytes=4),
        opener=lambda *args, **kwargs: calls.append(1),
    )

    assert client.synthesize("") is None
    assert client.synthesize("ééé") is None
    assert calls == []
    status = client.status()
    assert status.reason == "invalid_text"
    assert status.calls == 2
    assert status.network_attempts == 0
    assert status.failures == 2


def test_unpaired_unicode_fails_truthfully_before_network() -> None:
    calls = []
    client = CloudTTSClient(
        config(),
        opener=lambda *args, **kwargs: calls.append(1),
    )

    assert client.synthesize("private\ud800text") is None
    assert calls == []
    status = client.status()
    assert status.state == "degraded"
    assert status.reason == "invalid_text"
    assert status.calls == 1
    assert status.network_attempts == 0
    assert status.failures == 1


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/json", "audio/basic", ""],
)
def test_unapproved_content_type_returns_none(content_type: str) -> None:
    response = Response(headers={"Content-Type": content_type})
    client = CloudTTSClient(config(), opener=lambda request, timeout: response)

    assert client.synthesize("hello") is None
    assert client.status().reason == "content_type_not_allowed"
    assert response.read_sizes == []


def test_declared_oversized_body_is_rejected_without_reading() -> None:
    response = Response(headers={"Content-Length": "5"})
    client = CloudTTSClient(
        config(max_response_bytes=4),
        opener=lambda request, timeout: response,
    )

    assert client.synthesize("hello") is None
    assert client.status().reason == "response_too_large"
    assert client.status().last_response_bytes == 5
    assert response.read_sizes == []


def test_undeclared_oversized_body_uses_one_bounded_read() -> None:
    response = Response(body=b"12345")
    client = CloudTTSClient(
        config(max_response_bytes=4),
        opener=lambda request, timeout: response,
    )

    assert client.synthesize("hello") is None
    assert client.status().reason == "response_too_large"
    assert response.read_sizes == [5]


def test_declared_and_actual_body_lengths_must_match() -> None:
    response = Response(body=b"1234", headers={"Content-Length": "3"})
    client = CloudTTSClient(config(), opener=lambda request, timeout: response)

    assert client.synthesize("hello") is None
    assert client.status().reason == "content_length_mismatch"
    assert client.status().last_response_bytes == 4


@pytest.mark.parametrize("length", ["bad", "-1"])
def test_invalid_content_length_is_rejected(length: str) -> None:
    response = Response(headers={"Content-Length": length})
    client = CloudTTSClient(config(), opener=lambda request, timeout: response)

    assert client.synthesize("hello") is None
    assert client.status().reason == "invalid_content_length"


def test_elapsed_time_limit_discards_otherwise_valid_audio() -> None:
    client = CloudTTSClient(
        config(timeout_seconds=1.0),
        opener=lambda request, timeout: Response(),
        clock=Clock(10.0, 11.1),
    )

    assert client.synthesize("hello") is None
    assert client.status().reason == "time_limit_exceeded"
    assert client.status().last_elapsed_ms == 1100


def test_absolute_deadline_stops_slow_chunked_read_and_tightens_socket() -> None:
    class Socket:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def settimeout(self, value: float) -> None:
            self.timeouts.append(value)

    class SlowResponse(Response):
        def __init__(self) -> None:
            super().__init__(body=b"")
            self.chunks = [b"RI", b"FF", b"late"]
            self.socket = Socket()
            self.fp = SimpleNamespace(
                raw=SimpleNamespace(_sock=self.socket),
            )

        def read(self, size: int) -> bytes:
            self.read_sizes.append(size)
            return self.chunks.pop(0) if self.chunks else b""

    response = SlowResponse()
    client = CloudTTSClient(
        config(timeout_seconds=1.0),
        opener=lambda request, timeout: response,
        clock=Clock(0.0, 0.0, 0.4, 0.4, 1.0),
    )

    assert client.synthesize("hello") is None
    assert len(response.read_sizes) == 2
    assert all(size <= 64 * 1024 for size in response.read_sizes)
    assert response.chunks == [b"late"]
    assert response.socket.timeouts == pytest.approx([1.0, 0.6])
    status = client.status()
    assert status.reason == "time_limit_exceeded"
    assert status.last_elapsed_ms == 1000
    assert status.last_response_bytes == 4


@pytest.mark.parametrize(
    "failure",
    [
        URLError("contains private transport detail"),
        TimeoutError("contains private timeout detail"),
        OSError("contains private OS detail"),
    ],
)
def test_transport_errors_are_sanitized(failure: Exception) -> None:
    def opener(request, timeout):
        raise failure

    client = CloudTTSClient(config(), opener=opener)
    assert client.synthesize(PRIVATE_TEXT) is None

    encoded = repr(client.status())
    assert client.status().reason == "transport_error"
    assert "private" not in encoded
    assert SECRET not in encoded
    assert PRIVATE_TEXT not in encoded


def test_redirect_http_error_is_not_followed_or_exposed() -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        raise HTTPError(
            request.full_url,
            302,
            "redirect to secret location",
            {"Location": "https://other.example.test/voice/tts"},
            None,
        )

    client = CloudTTSClient(config(), opener=opener)

    assert client.synthesize("hello") is None
    assert calls == [ENDPOINT]
    assert client.status().reason == "http_status"
    assert client.status().last_http_status == 302
    assert "other.example" not in repr(client.status())


def test_injected_opener_cannot_hide_a_cross_target_final_url() -> None:
    response = Response(final_url="https://other.example.test/voice/tts")
    client = CloudTTSClient(config(), opener=lambda request, timeout: response)

    assert client.synthesize("hello") is None
    assert client.status().reason == "target_mismatch"
    assert response.read_sizes == []
    assert "other.example" not in repr(client.status())


def test_response_metadata_allows_only_safe_request_id() -> None:
    unsafe = Response(headers={"X-Alpecca-Request-Id": "secret value with spaces"})
    safe = Response(headers={"X-Alpecca-Request-Id": "req_42:attempt-1"})
    responses = iter((unsafe, safe))
    client = CloudTTSClient(
        config(), opener=lambda request, timeout: next(responses)
    )

    first = client.synthesize("one")
    second = client.synthesize("two")

    assert first is not None and "request_id" not in first[2]
    assert second is not None and second[2]["request_id"] == "req_42:attempt-1"


def test_non_200_and_empty_response_have_truthful_fixed_status() -> None:
    responses = iter((Response(status=503), Response(body=b"")))
    client = CloudTTSClient(
        config(), opener=lambda request, timeout: next(responses)
    )

    assert client.synthesize("one") is None
    assert client.status().reason == "http_status"
    assert client.status().last_http_status == 503
    assert client.synthesize("two") is None
    assert client.status().reason == "empty_response"
    assert client.status().last_response_bytes == 0
