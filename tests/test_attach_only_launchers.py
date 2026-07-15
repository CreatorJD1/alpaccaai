from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from alpecca import instance as instance_mod


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
SHARE_PATH = ROOT / "scripts" / "share.py"
NAMED_TUNNEL_PATH = ROOT / "scripts" / "run_cloudflare_tunnel.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_attach_only_entry_points_have_no_backend_loader():
    for path in (APP_PATH, SHARE_PATH, NAMED_TUNNEL_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            alias.name.partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            (node.module or "").partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert "server" not in imported
        assert "uvicorn" not in imported


def test_share_fails_closed_before_opening_a_relay(monkeypatch, capsys):
    share = _load(SHARE_PATH, "attach_only_share_missing")
    monkeypatch.setattr(instance_mod, "existing_server_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(share, "lan_ip", lambda: "192.0.2.1")
    monkeypatch.setattr(
        share,
        "start_tunnel",
        lambda port: (_ for _ in ()).throw(AssertionError("relay must stay closed")),
    )
    monkeypatch.setattr(share.sys, "argv", ["share.py", "--tunnel"])

    assert share.main() == 2
    assert "START_HERE.bat" in capsys.readouterr().err


def test_share_attaches_phone_relay_to_verified_instance(monkeypatch):
    share = _load(SHARE_PATH, "attach_only_share_running")
    monkeypatch.setattr(
        instance_mod,
        "existing_server_url",
        lambda *args, **kwargs: "http://127.0.0.1:8765",
    )
    monkeypatch.setattr(share, "lan_ip", lambda: "192.0.2.1")
    relays: list[int] = []
    monkeypatch.setattr(share, "start_tunnel", lambda port: relays.append(port) or True)
    monkeypatch.setattr(
        share.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(share.sys, "argv", ["share.py", "--tunnel"])

    assert share.main() == 0
    assert relays == [8765]


def test_named_tunnel_fails_before_cloudflared_or_subprocess(monkeypatch, capsys):
    tunnel = _load(NAMED_TUNNEL_PATH, "attach_only_named_tunnel")
    monkeypatch.setattr(tunnel.instance_mod, "existing_server_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tunnel.preview,
        "find_cloudflared",
        lambda: (_ for _ in ()).throw(AssertionError("cloudflared must not be inspected")),
    )
    monkeypatch.setattr(tunnel.sys, "argv", ["run_cloudflare_tunnel.py"])

    assert tunnel.main() == 2
    assert "scripts\\run_full.py" in capsys.readouterr().err


def test_app_fails_closed_without_opening_a_surface(monkeypatch, capsys):
    app = _load(APP_PATH, "attach_only_app_missing")
    monkeypatch.setattr(app.instance_mod, "existing_server_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app,
        "_issue_local_bootstrap_url",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no bootstrap")),
    )

    assert app.main() == 2
    assert "START_HERE.bat" in capsys.readouterr().err


def test_app_requests_bootstrap_from_verified_loopback_transport(monkeypatch):
    app = _load(APP_PATH, "attach_only_app_bootstrap")
    base_url = "http://127.0.0.1:8765"
    endpoint = base_url + "/auth/bootstrap/request"
    bootstrap = base_url + "/auth/bootstrap?code=one-use&next=%2F"
    seen: dict[str, object] = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return endpoint

        def read(self, limit):
            seen["limit"] = limit
            return json.dumps({"url": bootstrap}).encode("utf-8")

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["headers"] = {key.casefold(): value for key, value in request.header_items()}
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(
        app.auth_mod,
        "load_or_create_authorization_secret",
        lambda home: "protected-test-secret",
    )

    assert app._issue_local_bootstrap_url(base_url=base_url, opener=opener) == bootstrap
    assert seen["url"] == endpoint
    assert seen["method"] == "POST"
    assert seen["headers"][app.auth_mod.AUTHORIZATION_HEADER.casefold()] == "protected-test-secret"
    assert seen["limit"] == app._MAX_BOOTSTRAP_BYTES + 1


def test_app_rejects_non_loopback_or_malformed_bootstrap_urls():
    app = _load(APP_PATH, "attach_only_app_bootstrap_validation")
    base_url = "http://127.0.0.1:8765"

    assert app._valid_bootstrap_url(
        base_url + "/auth/bootstrap?code=one-use&next=%2Fhouse-hq",
        base_url,
    )
    assert not app._valid_bootstrap_url(
        "https://public.example/auth/bootstrap?code=one-use&next=%2F",
        base_url,
    )
    assert not app._valid_bootstrap_url(
        base_url + "/auth/bootstrap?next=%2F",
        base_url,
    )
    assert not app._valid_bootstrap_url(
        base_url + "/auth/bootstrap?code=one&code=two&next=%2F",
        base_url,
    )


def test_app_attaches_window_without_starting_backend(monkeypatch):
    app = _load(APP_PATH, "attach_only_app_running")
    base_url = "http://127.0.0.1:8765"
    bootstrap = base_url + "/auth/bootstrap?code=one-use&next=%2F"
    seen: dict[str, object] = {}
    monkeypatch.setattr(app.instance_mod, "existing_server_url", lambda *args, **kwargs: base_url)

    def issue_bootstrap(*args, **kwargs):
        seen["base_url"] = kwargs["base_url"]
        return bootstrap

    monkeypatch.setattr(
        app,
        "_issue_local_bootstrap_url",
        issue_bootstrap,
    )
    monkeypatch.setattr(app.config, "TUNNEL", "off")
    fake_webview = SimpleNamespace(
        create_window=lambda *args, **kwargs: seen.setdefault("window_url", args[1]),
        start=lambda: seen.setdefault("started", True),
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    assert app.main() == 0
    assert seen == {
        "base_url": base_url,
        "window_url": bootstrap,
        "started": True,
    }
