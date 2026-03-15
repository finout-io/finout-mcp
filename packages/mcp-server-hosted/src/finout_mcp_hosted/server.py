"""
Hosted public MCP service (Streamable HTTP transport).

Supports concurrent multi-user requests via per-request ContextVar isolation and
a pooled FinoutClient cache. Auth codes, sessions, and rate limits are Redis-backed.
"""

from __future__ import annotations

import asyncio
import fnmatch
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
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import finout_mcp_server.server as server_module

from .auth import _get_login_cookie_public_key, _get_public_key, check_sso, check_sso_debug, frontegg_base_url, verify_cookie_jwt, verify_login_jwt
from .circuit_breaker import CircuitBreaker
from .client_pool import ClientPool
from .oauth import TOKEN_PREFIX_ACCESS, TOKEN_PREFIX_CODE, TOKEN_PREFIX_REFRESH, generate_opaque_token, verify_pkce
from .rate_limit import RateLimitConfig, check_auth_rate_limit, check_mcp_rate_limit
from .redis_store import RedisStore, RedisUnavailableError
from finout_mcp_server.finout_client import InternalAuthMode
from finout_mcp_server.server import MCPMode, _client_var, _runtime_mode_var, server, set_request_client, set_request_runtime_mode
from finout_mcp_server.observability import reset_trace_context, set_trace_context

load_dotenv(override=True)

import logging as _logging
_logging.basicConfig(level=_logging.INFO, format="%(name)s %(levelname)s %(message)s")

# Load secrets from Vault (IRSA → Secrets Manager → Vault) with env var fallback.
from .vault import inject_secrets_into_env
inject_secrets_into_env()


# ── Redirect URI allowlist ────────────────────────────────────────────────────


def _get_allowed_redirect_patterns() -> list[str]:
    raw = os.getenv(
        "MCP_ALLOWED_REDIRECT_PATTERNS",
        "http://localhost/*,http://localhost:*/*,http://127.0.0.1/*,http://127.0.0.1:*/*",
    )
    return [p.strip() for p in raw.split(",") if p.strip()]


def _validate_redirect_uri(uri: str) -> bool:
    """Check redirect_uri against allowed patterns (fnmatch-style)."""
    patterns = _get_allowed_redirect_patterns()
    return any(fnmatch.fnmatch(uri, pattern) for pattern in patterns)



# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: Starlette):
    """Initialize MCP core, Redis, circuit breaker, and semaphore."""
    server_module.runtime_mode = MCPMode.PUBLIC.value
    server_module.finout_client = None

    pool = ClientPool(max_size=50, ttl=3600)
    app.state.client_pool = pool

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    store = RedisStore(redis_url)
    app.state.redis_store = store

    app.state.circuit_breaker = CircuitBreaker()
    app.state.mcp_semaphore = asyncio.Semaphore(
        int(os.getenv("MCP_MAX_CONCURRENT", "100"))
    )
    app.state.rate_limit_config = RateLimitConfig()

    try:
        yield
    finally:
        await pool.close_all()
        await store.close()


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


# ── Health ────────────────────────────────────────────────────────────────────


async def health(_: Request) -> JSONResponse:
    """Liveness check — always returns 200."""
    return JSONResponse(
        {
            "status": "healthy",
            "mode": "public",
            "transport": "streamable-http",
        }
    )


async def health_ready(request: Request) -> JSONResponse:
    """Readiness check — verifies Redis connectivity."""
    store: RedisStore = request.app.state.redis_store
    if await store.ping():
        return JSONResponse({"status": "ready", "redis": "connected"})
    return JSONResponse(
        {"status": "not ready", "redis": "disconnected"},
        status_code=503,
    )


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _extract_public_auth_from_scope(scope: Any) -> tuple[str, str, str]:
    """Extract required auth headers from ASGI scope."""
    headers = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
    }
    client_id = headers.get("x-finout-client-id", "").strip()
    secret_key = headers.get("x-finout-secret-key", "").strip()
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


