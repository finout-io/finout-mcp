"""
Hosted public MCP service (Streamable HTTP transport).

This service runs the same MCP tool core in fixed PUBLIC mode and is intentionally
separate from BILLY.
"""

from __future__ import annotations

import html
import os
import pathlib
import sys
from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

import anyio
from dotenv import load_dotenv
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import finout_mcp_server.server as server_module

from .auth import _get_login_cookie_public_key, _get_public_key, check_sso, check_sso_debug, frontegg_base_url, verify_cookie_jwt, verify_login_jwt
from .oauth import consume_auth_code, generate_auth_code
from finout_mcp_server.finout_client import FinoutClient, InternalAuthMode
from finout_mcp_server.server import MCPMode, server

load_dotenv(override=True)


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


def _authorization_complete_page(callback_url: str) -> str:
    """Render a success page that auto-redirects to the MCP client callback."""
    safe_url = html.escape(callback_url, quote=True)
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Finout — Authorized</title>
  <style>
    @font-face {{
      font-family: 'Inter';
      src: url('https://app.finout.io/app/assetsNew/inter-DNXbu9-7.woff2') format('woff2');
      font-weight: 100 900; font-style: normal; font-display: swap;
    }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #4fa882 url('https://fronteggprodeustorage.blob.core.windows.net/public-vendor-assets/d5069f33-9608-4141-9e1d-ebf8e9cf6582/assets/background-image-9fededda-593e-4749-ae93-2c8fd898b6f6.png') center / cover no-repeat fixed;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; flex-direction: column; padding: 24px;
    }}
    .card {{
      background: #fff; border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.18);
      max-width: 420px; width: 100%; text-align: center;
      padding: 36px 32px;
    }}
    .checkmark {{
      width: 56px; height: 56px; border-radius: 50%;
      background: #4fa882; display: flex; align-items: center;
      justify-content: center; margin: 0 auto 20px;
    }}
    .checkmark svg {{ width: 28px; height: 28px; fill: #fff; }}
    h1 {{ margin: 0 0 8px; font-size: 18px; font-weight: 600; color: #3d4f63; }}
    p {{ margin: 0; font-size: 14px; color: #7a8a9a; line-height: 1.5; }}
  </style>
</head>
<body>
  <img style="display:block;height:44px;filter:brightness(0) invert(1);margin-bottom:32px"
    src="https://fronteggprodeustorage.blob.core.windows.net/public-vendor-assets/d5069f33-9608-4141-9e1d-ebf8e9cf6582/assets/logo-8fb6fff6-65f8-4040-afee-bc2daf5ab529.png"
    alt="Finout">
  <div class="card">
    <div class="checkmark">
      <svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
    </div>
    <h1>Authorization Successful</h1>
    <p>You can close this window and return to your MCP client.</p>
  </div>
  <iframe src="{safe_url}" style="display:none" aria-hidden="true"></iframe>
</body>
</html>"""


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
    callback_url = f"{redirect_uri}?{urlencode(query)}"
    return HTMLResponse(_authorization_complete_page(callback_url))


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


async def mcp_asgi(scope, receive, send) -> None:
    """ASGI mount for Streamable HTTP MCP transport."""
    if scope.get("method") == "POST":
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")
        base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")

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

            token_fingerprint = sha256(token.encode("utf-8")).hexdigest()

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
                fingerprint: tuple[str, ...] = ("cookie", account_id, internal_api_url, token_fingerprint)
                async with scope["app"].state.client_lock:
                    if scope["app"].state.client_fingerprint != fingerprint:
                        if server_module.finout_client:
                            await server_module.finout_client.close()
                        server_module.runtime_mode = MCPMode.PUBLIC.value
                        server_module.finout_client = FinoutClient(
                            internal_api_url=internal_api_url,
                            account_id=account_id,
                            internal_auth_mode=InternalAuthMode.AUTHORIZED_HEADERS,
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

            # Frontegg JWT path: use BEARER_TOKEN mode via public API URL.
            api_url = os.getenv("FINOUT_API_URL", "https://app.finout.io")
            fingerprint = ("jwt", account_id, api_url, token_fingerprint)
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
        Route("/debug/sso", endpoint=debug_sso, methods=["GET"]),
        Route("/debug/cookies", endpoint=debug_cookies, methods=["GET"]),
        Route("/debug/verify-token", endpoint=debug_verify_token, methods=["GET"]),
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
