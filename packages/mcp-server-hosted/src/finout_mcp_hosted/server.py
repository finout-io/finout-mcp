"""
Hosted public MCP service (Streamable HTTP transport).

This service runs the same MCP tool core in fixed PUBLIC mode and is intentionally
separate from VECTIQOR.
"""

from __future__ import annotations

import html
import os
import sys
from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

import anyio
import jwt
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import finout_mcp_server.server as server_module

from .auth import _get_login_cookie_public_key, _get_public_key, authenticate_password, check_sso, check_sso_debug, exchange_sso_code, frontegg_base_url, verify_cookie_jwt, verify_login_jwt
from .oauth import consume_auth_code, consume_sso_flow, create_sso_flow, generate_auth_code, pkce_challenge
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


_LOGIN_FORM_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Finout — Sign in</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box}}
    body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      background:#f5f7fa;display:flex;align-items:center;justify-content:center;min-height:100vh}}
    .card{{background:#fff;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.08);
      padding:40px;width:100%;max-width:420px}}
    .logo{{font-size:24px;font-weight:700;color:#1a1a2e;margin-bottom:8px}}
    .subtitle{{color:#6b7280;font-size:14px;margin-bottom:32px}}
    label{{display:block;font-size:13px;font-weight:500;color:#374151;margin-bottom:6px}}
    input[type=email],input[type=password]{{width:100%;padding:10px 14px;border:1px solid #d1d5db;
      border-radius:8px;font-size:15px;outline:none;transition:border-color .15s}}
    input:focus{{border-color:#4f46e5}}
    .field{{margin-bottom:20px}}
    button{{width:100%;padding:11px;border-radius:8px;font-size:15px;font-weight:600;
      cursor:pointer;transition:background .15s;border:none}}
    .btn-primary{{background:#4f46e5;color:#fff}}
    .btn-primary:hover{{background:#4338ca}}
    .btn-sso{{background:#fff;color:#4f46e5;border:1px solid #4f46e5 !important;margin-top:10px}}
    .btn-sso:hover{{background:#eef2ff}}
    .divider{{display:flex;align-items:center;gap:12px;margin:20px 0}}
    .divider::before,.divider::after{{content:'';flex:1;height:1px;background:#e5e7eb}}
    .divider span{{color:#9ca3af;font-size:13px;white-space:nowrap}}
    .error{{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;border-radius:8px;
      padding:10px 14px;font-size:14px;margin-bottom:20px}}
  </style>
</head>
<body>
<div class="card">
  <div class="logo">Finout</div>
  <div class="subtitle">Sign in to connect your MCP client</div>
  {error_html}
  <form method="post" action="/authorize">
    <input type="hidden" name="redirect_uri" value="{redirect_uri}">
    <input type="hidden" name="code_challenge" value="{code_challenge}">
    <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
    <input type="hidden" name="state" value="{state}">
    <input type="hidden" name="client_id" value="{client_id}">
    <div class="field">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" required autofocus value="{email}">
    </div>
    <div class="field">
      <label for="password">Password</label>
      <input type="password" id="password" name="password">
    </div>
    <button type="submit" class="btn-primary">Sign in</button>
    {sso_button}
  </form>
</div>
</body>
</html>
"""

_SSO_BUTTON_HTML = """\
    <div class="divider"><span>or</span></div>
    <button type="submit" name="sso" value="true" class="btn-sso">Sign in with SSO</button>"""


def _render_login_form(
    *,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    state: str,
    client_id: str,
    error: str = "",
    email: str = "",
) -> HTMLResponse:
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    sso_button = _SSO_BUTTON_HTML if os.getenv("FRONTEGG_CLIENT_ID") else ""
    body = _LOGIN_FORM_HTML.format(
        error_html=error_html,
        sso_button=sso_button,
        redirect_uri=html.escape(redirect_uri, quote=True),
        code_challenge=html.escape(code_challenge, quote=True),
        code_challenge_method=html.escape(code_challenge_method, quote=True),
        state=html.escape(state, quote=True),
        client_id=html.escape(client_id, quote=True),
        email=html.escape(email, quote=True),
    )
    return HTMLResponse(body)


async def oauth_authorize_get(request: Request) -> Response:
    """Render Finout-branded login form for OAuth PKCE authorization."""
    params = request.query_params
    response_type = params.get("response_type", "")
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")

    if response_type != "code" or not redirect_uri or not code_challenge:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "response_type=code, redirect_uri, and code_challenge are required"},
            status_code=400,
        )

    # If the user already has a valid Finout session cookie (set by app.finout.io and
    # sent automatically when the MCP server is on a *.finout.io subdomain), skip the
    # login form entirely and complete the OAuth flow silently.
    cookie_token = request.cookies.get("__fnt_dd_", "")
    if cookie_token:
        try:
            verify_cookie_jwt(cookie_token)
            state = params.get("state", "")
            code = generate_auth_code(cookie_token, code_challenge, redirect_uri)
            query: dict[str, str] = {"code": code}
            if state:
                query["state"] = state
            return RedirectResponse(f"{redirect_uri}?{urlencode(query)}", status_code=302)
        except Exception:
            pass  # Cookie invalid/expired/unconfigured — fall through to login form

    return _render_login_form(
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=params.get("code_challenge_method", "S256"),
        state=params.get("state", ""),
        client_id=params.get("client_id", ""),
    )


async def oauth_authorize_post(request: Request) -> Response:
    """Process login form submission: authenticate, generate auth code, redirect."""
    form = await request.form()
    email = str(form.get("email", "")).strip()
    password = str(form.get("password", "")).strip()
    redirect_uri = str(form.get("redirect_uri", "")).strip()
    code_challenge = str(form.get("code_challenge", "")).strip()
    code_challenge_method = str(form.get("code_challenge_method", "S256")).strip()
    state = str(form.get("state", "")).strip()
    client_id = str(form.get("client_id", "")).strip()

    def _form_error(msg: str) -> HTMLResponse:
        return _render_login_form(
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
            client_id=client_id,
            error=msg,
            email=email,
        )

    if not redirect_uri or not code_challenge:
        return _form_error("Missing required OAuth parameters.")

    sso_requested = str(form.get("sso", "")).strip() == "true"

    if sso_requested:
        frontegg_client_id = os.getenv("FRONTEGG_CLIENT_ID", "")
        frontegg_base = frontegg_base_url()
        if not frontegg_base or not frontegg_client_id:
            return _form_error(
                "SSO is not configured on this server. Contact your administrator."
            )
        nonce, code_verifier = create_sso_flow(redirect_uri, code_challenge, state)
        base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
        params = urlencode({
            "response_type": "code",
            "client_id": frontegg_client_id,
            "redirect_uri": f"{base_url}/oauth/callback",
            "code_challenge": pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "state": nonce,
            "login_hint": email,
        })
        return RedirectResponse(f"{frontegg_base}/oauth/authorize?{params}", status_code=302)

    try:
        token = await authenticate_password(email, password)
    except ValueError as exc:
        return _form_error(str(exc))
    except Exception:
        return _form_error("Authentication service unavailable. Please try again.")

    code = generate_auth_code(token, code_challenge, redirect_uri)

    query: dict[str, str] = {"code": code}
    if state:
        query["state"] = state
    location = f"{redirect_uri}?{urlencode(query)}"
    return RedirectResponse(location, status_code=302)


async def oauth_sso_callback(request: Request) -> Response:
    """Handle Frontegg's redirect after SSO authentication.

    Frontegg redirects here after the user authenticates with their IdP.
    We exchange the Frontegg code for a JWT, then redirect to the original
    MCP client's redirect_uri with our own authorization code.
    """
    error = request.query_params.get("error", "")
    if error:
        desc = request.query_params.get("error_description", error)
        return HTMLResponse(
            f"<p>SSO authentication failed: {html.escape(desc)}</p>",
            status_code=400,
        )

    code = request.query_params.get("code", "")
    nonce = request.query_params.get("state", "")

    try:
        entry = consume_sso_flow(nonce)
    except ValueError:
        return JSONResponse({"error": "invalid_state"}, status_code=400)

    base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
    try:
        jwt_token = await exchange_sso_code(
            code=code,
            code_verifier=entry.frontegg_code_verifier,
            redirect_uri=f"{base_url}/oauth/callback",
        )
    except Exception as exc:
        return JSONResponse(
            {"error": "sso_token_exchange_failed", "error_description": str(exc)},
            status_code=502,
        )

    auth_code = generate_auth_code(jwt_token, entry.original_code_challenge, entry.original_redirect_uri)
    query: dict[str, str] = {"code": auth_code}
    if entry.original_state:
        query["state"] = entry.original_state
    location = f"{entry.original_redirect_uri}?{urlencode(query)}"
    return RedirectResponse(location, status_code=302)


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
        Route("/oauth/callback", endpoint=oauth_sso_callback, methods=["GET"]),
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


if __name__ == "__main__":
    main()