# ── Proxy endpoints ──────────────────────────────────────────────────────────


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

    refresh_token = body.get("refreshToken", "")
    if not refresh_token:
        return JSONResponse({"error": "refreshToken required"}, status_code=400)

    import logging
    logger = logging.getLogger("finout_mcp_hosted.tenant_switch")

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            switch_url = f"{fe_host}/identity/resources/users/v1/tenant"
            logger.info("PUT %s for tenant %s", switch_url, tenant_id)
            switch_resp = await http.put(
                switch_url,
                headers={"authorization": auth, "content-type": "application/json"},
                json={"tenantId": tenant_id},
            )
            logger.info("Switch response: %s", switch_resp.status_code)
            if switch_resp.status_code != 200:
                try:
                    err = switch_resp.json()
                except Exception:
                    err = {"error": f"Tenant switch failed: HTTP {switch_resp.status_code}"}
                return JSONResponse(err, status_code=switch_resp.status_code)

            refresh_url = f"{fe_host}/identity/resources/auth/v1/user/token/refresh"
            logger.info("POST %s", refresh_url)
            refresh_resp = await http.post(
                refresh_url,
                headers={"authorization": auth, "content-type": "application/json"},
                json={"refreshToken": refresh_token},
            )
            logger.info("Refresh response: %s", refresh_resp.status_code)
            if refresh_resp.status_code != 200:
                try:
                    err = refresh_resp.json()
                except Exception:
                    err = {"error": f"Token refresh failed: HTTP {refresh_resp.status_code}"}
                return JSONResponse(err, status_code=refresh_resp.status_code)

        try:
            tokens = refresh_resp.json()
        except Exception:
            return JSONResponse({"error": "Unexpected refresh response"}, status_code=502)
        return JSONResponse(tokens)

    except Exception as exc:
        logger.exception("Tenant switch failed")
        return JSONResponse({"error": f"Tenant switch error: {exc}"}, status_code=500)


async def frontegg_proxy(request: Request) -> Response:
    """Catch-all proxy for /frontegg/* -> Frontegg host."""
    fe_host = _frontegg_host()
    if not fe_host:
        return JSONResponse({"error": "Frontegg not configured"}, status_code=500)

    path = request.url.path
    if path.startswith("/frontegg"):
        path = path[len("/frontegg"):]

    target_url = f"{fe_host}{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    body = await request.body()

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.request(
            method=request.method,
            url=target_url,
            headers=fwd_headers,
            content=body,
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )


# ── OAuth login page ─────────────────────────────────────────────────────────


_LOGIN_HTML_TEMPLATE = (pathlib.Path(__file__).parent / "login.html").read_text()


def _embedded_login_page(
    redirect_uri: str = "",
    code_challenge: str = "",
    state: str = "",
) -> HTMLResponse:
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
    """Handle Frontegg SDK navigation under /account/*."""
    return _embedded_login_page()


# ── OAuth authorize ──────────────────────────────────────────────────────────


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

    if not _validate_redirect_uri(redirect_uri):
        return JSONResponse(
            {"error": "invalid_request", "error_description": "redirect_uri not allowed"},
            status_code=400,
        )

    return _embedded_login_page(
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        state=params.get("state", ""),
    )


async def oauth_authorize_post(request: Request) -> Response:
    """Complete OAuth after Frontegg embedded login — store opaque auth code in Redis."""
    import logging
    _log = logging.getLogger("finout_mcp_hosted.oauth")

    form = await request.form()
    access_token = str(form.get("access_token", "")).strip()
    refresh_token = str(form.get("refresh_token", "")).strip()
    redirect_uri = str(form.get("redirect_uri", "")).strip()
    code_challenge = str(form.get("code_challenge", "")).strip()
    state = str(form.get("state", "")).strip()

    _log.info("POST /authorize — token_len=%d redirect_uri=%s", len(access_token), redirect_uri)

    if not access_token or not redirect_uri or not code_challenge:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "Missing required parameters"},
            status_code=400,
        )

    if not _validate_redirect_uri(redirect_uri):
        return JSONResponse(
            {"error": "invalid_request", "error_description": "redirect_uri not allowed"},
            status_code=400,
        )

    try:
        payload = verify_login_jwt(access_token)
        _log.info("POST /authorize — JWT valid, tenantId=%s", payload.get("tenantId"))
    except Exception as exc:
        _log.warning("POST /authorize — JWT validation failed: %s", exc)
        return JSONResponse(
            {"error": "invalid_token", "error_description": "Invalid or expired Frontegg token"},
            status_code=401,
        )

    store: RedisStore = request.app.state.redis_store
    code = generate_opaque_token(TOKEN_PREFIX_CODE)
    code_data = {
        "jwt": access_token,
        "refresh_token": refresh_token,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "account_id": payload.get("tenantId", ""),
        "user_id": payload.get("sub") or payload.get("email") or "",
        "email": payload.get("email", ""),
    }

    try:
        await store.store_auth_code(code, code_data, ttl=120)
    except RedisUnavailableError:
        return JSONResponse(
            {"error": "server_error", "error_description": "Service temporarily unavailable"},
            status_code=503,
        )

    query: dict[str, str] = {"code": code}
    if state:
        query["state"] = state
    redirect_url = f"{redirect_uri}?{urlencode(query)}"
    return RedirectResponse(redirect_url, status_code=302)


