"""PKCE utilities and stateless HMAC-signed authorization codes.

Codes are self-contained signed tokens, so any pod can verify them
without shared in-memory state.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import zlib

_CODE_TTL = 600  # 10 minutes


def _signing_key() -> bytes:
    """Return the HMAC signing key for auth codes.

    Uses MCP_CODE_SECRET env var. Each pod must share the same value.
    Falls back to a per-process random key (only works with 1 replica).
    """
    key = os.getenv("MCP_CODE_SECRET", "")
    if not key:
        global _FALLBACK_KEY
        key = _FALLBACK_KEY
    return key.encode()


_FALLBACK_KEY: str = secrets.token_hex(32)


# ── Auth code generation / consumption ────────────────────────────────────────


def generate_auth_code(
    jwt: str,
    code_challenge: str,
    redirect_uri: str,
    refresh_token: str = "",
) -> str:
    """Create a signed, self-contained authorization code.

    The payload is zlib-compressed before base64 encoding to keep codes
    under URL length limits (Frontegg JWTs can be 7000+ chars).
    """
    data: dict[str, object] = {
        "jwt": jwt,
        "cc": code_challenge,
        "ru": redirect_uri,
        "exp": time.time() + _CODE_TTL,
        "n": secrets.token_hex(8),  # nonce, makes each code unique
    }
    if refresh_token:
        data["rt"] = refresh_token
    payload = json.dumps(data, separators=(",", ":"))
    compressed = zlib.compress(payload.encode(), level=9)
    b64 = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode()
    sig = hmac.new(key=_signing_key(), msg=b64.encode(), digestmod=hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def consume_auth_code(
    code: str,
    code_verifier: str,
    redirect_uri: str = "",
) -> tuple[str, str]:
    """Verify signature, check expiry, verify PKCE and redirect_uri.

    Returns (access_token, refresh_token).
    Raises ValueError on any failure.
    """
    try:
        b64, sig = code.rsplit(".", 1)
    except ValueError:
        raise ValueError("Invalid authorization code")

    expected = hmac.new(key=_signing_key(), msg=b64.encode(), digestmod=hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid authorization code")

    try:
        padding = "=" * (-len(b64) % 4)
        raw = base64.urlsafe_b64decode(b64 + padding)
        # Try decompressing (new format), fall back to plain JSON (old format).
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        payload = json.loads(raw)
    except Exception:
        raise ValueError("Invalid authorization code")

    if time.time() > payload["exp"]:
        raise ValueError("Authorization code expired")

    if not _verify_pkce(code_verifier, payload["cc"]):
        raise ValueError("PKCE verification failed")

    # RFC 6749 §4.1.3: verify redirect_uri matches the one in the authorization request.
    stored_uri = payload.get("ru", "")
    if stored_uri:
        if not redirect_uri:
            raise ValueError("redirect_uri required")
        if redirect_uri != stored_uri:
            raise ValueError("redirect_uri mismatch")

    return payload["jwt"], payload.get("rt", "")


# ── PKCE helpers ───────────────────────────────────────────────────────────────


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    return _pkce_challenge(code_verifier) == code_challenge
