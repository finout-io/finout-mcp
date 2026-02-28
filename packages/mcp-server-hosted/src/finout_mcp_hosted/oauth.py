"""PKCE utilities and in-memory authorization code / SSO flow stores."""

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


# ── SSO proxy flow store ───────────────────────────────────────────────────────


@dataclass
class SSOFlowEntry:
    original_redirect_uri: str
    original_code_challenge: str
    original_state: str
    frontegg_code_verifier: str
    expires_at: float


_sso_store: dict[str, SSOFlowEntry] = {}


def create_sso_flow(
    original_redirect_uri: str,
    original_code_challenge: str,
    original_state: str,
) -> tuple[str, str]:
    """Store SSO proxy state. Returns (nonce, frontegg_code_verifier)."""
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(48)
    _sso_store[nonce] = SSOFlowEntry(
        original_redirect_uri=original_redirect_uri,
        original_code_challenge=original_code_challenge,
        original_state=original_state,
        frontegg_code_verifier=code_verifier,
        expires_at=time.time() + _CODE_TTL,
    )
    return nonce, code_verifier


def consume_sso_flow(nonce: str) -> SSOFlowEntry:
    """Look up and delete SSO flow state. Raises ValueError if invalid/expired."""
    entry = _sso_store.get(nonce)
    if entry is None:
        raise ValueError("Invalid SSO state")
    if time.time() > entry.expires_at:
        del _sso_store[nonce]
        raise ValueError("SSO state expired")
    del _sso_store[nonce]
    return entry


# ── PKCE helpers ───────────────────────────────────────────────────────────────


def pkce_challenge(verifier: str) -> str:
    """Compute BASE64URL(SHA256(verifier))."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    return pkce_challenge(code_verifier) == code_challenge
