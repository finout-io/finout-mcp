"""
Hosted public MCP service (Streamable HTTP transport).

This service runs the same MCP tool core in fixed PUBLIC mode and is intentionally
separate from BILLY.

Supports concurrent multi-user requests via per-request ContextVar isolation and
a pooled FinoutClient cache.
"""

from __future__ import annotations

import html
import os
import pathlib
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

import anyio
import httpx
from dotenv import load_dotenv
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import finout_mcp_server.server as server_module

from .auth import _get_login_cookie_public_key, _get_public_key, check_sso, check_sso_debug, frontegg_base_url, verify_cookie_jwt, verify_login_jwt
from .client_pool import ClientPool
from .oauth import consume_auth_code, generate_auth_code
from finout_mcp_server.finout_client import InternalAuthMode
from finout_mcp_server.server import MCPMode, _client_var, _runtime_mode_var, server, set_request_client, set_request_runtime_mode
from finout_mcp_server.observability import reset_trace_context, set_trace_context

load_dotenv(override=True)


@asynccontextmanager
async def lifespan(app: Starlette):
    """Initialize MCP core in fixed public mode."""
    server_module.runtime_mode = MCPMode.PUBLIC.value
    server_module.finout_client = None

    pool = ClientPool(max_size=50, ttl=3600)
    app.state.client_pool = pool

    try:
        yield
    finally:
        await pool.close_all()


def _debug_enabled() -> bool:
    return os.getenv("MCP_DEBUG", "").lower() in ("1", "true", "yes")


async def debug_sso(request: Request) -> JSONResponse:
    """Debug endpoint: check SSO status for an email address."""
    if not _debug_enabled():
        return JSONResponse({"error": "not found"}, status_code=404)
    email = request.query_params.get("email", "")
    if not email:
        return JSONResponse({"error": "email query param required"}, status_code=400)
    result = await check_sso_debug(email)
    result["sso_detected"] = await check_sso(email)
    result["frontegg_base_url"] = frontegg_base_url()
    return JSONResponse(result)


async def debug_cookies(request: Request) -> JSONResponse:
    """Debug endpoint: show all cookies and headers received by the server."""
    if not _debug_enabled():
        return JSONResponse({"error": "not found"}, status_code=404)
    headers_dict = dict(request.headers)
    cookies_dict = dict(request.cookies)
    return JSONResponse({
        "cookies_received": cookies_dict,
        "cookie_header_raw": headers_dict.get("cookie", "(none)"),
        "host": headers_dict.get("host", "(none)"),
        "origin": headers_dict.get("origin", "(none)"),
        "referer": headers_dict.get("referer", "(none)"),
        "fnt_dd_present": "__fnt_dd_" in cookies_dict,
    })


async def debug_verify_token(request: Request) -> JSONResponse:
    """Debug endpoint: verbose token + key diagnostics."""
    if not _debug_enabled():
        return JSONResponse({"error": "not found"}, status_code=404)
    import base64 as _b64
    import traceback
    from urllib.parse import unquote as _unquote

    # Clear caches so env var changes take effect without restart.
    _get_login_cookie_public_key.cache_clear()
    _get_public_key.cache_clear()

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": "Pass token as Authorization: Bearer <token>"}, status_code=400)
    token = auth[7:]

    # ── key diagnostics ────────────────────────────────────────────────────────
    raw_login_key = os.getenv("FINOUT_LOGIN_JWT_PUBLIC_KEY", "")
    raw_frontegg_key = os.getenv("FINOUT_JWT_PUBLIC_KEY", "")

    def _describe_key(raw: str) -> dict:
        if not raw:
            return {"set": False}
        info: dict = {"set": True, "length": len(raw), "first_50": raw[:50]}
        unquoted = _unquote(raw)
        info["starts_with_pem_after_unquote"] = unquoted.startswith("-----")
        info["unquoted_first_80"] = unquoted[:80]
        try:
            b64decoded = _b64.b64decode(raw).decode("utf-8", errors="replace")
            info["b64_decoded_first_80"] = b64decoded[:80]
            info["starts_with_pem_after_b64"] = b64decoded.startswith("-----")
        except Exception as exc:
            info["b64_decode_error"] = str(exc)
        return info

    key_info = {
        "FINOUT_LOGIN_JWT_PUBLIC_KEY": _describe_key(raw_login_key),
        "FINOUT_JWT_PUBLIC_KEY": _describe_key(raw_frontegg_key),
        "FINOUT_JWT_ISSUER": os.getenv("FINOUT_JWT_ISSUER", "(not set)"),
        "FINOUT_JWT_AUDIENCE": os.getenv("FINOUT_JWT_AUDIENCE", "(not set)"),
        "FINOUT_INTERNAL_API_URL": os.getenv("FINOUT_INTERNAL_API_URL", "(not set)"),
    }

    # ── token diagnostics ──────────────────────────────────────────────────────
    token_parts = token.split(".")
    token_info: dict = {"parts": len(token_parts), "first_20": token[:20]}
    if len(token_parts) >= 2:
        try:
            import json as _json
            pad = "=" * (-len(token_parts[1]) % 4)
            header_raw = _b64.urlsafe_b64decode(token_parts[0] + "=" * (-len(token_parts[0]) % 4))
            payload_raw = _b64.urlsafe_b64decode(token_parts[1] + pad)
            token_info["header"] = _json.loads(header_raw)
            token_info["payload_claims"] = list(_json.loads(payload_raw).keys())
        except Exception as exc:
            token_info["decode_error"] = str(exc)

    # ── verification attempts ──────────────────────────────────────────────────
    result: dict = {"keys": key_info, "token": token_info}

    try:
        payload = verify_login_jwt(token)
        result["frontegg_jwt"] = {"ok": True, "tenantId": payload.get("tenantId")}
    except Exception as exc:
        result["frontegg_jwt"] = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}

    try:
        payload = verify_cookie_jwt(token)
        result["cookie_jwt"] = {"ok": True, "tenantId": payload.get("tenantId")}
    except Exception as exc:
        result["cookie_jwt"] = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}

    return JSONResponse(result)


