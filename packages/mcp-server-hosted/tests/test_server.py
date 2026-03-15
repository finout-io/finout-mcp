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
    assert "/health/ready" in paths
    assert "/mcp" in paths
    assert "/authorize" in paths
    assert "/token" in paths
    assert "/revoke" in paths


def test_main_uses_env_host_port(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")

    captured: dict[str, object] = {}

    def fake_run(app: str, host: str, port: int, lifespan: str, workers: int = 1):
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port
        captured["lifespan"] = lifespan
        captured["workers"] = workers

    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", "19090")
    monkeypatch.setenv("MCP_WORKERS", "2")
    monkeypatch.setattr("uvicorn.run", fake_run)

    module.main()

    assert captured["app"] == "finout_mcp_hosted.server:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 19090
    assert captured["lifespan"] == "on"
    assert captured["workers"] == 2


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


# ── /health ──────────────────────────────────────────────────────────────────


def test_health_returns_200():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_health_ready_checks_redis():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["redis"] == "connected"


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


def test_authorize_get_disallowed_redirect_uri_returns_400(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("FRONTEGG_BASE_URL", "https://app-abc.frontegg.com")
    monkeypatch.setenv("FRONTEGG_MCP_CLIENT_ID", "test-client-id")
    with TestClient(module.app) as client:
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "redirect_uri": "https://evil.example.com/steal",
                "code_challenge": _make_challenge("v"),
            },
        )
    assert response.status_code == 400
    assert "redirect_uri" in response.json()["error_description"]


