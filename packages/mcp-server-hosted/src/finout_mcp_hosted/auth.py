"""JWT authentication for hosted public MCP service."""

import base64
import os
from functools import lru_cache

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
def _get_expected_audience() -> str:
    audience = os.getenv("FINOUT_JWT_AUDIENCE", "").strip()
    if not audience:
        raise ValueError("FINOUT_JWT_AUDIENCE is required for OAuth JWT validation.")
    return audience


def verify_login_jwt(token: str) -> dict:
    """Verify RS256 JWT, return payload with tenantId, email, id."""
    payload = jwt.decode(
        token,
        _get_public_key(),
        algorithms=["RS256"],
        issuer=_get_expected_issuer(),
        audience=_get_expected_audience(),
    )
    tenant_id = payload.get("tenantId")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise jwt.InvalidTokenError("Missing tenantId claim")
    return payload
