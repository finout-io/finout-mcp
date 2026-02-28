import base64
import hashlib
import time

import pytest

from finout_mcp_hosted.oauth import (
    _sso_store,
    _store,
    _verify_pkce,
    consume_auth_code,
    consume_sso_flow,
    create_sso_flow,
    generate_auth_code,
    pkce_challenge,
)


def _make_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_generate_and_consume_auth_code_valid_pkce():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = _make_challenge(verifier)

    code = generate_auth_code("test-jwt", challenge, "http://localhost/callback")
    jwt_out = consume_auth_code(code, verifier)

    assert jwt_out == "test-jwt"


def test_consume_auth_code_wrong_verifier_raises():
    verifier = "correct-verifier-abcdefghij1234567890abcdef"
    challenge = _make_challenge(verifier)

    code = generate_auth_code("jwt", challenge, "http://localhost/cb")

    with pytest.raises(ValueError, match="PKCE"):
        consume_auth_code(code, "wrong-verifier")


def test_consume_auth_code_expired_raises():
    verifier = "some-verifier-abcdefghij1234567890abcdef01"
    challenge = _make_challenge(verifier)

    code = generate_auth_code("jwt", challenge, "http://localhost/cb")
    # Manually expire the entry.
    _store[code].expires_at = time.time() - 1

    with pytest.raises(ValueError, match="expired"):
        consume_auth_code(code, verifier)


def test_consume_auth_code_once_only():
    verifier = "once-only-verifier-abcdefghij1234567890ab"
    challenge = _make_challenge(verifier)

    code = generate_auth_code("jwt", challenge, "http://localhost/cb")
    consume_auth_code(code, verifier)

    with pytest.raises(ValueError, match="Invalid"):
        consume_auth_code(code, verifier)


def test_verify_pkce_correct_sha256():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected_challenge = _make_challenge(verifier)
    assert _verify_pkce(verifier, expected_challenge) is True


def test_verify_pkce_wrong_verifier():
    verifier = "correct-verifier-00000000000000000000000000"
    challenge = _make_challenge(verifier)
    assert _verify_pkce("wrong-verifier", challenge) is False


# ── pkce_challenge ─────────────────────────────────────────────────────────────


def test_pkce_challenge_matches_manual_calculation():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == _make_challenge(verifier)


# ── SSO flow store ─────────────────────────────────────────────────────────────


def test_create_and_consume_sso_flow():
    nonce, code_verifier = create_sso_flow(
        "http://localhost/cb", "challenge-abc", "state-xyz"
    )
    entry = consume_sso_flow(nonce)
    assert entry.original_redirect_uri == "http://localhost/cb"
    assert entry.original_code_challenge == "challenge-abc"
    assert entry.original_state == "state-xyz"
    assert entry.frontegg_code_verifier == code_verifier


def test_consume_sso_flow_expired():
    nonce, _ = create_sso_flow("http://localhost/cb", "ch", "st")
    _sso_store[nonce].expires_at = time.time() - 1
    with pytest.raises(ValueError, match="expired"):
        consume_sso_flow(nonce)


def test_consume_sso_flow_once_only():
    nonce, verifier = create_sso_flow("http://localhost/cb", "ch", "st")
    consume_sso_flow(nonce)
    with pytest.raises(ValueError, match="Invalid"):
        consume_sso_flow(nonce)