def test_authorize_post_valid_jwt_redirects_with_opaque_code(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("FRONTEGG_BASE_URL", "https://app-abc.frontegg.com")
    monkeypatch.setenv("FRONTEGG_MCP_CLIENT_ID", "test-client-id")
    with patch(
        "finout_mcp_hosted.server.verify_login_jwt",
        return_value={"tenantId": "tenant-123", "email": "test@example.com", "sub": "user-1"},
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
    assert "code=fmcp_ac_" in location
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


def _do_oauth_flow(module, verifier: str, jwt: str, tenant_id: str) -> dict:
    """Run the full OAuth PKCE flow and return the token response."""
    challenge = _make_challenge(verifier)
    with patch(
        "finout_mcp_hosted.server.verify_login_jwt",
        return_value={"tenantId": tenant_id, "email": "test@example.com", "sub": "user-1"},
    ):
        with TestClient(module.app, follow_redirects=False) as client:
            auth_resp = client.post(
                "/authorize",
                data={
                    "access_token": jwt,
                    "redirect_uri": "http://localhost/cb",
                    "code_challenge": challenge,
                    "state": "s",
                },
            )
        assert auth_resp.status_code == 302, f"Authorize failed: {auth_resp.status_code}"
        code = auth_resp.headers["location"].split("code=")[1].split("&")[0]

        with TestClient(module.app) as client:
            token_resp = client.post(
                "/token",
                content=f"grant_type=authorization_code&code={code}&code_verifier={verifier}&redirect_uri=http%3A%2F%2Flocalhost%2Fcb",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        assert token_resp.status_code == 200, f"Token exchange failed: {token_resp.text}"
        return token_resp.json()


def test_token_exchange_returns_opaque_tokens():
    module = importlib.import_module("finout_mcp_hosted.server")
    data = _do_oauth_flow(module, "token-exchange-verifier-abcdefghij1234567", "jwt-from-frontegg", "tenant-123")
    assert data["access_token"].startswith("fmcp_at_")
    assert data["refresh_token"].startswith("fmcp_rt_")
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600


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


def test_token_exchange_code_single_use():
    """Second exchange with same code fails."""
    module = importlib.import_module("finout_mcp_hosted.server")
    verifier = "single-use-verifier-abcdefghij1234567890"
    challenge = _make_challenge(verifier)

    with patch(
        "finout_mcp_hosted.server.verify_login_jwt",
        return_value={"tenantId": "t1", "email": "a@b.com", "sub": "u1"},
    ):
        with TestClient(module.app, follow_redirects=False) as client:
            auth_resp = client.post(
                "/authorize",
                data={
                    "access_token": "jwt",
                    "redirect_uri": "http://localhost/cb",
                    "code_challenge": challenge,
                    "state": "",
                },
            )
        code = auth_resp.headers["location"].split("code=")[1].split("&")[0]

        with TestClient(module.app) as client:
            # First exchange succeeds
            resp1 = client.post(
                "/token",
                content=f"grant_type=authorization_code&code={code}&code_verifier={verifier}&redirect_uri=http%3A%2F%2Flocalhost%2Fcb",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            assert resp1.status_code == 200

            # Second exchange fails
            resp2 = client.post(
                "/token",
                content=f"grant_type=authorization_code&code={code}&code_verifier={verifier}&redirect_uri=http%3A%2F%2Flocalhost%2Fcb",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            assert resp2.status_code == 400
            assert resp2.json()["error"] == "invalid_grant"


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


# ── /revoke ──────────────────────────────────────────────────────────────────


def test_revoke_invalidates_session():
    module = importlib.import_module("finout_mcp_hosted.server")
    data = _do_oauth_flow(module, "revoke-verifier-abcdefghij1234567890", "jwt-1", "t1")
    access_token = data["access_token"]

    with TestClient(module.app) as client:
        # Verify session is valid first
        mcp_resp = client.post(
            "/mcp",
            headers={
                "authorization": f"Bearer {access_token}",
                "accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert mcp_resp.status_code == 200

        # Revoke
        revoke_resp = client.post(
            "/revoke",
            content=f"token={access_token}",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert revoke_resp.status_code == 200

        # Session should now be invalid
        mcp_resp2 = client.post(
            "/mcp",
            headers={
                "authorization": f"Bearer {access_token}",
                "accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert mcp_resp2.status_code == 401


def test_revoke_empty_token_returns_200():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        resp = client.post(
            "/revoke",
            content="token=",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert resp.status_code == 200


# ── /.well-known/oauth-authorization-server ───────────────────────────────────


def test_oauth_metadata_includes_revocation_endpoint(monkeypatch):
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
    assert data["revocation_endpoint"] == "https://mcp.example.com/revoke"
    assert "S256" in data["code_challenge_methods_supported"]
    assert "refresh_token" in data["grant_types_supported"]


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


# ── /frontegg/* proxy ─────────────────────────────────────────────────────────


def test_frontegg_proxy_forwards_to_frontegg_host(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("FRONTEGG_BASE_URL", "https://app-test.frontegg.com/oauth")

    captured = {}

    with patch("finout_mcp_hosted.server.httpx.AsyncClient") as mock_cls:
        mock_resp = type("R", (), {
            "status_code": 200,
            "content": b'{"ok":true}',
            "headers": {"content-type": "application/json"},
        })()

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def request(self, method, url, **kwargs):
                captured["method"] = method
                captured["url"] = url
                return mock_resp

        mock_cls.return_value = FakeClient()

        with TestClient(module.app) as client:
            resp = client.put(
                "/frontegg/identity/resources/users/v1/tenant",
                json={"tenantId": "t2"},
                headers={"authorization": "Bearer some-jwt"},
            )
    assert resp.status_code == 200
    assert captured["method"] == "PUT"
    assert captured["url"] == "https://app-test.frontegg.com/identity/resources/users/v1/tenant"


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
            json={"refreshToken": "rt"},
            headers={"authorization": "Bearer some-jwt"},
        )
    assert response.status_code == 400
    assert "tenantId" in response.json()["error"]


def test_proxy_tenant_switch_requires_refresh_token():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        response = client.put(
            "/api/tenant-switch",
            json={"tenantId": "t2"},
            headers={"authorization": "Bearer some-jwt"},
        )
    assert response.status_code == 400
    assert "refreshToken" in response.json()["error"]


def test_proxy_tenant_switch_returns_new_token(monkeypatch):
    module = importlib.import_module("finout_mcp_hosted.server")
    monkeypatch.setenv("FRONTEGG_BASE_URL", "https://app-test.frontegg.com/oauth")

    switch_user = {"tenantId": "t2", "name": "User"}
    refresh_tokens = {"accessToken": "new-jwt-for-t2", "refreshToken": "new-rt"}

    with patch("finout_mcp_hosted.server.httpx.AsyncClient") as mock_cls:
        switch_resp = type("R", (), {"status_code": 200, "json": lambda self: switch_user})()
        refresh_resp = type("R", (), {"status_code": 200, "json": lambda self: refresh_tokens})()

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def put(self, url, **kwargs):
                return switch_resp

            async def post(self, url, **kwargs):
                return refresh_resp

        mock_cls.return_value = FakeClient()

        with TestClient(module.app) as client:
            response = client.put(
                "/api/tenant-switch",
                json={"tenantId": "t2", "refreshToken": "old-rt"},
                headers={"authorization": "Bearer original-jwt"},
            )
    assert response.status_code == 200
    assert response.json()["accessToken"] == "new-jwt-for-t2"


# ── End-to-end: OAuth → token → MCP tools/list ───────────────────────────────


def _mcp_headers(bearer: str) -> dict:
    return {
        "authorization": f"Bearer {bearer}",
        "accept": "application/json, text/event-stream",
    }


def test_oauth_then_mcp_tools_list():
    """Full flow: authorize → token exchange → use opaque Bearer to list MCP tools."""
    module = importlib.import_module("finout_mcp_hosted.server")
    data = _do_oauth_flow(module, "e2e-verifier-abcdefghij1234567890", "fake-frontegg-jwt", "tenant-e2e")
    access_token = data["access_token"]
    assert access_token.startswith("fmcp_at_")

    with TestClient(module.app) as client:
        mcp_resp = client.post(
            "/mcp",
            headers=_mcp_headers(access_token),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert mcp_resp.status_code == 200, f"MCP failed: {mcp_resp.status_code} {mcp_resp.text}"
    body = mcp_resp.json()
    assert "error" not in body, f"MCP error: {body}"
    assert "result" in body
    assert "tools" in body["result"]
    assert len(body["result"]["tools"]) > 0


def test_mcp_tools_list_with_key_secret():
    """Key/secret auth → tools/list should work."""
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        resp = client.post(
            "/mcp",
            headers={
                "x-finout-client-id": "cid",
                "x-finout-secret-key": "sk",
                "accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert resp.status_code == 200, f"MCP failed: {resp.status_code} {resp.text}"
    body = resp.json()
    assert "error" not in body, f"MCP error: {body}"
    assert "result" in body
    assert "tools" in body["result"]


def test_mcp_raw_jwt_returns_401():
    """Raw Frontegg JWT (not opaque session token) should be rejected."""
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        resp = client.post(
            "/mcp",
            headers={
                "authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyMSJ9.fake",
                "accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert resp.status_code == 401


def test_e2e_oauth_tools_list_then_call_tool():
    """Full flow: OAuth → tools/list → call a tool."""
    module = importlib.import_module("finout_mcp_hosted.server")
    data = _do_oauth_flow(module, "e2e-full-verifier-1234567890ab", "jwt-t1", "tenant-1")
    access_token = data["access_token"]

    with TestClient(module.app) as client:
        # tools/list
        resp = client.post("/mcp", headers=_mcp_headers(access_token),
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert resp.status_code == 200
        body = resp.json()
        assert "result" in body, f"tools/list error: {body}"
        tool_names = [t["name"] for t in body["result"]["tools"]]
        assert "query_costs" in tool_names

        # call_tool (will fail at API level but should NOT fail at protocol level)
        resp2 = client.post("/mcp", headers=_mcp_headers(access_token),
                            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": "query_costs", "arguments": {
                                      "time_period": "last_7_days"}}})
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert "result" in body2 or ("error" not in body2 or body2["error"]["code"] != -32602), \
            f"Protocol error on call_tool: {body2}"


def test_e2e_two_tenants_isolated():
    """Two users with different tenants get isolated tool responses."""
    module = importlib.import_module("finout_mcp_hosted.server")
    data_a = _do_oauth_flow(module, "tenant-a-verifier-1234567890ab", "jwt-a", "tenant-a")
    data_b = _do_oauth_flow(module, "tenant-b-verifier-1234567890ab", "jwt-b", "tenant-b")

    with TestClient(module.app) as client:
        resp_a = client.post("/mcp", headers=_mcp_headers(data_a["access_token"]),
                             json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        resp_b = client.post("/mcp", headers=_mcp_headers(data_b["access_token"]),
                             json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert "result" in resp_a.json(), f"Tenant A error: {resp_a.json()}"
    assert "result" in resp_b.json(), f"Tenant B error: {resp_b.json()}"


# ── Client pool ──────────────────────────────────────────────────────────────


def test_lifespan_creates_client_pool_and_redis():
    module = importlib.import_module("finout_mcp_hosted.server")
    with TestClient(module.app) as client:
        pool = module.app.state.client_pool
        assert pool is not None
        assert len(pool) == 0

        store = module.app.state.redis_store
        assert store is not None

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
