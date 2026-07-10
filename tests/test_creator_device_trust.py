"""Creator device trust and password-enrollment regression coverage."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi.testclient import TestClient

from alpecca import auth


TEST_PASSWORD = "test-only-creator-password-2044"


def test_password_exchange_mints_long_lived_signed_session_without_plaintext():
    authority = auth.SessionAuthority(
        "test-only-server-authorization-secret",
        session_ttl_s=180 * 24 * 60 * 60,
        creator_password=TEST_PASSWORD,
    )

    denied, missing_cookie = authority.exchange_password(
        "wrong-password", "192.0.2.10", secure=True, now=1_000
    )
    accepted, cookie = authority.exchange_password(
        TEST_PASSWORD, "192.0.2.10", secure=True, now=1_001
    )

    assert denied.allowed is False
    assert missing_cookie is None
    assert accepted.allowed is True
    assert cookie is not None
    assert cookie.max_age == 180 * 24 * 60 * 60
    assert cookie.httponly is True
    assert cookie.samesite == "strict"
    assert TEST_PASSWORD not in cookie.value
    assert authority.validate_session_cookie(cookie.value, now=1_002).allowed


def test_password_failures_are_rate_limited_per_remote_peer():
    authority = auth.SessionAuthority(
        "test-only-server-authorization-secret",
        creator_password=TEST_PASSWORD,
    )
    for second in range(5):
        decision = authority.validate_password(
            "wrong-password", "198.51.100.20", now=1_000 + second
        )
        assert decision.reason == "rejected"

    limited = authority.validate_password(
        TEST_PASSWORD, "198.51.100.20", now=1_005
    )
    later = authority.validate_password(
        TEST_PASSWORD, "198.51.100.20", now=1_061
    )

    assert limited.reason == "rate_limited"
    assert later.allowed is True


def test_loopback_browser_is_enrolled_without_password(monkeypatch):
    import server

    authority = auth.SessionAuthority(
        "test-only-loopback-secret",
        session_ttl_s=180 * 24 * 60 * 60,
        creator_password=TEST_PASSWORD,
    )
    monkeypatch.setattr(server, "_AUTHORITY", authority)
    client = TestClient(server.app, client=("127.0.0.1", 50100))

    first = client.get(
        "/house-hq",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert first.status_code == 303
    bootstrap = urlsplit(first.headers["location"])
    assert bootstrap.path == "/auth/bootstrap"
    query = parse_qs(bootstrap.query)
    exchange = client.post(
        "/auth/bootstrap/exchange?" + urlencode({
            "code": query["code"][0],
            "next": query["next"][0],
        }),
        follow_redirects=False,
    )
    assert exchange.status_code == 303
    assert exchange.headers["location"] == "/house-hq"
    assert auth.SESSION_COOKIE_NAME in exchange.headers["set-cookie"]
    assert "HttpOnly" in exchange.headers["set-cookie"]
    assert client.get("/house-hq").status_code == 200


def test_remote_browser_validates_once_then_uses_trusted_cookie(monkeypatch):
    import server

    authority = auth.SessionAuthority(
        "test-only-remote-secret",
        session_ttl_s=180 * 24 * 60 * 60,
        creator_password=TEST_PASSWORD,
    )
    monkeypatch.setattr(server, "_AUTHORITY", authority)
    client = TestClient(
        server.app,
        base_url="https://alpecca.example",
        client=("192.0.2.44", 50101),
    )

    sign_in = client.get("/house-hq", headers={"Accept": "text/html"})
    assert sign_in.status_code == 401
    assert 'type="password"' in sign_in.text
    assert TEST_PASSWORD not in sign_in.text

    enrolled = client.post(
        "/auth/password",
        data={"password": TEST_PASSWORD, "next": "/house-hq"},
        headers={"Origin": "https://alpecca.example"},
        follow_redirects=False,
    )
    assert enrolled.status_code == 303
    assert enrolled.headers["location"] == "/house-hq"
    assert "HttpOnly" in enrolled.headers["set-cookie"]
    assert client.get("/house-hq").status_code == 200
    same_origin_post = client.post(
        "/route-that-does-not-exist",
        headers={"Origin": "https://alpecca.example"},
    )
    assert same_origin_post.status_code == 404


def test_remote_password_exchange_rejects_cleartext_http(monkeypatch):
    import server

    authority = auth.SessionAuthority(
        "test-only-remote-secret",
        creator_password=TEST_PASSWORD,
    )
    monkeypatch.setattr(server, "_AUTHORITY", authority)
    client = TestClient(
        server.app,
        base_url="http://192.0.2.44",
        client=("192.0.2.44", 50102),
    )

    landing = client.get("/house-hq", headers={"Accept": "text/html"})
    assert landing.status_code == 401
    assert 'type="password"' not in landing.text
    assert "requires an HTTPS address" in landing.text

    response = client.post(
        "/auth/password",
        data={"password": TEST_PASSWORD, "next": "/house-hq"},
        headers={"Origin": "http://192.0.2.44"},
        follow_redirects=False,
    )

    assert response.status_code == 426
    assert response.json()["detail"] == "remote creator sign-in requires HTTPS"
    assert "set-cookie" not in response.headers


def test_launcher_and_app_sources_do_not_put_credentials_in_urls():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "apps" / "launcher" / "src" / "alpecca_launcher.py").read_text(
        encoding="utf-8"
    )
    app = (root / "web" / "app.html").read_text(encoding="utf-8")

    assert "from config import ACCESS_TOKEN" not in launcher
    assert "?token=" not in launcher
    assert "?token=" not in app
    assert "/auth/bootstrap/request" in launcher
    assert 'type="password"' not in app
