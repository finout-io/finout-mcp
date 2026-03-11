"""PKCE utilities and in-memory authorization code store."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass

_CODE_TTL = 600  # 10 minutes


# ── Auth code store ────────────────────────────────────────────────────────────


@dataclass
class AuthCodeEntry:
    jwt: str
    code_challenge: str
    redirect_uri: str
    expires_at: float


_store: dict[str, AuthCodeEntry] = {}


def generate_auth_code(jwt: str, code_challenge: str, redirect_uri: str) -> str:
    code = secrets.token_urlsafe(32)
    _store[code] = AuthCodeEntry(
        jwt=jwt,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
        expires_at=time.time() + _CODE_TTL,
    )
    return code


def consume_auth_code(code: str, code_verifier: str) -> str:
    """Look up code, verify PKCE, delete entry, and return JWT.

    Raises ValueError on invalid code, expiry, or PKCE mismatch.
    """
    entry = _store.get(code)
    if entry is None:
        raise ValueError("Invalid authorization code")
    if time.time() > entry.expires_at:
        del _store[code]
        raise ValueError("Authorization code expired")
    if not _verify_pkce(code_verifier, entry.code_challenge):
        raise ValueError("PKCE verification failed")
    del _store[code]
    return entry.jwt


# ── PKCE helpers ───────────────────────────────────────────────────────────────


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    return _pkce_challenge(code_verifier) == code_challenge