# ── OAuth token ──────────────────────────────────────────────────────────────


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
            "revocation_endpoint": f"{base_url}/revoke",
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }
    )


def _jwt_expires_in(token: str) -> int:
    """Compute seconds until a JWT expires. Falls back to 3600 on decode errors."""
    import base64 as _b64
    import json as _json
    import time as _time
    try:
        parts = token.split(".")
        pad = "=" * (-len(parts[1]) % 4)
        payload = _json.loads(_b64.urlsafe_b64decode(parts[1] + pad))
        return max(int(payload["exp"] - _time.time()), 0)
    except Exception:
        return 3600


async def _refresh_via_frontegg(refresh_token: str) -> tuple[str, str] | None:
    """Exchange a Frontegg refresh token for new access + refresh tokens.

    Returns (new_access, new_refresh) or None on failure.
    """
    import logging
    _log = logging.getLogger("finout_mcp_hosted.oauth")

    fe_host = _frontegg_host()
    if not fe_host:
        return None

    url = f"{fe_host}/identity/resources/auth/v1/user/token/refresh"
    _log.info("POST /token [refresh] — calling %s", url)
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(url, json={"refreshToken": refresh_token})

    if resp.status_code != 200:
        _log.warning("POST /token [refresh] — Frontegg returned %d", resp.status_code)
        return None

    try:
        tokens = resp.json()
    except Exception:
        return None

    new_access = tokens.get("accessToken", tokens.get("access_token", ""))
    new_refresh = tokens.get("refreshToken", tokens.get("refresh_token", ""))
    if not new_access:
        return None

    return new_access, new_refresh