async def health(_: Request) -> JSONResponse:
    """Health check endpoint for hosted deployment."""
    return JSONResponse(
        {
            "status": "healthy",
            "mode": "public",
            "transport": "streamable-http",
        }
    )


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


def _frontegg_host() -> str:
    """Derive Frontegg host (scheme://netloc) from FRONTEGG_BASE_URL."""
    base = os.getenv("FRONTEGG_BASE_URL", "").rstrip("/")
    if not base:
        return ""
    parsed = urlparse(base)
    return f"{parsed.scheme}://{parsed.netloc}"


async def proxy_tenants(request: Request) -> JSONResponse:
    """Proxy Frontegg user-tenants API to avoid CORS."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    fe_host = _frontegg_host()
    if not fe_host:
        return JSONResponse({"error": "Frontegg not configured"}, status_code=500)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{fe_host}/identity/resources/users/v2/me/tenants",
            headers={"authorization": auth},
        )
    try:
        body = resp.json()
    except Exception:
        body = {"error": "Unexpected response from Frontegg"}
    return JSONResponse(body, status_code=resp.status_code)


async def proxy_tenant_switch(request: Request) -> JSONResponse:
    """Proxy Frontegg tenant-switch API to avoid CORS."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    tenant_id = body.get("tenantId", "")
    if not tenant_id:
        return JSONResponse({"error": "tenantId required"}, status_code=400)

    fe_host = _frontegg_host()
    if not fe_host:
        return JSONResponse({"error": "Frontegg not configured"}, status_code=500)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{fe_host}/identity/resources/auth/v1/user/token/tenant",
            headers={"authorization": auth, "content-type": "application/json"},
            json={"tenantId": tenant_id},
        )
    try:
        resp_body = resp.json()
    except Exception:
        resp_body = {"error": "Unexpected response from Frontegg"}
    return JSONResponse(resp_body, status_code=resp.status_code)


_LOGIN_HTML_TEMPLATE = (pathlib.Path(__file__).parent / "login.html").read_text()


def _embedded_login_page(
    redirect_uri: str = "",
    code_challenge: str = "",
    state: str = "",
) -> HTMLResponse:
    """Render the Frontegg embedded login page.

    Called both for the initial /authorize GET (params embedded in HTML) and for
    post-login callback routes (empty params, restored from sessionStorage by JS).
    """
    fe_base_url = os.getenv("FRONTEGG_BASE_URL", "")
    fe_client_id = os.getenv("FRONTEGG_MCP_CLIENT_ID", "")
    if not fe_base_url or not fe_client_id:
        return HTMLResponse(
            "<p>Server misconfiguration: Frontegg not configured.</p>", status_code=500
        )
    body = (
        _LOGIN_HTML_TEMPLATE
        .replace("__REDIRECT_URI__",    html.escape(redirect_uri,   quote=True))
        .replace("__CODE_CHALLENGE__",  html.escape(code_challenge, quote=True))
        .replace("__STATE__",           html.escape(state,          quote=True))
        .replace("__FRONTEGG_BASE_URL__", html.escape(fe_base_url,  quote=True))
        .replace("__FRONTEGG_CLIENT_ID__", html.escape(fe_client_id, quote=True))
    )
    return HTMLResponse(body)


