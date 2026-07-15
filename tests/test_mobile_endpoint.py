from __future__ import annotations

import json

from alpecca.mobile_endpoint import (
    build_endpoint_document,
    probe_alpecca_endpoint,
    read_endpoint_candidates,
)


def test_mobile_discovery_orders_named_and_rejects_expired_quick_endpoints():
    document = build_endpoint_document(
        [
            ("https://quick-name.trycloudflare.com", "quick", 10),
            ("https://alpecca.example.com", "named", 0),
        ],
        now=100,
        quick_ttl_seconds=60,
    )
    assert [row["kind"] for row in document["endpoints"]] == ["named", "quick"]
    assert [item.url for item in read_endpoint_candidates(document, now=159)] == [
        "https://alpecca.example.com",
        "https://quick-name.trycloudflare.com",
    ]
    assert [item.url for item in read_endpoint_candidates(document, now=160)] == [
        "https://alpecca.example.com",
    ]


def test_mobile_discovery_never_serializes_credentials_or_query_tokens():
    document = build_endpoint_document(
        [
            ("https://user:secret@example.com", "named", 0),
            ("https://example.com/?token=secret", "quick", 10),
        ],
        now=100,
    )
    assert document["endpoints"] == []
    serialized = json.dumps(document)
    assert "secret" not in serialized
    assert "token" not in serialized


def test_mobile_probe_requires_exact_alpecca_identity():
    good = lambda _url, _timeout: (200, b'{"service":"alpecca","version":1}')
    wrong = lambda _url, _timeout: (200, b'{"service":"other","version":1}')
    unauthorized = lambda _url, _timeout: (401, b'{"service":"alpecca","version":1}')

    assert probe_alpecca_endpoint("https://alpecca.example.com", opener=good)
    assert not probe_alpecca_endpoint("https://alpecca.example.com", opener=wrong)
    assert not probe_alpecca_endpoint("https://alpecca.example.com", opener=unauthorized)