async def oauth_token(request: Request) -> JSONResponse:
    """Token endpoint: authorization_code and refresh_token grant types."""
    import logging
    _log = logging.getLogger("finout_mcp_hosted.oauth")

    body = await request.body()
    from urllib.parse import parse_qs
    params = parse_qs(body.decode("utf-8"), keep_blank_values=True)

    def _get(key: str) -> str:
        vals = params.get(key, [])
        return vals[0] if vals else ""

    grant_type = _get("grant_type")
    _log.info("POST /token — grant_type=%s", grant_type)

    store: RedisStore = request.app.state.redis_store

    if grant_type == "refresh_token":
        rt = _get("refresh_token")
        if not rt:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "refresh_token required"},
                status_code=400,
            )

        # Look up stored refresh entry in Redis
        try:
            rt_data = await store.get_refresh_token(rt)
        except RedisUnavailableError:
            return JSONResponse(
                {"error": "server_error", "error_description": "Service temporarily unavailable"},
                status_code=503,
            )

        if rt_data is None:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "Invalid or expired refresh token"},
                status_code=400,
            )

        # Refresh via Frontegg
        frontegg_rt = rt_data.get("frontegg_refresh_token", "")
        result = await _refresh_via_frontegg(frontegg_rt)
        if result is None:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "Refresh token rejected"},
                status_code=400,
            )

        new_frontegg_access, new_frontegg_refresh = result

        # Decode new JWT for session data
        try:
            new_payload = verify_login_jwt(new_frontegg_access)
        except Exception:
            # If verification fails, use data from the old refresh token entry
            new_payload = {
                "tenantId": rt_data.get("account_id", ""),
                "sub": rt_data.get("user_id", ""),
                "email": rt_data.get("email", ""),
            }

        # Create new session + refresh token, delete old
        new_session_token = generate_opaque_token(TOKEN_PREFIX_ACCESS)
        new_refresh_token = generate_opaque_token(TOKEN_PREFIX_REFRESH)

        session_data = {
            "frontegg_jwt": new_frontegg_access,
            "frontegg_refresh_token": new_frontegg_refresh,
            "account_id": new_payload.get("tenantId", rt_data.get("account_id", "")),
            "user_id": new_payload.get("sub") or new_payload.get("email") or rt_data.get("user_id", ""),
            "email": new_payload.get("email", rt_data.get("email", "")),
        }

        try:
            await store.store_session(new_session_token, session_data, ttl=3600)
            await store.store_refresh_token(new_refresh_token, {
                **session_data,
            }, ttl=86400)
            await store.delete_refresh_token(rt)
        except RedisUnavailableError:
            return JSONResponse(
                {"error": "server_error", "error_description": "Service temporarily unavailable"},
                status_code=503,
            )

        return JSONResponse({
            "access_token": new_session_token,
            "token_type": "bearer",
            "expires_in": 3600,
            "refresh_token": new_refresh_token,
        })

    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    code = _get("code")
    code_verifier = _get("code_verifier")
    redirect_uri = _get("redirect_uri")

    # Atomic single-use consumption from Redis
    try:
        code_data = await store.consume_auth_code(code)
    except RedisUnavailableError:
        return JSONResponse(
            {"error": "server_error", "error_description": "Service temporarily unavailable"},
            status_code=503,
        )

    if code_data is None:
        return JSONResponse(
            {"error": "invalid_grant", "error_description": "Invalid or already used authorization code"},
            status_code=400,
        )

    # Verify PKCE
    stored_challenge = code_data.get("code_challenge", "")
    if not code_verifier or not verify_pkce(code_verifier, stored_challenge):
        return JSONResponse(
            {"error": "invalid_grant", "error_description": "PKCE verification failed"},
            status_code=400,
        )

    # Verify redirect_uri
    stored_redirect = code_data.get("redirect_uri", "")
    if stored_redirect and redirect_uri != stored_redirect:
        return JSONResponse(
            {"error": "invalid_grant", "error_description": "redirect_uri mismatch"},
            status_code=400,
        )

    # Create opaque session + refresh tokens
    session_token = generate_opaque_token(TOKEN_PREFIX_ACCESS)
    refresh_token = generate_opaque_token(TOKEN_PREFIX_REFRESH)

    session_data = {
        "frontegg_jwt": code_data["jwt"],
        "frontegg_refresh_token": code_data.get("refresh_token", ""),
        "account_id": code_data.get("account_id", ""),
        "user_id": code_data.get("user_id", ""),
        "email": code_data.get("email", ""),
    }

    try:
        await store.store_session(session_token, session_data, ttl=3600)
        await store.store_refresh_token(refresh_token, {
            **session_data,
        }, ttl=86400)
    except RedisUnavailableError:
        return JSONResponse(
            {"error": "server_error", "error_description": "Service temporarily unavailable"},
            status_code=503,
        )

    return JSONResponse({
        "access_token": session_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "refresh_token": refresh_token,
    })


# ── Revocation (RFC 7009) ────────────────────────────────────────────────────


async def oauth_revoke(request: Request) -> JSONResponse:
    """Revoke a session or refresh token. Always returns 200 per RFC 7009."""
    body = await request.body()
    from urllib.parse import parse_qs
    params = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    token = (params.get("token", [""]))[0]

    if not token:
        return JSONResponse({})

    store: RedisStore = request.app.state.redis_store

    try:
        if token.startswith(TOKEN_PREFIX_ACCESS):
            await store.delete_session(token)
        elif token.startswith(TOKEN_PREFIX_REFRESH):
            await store.delete_refresh_token(token)
        else:
            # Try both
            await store.delete_session(token)
            await store.delete_refresh_token(token)
    except RedisUnavailableError:
        pass  # RFC 7009: always return 200

    return JSONResponse({})


