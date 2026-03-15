"""PKCE utilities and opaque token generation for OAuth flows."""

from __future__ import annotations

import base64
import hashlib
import secrets

TOKEN_PREFIX_ACCESS = "fmcp_at_"
TOKEN_PREFIX_REFRESH = "fmcp_rt_"
TOKEN_PREFIX_CODE = "fmcp_ac_"


def generate_opaque_token(prefix: str) -> str:
    """Generate a prefixed opaque token (prefix + 64 hex chars)."""
    return prefix + secrets.token_hex(32)


# ── PKCE helpers ───────────────────────────────────────────────────────────────


def pkce_challenge(verifier: str) -> str:
    """Compute S256 PKCE challenge from a code verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Verify S256 PKCE: SHA256(verifier) must match challenge."""
    return pkce_challenge(code_verifier) == code_challenge
