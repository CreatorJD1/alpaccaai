"""Standalone HTTP process for Agentic Frontier.

This module intentionally does not import Alpecca CoreMind, House HQ, config,
memory, or the companion database. The game exports episode candidates; a
separate companion-owned adapter decides whether any candidate becomes memory.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from .accounts import (
    MAX_AVATAR_BYTES,
    SESSION_SECONDS,
    AccountError,
    AuthenticationError,
    GameAccountStore,
)
from .engine import ACTION_CONTRACT_VERSION, AgenticFrontierStore, ContractError


APP_ID = "agentic-frontier"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8870
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOME = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "AgenticFrontier"
DEFAULT_DB = DEFAULT_HOME / "frontier.db"
WEB_ROOT = PACKAGE_ROOT / "web"
REPO_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_VRM = REPO_ROOT / "data" / "avatar" / "vrm" / "alpecca.vrm"
ACCOUNT_COOKIE = "alventius_session"


def _authorized(request: Request, token: str) -> bool:
    if not token:
        return False
    supplied = request.headers.get("authorization", "")
    return hmac.compare_digest(supplied, f"Bearer {token}")


def _secure_cookie(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    return forwarded == "https" or request.url.scheme == "https"


def create_app(
    *, db_path: Path | str | None = None, access_token: str | None = None
) -> FastAPI:
    selected_db = Path(db_path or os.environ.get(
        "AGENTIC_FRONTIER_DB", str(DEFAULT_DB)
    ))
    store_holder: dict[str, AgenticFrontierStore] = {}
    account_holder: dict[str, GameAccountStore] = {}

    def game_store() -> AgenticFrontierStore:
        if "store" not in store_holder:
            store_holder["store"] = AgenticFrontierStore(selected_db)
        return store_holder["store"]

    def account_store() -> GameAccountStore:
        if "store" not in account_holder:
            account_holder["store"] = GameAccountStore(selected_db)
        return account_holder["store"]

    token = os.environ.get("AGENTIC_FRONTIER_TOKEN", "") if access_token is None else access_token
    app = FastAPI(title="Alventius Experimentus API", version="0.3.0")
    app.state.frontier_db_path = selected_db
    app.state.frontier_store_factory = game_store
    app.state.app_id = APP_ID

    def cookie_account(request: Request) -> dict[str, Any] | None:
        return account_store().authenticate(request.cookies.get(ACCOUNT_COOKIE))

    async def require_account(request: Request) -> dict[str, Any]:
        account = cookie_account(request)
        if account is None:
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        return account

    async def require_player(request: Request) -> dict[str, Any] | None:
        account = cookie_account(request)
        if account is not None:
            return account
        if _authorized(request, token):
            return None
        raise HTTPException(status_code=401, detail="Sign in to continue.")

    def require_owned_world(account: dict[str, Any] | None, session_id: object) -> None:
        if account is not None and session_id != account["worldId"]:
            raise HTTPException(status_code=403, detail="That expedition belongs to another account.")

    def set_login_cookie(response: Response, request: Request, value: str) -> None:
        response.set_cookie(
            ACCOUNT_COOKIE,
            value,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=_secure_cookie(request),
            samesite="strict",
            path="/",
        )

    async def json_body(request: Request) -> Any:
        try:
            return await request.json()
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from exc

    @app.get("/healthz")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "appId": APP_ID,
            "kind": "game",
            "coreMind": False,
            "databaseOwner": APP_ID,
            "accessProtected": True,
            "accountAccess": True,
        }

    @app.get("/")
    def client() -> FileResponse:
        return FileResponse(
            WEB_ROOT / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/config")
    def game_config() -> dict[str, object]:
        selected_vrm = Path(os.environ.get("AGENTIC_FRONTIER_VRM", str(DEFAULT_VRM)))
        return {
            "appId": APP_ID,
            "title": "Alventius Experimentus",
            "contractVersion": ACTION_CONTRACT_VERSION,
            "world": "Vesper Dome / Tartarus Prime",
            "visualStyle": "anime-cel-shaded",
            "modes": ["first-person-exploration", "orthographic-colony-command"],
            "vrmUrl": "/assets/alpecca.vrm" if selected_vrm.is_file() else None,
            "accessProtected": True,
            "accountAccess": True,
        }

    @app.post("/api/auth/register")
    async def register(request: Request, response: Response) -> dict[str, Any]:
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {"username", "displayName", "password"}:
            raise HTTPException(status_code=400, detail="Registration fields are invalid.")
        try:
            account, session_token = account_store().register(
                body["username"], body["displayName"], body["password"]
            )
        except AccountError as exc:
            raise HTTPException(status_code=409 if "already registered" in str(exc) else 400, detail=str(exc)) from exc
        set_login_cookie(response, request, session_token)
        return {"account": account}

    @app.post("/api/auth/login")
    async def login(request: Request, response: Response) -> dict[str, Any]:
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {"username", "password"}:
            raise HTTPException(status_code=400, detail="Login fields are invalid.")
        try:
            account, session_token = account_store().login(body["username"], body["password"])
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except AccountError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        set_login_cookie(response, request, session_token)
        return {"account": account}

    @app.get("/api/auth/me")
    async def me(request: Request) -> dict[str, Any]:
        return {"account": await require_account(request)}

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response) -> dict[str, bool]:
        account_store().logout(request.cookies.get(ACCOUNT_COOKIE))
        response.delete_cookie(ACCOUNT_COOKIE, path="/", samesite="strict")
        return {"ok": True}

    @app.get("/api/avatars")
    async def avatars(request: Request) -> dict[str, Any]:
        account = await require_account(request)
        return account_store().avatar_catalog(account["accountId"])

    @app.put("/api/account/avatar")
    async def select_avatar(request: Request) -> dict[str, Any]:
        account = await require_account(request)
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {"avatarId"}:
            raise HTTPException(status_code=400, detail="avatarId is required.")
        try:
            return account_store().select_avatar(account["accountId"], body["avatarId"])
        except AccountError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/account/avatar/custom")
    async def upload_avatar(request: Request) -> dict[str, Any]:
        account = await require_account(request)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_AVATAR_BYTES:
            raise HTTPException(status_code=413, detail="Player VRM cannot exceed 32 MiB.")
        payload = await request.body()
        try:
            return account_store().store_custom_avatar(account["accountId"], payload)
        except AccountError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/account/avatar/model")
    async def player_avatar(request: Request) -> FileResponse:
        account = await require_account(request)
        try:
            selected = account_store().avatar_path(account["accountId"])
        except AccountError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            selected,
            media_type="model/gltf-binary",
            filename="player-avatar.vrm",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.get("/assets/alpecca.vrm")
    def alpecca_vrm() -> FileResponse:
        selected_vrm = Path(os.environ.get("AGENTIC_FRONTIER_VRM", str(DEFAULT_VRM)))
        if not selected_vrm.is_file():
            raise HTTPException(status_code=404, detail="Configured VRM asset is unavailable")
        return FileResponse(
            selected_vrm,
            media_type="model/gltf-binary",
            filename="alpecca.vrm",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.post("/api/sessions")
    async def create_session(request: Request) -> dict[str, Any]:
        account = await require_player(request)
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {"session_id"}:
            raise HTTPException(status_code=400, detail="session_id is required")
        require_owned_world(account, body["session_id"])
        try:
            state = game_store().create_session(body["session_id"])
            return {
                "appId": APP_ID,
                "session_id": state["session_id"],
                "revision": state["revision"],
                "status": state["status"],
            }
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/perception/{actor_id}")
    async def perception(session_id: str, actor_id: str, request: Request) -> dict[str, Any]:
        account = await require_player(request)
        require_owned_world(account, session_id)
        if account is not None and actor_id != "Jason":
            raise HTTPException(status_code=403, detail="Player accounts cannot assume companion identity.")
        try:
            return game_store().perceive(session_id, actor_id)
        except ContractError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/actions")
    async def action(request: Request) -> dict[str, Any]:
        account = await require_player(request)
        body = await json_body(request)
        if isinstance(body, dict):
            require_owned_world(account, body.get("session_id"))
            if account is not None and body.get("actor_id") != "Jason":
                raise HTTPException(status_code=403, detail="Player accounts cannot act as Alpecca.")
        try:
            return game_store().execute_action(body)
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/reconnect/{actor_id}")
    async def reconnect(
        session_id: str, actor_id: str, request: Request, after_revision: int = 0
    ) -> dict[str, Any]:
        account = await require_player(request)
        require_owned_world(account, session_id)
        if account is not None and actor_id != "Jason":
            raise HTTPException(status_code=403, detail="Player accounts cannot assume companion identity.")
        try:
            return game_store().reconnect(session_id, actor_id, after_revision)
        except ContractError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/episode-candidates")
    async def episodes(session_id: str, request: Request) -> dict[str, object]:
        account = await require_player(request)
        require_owned_world(account, session_id)
        try:
            candidates = game_store().list_episode_candidates(session_id)
        except ContractError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "appId": APP_ID,
            "companionWritePerformed": False,
            "candidates": candidates,
        }

    return app


app = create_app()


def main() -> None:
    host = os.environ.get("AGENTIC_FRONTIER_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    port = int(os.environ.get("AGENTIC_FRONTIER_PORT", str(DEFAULT_PORT)))
    if host not in {"127.0.0.1", "::1", "localhost"} and not os.environ.get(
        "AGENTIC_FRONTIER_TOKEN", ""
    ):
        raise SystemExit("AGENTIC_FRONTIER_TOKEN is required for non-loopback binding")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
