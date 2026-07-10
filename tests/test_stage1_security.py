"""Stage 1 authorization and security-containment contract tests.

The required ``alpecca.auth`` API is intentionally small and deterministic:

* ``load_or_create_authorization_secret`` obtains a protected secret without
  creating a plaintext file.
* ``SessionAuthority`` validates the protected bearer header, signs sessions,
  and owns the bounded loopback bootstrap store.
* ``AuthDecision`` exposes secret-free structured audit metadata.

Authorization secrets are injected from a protected runtime provider. This
module must not create or maintain a plaintext secret file.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
from pathlib import Path
from types import ModuleType
import pytest


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_IDENTITY = "wLbIoOwoOJHQR4QQ_goptIa2"
AUTHORIZATION_SECRET = "stage1-authorization-secret-that-is-not-public"


@pytest.fixture
def auth_module() -> ModuleType:
    try:
        module = importlib.import_module("alpecca.auth")
    except ModuleNotFoundError:
        pytest.fail("Stage 1 requires the new alpecca.auth module", pytrace=False)
    assert hasattr(module, "SessionAuthority"), (
        "alpecca.auth.SessionAuthority is required"
    )
    assert hasattr(module, "load_or_create_authorization_secret")
    return module


@pytest.fixture
def capability_module() -> ModuleType:
    try:
        return importlib.import_module("alpecca.capabilities")
    except ModuleNotFoundError:
        pytest.fail(
            "Stage 1 requires the alpecca.capabilities registry",
            pytrace=False,
        )


@pytest.fixture
def authority(auth_module: ModuleType):
    return auth_module.SessionAuthority(
        AUTHORIZATION_SECRET,
        session_ttl_s=30,
        bootstrap_ttl_s=10,
    )


def _tamper(token: str) -> str:
    index = max(0, len(token) // 2)
    replacement = "A" if token[index] != "A" else "B"
    return f"{token[:index]}{replacement}{token[index + 1:]}"


def test_authorization_secret_is_separate_from_public_identity(
    tmp_path: Path, auth_module: ModuleType
):
    environ = {
        auth_module.AUTH_ENV_NAME: AUTHORIZATION_SECRET,
        "ALPECCA_ACCESS_TOKEN": PUBLIC_IDENTITY,
        "PYTEST_CURRENT_TEST": "stage1",
    }
    loaded = auth_module.load_or_create_authorization_secret(tmp_path, environ)

    assert loaded == AUTHORIZATION_SECRET
    assert loaded != PUBLIC_IDENTITY
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("headers", "query", "cookies"),
    (
        ({"Authorization": f"Bearer {PUBLIC_IDENTITY}"}, {}, {}),
        ({"X-Alpecca-Token": PUBLIC_IDENTITY}, {}, {}),
        ({}, {"token": PUBLIC_IDENTITY}, {}),
        ({}, {}, {"alpecca_token": PUBLIC_IDENTITY}),
    ),
)
def test_public_identity_never_authorizes(
    authority,
    headers: dict[str, str],
    query: dict[str, str],
    cookies: dict[str, str],
):
    decision = authority.authorize_request(
        headers=headers,
        query=query,
        cookies=cookies,
        now=1_000,
    )

    assert decision.allowed is False
    assert decision.public_identity_ignored is True

    protected = authority.validate_bearer(
        {authority.authorization_header: f"Bearer {PUBLIC_IDENTITY}"}
    )
    assert protected.allowed is False


def test_bearer_verification_uses_constant_time_comparison(
    auth_module: ModuleType, authority
):
    source = inspect.getsource(auth_module.SessionAuthority.validate_bearer)
    assert "compare_digest" in source
    accepted = authority.validate_bearer(
        {authority.authorization_header: f"Bearer {AUTHORIZATION_SECRET}"}
    )
    assert accepted.allowed is True
    same_length_wrong = "X" * len(AUTHORIZATION_SECRET)
    rejected = authority.validate_bearer(
        {authority.authorization_header: f"Bearer {same_length_wrong}"}
    )
    assert rejected.allowed is False


def test_signed_session_rejects_expiry_and_tampering(authority):
    token = authority.issue_session_value(now=1_000)
    assert isinstance(token, str) and token
    assert AUTHORIZATION_SECRET not in token

    accepted = authority.validate_session_cookie(token, now=1_000)
    assert accepted.allowed is True
    assert accepted.principal == "creator"
    assert authority.validate_session_cookie(_tamper(token), now=1_000).allowed is False
    expired = authority.validate_session_cookie(token, now=1_031)
    assert expired.allowed is False
    assert expired.reason == "expired"

    cookie = authority.issue_session_cookie(now=1_000)
    assert cookie.secure is True
    assert cookie.httponly is True
    assert cookie.samesite == "strict"


def test_bootstrap_is_loopback_only_and_one_use(authority):
    bootstrap = authority.issue_bootstrap_code("127.0.0.1", now=1_000)
    ipv6_bootstrap = authority.issue_bootstrap_code("::1", now=1_000)
    assert isinstance(bootstrap, str) and bootstrap
    assert isinstance(ipv6_bootstrap, str) and ipv6_bootstrap
    with pytest.raises(PermissionError, match="loopback"):
        authority.issue_bootstrap_code("192.168.1.10", now=1_000)

    # A remote attempt must neither authenticate nor consume the local grant.
    remote = authority.consume_bootstrap_code(
        bootstrap,
        "192.168.1.10",
        now=1_000,
    )
    assert remote.allowed is False
    accepted = authority.consume_bootstrap_code(
        bootstrap,
        "127.0.0.1",
        now=1_000,
    )
    assert accepted.allowed is True
    reused = authority.consume_bootstrap_code(
        bootstrap,
        "127.0.0.1",
        now=1_000,
    )
    assert reused.allowed is False


def test_bootstrap_expires(authority):
    bootstrap = authority.issue_bootstrap_code("127.0.0.1", now=1_000)
    expired = authority.consume_bootstrap_code(
        bootstrap,
        "127.0.0.1",
        now=1_011,
    )

    assert expired.allowed is False
    assert expired.reason == "invalid_or_expired"


def test_bootstrap_store_is_bounded(
    auth_module: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(auth_module, "_MAX_BOOTSTRAP_CODES", 3)
    monkeypatch.setattr(auth_module.time, "time", lambda: 1_000.0)
    authority = auth_module.SessionAuthority(
        AUTHORIZATION_SECRET,
        session_ttl_s=30,
        bootstrap_ttl_s=10,
    )
    bootstraps = [
        authority.issue_bootstrap_code("127.0.0.1", now=1_000) for _ in range(4)
    ]
    assert all(isinstance(item, str) and item for item in bootstraps)
    assert authority.active_bootstrap_count == 3

    oldest = authority.consume_bootstrap_code(
        bootstraps[0],
        "127.0.0.1",
        now=1_000,
    )
    assert oldest.allowed is False
    for bootstrap in bootstraps[1:]:
        assert authority.consume_bootstrap_code(
            bootstrap,
            "127.0.0.1",
            now=1_000,
        ).allowed


def test_audit_metadata_is_structured_and_contains_no_secrets(authority):
    session = authority.issue_session_value(now=1_000)
    bootstrap = authority.issue_bootstrap_code("127.0.0.1", now=1_000)
    decision = authority.authorize_request(
        headers={"X-Alpecca-Token": PUBLIC_IDENTITY},
        now=1_000,
    )
    metadata = decision.as_audit_metadata()

    assert isinstance(metadata, dict)
    assert metadata == decision.audit
    assert metadata.get("allowed") is False
    assert metadata.get("mechanism") == "none"
    assert metadata.get("reason") == "credentials_missing"
    assert metadata.get("public_identity_ignored") is True
    encoded = json.dumps(metadata, sort_keys=True)
    for private_value in (AUTHORIZATION_SECRET, session, bootstrap):
        assert private_value not in encoded


def test_auth_module_and_config_do_not_persist_plaintext_authorization_secret(
    tmp_path: Path, auth_module: ModuleType
):
    auth_path = ROOT / "alpecca" / "auth.py"
    assert auth_path.is_file(), "Stage 1 requires alpecca/auth.py"
    auth_source = auth_path.read_text(encoding="utf-8")
    config_source = (ROOT / "config.py").read_text(encoding="utf-8")

    for forbidden in (
        "authorization_secret.txt",
        "auth_secret.txt",
        "access_token.txt",
    ):
        assert forbidden not in auth_source.lower()
    assert ".write_text(" not in auth_source
    assert ".write_bytes(" not in auth_source
    secret = auth_module.load_or_create_authorization_secret(
        tmp_path,
        {
            auth_module.AUTH_ENV_NAME: AUTHORIZATION_SECRET,
            "PYTEST_CURRENT_TEST": "stage1",
        },
    )
    assert secret == AUTHORIZATION_SECRET
    assert list(tmp_path.iterdir()) == []
    assert "ACCESS_TOKEN_FILE" not in config_source
    assert "access_token.txt" not in config_source.lower()


def test_capability_registry_defaults_every_risky_surface_off(
    capability_module: ModuleType,
):
    states = capability_module.snapshot({})

    assert states
    assert all(state.enabled is False for state in states)
    assert all(state.explicit_opt_in is False for state in states)
    assert all(state.source == "safe_default" for state in states)
    public = capability_module.public_snapshot({})
    assert public["safe_by_default"] is True
    assert public["enabled"] == []


def test_capability_registry_requires_explicit_opt_in(
    capability_module: ModuleType,
):
    for spec in capability_module.CAPABILITY_SPECS:
        enabled_value = "1" if spec.mode == "boolean" else "explicit-choice"
        states = {
            state.name: state
            for state in capability_module.snapshot(
                {spec.environment: enabled_value}
            )
        }
        selected = states[spec.name]
        assert selected.enabled is True
        assert selected.explicit_opt_in is True
        assert selected.source == "explicit_environment"
        assert all(
            state.enabled is False
            for name, state in states.items()
            if name != spec.name
        )

        disabled = {
            state.name: state
            for state in capability_module.snapshot({spec.environment: "off"})
        }[spec.name]
        assert disabled.enabled is False
        assert disabled.explicit_opt_in is False


def test_capability_public_snapshot_excludes_values_and_identifiers(
    capability_module: ModuleType,
):
    private_values = (
        AUTHORIZATION_SECRET,
        PUBLIC_IDENTITY,
        "9712042378",
        "123456789012345678",
        r"C:\Users\Jason\private-tool.exe",
    )
    environ = {
        "ALPECCA_REMOTE": "1",
        "ALPECCA_TUNNEL": "cloudflare",
        "ALPECCA_APPS": f"private={private_values[4]}",
        "ALPECCA_WATCH_DIRS": rf"C:\Private\{private_values[3]}",
        "ALPECCA_AUTH_SECRET": private_values[0],
        "ALPECCA_PUBLIC_IDENTITY": private_values[1],
        "ALPECCA_CREATOR_PHONE": private_values[2],
    }

    encoded = json.dumps(
        capability_module.public_snapshot(environ),
        sort_keys=True,
    )
    for private_value in private_values:
        assert private_value not in encoded


def test_capability_audit_metadata_excludes_secrets_and_identifiers(
    capability_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    captured = []

    def capture_observation(observation, *, db_path):
        captured.append(observation)
        return len(captured)

    monkeypatch.setattr(
        capability_module.cognition_mod,
        "record_observation",
        capture_observation,
    )
    private_values = (
        AUTHORIZATION_SECRET,
        PUBLIC_IDENTITY,
        "9712042378",
        "123456789012345678",
        r"C:\Users\Jason\private-tool.exe",
    )
    capability_module.record_snapshot(
        {
            "ALPECCA_APPS": f"private={private_values[4]}",
            "ALPECCA_AUTH_SECRET": private_values[0],
            "ALPECCA_PUBLIC_IDENTITY": private_values[1],
            "ALPECCA_CREATOR_PHONE": private_values[2],
        },
        source=f"runtime-{private_values[3]}",
        db_path=tmp_path / "audit.db",
    )
    capability_module.record_use(
        "app_control",
        action=f"open-{private_values[4]}",
        allowed=False,
        principal_role=f"creator-{private_values[2]}",
        source=f"bridge-{private_values[0]}",
        db_path=tmp_path / "audit.db",
    )

    assert captured
    metadata = json.dumps(
        [observation.metadata for observation in captured],
        sort_keys=True,
    )
    for private_value in private_values:
        assert private_value not in metadata


def _python_env_defaults(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defaults: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (
                node.func.attr == "setdefault"
                and isinstance(owner, ast.Attribute)
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "os"
                and owner.attr == "environ"
                and len(node.args) >= 2
            ):
                try:
                    name = ast.literal_eval(node.args[0])
                    value = ast.literal_eval(node.args[1])
                except (ValueError, TypeError):
                    continue
                if isinstance(name, str) and isinstance(value, str):
                    defaults[name] = value
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value_node = node.value
            for target in targets:
                if not isinstance(target, ast.Subscript):
                    continue
                owner = target.value
                if not (
                    isinstance(owner, ast.Attribute)
                    and isinstance(owner.value, ast.Name)
                    and owner.value.id == "os"
                    and owner.attr == "environ"
                ):
                    continue
                try:
                    name = ast.literal_eval(target.slice)
                    value = ast.literal_eval(value_node)
                except (ValueError, TypeError):
                    continue
                if isinstance(name, str) and isinstance(value, str):
                    defaults[name] = value
    return defaults


def _bat_env_defaults(path: Path) -> dict[str, str]:
    defaults: dict[str, str] = {}
    assignment = re.compile(
        r'^\s*set\s+"?(ALPECCA_[A-Za-z0-9_]+)=(.*?)"?\s*$', re.I
    )
    for line in path.read_text(encoding="utf-8").splitlines():
        match = assignment.match(line)
        if match:
            defaults[match.group(1).upper()] = match.group(2).strip().strip('"')
    return defaults


@pytest.mark.parametrize(
    "relative_path",
    ("START_HERE.bat", "scripts/run_full.py", "app.py"),
)
def test_launchers_do_not_enable_risky_capabilities_by_default(relative_path: str):
    path = ROOT / relative_path
    defaults = (
        _bat_env_defaults(path)
        if path.suffix.lower() == ".bat"
        else _python_env_defaults(path)
    )
    off_values = {"", "0", "false", "off", "none"}
    for name in (
        "ALPECCA_SIGHT",
        "ALPECCA_FACE",
        "ALPECCA_VOICE",
        "ALPECCA_COMPUTER_USE",
        "ALPECCA_FILES",
        "ALPECCA_REMOTE",
    ):
        if name in defaults:
            assert defaults[name].strip().lower() in off_values, (
                f"{relative_path} enables {name} by default"
            )
    if "ALPECCA_APPS" in defaults:
        assert defaults["ALPECCA_APPS"].strip() == "", (
            f"{relative_path} grants an application allowlist by default"
        )
    if "ALPECCA_TUNNEL" in defaults:
        assert defaults["ALPECCA_TUNNEL"].strip().lower() in off_values


def _server_contract() -> tuple[str, ast.Module]:
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    return source, ast.parse(source)


def _server_functions(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _decorator_call(
    node: ast.AST,
    decorator_name: str,
    first_argument: str | None = None,
) -> bool:
    decorators = getattr(node, "decorator_list", ())
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        function = decorator.func
        if not isinstance(function, ast.Attribute) or function.attr != decorator_name:
            continue
        if first_argument is None:
            return True
        if (
            decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and decorator.args[0].value == first_argument
        ):
            return True
    return False


def _reachable_function_source(
    source: str,
    tree: ast.Module,
    entry: ast.AST,
) -> str:
    functions = _server_functions(tree)
    queue = [entry]
    visited: set[str] = set()
    segments: list[str] = []
    while queue:
        node = queue.pop()
        name = getattr(node, "name", "")
        if name in visited:
            continue
        visited.add(name)
        segments.append(ast.get_source_segment(source, node) or "")
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            called = child.func.id if isinstance(child.func, ast.Name) else ""
            if called in functions and called not in visited:
                queue.append(functions[called])
    return "\n".join(segments)


def _http_middleware(tree: ast.Module) -> ast.AST:
    candidates = [
        node
        for node in _server_functions(tree).values()
        if _decorator_call(node, "middleware", "http")
    ]
    assert len(candidates) == 1, "server must expose one HTTP auth middleware"
    return candidates[0]


def _websocket_route(tree: ast.Module) -> ast.AST:
    candidates = [
        node
        for node in _server_functions(tree).values()
        if _decorator_call(node, "websocket", "/ws")
    ]
    assert len(candidates) == 1, "server must expose the /ws route"
    return candidates[0]


def _server_routes(source: str, tree: ast.Module) -> list[tuple[str, str, str]]:
    routes: list[tuple[str, str, str]] = []
    methods = {"get", "post", "put", "patch", "delete", "websocket"}
    for node in _server_functions(tree).values():
        for decorator in getattr(node, "decorator_list", ()):
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            function = decorator.func
            path = decorator.args[0]
            if (
                isinstance(function, ast.Attribute)
                and function.attr in methods
                and isinstance(path, ast.Constant)
                and isinstance(path.value, str)
            ):
                routes.append(
                    (
                        function.attr.upper(),
                        path.value,
                        _reachable_function_source(source, tree, node),
                    )
                )
    return routes


def test_server_auth_paths_remove_legacy_token_and_cookie_bootstrap():
    source, tree = _server_contract()
    functions = _server_functions(tree)
    assert "_token_ok" not in functions

    contracts = (
        _reachable_function_source(source, tree, _http_middleware(tree)),
        _reachable_function_source(source, tree, _websocket_route(tree)),
    )
    for contract in contracts:
        assert "X-Alpecca-Token" not in contract
        assert "alpecca_token" not in contract
        assert "_set_alpecca_token_cookie" not in contract
        assert "parse_qs" not in contract
        assert not re.search(
            r"query_params\s*\.get\(\s*['\"]token['\"]",
            contract,
        )
    # Sessions are minted only by the explicit bootstrap exchange route.
    assert ".set_cookie(" not in contracts[0]


def test_server_http_and_websocket_use_protected_authorization():
    source, tree = _server_contract()
    assert "alpecca.auth" in source or "from alpecca import auth" in source
    assert "AUTHORIZATION_HEADER" in source or "X-Alpecca-Authorization" in source

    markers = ("authorize_request", "validate_bearer", "validate_session_cookie")
    http_contract = _reachable_function_source(source, tree, _http_middleware(tree))
    websocket_contract = _reachable_function_source(
        source,
        tree,
        _websocket_route(tree),
    )
    assert any(marker in http_contract for marker in markers)
    assert any(marker in websocket_contract for marker in markers)


def test_server_exposes_loopback_bootstrap_and_signed_session_exchange_routes():
    source, tree = _server_contract()
    routes = _server_routes(source, tree)
    issuers = [route for route in routes if "issue_bootstrap_code" in route[2]]
    exchangers = [route for route in routes if "exchange_bootstrap_code" in route[2]]

    assert issuers, "server needs a loopback bootstrap issuance route"
    assert exchangers, "server needs a one-use bootstrap exchange route"
    assert all(method == "POST" for method, _, _ in issuers)
    assert all(method in {"GET", "POST"} for method, _, _ in exchangers)
    for _, path, contract in issuers:
        assert "bootstrap" in path.lower()
        assert "client" in contract.lower() or "remote" in contract.lower()
    for _, path, contract in exchangers:
        assert "bootstrap" in path.lower() or "session" in path.lower()
        assert ".set_cookie(" in contract
        assert "set_cookie_kwargs" in contract or "httponly" in contract.lower()


def test_server_cors_is_local_only_by_default_and_allows_protected_header():
    source, tree = _server_contract()
    for local_host in ("localhost", "127.0.0.1", "::1"):
        assert local_host in source
    assert "AUTHORIZATION_HEADER" in source or "X-Alpecca-Authorization" in source
    assert not re.search(
        r"Access-Control-Allow-Origin[^\n]*[=,:]\s*['\"]\*['\"]",
        source,
    )

    cors_contract = "\n".join(
        _reachable_function_source(source, tree, node)
        for name, node in _server_functions(tree).items()
        if "cors" in name.casefold()
    )
    public_origin_markers = (
        ".r2.dev",
        ".pages.dev",
        ".trycloudflare.com",
        ".cloudflarestorage.com",
    )
    if any(marker in source for marker in public_origin_markers):
        explicit_remote_gate = (
            "REMOTE_ACCESS",
            "ALLOW_REMOTE_CORS",
            "CORS_REMOTE",
            "ALPECCA_CORS",
        )
        assert any(marker in cors_contract for marker in explicit_remote_gate), (
            "public CORS origins must require an explicit remote-access opt-in"
        )


def _house_source() -> str:
    source_root = ROOT / "apps" / "house-hq" / "src"
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(source_root.rglob("*"))
        if path.suffix.lower() in {".ts", ".tsx", ".js", ".jsx"}
    )


def test_house_hq_does_not_use_legacy_authorization_header():
    assert "X-Alpecca-Token" not in _house_source()


def test_house_hq_only_deletes_stale_legacy_token_storage():
    source = _house_source()
    assert 'localStorage.getItem("alpeccaAccessToken")' not in source
    assert 'localStorage.setItem("alpeccaAccessToken"' not in source
    without_cleanup = re.sub(
        r'localStorage\.removeItem\(["\']alpeccaAccessToken["\']\);?', "", source
    )
    assert "alpeccaAccessToken" not in without_cleanup


def test_house_hq_preserves_public_alpecca_identity():
    assert PUBLIC_IDENTITY in _house_source()
