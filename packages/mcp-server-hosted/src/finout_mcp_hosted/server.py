"""
Hosted public MCP service (Streamable HTTP transport).

This service runs the same MCP tool core in fixed PUBLIC mode and is intentionally
separate from VECTIQOR.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Any

import anyio
import httpx
import jwt
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import finout_mcp_server.server as server_module

from .auth import verify_login_jwt
from finout_mcp_server.finout_client import FinoutClient, InternalAuthMode
from finout_mcp_server.server import MCPMode, server


@asynccontextmanager
async def lifespan(app: Starlette):
    """Initialize MCP core in fixed public mode and expose it over HTTP transport."""
    server_module.runtime_mode = MCPMode.PUBLIC.value
    # Hosted public mode receives Finout credentials per HTTP call.
    server_module.finout_client = None

    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    app.state.transport = transport
    app.state.client_lock = anyio.Lock()
    app.state.client_fingerprint = None

    try:
        async with transport.connect() as (read_stream, write_stream):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(
                    server.run,
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
                yield
                task_group.cancel_scope.cancel()
    finally:
        if server_module.finout_client:
            await server_module.finout_client.close()


async def health(_: Request) -> JSONResponse:
    """Health check endpoint for hosted deployment."""
    return JSONResponse(
        {
            "status": "healthy",
            "mode": "public",
            "transport": "streamable-http",
        }
    )


def _sync_server_state_across_imports(client: FinoutClient | None, mode: str) -> None:
    """Keep runtime globals aligned even if server.py is imported under multiple module refs."""
    for module in list(sys.modules.values()):
        if module is None:
            continue
        module_any: Any = module
        module_file = getattr(module, "__file__", "") or ""
        if module_file.endswith("/finout_mcp_server/server.py"):
            try:
                module_any.finout_client = client
                module_any.runtime_mode = mode
            except Exception:
                pass


def _extract_public_auth_from_scope(scope: Any) -> tuple[str, str, str]:
    """Extract required auth headers from ASGI scope."""
    headers = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
    }
    client_id = headers.get("x-finout-client-id", "").strip()
    secret_key = headers.get("x-finout-secret-key", "").strip()
    # Intentionally ignore client-provided API URL in hosted mode.
    # This avoids request-driven upstream URL override.
    api_url = os.getenv("FINOUT_API_URL", "https://app.finout.io")

    if not client_id or not secret_key:
        raise ValueError("Unauthorized")
    return client_id, secret_key, api_url


async def oauth_register(request: Request) -> JSONResponse:
    """Dynamic Client Registration (RFC 7591) stub.

    mcp-inspector requires DCR to self-register before starting the OAuth flow.
    We return a static pre-configured Frontegg client so the inspector can proceed.
    FRONTEGG_MCP_CLIENT_ID must be a public Frontegg OAuth app with PKCE enabled
    and the inspector's redirect URI registered (e.g. http://localhost:6274/oauth/callback).
    """
    client_id = os.getenv("FRONTEGG_MCP_CLIENT_ID", "")
    if not client_id:
        return JSONResponse(
            {"error": "invalid_client_metadata", "error_description": "FRONTEGG_MCP_CLIENT_ID not configured"},
            status_code=400,
        )
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    redirect_uris = body.get("redirect_uris", [])
    return JSONResponse(
        {
            "client_id": client_id,
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


async def oauth_protected_resource(request: Request) -> JSONResponse:
    """RFC 9728 OAuth 2.0 Protected Resource Metadata."""
    base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
    return JSONResponse(
        {
            "resource": f"{base_url}/mcp",
            # Point to ourselves so clients fetch metadata from our CORS-enabled proxy,
            # not directly from Frontegg (which doesn't expose CORS headers on discovery).
            "authorization_servers": [base_url] if base_url else [],
        }
    )


async def oauth_authorization_server(request: Request) -> Response:
    """Proxy Frontegg's OAuth 2.0 authorization server metadata.

    Returns Frontegg's metadata with the issuer overridden to our own URL so that
    clients fetching from this proxy pass issuer-URL validation.
    The actual authorization_endpoint and token_endpoint still point to Frontegg.
    """
    frontegg_base = os.getenv("FRONTEGG_BASE_URL", "").rstrip("/")
    base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
    if not frontegg_base:
        return JSONResponse({"error": "FRONTEGG_BASE_URL not configured"}, status_code=503)
    # Try RFC 8414 path first, fall back to OIDC discovery (Frontegg uses the latter).
    candidates = [
        f"{frontegg_base}/.well-known/oauth-authorization-server",
        f"{frontegg_base}/.well-known/openid-configuration",
    ]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for url in candidates:
                resp = await client.get(url)
                if resp.status_code == 200:
                    if base_url:
                        metadata = resp.json()
                        metadata["issuer"] = base_url
                        metadata["registration_endpoint"] = f"{base_url}/register"
                        metadata["token_endpoint"] = f"{base_url}/token"
                        return JSONResponse(metadata)
                    return Response(
                        content=resp.content,
                        status_code=resp.status_code,
                        headers={"Content-Type": "application/json"},
                    )
        return JSONResponse({"error": "OAuth metadata not found at authorization server"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


async def oauth_token_proxy(request: Request) -> Response:
    """Proxy token requests to Frontegg to avoid CORS issues in browser-based clients.

    mcp-inspector runs in a browser and cannot POST directly to Frontegg's token
    endpoint (Frontegg doesn't expose CORS headers). We forward the request server-side.
    """
    frontegg_base = os.getenv("FRONTEGG_BASE_URL", "").rstrip("/")
    if not frontegg_base:
        return JSONResponse({"error": "FRONTEGG_BASE_URL not configured"}, status_code=503)

    body = await request.body()
    headers = {
        "Content-Type": request.headers.get("content-type", "application/x-www-form-urlencoded"),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_endpoint = os.getenv("FRONTEGG_TOKEN_ENDPOINT", "").strip()
            if not token_endpoint:
                token_endpoint = f"{frontegg_base}/oauth/token"
            resp = await client.post(
                token_endpoint,
                content=body,
                headers=headers,
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={"Content-Type": resp.headers.get("content-type", "application/json")},
            )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


def _oauth_challenge_headers(base_url: str, error: str | None = None) -> dict[str, str]:
    resource_metadata = f'{base_url}/.well-known/oauth-protected-resource' if base_url else ""
    value = f'Bearer resource_metadata="{resource_metadata}"'
    if error:
        value = f'{value}, error="{error}"'
    return {"WWW-Authenticate": value}


async def mcp_asgi(scope, receive, send) -> None:
    """ASGI mount for Streamable HTTP MCP transport."""
    if scope.get("method") == "POST":
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")
        base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")

        if auth_header.startswith("Bearer "):
            # OAuth / JWT auth path
            token = auth_header[7:]
            try:
                payload = verify_login_jwt(token)
            except jwt.ExpiredSignatureError:
                response = JSONResponse(
                    {"error": "Token expired"},
                    status_code=401,
                    headers=_oauth_challenge_headers(base_url, "invalid_token"),
                )
                await response(scope, receive, send)
                return
            except Exception:
                response = JSONResponse(
                    {"error": "Invalid token"},
                    status_code=401,
                    headers=_oauth_challenge_headers(base_url, "invalid_token"),
                )
                await response(scope, receive, send)
                return

            account_id = payload.get("tenantId", "").strip()
            if not account_id:
                response = JSONResponse(
                    {"error": "Invalid token"},
                    status_code=401,
                    headers=_oauth_challenge_headers(base_url, "invalid_token"),
                )
                await response(scope, receive, send)
                return

            api_url = os.getenv("FINOUT_API_URL", "https://app.finout.io")
            token_fingerprint = sha256(token.encode("utf-8")).hexdigest()
            fingerprint: tuple[str, ...] = ("jwt", account_id, api_url, token_fingerprint)
            async with scope["app"].state.client_lock:
                if scope["app"].state.client_fingerprint != fingerprint:
                    if server_module.finout_client:
                        await server_module.finout_client.close()
                    server_module.runtime_mode = MCPMode.PUBLIC.value
                    server_module.finout_client = FinoutClient(
                        bearer_token=token,
                        internal_api_url=api_url,
                        account_id=account_id,
                        internal_auth_mode=InternalAuthMode.BEARER_TOKEN,
                        allow_missing_credentials=True,
                    )
                    _sync_server_state_across_imports(
                        server_module.finout_client,
                        MCPMode.PUBLIC.value,
                    )
                    scope["app"].state.client_fingerprint = fingerprint
                else:
                    _sync_server_state_across_imports(
                        server_module.finout_client,
                        MCPMode.PUBLIC.value,
                    )
                await scope["app"].state.transport.handle_request(scope, receive, send)
            return

        # Key/secret header auth path (backward compatible)
        try:
            client_id, secret_key, api_url = _extract_public_auth_from_scope(scope)
        except ValueError:
            response = JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
                headers=_oauth_challenge_headers(base_url),
            )
            await response(scope, receive, send)
            return

        fingerprint = (client_id, secret_key, api_url)
        async with scope["app"].state.client_lock:
            if scope["app"].state.client_fingerprint != fingerprint:
                if server_module.finout_client:
                    await server_module.finout_client.close()
                server_module.runtime_mode = MCPMode.PUBLIC.value
                server_module.finout_client = FinoutClient(
                    client_id=client_id,
                    secret_key=secret_key,
                    internal_api_url=api_url,
                    internal_auth_mode=InternalAuthMode.KEY_SECRET,
                    allow_missing_credentials=False,
                )
                _sync_server_state_across_imports(
                    server_module.finout_client,
                    MCPMode.PUBLIC.value,
                )
                scope["app"].state.client_fingerprint = fingerprint
            else:
                _sync_server_state_across_imports(
                    server_module.finout_client,
                    MCPMode.PUBLIC.value,
                )
            await scope["app"].state.transport.handle_request(scope, receive, send)
        return

    # For non-POST requests (GET/DELETE), require valid auth as well.
    headers = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
    }
    base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
    auth_header = headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            verify_login_jwt(token)
        except Exception:
            response = JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
                headers=_oauth_challenge_headers(base_url, "invalid_token"),
            )
            await response(scope, receive, send)
            return
    elif not (
        headers.get("x-finout-client-id", "").strip()
        and headers.get("x-finout-secret-key", "").strip()
    ):
        response = JSONResponse(
            {"error": "Unauthorized"},
            status_code=401,
            headers=_oauth_challenge_headers(base_url),
        )
        await response(scope, receive, send)
        return
    await scope["app"].state.transport.handle_request(scope, receive, send)


async def _invoke_asgi_as_response(request: Request) -> Response:
    """Invoke ASGI MCP transport and adapt output to a Starlette Response."""
    events: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        events.append(message)

    await mcp_asgi(request.scope, request.receive, send)

    start = next((event for event in events if event.get("type") == "http.response.start"), None)
    body_events = [event for event in events if event.get("type") == "http.response.body"]
    status_code = int(start.get("status", 500)) if start else 500
    raw_headers = start.get("headers", []) if start else []
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in raw_headers}
    body = b"".join(event.get("body", b"") for event in body_events)

    return Response(content=body, status_code=status_code, headers=headers)


async def mcp_route(request: Request) -> Response:
    """Request-style route wrapper for the MCP ASGI transport."""
    return await _invoke_asgi_as_response(request)


app = Starlette(
    routes=[
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/register", endpoint=oauth_register, methods=["POST"]),
        Route("/token", endpoint=oauth_token_proxy, methods=["POST"]),
        Route(
            "/.well-known/oauth-protected-resource",
            endpoint=oauth_protected_resource,
            methods=["GET"],
        ),
        # RFC 9728 canonical path: /.well-known/oauth-protected-resource/{resource-path}
        Route(
            "/.well-known/oauth-protected-resource/mcp",
            endpoint=oauth_protected_resource,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=oauth_authorization_server,
            methods=["GET"],
        ),
        # OIDC configuration — some clients probe this in addition to oauth-authorization-server.
        Route(
            "/.well-known/openid-configuration",
            endpoint=oauth_authorization_server,
            methods=["GET"],
        ),
        # Register both variants explicitly to avoid framework-level slash redirects.
        Route("/mcp", endpoint=mcp_route, methods=["GET", "POST", "DELETE"]),
        Route("/mcp/", endpoint=mcp_route, methods=["GET", "POST", "DELETE"]),
    ],
    lifespan=lifespan,
)
app.router.redirect_slashes = False
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["WWW-Authenticate"],
)


def main() -> None:
    """Run hosted public MCP service."""
    import uvicorn

    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8080"))
    uvicorn.run("finout_mcp_hosted.server:app", host=host, port=port, lifespan="on")


if __name__ == "__main__":
    main()
