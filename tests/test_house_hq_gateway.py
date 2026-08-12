"""Focused verification for the compute-only House HQ edge gateway.

Spins up a real stub "primary" over a loopback socket and drives the gateway
end-to-end: static SPA/assets/VRM served locally, authenticated HTTP + WebSocket
proxied to the primary, anonymous protected-route rejection relayed, read-only
standby and offline fallback when the primary is down, and the compute-only
contract (never imports ``server``).
"""
from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

ROOT = Path(__file__).resolve().parent.parent
_GW_PATH = ROOT / "scripts" / "run_house_hq_gateway.py"
_spec = importlib.util.spec_from_file_location("run_house_hq_gateway", _GW_PATH)
gw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gw)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _StubServer:
    def __init__(self, app: FastAPI) -> None:
        self.port = _free_port()
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port,
                           log_level="warning", ws_max_size=None)
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> "_StubServer":
        self._thread.start()
        for _ in range(200):
            if self._server.started:
                break
            time.sleep(0.02)
        return self

    def __exit__(self, *exc) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)

    @property
    def http(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _primary_app() -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "upstream": "primary-stub"})

    @app.post("/channel/house-hq")
    async def channel(request: Request) -> JSONResponse:
        if request.headers.get("x-alpecca-authorization") != "Bearer test-secret":
            return JSONResponse({"detail": "authorization required"},
                                status_code=401)
        return JSONResponse({"reply": "acknowledged", "authed": True})

    @app.get("/state/read")
    async def read() -> JSONResponse:
        return JSONResponse({"ok": True, "source": "primary"})

    @app.websocket("/ws/house-hq")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()
        try:
            while True:
                msg = await sock.receive_text()
                await sock.send_text("echo:" + msg)
        except Exception:  # noqa: BLE001
            pass

    return app


def _standby_app() -> FastAPI:
    app = FastAPI()

    @app.get("/state/read")
    async def read() -> JSONResponse:
        # Standby tries to set a session; the gateway must strip it (read-only).
        return JSONResponse(
            {"ok": True, "source": "standby"},
            headers={"set-cookie": "alpecca_authorization=leak; Path=/"},
        )

    return app


def _client(primary: str, standby: str = "") -> TestClient:
    cfg = gw.GatewayConfig(environ={
        "ALPECCA_HOUSE_PRIMARY_URL": primary,
        "ALPECCA_HOUSE_STANDBY_URL": standby,
        "ALPECCA_HOUSE_PRIMARY_TIMEOUT": "2.0",
    })
    return TestClient(gw.build_app(cfg))


# --------------------------------------------------------------------------- #
# compute-only contract
# --------------------------------------------------------------------------- #
def test_gateway_never_imports_authoritative_server() -> None:
    assert "server" not in sys.modules, (
        "the House HQ edge gateway must never import the authoritative server"
    )
    # build_app must not raise ComputeOnlyHostError on this compute-only host.
    app = gw.build_app(gw.GatewayConfig(environ={}))
    assert app is not None


# --------------------------------------------------------------------------- #
# static: SPA / assets / VRM
# --------------------------------------------------------------------------- #
def test_house_hq_html_served_at_root_and_house_hq() -> None:
    with _client("http://127.0.0.1:%d" % _free_port()) as client:
        for path in ("/", "/house-hq"):
            r = client.get(path)
            assert r.status_code == 200
            assert "text/html" in r.headers["content-type"]
            assert 'id="app"' in r.text
            assert "/assets/index-" in r.text


def test_static_asset_and_vrma_animation_served_locally() -> None:
    with _client("http://127.0.0.1:%d" % _free_port()) as client:
        r = client.get("/assets/vrma/CC0-walk.vrma")
        assert r.status_code == 200
        assert len(r.content) > 0


def test_vrm_manifest_and_model_served_from_placed_body() -> None:
    with _client("http://127.0.0.1:%d" % _free_port()) as client:
        m = client.get("/vrm/manifest")
        assert m.status_code == 200
        body = m.json()
        assert body["vrm_mode"] is True
        assert body["model_file"].endswith(".vrm")
        assert body["model_bytes"] > 0
        model = client.get("/vrm/model/" + body["model_file"])
        assert model.status_code == 200
        assert model.headers["content-type"] == "model/gltf-binary"
        assert len(model.content) == body["model_bytes"]


# --------------------------------------------------------------------------- #
# proxy: health / chat / auth forwarding / anonymous rejection
# --------------------------------------------------------------------------- #
def test_health_and_chat_proxied_with_auth_forwarding() -> None:
    with _StubServer(_primary_app()) as primary:
        with _client(primary.http) as client:
            h = client.get("/healthz")  # gateway's own health, not proxied
            assert h.json()["role"] == "compute-only-house-gateway"

            authed = client.post(
                "/channel/house-hq",
                headers={"X-Alpecca-Authorization": "Bearer test-secret"},
                json={"text": "hello"},
            )
            assert authed.status_code == 200
            assert authed.json()["authed"] is True


def test_anonymous_protected_route_is_rejected() -> None:
    with _StubServer(_primary_app()) as primary:
        with _client(primary.http) as client:
            anon = client.post("/channel/house-hq", json={"text": "hello"})
            assert anon.status_code == 401
            assert anon.json()["detail"] == "authorization required"


def test_chat_websocket_is_proxied_bidirectionally() -> None:
    with _StubServer(_primary_app()) as primary:
        with _client(primary.http) as client:
            with client.websocket_connect("/ws/house-hq") as ws:
                ws.send_text("ping")
                assert ws.receive_text() == "echo:ping"


# --------------------------------------------------------------------------- #
# offline / standby behavior
# --------------------------------------------------------------------------- #
def test_backend_offline_returns_503_without_fabricating() -> None:
    dead = "http://127.0.0.1:%d" % _free_port()  # nothing is listening
    with _client(dead) as client:
        r = client.post("/channel/house-hq", json={"text": "hi"})
        assert r.status_code == 503
        assert r.json()["mode"] == "offline"
        assert r.headers.get("X-Alpecca-Edge-Mode") == "offline"


def test_offline_websocket_closes_with_try_again_later() -> None:
    dead = "http://127.0.0.1:%d" % _free_port()
    with _client(dead) as client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/ws/house-hq") as ws:
                ws.receive_text()
        assert excinfo.value.code == 1013


def test_safe_read_falls_back_to_readonly_standby_and_strips_cookie() -> None:
    dead = "http://127.0.0.1:%d" % _free_port()
    with _StubServer(_standby_app()) as standby:
        with _client(dead, standby=standby.http) as client:
            r = client.get("/state/read")
            assert r.status_code == 200
            assert r.json()["source"] == "standby"
            assert r.headers.get("X-Alpecca-Edge-Mode") == "standby-read-only"
            assert "set-cookie" not in {k.lower() for k in r.headers}