async def oauth_login_callback(request: Request) -> Response:
    """Handle Frontegg's post-login redirect (e.g. /account/login-callback).

    After embedded login, Frontegg navigates to {appUrl}/account/login-callback.
    We serve the same login page (no params) so the JS picks them up from sessionStorage.
    """
    return _embedded_login_page()


async def oauth_authorize_get(request: Request) -> Response:
    """Serve Frontegg embedded login for OAuth PKCE authorization."""
    params = request.query_params
    response_type = params.get("response_type", "")
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")

    if response_type != "code" or not redirect_uri or not code_challenge:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "response_type=code, redirect_uri, and code_challenge are required"},
            status_code=400,
        )

    return _embedded_login_page(
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        state=params.get("state", ""),
    )


async def oauth_authorize_post(request: Request) -> Response:
    """Complete OAuth after Frontegg embedded login.

    Receives the Frontegg JWT from the client-side SDK, validates it,
    generates an auth code, and redirects to the MCP client's redirect_uri.
    """
    form = await request.form()
    access_token = str(form.get("access_token", "")).strip()
    redirect_uri = str(form.get("redirect_uri", "")).strip()
    code_challenge = str(form.get("code_challenge", "")).strip()
    state = str(form.get("state", "")).strip()

    if not access_token or not redirect_uri or not code_challenge:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "Missing required parameters"},
            status_code=400,
        )

    try:
        verify_login_jwt(access_token)
    except Exception:
        return JSONResponse(
            {"error": "invalid_token", "error_description": "Invalid or expired Frontegg token"},
            status_code=401,
        )

    code = generate_auth_code(access_token, code_challenge, redirect_uri)
    query: dict[str, str] = {"code": code}
    if state:
        query["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urlencode(query)}", status_code=302)


async def oauth_register(request: Request) -> JSONResponse:
    """Dynamic Client Registration (RFC 7591) stub."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    redirect_uris = body.get("redirect_uris", [])
    return JSONResponse(
        {
            "client_id": "finout-mcp",
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
            "authorization_servers": [base_url] if base_url else [],
        }
    )


async def oauth_authorization_server(request: Request) -> JSONResponse:
    """OAuth 2.0 authorization server metadata (RFC 8414 / OIDC discovery)."""
    base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
    return JSONResponse(
        {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "registration_endpoint": f"{base_url}/register",
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "grant_types_supported": ["authorization_code"],
        }
    )


async def oauth_token(request: Request) -> JSONResponse:
    """Token endpoint: exchange authorization code + PKCE verifier for access token."""
    body = await request.body()
    from urllib.parse import parse_qs
    params = parse_qs(body.decode("utf-8"), keep_blank_values=True)

    def _get(key: str) -> str:
        vals = params.get(key, [])
        return vals[0] if vals else ""

    grant_type = _get("grant_type")
    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    code = _get("code")
    code_verifier = _get("code_verifier")

    try:
        access_token = consume_auth_code(code, code_verifier)
    except ValueError as exc:
        return JSONResponse({"error": "invalid_grant", "error_description": str(exc)}, status_code=400)

    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 3600,
        }
    )


def _oauth_challenge_headers(base_url: str, error: str | None = None) -> dict[str, str]:
    resource_metadata = f'{base_url}/.well-known/oauth-protected-resource' if base_url else ""
    value = f'Bearer resource_metadata="{resource_metadata}"'
    if error:
        value = f'{value}, error="{error}"'
    return {"WWW-Authenticate": value}


async def _handle_with_transport(scope: Any, receive: Any, send: Any) -> None:
    """Create a per-request transport, wire it to the MCP server, and process."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    async with transport.connect() as (read_stream, write_stream):
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                server.run,
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
            await transport.handle_request(scope, receive, send)
            tg.cancel_scope.cancel()


