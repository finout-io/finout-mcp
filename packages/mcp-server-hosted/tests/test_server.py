import base64
import hashlib
import importlib
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


def _make_fake_httpx_client(method: str, response):
    """Create a fake httpx.AsyncClient that returns *response* for the given HTTP method."""

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    async def _handler(self, *a, **kw):
        return response

    setattr(_FakeClient, method, _handler)
    return _FakeClient()


def _make_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_app_routes_exposed():
    module = importlib.import_module("finout_mcp_hosted.server")
    paths = {getattr(route, "path", "") for route in module.app.routes}

    assert "/health" in paths
    assert "/mcp" in paths
    assert "/authorize" in paths
    assert "/token" in paths


def test_main_uses_env_host_port(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")

    captured: dict[str, object] = {}

    def fake_run(app: str, host: str, port: int, lifespan: str):
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port
        captured["lifespan"] = lifespan

    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", "19090")
    monkeypatch.setattr("uvicorn.run", fake_run)

    module.main()

    assert captured["app"] == "finout_mcp_hosted.server:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 19090
    assert captured["lifespan"] == "on"


def test_extract_public_auth_from_scope_defaults_api_url(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.delenv("FINOUT_API_URL", raising=False)
    scope = {
        "headers": [
            (b"x-finout-client-id", b"cid"),
            (b"x-finout-secret-key", b"sk"),
        ]
    }
    client_id, secret_key, api_url = module._extract_public_auth_from_scope(scope)
    assert client_id == "cid"
    assert secret_key == "sk"
    assert api_url == "https://app.finout.io"


def test_extract_public_auth_from_scope_ignores_header_api_url(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("FINOUT_API_URL", "https://app.finout.io")
    scope = {
        "headers": [
            (b"x-finout-client-id", b"cid"),
            (b"x-finout-secret-key", b"sk"),
            (b"x-finout-api-url", b"https://evil.example"),
        ]
    }
    _, _, api_url = module._extract_public_auth_from_scope(scope)
    assert api_url == "https://app.finout.io"


def test_extract_public_auth_from_scope_requires_credentials():
    module = importlib.import_module("finout_mcp_hosted.server")
    scope = {"headers": []}
    with pytest.raises(ValueError, match="Unauthorized"):
        module._extract_public_auth_from_scope(scope)


def test_mcp_post_requires_auth_headers():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        )
        assert response.status_code == 401


def test_mcp_post_with_auth_headers_passes_auth_gate():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.post(
            "/mcp",
            headers={
                "x-finout-client-id": "cid",
                "x-finout-secret-key": "sk",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        )
        assert response.status_code != 401


def test_mcp_post_no_trailing_slash_no_redirect():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.post(
            "/mcp",
            headers={
                "x-finout-client-id": "cid",
                "x-finout-secret-key": "sk",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            follow_redirects=False,
        )
        assert response.status_code != 307


def test_mcp_get_with_invalid_bearer_is_unauthorized():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.get("/mcp", headers={"authorization": "Bearer bad-token"})
        assert response.status_code == 401


# ── /authorize ────────────────────────────────────────────────────────────────


def test_authorize_get_returns_embedded_login_page(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("FRONTEGG_BASE_URL", "https://app-abc.frontegg.com")
    monkeypatch.setenv("FRONTEGG_MCP_CLIENT_ID", "test-client-id")
    with TestClient(module.app) as client:
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "redirect_uri": "http://localhost:6274/oauth/callback",
                "code_challenge": _make_challenge("verifier-abc"),
                "code_challenge_method": "S256",
                "state": "xyz",
                "client_id": "finout-mcp",
            },
        )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "frontegg" in response.text.lower()
    assert "app-abc.frontegg.com" in response.text
    assert "test-client-id" in response.text


def test_authorize_get_missing_frontegg_config_returns_500(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.delenv("FRONTEGG_BASE_URL", raising=False)
    monkeypatch.delenv("FRONTEGG_MCP_CLIENT_ID", raising=False)
    with TestClient(module.app) as client:
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "redirect_uri": "http://localhost:6274/oauth/callback",
                "code_challenge": _make_challenge("verifier-abc"),
                "code_challenge_method": "S256",
                "state": "xyz",
            },
        )
    assert response.status_code == 500


def test_authorize_get_missing_params_returns_400():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.get(
            "/authorize",
            params={"response_type": "code"},
        )
    assert response.status_code == 400


def test_authorize_get_wrong_response_type_returns_400():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.get(
            "/authorize",
            params={
                "response_type": "token",
                "redirect_uri": "http://localhost/cb",
                "code_challenge": _make_challenge("v"),
            },
        )
    assert response.status_code == 400


def test_authorize_post_valid_jwt_redirects_with_code():
    module = importlib.import_module("finout_mcp_hosted.server")
    with patch(
        "finout_mcp_hosted.server.verify_login_jwt",
        return_value={"tenantId": "tenant-123"},
    ):
        with TestClient(module.app, follow_redirects=False) as client:
            response = client.post(
                "/authorize",
                data={
                    "access_token": "fake-frontegg-jwt",
                    "redirect_uri": "http://localhost:6274/oauth/callback",
                    "code_challenge": _make_challenge("verifier-xyz"),
                    "state": "mystate",
                },
            )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "code=" in location
    assert "state=mystate" in location


def test_authorize_post_invalid_jwt_returns_401():
    module = importlib.import_module("finout_mcp_hosted.server")
    with patch(
        "finout_mcp_hosted.server.verify_login_jwt",
        side_effect=Exception("bad token"),
    ):
        with TestClient(module.app) as client:
            response = client.post(
                "/authorize",
                data={
                    "access_token": "invalid-token",
                    "redirect_uri": "http://localhost/cb",
                    "code_challenge": _make_challenge("v"),
                    "state": "",
                },
            )
    assert response.status_code == 401


def test_authorize_post_missing_params_returns_400():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.post("/authorize", data={})
    assert response.status_code == 400


# ── /token ────────────────────────────────────────────────────────────────────


def test_token_exchange_valid():
    module = importlib.import_module("finout_mcp_hosted.server")
    verifier = "token-exchange-verifier-abcdefghij1234567"
    challenge = _make_challenge(verifier)

    with patch(
        "finout_mcp_hosted.server.verify_login_jwt",
        return_value={"tenantId": "tenant-123"},
    ):
        with TestClient(module.app, follow_redirects=False) as client:
            post_resp = client.post(
                "/authorize",
                data={
                    "access_token": "jwt-from-frontegg",
                    "redirect_uri": "http://localhost/cb",
                    "code_challenge": challenge,
                    "state": "",
                },
            )
        assert post_resp.status_code == 302
        location = post_resp.headers["location"]
        code = location.split("code=")[1].split("&")[0]

        with TestClient(module.app) as client:
            token_resp = client.post(
                "/token",
                content=f"grant_type=authorization_code&code={code}&code_verifier={verifier}",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
    assert token_resp.status_code == 200
    data = token_resp.json()
    assert data["access_token"] == "jwt-from-frontegg"
    assert data["token_type"] == "bearer"


def test_token_exchange_invalid_code():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.post(
            "/token",
            content="grant_type=authorization_code&code=no-such-code&code_verifier=anything",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_token_unsupported_grant_type():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.post(
            "/token",
            content="grant_type=client_credentials",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


# ── /.well-known/oauth-authorization-server ───────────────────────────────────


def test_oauth_metadata_returns_own_endpoints(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("MCP_BASE_URL", "https://mcp.example.com")
    with TestClient(module.app) as client:
        response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.json()
    assert data["issuer"] == "https://mcp.example.com"
    assert data["authorization_endpoint"] == "https://mcp.example.com/authorize"
    assert data["token_endpoint"] == "https://mcp.example.com/token"
    assert data["registration_endpoint"] == "https://mcp.example.com/register"
    assert "S256" in data["code_challenge_methods_supported"]


def test_openid_configuration_same_as_auth_server(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("MCP_BASE_URL", "https://mcp.example.com")
    with TestClient(module.app) as client:
        response = client.get("/.well-known/openid-configuration")
    assert response.status_code == 200
    assert response.json()["issuer"] == "https://mcp.example.com"


# ── /register ─────────────────────────────────────────────────────────────────


def test_register_returns_static_client_id():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.post(
            "/register",
            json={"redirect_uris": ["http://localhost:6274/oauth/callback"]},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == "finout-mcp"
    assert "http://localhost:6274/oauth/callback" in data["redirect_uris"]


# ── /api/tenants ──────────────────────────────────────────────────────────────


def test_proxy_tenants_requires_auth():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.get("/api/tenants")
    assert response.status_code == 401


def test_proxy_tenants_returns_frontegg_response(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("FRONTEGG_BASE_URL", "https://app-test.frontegg.com/oauth")

    tenants = [
        {"tenantId": "t1", "name": "Acme Corp"},
        {"tenantId": "t2", "name": "Beta Inc"},
    ]

    with patch("finout_mcp_hosted.server.httpx.AsyncClient") as mock_cls:
        mock_resp = type("R", (), {"status_code": 200, "json": lambda self: tenants})()

        mock_cls.return_value = _make_fake_httpx_client("get", mock_resp)

        with TestClient(module.app) as client:
            response = client.get(
                "/api/tenants",
                headers={"authorization": "Bearer some-jwt"},
            )
    assert response.status_code == 200
    assert response.json() == tenants


# ── /api/tenant-switch ────────────────────────────────────────────────────────


def test_proxy_tenant_switch_requires_auth():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.put(
            "/api/tenant-switch",
            json={"tenantId": "t2"},
        )
    assert response.status_code == 401


def test_proxy_tenant_switch_requires_tenant_id():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.put(
            "/api/tenant-switch",
            json={},
            headers={"authorization": "Bearer some-jwt"},
        )
    assert response.status_code == 400
    assert "tenantId" in response.json()["error"]


def test_proxy_tenant_switch_returns_new_token(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("FRONTEGG_BASE_URL", "https://app-test.frontegg.com/oauth")

    switch_resp_body = {"accessToken": "new-jwt-for-t2", "refreshToken": "rt"}

    with patch("finout_mcp_hosted.server.httpx.AsyncClient") as mock_cls:
        mock_resp = type("R", (), {
            "status_code": 200,
            "json": lambda self: switch_resp_body,
        })()

        mock_cls.return_value = _make_fake_httpx_client("put", mock_resp)

        with TestClient(module.app) as client:
            response = client.put(
                "/api/tenant-switch",
                json={"tenantId": "t2"},
                headers={"authorization": "Bearer original-jwt"},
            )
    assert response.status_code == 200
    assert response.json()["accessToken"] == "new-jwt-for-t2"


# ── Client pool ──────────────────────────────────────────────────────────────


def test_lifespan_creates_client_pool():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        pool = module.app.state.client_pool
        assert pool is not None
        assert len(pool) == 0

        # A request with key/secret auth should create a pooled client.
        client.post(
            "/mcp",
            headers={
                "x-finout-client-id": "cid",
                "x-finout-secret-key": "sk",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        )
        assert len(pool) >= 1
