"""JWT authentication and Frontegg API calls for hosted public MCP service."""

import base64
import os
from functools import lru_cache
from urllib.parse import unquote, urlparse

import httpx
import jwt


@lru_cache(maxsize=1)
def _get_public_key() -> str:
    """Load base64-encoded RSA public key from FINOUT_JWT_PUBLIC_KEY env var."""
    raw = os.getenv("FINOUT_JWT_PUBLIC_KEY", "")
    return base64.b64decode(raw).decode()


@lru_cache(maxsize=1)
def _get_expected_issuer() -> str:
    issuer = os.getenv("FINOUT_JWT_ISSUER", "").strip()
    if not issuer:
        raise ValueError("FINOUT_JWT_ISSUER is required for OAuth JWT validation.")
    return issuer


@lru_cache(maxsize=1)
def _get_expected_audience() -> str | None:
    return os.getenv("FINOUT_JWT_AUDIENCE", "").strip() or None


@lru_cache(maxsize=1)
def _get_login_cookie_public_key() -> str | None:
    """Load RSA public key for __fnt_dd_ cookie (AUTH_LOGIN.PUBLIC).

    Accepts the key as base64-encoded PEM or URL-encoded PEM.
    """
    raw = os.getenv("FINOUT_LOGIN_JWT_PUBLIC_KEY", "")
    if not raw:
        return None
    decoded = unquote(raw)
    if decoded.startswith("-----"):
        return decoded
    b64decoded = base64.b64decode(raw).decode()
    return unquote(b64decoded)


def verify_cookie_jwt(token: str) -> dict:
    """Verify Finout __fnt_dd_ login cookie JWT, return payload with tenantId.

    Uses AUTH_LOGIN.PUBLIC (FINOUT_LOGIN_JWT_PUBLIC_KEY), which is separate from
    the Frontegg RSA key. No issuer/audience validation — Finout-internal token.
    """
    key = _get_login_cookie_public_key()
    if not key:
        raise ValueError("FINOUT_LOGIN_JWT_PUBLIC_KEY not configured")
    payload = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        options={"verify_aud": False, "verify_iss": False},
    )
    tenant_id = payload.get("tenantId")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise jwt.InvalidTokenError("Missing tenantId claim")
    return payload


def frontegg_base_url() -> str:
    """Derive Frontegg base URL (scheme + host) from FRONTEGG_AUTH_URL."""
    auth_url = os.getenv("FRONTEGG_AUTH_URL", "")
    if not auth_url:
        return ""
    parsed = urlparse(auth_url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def authenticate_password(email: str, password: str) -> str:
    """Call Frontegg's password auth API, return Frontegg JWT access token."""
    url = os.getenv("FRONTEGG_AUTH_URL", "")
    if not url:
        raise ValueError("FRONTEGG_AUTH_URL not configured")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json={"email": email, "password": password})
        if not resp.is_success:
            try:
                body = resp.json()
                msg = body.get("message") or body.get("error") or f"HTTP {resp.status_code}"
            except Exception:
                msg = f"HTTP {resp.status_code}"
            raise ValueError(msg)
        token = resp.json().get("accessToken", "")
        if not token:
            raise ValueError("No token in response")
        return token


async def check_sso(email: str) -> bool:
    """Return True if the email domain requires SSO login."""
    base = frontegg_base_url()
    if not base:
        return False
    url = f"{base}/identity/resources/sso/v2/by-email"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"email": email})
        if resp.status_code != 200:
            return False
        data = resp.json()
        # If the response has an explicit enabled flag, respect it.
        enabled = data.get("enabled")
        if isinstance(enabled, bool):
            return enabled
        # A 200 with any ssoEndpoint means SSO is configured.
        return bool(data.get("ssoEndpoint"))
    except Exception:
        return False


async def check_sso_debug(email: str) -> dict:
    """Return raw SSO check result for debugging."""
    base = frontegg_base_url()
    if not base:
        return {"error": "FRONTEGG_AUTH_URL not set — cannot derive base URL"}
    url = f"{base}/identity/resources/sso/v2/by-email"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"email": email})
        return {"status": resp.status_code, "body": resp.text}
    except Exception as exc:
        return {"error": str(exc)}


async def exchange_sso_code(code: str, code_verifier: str, redirect_uri: str) -> str:
    """Exchange a Frontegg authorization code (from SSO callback) for a JWT."""
    base = frontegg_base_url()
    client_id = os.getenv("FRONTEGG_CLIENT_ID", "")
    if not base or not client_id:
        raise ValueError("FRONTEGG_AUTH_URL and FRONTEGG_CLIENT_ID are required for SSO")
    token_url = f"{base}/oauth/token"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        token = resp.json().get("access_token", "")
        if not token:
            raise ValueError("No access_token in SSO token response")
        return token


def verify_login_jwt(token: str) -> dict:
    """Verify RS256 JWT, return payload with tenantId, email, id."""
    audience = _get_expected_audience()
    options = {} if audience else {"verify_aud": False}
    payload = jwt.decode(
        token,
        _get_public_key(),
        algorithms=["RS256"],
        issuer=_get_expected_issuer(),
        audience=audience,
        options=options,
    )
    tenant_id = payload.get("tenantId")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise jwt.InvalidTokenError("Missing tenantId claim")
    return payload