# ── OAuth challenge headers ──────────────────────────────────────────────────


def _oauth_challenge_headers(base_url: str, error: str | None = None) -> dict[str, str]:
    resource_metadata = f'{base_url}/.well-known/oauth-protected-resource' if base_url else ""
    value = f'Bearer resource_metadata="{resource_metadata}"'
    if error:
        value = f'{value}, error="{error}"'
    return {"WWW-Authenticate": value}


# ── MCP transport ────────────────────────────────────────────────────────────


async def _handle_with_transport(scope: Any, receive: Any, send: Any) -> None:
    """Create a per-request transport, wire it to the MCP server, and process."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    async with transport.connect() as (read_stream, write_stream):
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                    stateless=True,
                )
            )
            await transport.handle_request(scope, receive, send)
            tg.cancel_scope.cancel()


async def mcp_asgi(scope: Any, receive: Any, send: Any) -> None:
    """ASGI mount for Streamable HTTP MCP transport.

    Auth paths:
    1. Bearer token (opaque session token from Redis)
    2. Key/secret headers (backward compatible, no Redis dependency)
    """
    if scope.get("method") == "POST":
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")
        base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
        pool: ClientPool = scope["app"].state.client_pool
        store: RedisStore = scope["app"].state.redis_store
        cb: CircuitBreaker = scope["app"].state.circuit_breaker
        semaphore: asyncio.Semaphore = scope["app"].state.mcp_semaphore
        rl_config: RateLimitConfig = scope["app"].state.rate_limit_config
        request_id = headers.get("x-request-id", "").strip() or str(uuid4())
        session_id = (
            headers.get("mcp-session-id", "").strip()
            or headers.get("x-session-id", "").strip()
            or request_id
        )

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

            import logging
            _mcp_log = logging.getLogger("finout_mcp_hosted.mcp_asgi")

            # Session lookup in Redis
            try:
                session = await store.get_session(token)
            except RedisUnavailableError:
                response = JSONResponse(
                    {"error": "Service temporarily unavailable"},
                    status_code=503,
                )
                await response(scope, receive, send)
                return

            if session is None:
                response = JSONResponse(
                    {"error": "Invalid or expired token"},
                    status_code=401,
                    headers=_oauth_challenge_headers(base_url, "invalid_token"),
                )
                await response(scope, receive, send)
                return

            account_id = session.get("account_id", "")
            user_id = session.get("user_id", "")
            frontegg_jwt = session.get("frontegg_jwt", "")

            if not account_id:
                response = JSONResponse(
                    {"error": "Invalid session"},
                    status_code=401,
                    headers=_oauth_challenge_headers(base_url, "invalid_token"),
                )
                await response(scope, receive, send)
                return

            # Rate limit check
            allowed, rl_headers = await check_mcp_rate_limit(
                store, user_id, account_id, rl_config
            )
            if not allowed:
                response = JSONResponse(
                    {"error": "Rate limit exceeded"},
                    status_code=429,
                    headers=rl_headers,
                )
                await response(scope, receive, send)
                return

            # Circuit breaker check
            if not cb.allow_request():
                response = JSONResponse(
                    {"error": "Service temporarily unavailable"},
                    status_code=503,
                )
                await response(scope, receive, send)
                return

            # Semaphore for concurrency control
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=1.0)
            except asyncio.TimeoutError:
                response = JSONResponse(
                    {"error": "Server at capacity"},
                    status_code=503,
                )
                await response(scope, receive, send)
                return

            try:
                api_url = os.getenv("FINOUT_API_URL", "https://app.finout.io")
                fingerprint: tuple[str, ...] = ("session", account_id, user_id, api_url)
                client = await pool.get_or_create(
                    fingerprint,
                    bearer_token=frontegg_jwt,
                    internal_api_url=api_url,
                    account_id=account_id,
                    internal_auth_mode=InternalAuthMode.BEARER_TOKEN,
                    allow_missing_credentials=True,
                )
                # Always update to the current JWT
                client.bearer_token = frontegg_jwt

                # Refresh session TTL on use
                try:
                    await store.refresh_session_ttl(token, ttl=3600)
                except RedisUnavailableError:
                    pass

                client_token = set_request_client(client)
                mode_token = set_request_runtime_mode(MCPMode.PUBLIC.value)
                trace_token = set_trace_context(
                    {
                        "origin": "direct_mcp",
                        "request_id": request_id,
                        "session_id": session_id,
                        "account_id": account_id,
                        "user_id": user_id,
                        "auth_mode": "session",
                    }
                )
                try:
                    await asyncio.wait_for(
                        _handle_with_transport(scope, receive, send),
                        timeout=30.0,
                    )
                    cb.record_success()
                except asyncio.TimeoutError:
                    cb.record_failure()
                    response = JSONResponse(
                        {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Request timeout"}, "id": None},
                        status_code=504,
                    )
                    await response(scope, receive, send)
                except Exception:
                    cb.record_failure()
                    raise
                finally:
                    reset_trace_context(trace_token)
                    _client_var.reset(client_token)
                    _runtime_mode_var.reset(mode_token)
            finally:
                semaphore.release()
            return

        # Key/secret header auth path (backward compatible, no Redis dependency)
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

    # For non-POST requests (GET/DELETE), require valid auth.
    headers = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
    }
    base_url = os.getenv("MCP_BASE_URL", "").rstrip("/")
    auth_header = headers.get("authorization", "")

    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        store = scope["app"].state.redis_store
        try:
            session = await store.get_session(token)
        except RedisUnavailableError:
            session = None
        if session is None:
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


# ── App ──────────────────────────────────────────────────────────────────────


app = Starlette(
    routes=[
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/health/ready", endpoint=health_ready, methods=["GET"]),
        Route("/debug/sso", endpoint=debug_sso, methods=["GET"]),
        Route("/debug/cookies", endpoint=debug_cookies, methods=["GET"]),
        Route("/debug/verify-token", endpoint=debug_verify_token, methods=["GET"]),
        Route("/api/tenants", endpoint=proxy_tenants, methods=["GET"]),
        Route("/api/tenant-switch", endpoint=proxy_tenant_switch, methods=["POST", "PUT"]),
        Route("/frontegg/{path:path}", endpoint=frontegg_proxy, methods=["GET", "POST", "PUT", "DELETE", "PATCH"]),
        Route("/authorize", endpoint=oauth_authorize_get, methods=["GET"]),
        Route("/authorize", endpoint=oauth_authorize_post, methods=["POST"]),
        Route("/account/{path:path}", endpoint=oauth_login_callback, methods=["GET"]),
        Route("/register", endpoint=oauth_register, methods=["POST"]),
        Route("/token", endpoint=oauth_token, methods=["POST"]),
        Route("/revoke", endpoint=oauth_revoke, methods=["POST"]),
        Route(
            "/.well-known/oauth-protected-resource",
            endpoint=oauth_protected_resource,
            methods=["GET"],
        ),
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
        Route(
            "/.well-known/openid-configuration",
            endpoint=oauth_authorization_server,
            methods=["GET"],
        ),
        Route("/mcp", endpoint=mcp_route, methods=["GET", "POST", "DELETE"]),
        Route("/mcp/", endpoint=mcp_route, methods=["GET", "POST", "DELETE"]),
    ],
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["WWW-Authenticate"],
        ),
    ],
)
app.router.redirect_slashes = False


class _HealthFilter(_logging.Filter):
    """Suppress noisy GET /health access log lines."""

    def filter(self, record: _logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "GET /health" in msg:
            return False
        if "com.chrome.devtools" in msg:
            return False
        return True


def main() -> None:
    """Run hosted public MCP service."""
    import multiprocessing
    import uvicorn

    _logging.getLogger("uvicorn.access").addFilter(_HealthFilter())
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8080"))
    workers = int(os.getenv("MCP_WORKERS", str(min(multiprocessing.cpu_count(), 4))))
    uvicorn.run("finout_mcp_hosted.server:app", host=host, port=port, lifespan="on", workers=workers)


def dev() -> None:
    """Run with auto-reload for local development."""
    import uvicorn

    _logging.getLogger("uvicorn.access").addFilter(_HealthFilter())
    uvicorn.run("finout_mcp_hosted.server:app", host="0.0.0.0", port=8080, reload=True)


if __name__ == "__main__":
    main()
