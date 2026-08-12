#!/usr/bin/env python3
"""Alpecca House HQ compute-only edge gateway (assigned host: Jason_HOLYROG).

This process serves the *built* House HQ single-page app statically and
reverse-proxies authenticated HTTP + WebSocket traffic to the single
authoritative primary (RygenART), with an optional read-only cloud standby and
a safe offline fallback when the primary is unreachable.

COMPUTE-ONLY CONTRACT (mirrors scripts/run_rog_compute_worker.py's discipline):
  * It never imports ``server`` and never calls ``require_primary_runtime_host``
    -- so it is not one of the authoritative entrypoints pinned by
    tests/test_host_roles.py and it does not trip ComputeOnlyHostError.
  * It owns no CoreMind, Discord bridge, autonomy loop, memory writer, model,
    tunnel-of-its-own, or continuity lease.
  * It mints no authorization. It only forwards the caller's ``Cookie``,
    ``X-Alpecca-Authorization`` and ``Origin`` to the primary, which stays the
    sole authority. Anonymous requests to protected routes are rejected by the
    primary (401/403) and that rejection is relayed verbatim; when the primary
    is offline the gateway returns 503 and never fabricates a success or serves
    protected content itself.

The SPA resolves its backend to ``window.location.origin`` when served from a
non-preview host (apps/house-hq/src/main.ts), so fronting it same-origin needs
no ``?backend=`` parameter: the browser's /ws/house-hq, /channel/house-hq and
/vrm/* calls arrive here and are proxied.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterable, Optional

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.background import BackgroundTask

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Informational only -- is_compute_only_host() never raises (unlike
# require_primary_runtime_host, which we deliberately do NOT call).
from alpecca.host_roles import is_compute_only_host  # noqa: E402

DIST = ROOT / "apps" / "house-hq" / "dist"
PUBLIC = ROOT / "apps" / "house-hq" / "public"
VRM_DIR = ROOT / "data" / "avatar" / "vrm"

# Static clip roster the primary advertises (alpecca/vrm.py); kept in sync so an
# offline edge still describes the body the SPA loads from /vrm/model.
VRM_CLIPS = [
    "cheer", "cry", "dance", "idle", "idle_soft",
    "sit", "sleep", "talking", "thinking", "wave",
]

# Hop-by-hop headers must not be forwarded across the proxy boundary.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
})

# Paths served locally from the built bundle / placed assets. Everything else is
# proxied to the primary.
_STATIC_PREFIXES = ("/assets/",)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value is not None else default


class GatewayConfig:
    def __init__(self, environ: Optional[dict] = None) -> None:
        e = environ if environ is not None else os.environ
        self.host = e.get("ALPECCA_HOUSE_GATEWAY_HOST", "127.0.0.1")
        self.port = int(e.get("ALPECCA_HOUSE_GATEWAY_PORT", "8765"))
        # The single authoritative primary (RygenART). Tailscale encrypts the
        # hop, so plain http over the tailnet is the default.
        self.primary = e.get(
            "ALPECCA_HOUSE_PRIMARY_URL", "http://100.96.54.97:8765"
        ).rstrip("/")
        # Optional read-only cloud standby used only for SAFE (GET/HEAD) requests
        # when the primary is unreachable. Never receives writes.
        self.standby = e.get("ALPECCA_HOUSE_STANDBY_URL", "").rstrip("/")
        self.public_origin = e.get(
            "ALPECCA_HOUSE_PUBLIC_ORIGIN",
            "https://jason-holyrog.tailda0108.ts.net",
        )
        self.connect_timeout = float(e.get("ALPECCA_HOUSE_PRIMARY_TIMEOUT", "3.0"))

    def ws_base(self, http_base: str) -> str:
        if http_base.startswith("https://"):
            return "wss://" + http_base[len("https://"):]
        if http_base.startswith("http://"):
            return "ws://" + http_base[len("http://"):]
        return http_base


def _safe_static(base: Path, rel: str) -> Optional[Path]:
    """Resolve ``rel`` under ``base`` refusing traversal outside it."""
    rel = rel.lstrip("/")
    try:
        candidate = (base / rel).resolve()
        base_resolved = base.resolve()
    except (OSError, RuntimeError):
        return None
    if candidate == base_resolved or base_resolved in candidate.parents:
        if candidate.is_file():
            return candidate
    return None


def _forward_request_headers(request: Request) -> dict:
    headers = {}
    for key, value in request.headers.items():
        if key.lower() in _HOP_BY_HOP:
            continue
        headers[key] = value
    return headers


def _forward_response_headers(upstream: httpx.Response) -> dict:
    headers = {}
    for key, value in upstream.headers.items():
        if key.lower() in _HOP_BY_HOP or key.lower() == "content-encoding":
            # httpx already decoded the body; drop content-encoding/length so the
            # ASGI server frames it correctly.
            continue
        headers[key] = value
    return headers


def build_app(config: Optional[GatewayConfig] = None) -> FastAPI:
    cfg = config or GatewayConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=cfg.connect_timeout),
            follow_redirects=False,
        )
        try:
            yield
        finally:
            await app.state.client.aclose()

    app = FastAPI(
        title="Alpecca House HQ Gateway",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.config = cfg

    # ---- gateway's own health (content-free; not proxied) -----------------
    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "role": "compute-only-house-gateway",
                "host": socket.gethostname(),
                "compute_only": is_compute_only_host(),
            }
        )

    # ---- static SPA shell --------------------------------------------------
    async def _serve_index() -> Response:
        index = DIST / "index.html"
        if not index.is_file():
            return JSONResponse(
                {"detail": "House HQ bundle not built"}, status_code=503
            )
        return FileResponse(index, media_type="text/html")

    @app.get("/")
    async def root_index() -> Response:
        return await _serve_index()

    @app.get("/house-hq")
    @app.get("/house-hq/{_path:path}")
    async def house_hq(_path: str = "") -> Response:
        return await _serve_index()

    @app.get("/manifest.webmanifest")
    async def manifest() -> Response:
        for base in (DIST, PUBLIC):
            hit = _safe_static(base, "manifest.webmanifest")
            if hit:
                return FileResponse(hit, media_type="application/manifest+json")
        return Response(status_code=404)

    # ---- static bundle + art assets (dist first, then public) --------------
    @app.get("/assets/{path:path}")
    async def assets(path: str, request: Request) -> Response:
        for base in (DIST / "assets", PUBLIC / "assets"):
            hit = _safe_static(base, path)
            if hit:
                return FileResponse(hit)
        # Fall back to proxying (e.g. art the primary generates on demand).
        return await _proxy_http(request)

    # ---- VRM served locally from the placed body ---------------------------
    @app.get("/vrm/manifest")
    async def vrm_manifest() -> JSONResponse:
        model = _current_vrm()
        if model is None:
            return JSONResponse(
                {"vrm_mode": False, "model_file": None, "clips": VRM_CLIPS}
            )
        raw = model.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        stat = model.stat()
        return JSONResponse(
            {
                "vrm_mode": True,
                "model_file": model.name,
                "model_version": digest[:16],
                "model_sha256": digest,
                "model_bytes": len(raw),
                "model_mtime_ns": stat.st_mtime_ns,
                "clips": VRM_CLIPS,
                "vrm_spec_version": "1.0",
                "look_at": True,
                "look_at_type": "bone",
                "expressions": [],
                "studio": False,
            }
        )

    @app.get("/vrm/model/{name}")
    async def vrm_model(name: str) -> Response:
        hit = _safe_static(VRM_DIR, name)
        if hit and hit.suffix.lower() == ".vrm":
            return FileResponse(
                hit,
                media_type="model/gltf-binary",
                headers={"Cache-Control": "no-cache, max-age=0, must-revalidate"},
            )
        return Response(status_code=404)

    # ---- reverse proxy: everything else ------------------------------------
    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def catch_all(path: str, request: Request) -> Response:
        return await _proxy_http(request)

    async def _proxy_http(request: Request) -> Response:
        cfg = app.state.config
        client: httpx.AsyncClient = app.state.client
        body = await request.body()
        headers = _forward_request_headers(request)
        target_path = request.url.path
        query = ("?" + request.url.query) if request.url.query else ""
        url = cfg.primary + target_path + query
        try:
            upstream = await client.request(
                request.method, url, headers=headers, content=body
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                httpx.RemoteProtocolError, socket.gaierror, OSError):
            return await _offline_fallback(request, body, headers)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=_forward_response_headers(upstream),
        )

    async def _offline_fallback(request: Request, body: bytes,
                                headers: dict) -> Response:
        cfg = app.state.config
        safe = request.method in ("GET", "HEAD")
        if safe and cfg.standby:
            client: httpx.AsyncClient = app.state.client
            url = cfg.standby + request.url.path + (
                ("?" + request.url.query) if request.url.query else ""
            )
            try:
                upstream = await client.request(
                    request.method, url, headers=headers, content=body
                )
            except Exception:  # noqa: BLE001 -- standby is best-effort
                pass
            else:
                resp_headers = _forward_response_headers(upstream)
                # Standby is strictly read-only: never let it set a session.
                resp_headers.pop("set-cookie", None)
                resp_headers["X-Alpecca-Edge-Mode"] = "standby-read-only"
                return Response(
                    content=upstream.content,
                    status_code=upstream.status_code,
                    headers=resp_headers,
                )
        return JSONResponse(
            {
                "detail": "authoritative backend offline",
                "mode": "offline",
                "role": "compute-only-house-gateway",
            },
            status_code=503,
            headers={"X-Alpecca-Edge-Mode": "offline"},
        )

    # ---- reverse proxy: chat WebSocket -------------------------------------
    @app.websocket("/ws")
    @app.websocket("/ws/house-hq")
    async def ws_proxy(websocket: WebSocket) -> None:
        await _proxy_ws(websocket)

    async def _proxy_ws(client_ws: WebSocket) -> None:
        cfg = app.state.config
        await client_ws.accept()
        ws_base = cfg.ws_base(cfg.primary)
        query = client_ws.url.query
        target = ws_base + client_ws.url.path + (("?" + query) if query else "")
        # Forward the auth-bearing headers the primary needs (Cookie,
        # X-Alpecca-Authorization) and the browser's Origin (the primary
        # enforces same-origin against its configured public origins).
        fwd_headers = [
            (k, v) for k, v in client_ws.headers.items()
            if k.lower() in ("cookie", "x-alpecca-authorization", "origin",
                             "user-agent")
        ]
        try:
            upstream = await websockets.connect(
                target,
                additional_headers=fwd_headers,
                open_timeout=cfg.connect_timeout,
                max_size=None,
            )
        except Exception:  # noqa: BLE001 -- primary unreachable / rejected
            # 1013 = try again later; never leave the client hanging.
            await client_ws.close(code=1013)
            return
        await _pump_ws(client_ws, upstream)

    async def _pump_ws(client_ws: WebSocket, upstream) -> None:
        async def client_to_upstream() -> None:
            try:
                while True:
                    message = await client_ws.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
            except (WebSocketDisconnect, Exception):  # noqa: BLE001
                pass
            finally:
                await upstream.close()

        async def upstream_to_client() -> None:
            try:
                async for message in upstream:
                    if isinstance(message, (bytes, bytearray)):
                        await client_ws.send_bytes(bytes(message))
                    else:
                        await client_ws.send_text(message)
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    await client_ws.close()
                except Exception:  # noqa: BLE001
                    pass

        await asyncio.gather(
            client_to_upstream(), upstream_to_client(), return_exceptions=True
        )

    return app


def _current_vrm() -> Optional[Path]:
    if not VRM_DIR.is_dir():
        return None
    models = sorted(VRM_DIR.glob("*.vrm"))
    return models[0] if models else None


def main(argv: Optional[Iterable[str]] = None) -> int:
    cfg = GatewayConfig()
    host_label = socket.gethostname()
    print(
        f"House HQ edge gateway (compute-only={is_compute_only_host()}, "
        f"host={host_label}) binding {cfg.host}:{cfg.port} -> primary "
        f"{cfg.primary}"
        + (f", standby {cfg.standby}" if cfg.standby else "")
    )
    app = build_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info", ws_max_size=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
