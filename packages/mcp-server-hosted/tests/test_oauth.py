"""Tests for PKCE utilities and opaque token generation."""

import base64
import hashlib

from finout_mcp_hosted.oauth import (
    TOKEN_PREFIX_ACCESS,
    TOKEN_PREFIX_CODE,
    TOKEN_PREFIX_REFRESH,
    generate_opaque_token,
    pkce_challenge,
    verify_pkce,
)


def _make_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_generate_opaque_token_has_prefix():
    token = generate_opaque_token(TOKEN_PREFIX_ACCESS)
    assert token.startswith("fmcp_at_")


def test_generate_opaque_token_length():
    token = generate_opaque_token(TOKEN_PREFIX_ACCESS)
    # prefix (8 chars) + 64 hex chars = 72
    assert len(token) == 8 + 64


def test_generate_opaque_token_unique():
    t1 = generate_opaque_token(TOKEN_PREFIX_CODE)
    t2 = generate_opaque_token(TOKEN_PREFIX_CODE)
    assert t1 != t2


def test_token_prefixes():
    assert generate_opaque_token(TOKEN_PREFIX_ACCESS).startswith("fmcp_at_")
    assert generate_opaque_token(TOKEN_PREFIX_REFRESH).startswith("fmcp_rt_")
    assert generate_opaque_token(TOKEN_PREFIX_CODE).startswith("fmcp_ac_")


def test_verify_pkce_correct_sha256():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected_challenge = _make_challenge(verifier)
    assert verify_pkce(verifier, expected_challenge) is True


def test_verify_pkce_wrong_verifier():
    verifier = "correct-verifier-00000000000000000000000000"
    challenge = _make_challenge(verifier)
    assert verify_pkce("wrong-verifier", challenge) is False


def test_pkce_challenge_matches_manual():
    verifier = "test-verifier-1234567890"
    expected = _make_challenge(verifier)
    assert pkce_challenge(verifier) == expected