async def mcp_asgi(scope: Any, receive: Any, send: Any) -> None:
    """ASGI mount for Streamable HTTP MCP transport.

    Each request gets its own transport + ContextVar-isolated client from the pool.
    No serialization lock — concurrent requests run in parallel.
    """
    if scope.get("method") == "POST":
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")
        base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
        pool: ClientPool = scope["app"].state.client_pool
        request_id = headers.get("x-request-id", "").strip() or str(uuid4())
        session_id = (
            headers.get("mcp-session-id", "").strip()
            or headers.get("x-session-id", "").strip()
            or request_id
        )

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

            # Try Frontegg JWT first, then fall back to Finout login cookie JWT.
            payload: dict | None = None
            use_cookie_auth = False
            try:
                payload = verify_login_jwt(token)
            except Exception:
                try:
                    payload = verify_cookie_jwt(token)
                    use_cookie_auth = True
                except Exception:
                    pass

            if payload is None:
                response = JSONResponse(
                    {"error": "Invalid or expired token"},
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

            if use_cookie_auth:
                # Cookie JWT path: use AUTHORIZED_HEADERS mode via internal API URL.
                internal_api_url = os.getenv("FINOUT_INTERNAL_API_URL", "")
                if not internal_api_url:
                    response = JSONResponse(
                        {"error": "FINOUT_INTERNAL_API_URL not configured"},
                        status_code=503,
                    )
                    await response(scope, receive, send)
                    return
                fingerprint: tuple[str, ...] = ("cookie", account_id, internal_api_url)
                client = await pool.get_or_create(
                    fingerprint,
                    internal_api_url=internal_api_url,
                    account_id=account_id,
                    internal_auth_mode=InternalAuthMode.AUTHORIZED_HEADERS,
                    allow_missing_credentials=True,
                )
            else:
                # Frontegg JWT path: use BEARER_TOKEN mode via public API URL.
                api_url = os.getenv("FINOUT_API_URL", "https://app.finout.io")
                fingerprint = ("jwt", account_id, api_url)
                client = await pool.get_or_create(
                    fingerprint,
                    bearer_token=token,
                    internal_api_url=api_url,
                    account_id=account_id,
                    internal_auth_mode=InternalAuthMode.BEARER_TOKEN,
                    allow_missing_credentials=True,
                )

            # Set per-coroutine context so tool impls see this client.
            client_token = set_request_client(client)
            mode_token = set_request_runtime_mode(MCPMode.PUBLIC.value)
            trace_token = set_trace_context(
                {
                    "origin": "direct_mcp",
                    "request_id": request_id,
                    "session_id": session_id,
                    "account_id": account_id,
                    "user_id": payload.get("email") or payload.get("sub") or account_id,
                    "auth_mode": "cookie_jwt" if use_cookie_auth else "bearer_token",
                }
            )
            try:
                await _handle_with_transport(scope, receive, send)
            finally:
                reset_trace_context(trace_token)
                _client_var.reset(client_token)
                _runtime_mode_var.reset(mode_token)
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

        fingerprint = ("key", client_id, api_url)
        client = await pool.get_or_create(
            fingerprint,
            client_id=client_id,
            secret_key=secret_key,
            internal_api_url=api_url,
            internal_auth_mode=InternalAuthMode.KEY_SECRET,
            allow_missing_credentials=False,
        )

        client_token = set_request_client(client)
        mode_token = set_request_runtime_mode(MCPMode.PUBLIC.value)
        trace_token = set_trace_context(
            {
                "origin": "direct_mcp",
                "request_id": request_id,
                "session_id": session_id,
                "client_id": client_id,
                "user_id": f"client:{client_id}",
                "auth_mode": "key_secret",
            }
        )
        try:
            await _handle_with_transport(scope, receive, send)
        finally:
            reset_trace_context(trace_token)
            _client_var.reset(client_token)
            _runtime_mode_var.reset(mode_token)
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
            try:
                verify_cookie_jwt(token)
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
    await _handle_with_transport(scope, receive, send)


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
        Route("/debug/sso", endpoint=debug_sso, methods=["GET"]),
        Route("/debug/cookies", endpoint=debug_cookies, methods=["GET"]),
        Route("/debug/verify-token", endpoint=debug_verify_token, methods=["GET"]),
        Route("/api/tenants", endpoint=proxy_tenants, methods=["GET"]),
        Route("/api/tenant-switch", endpoint=proxy_tenant_switch, methods=["POST", "PUT"]),
        Route("/authorize", endpoint=oauth_authorize_get, methods=["GET"]),
        Route("/authorize", endpoint=oauth_authorize_post, methods=["POST"]),
        # Frontegg redirects to {appUrl}/account/login-callback after embedded login.
        Route("/account/login-callback", endpoint=oauth_login_callback, methods=["GET"]),
        Route("/account/login", endpoint=oauth_login_callback, methods=["GET"]),
        Route("/register", endpoint=oauth_register, methods=["POST"]),
        Route("/token", endpoint=oauth_token, methods=["POST"]),
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


def dev() -> None:
    """Run with auto-reload for local development."""
    import uvicorn

    uvicorn.run("finout_mcp_hosted.server:app", host="0.0.0.0", port=8080, reload=True)


if __name__ == "__main__":
    main()
