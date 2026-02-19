import importlib

import pytest
from starlette.testclient import TestClient


def test_hosted_public_app_routes_exposed():
    module = importlib.import_module("src.finout_mcp_server.hosted_public")
    paths = {getattr(route, "path", "") for route in module.app.routes}

    assert "/health" in paths
    assert "/mcp" in paths


def test_hosted_public_main_uses_env_host_port(monkeypatch):
    module = importlib.import_module("src.finout_mcp_server.hosted_public")

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

    assert captured["app"] == "finout_mcp_server.hosted_public:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 19090
    assert captured["lifespan"] == "on"


def test_extract_public_auth_from_scope_defaults_api_url():
    module = importlib.import_module("src.finout_mcp_server.hosted_public")
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


def test_extract_public_auth_from_scope_requires_credentials():
    module = importlib.import_module("src.finout_mcp_server.hosted_public")
    scope = {"headers": []}
    with pytest.raises(ValueError, match="Missing credentials"):
        module._extract_public_auth_from_scope(scope)


def test_mcp_post_requires_auth_headers():
    module = importlib.import_module("src.finout_mcp_server.hosted_public")
    with TestClient(module.app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        )
        assert response.status_code == 401


def test_mcp_post_with_auth_headers_passes_auth_gate():
    module = importlib.import_module("src.finout_mcp_server.hosted_public")
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
