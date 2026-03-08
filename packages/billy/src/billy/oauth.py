"""OAuth 2.0 + PKCE endpoints for direct MCP client authentication.

Allows MCP clients (Claude Desktop, Cursor, etc.) to authenticate via
Frontegg embedded login, then use Bearer tokens for /mcp requests.
"""

from __future__ import annotations

import base64
import hashlib
import html
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .auth import verify_jwt

_CODE_TTL = 600  # 10 minutes


# ── Auth code store ───────────────────────────────────────────────────────────

@dataclass
class AuthCodeEntry:
    jwt: str
    code_challenge: str
    redirect_uri: str
    expires_at: float


_store: dict[str, AuthCodeEntry] = {}


def _generate_auth_code(jwt_token: str, code_challenge: str, redirect_uri: str) -> str:
    code = secrets.token_urlsafe(32)
    _store[code] = AuthCodeEntry(
        jwt=jwt_token,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
        expires_at=time.time() + _CODE_TTL,
    )
    return code


def _consume_auth_code(code: str, code_verifier: str) -> str:
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


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    return _pkce_challenge(code_verifier) == code_challenge


# ── Embedded login page ──────────────────────────────────────────────────────

_EMBEDDED_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Finout — Sign in</title>
  <script src="https://cdn.jsdelivr.net/npm/@frontegg/js@latest/umd/frontegg.production.min.js"></script>
  <style>
    *,*::before,*::after{{box-sizing:border-box}}
    body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      background:#f5f7fa;display:flex;align-items:center;justify-content:center;
      min-height:100vh;flex-direction:column}}
    #frontegg-login-box{{width:100%;max-width:480px}}
    .error{{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;border-radius:8px;
      padding:10px 14px;font-size:14px;margin:20px;max-width:480px;text-align:center}}
    .loading{{color:#6b7280;font-size:16px}}
  </style>
</head>
<body>
  <div id="frontegg-login-box"></div>
  <div id="error-container"></div>
  <script>
    (function() {{
      var OAUTH_PARAMS = {{
        redirect_uri: "{redirect_uri}",
        code_challenge: "{code_challenge}",
        state: "{state}"
      }};

      var app = Frontegg.initialize({{
        contextOptions: {{
          baseUrl: "{frontegg_base_url}",
          clientId: "{frontegg_client_id}"
        }},
        hostedLoginBox: false
      }});

      var handled = false;

      app.store.subscribe(function() {{
        if (handled) return;
        var state = app.store.getState();
        if (state.auth.isAuthenticated && state.auth.user && state.auth.user.accessToken) {{
          handled = true;
          completeOAuth(state.auth.user.accessToken);
        }}
      }});

      function completeOAuth(accessToken) {{
        var form = document.createElement("form");
        form.method = "POST";
        form.action = "/authorize";
        form.style.display = "none";

        var fields = {{
          access_token: accessToken,
          redirect_uri: OAUTH_PARAMS.redirect_uri,
          code_challenge: OAUTH_PARAMS.code_challenge,
          state: OAUTH_PARAMS.state
        }};

        for (var key in fields) {{
          var input = document.createElement("input");
          input.type = "hidden";
          input.name = key;
          input.value = fields[key] || "";
          form.appendChild(input);
        }}

        document.body.appendChild(form);
        form.submit();
      }}
    }})();
  </script>
</body>
</html>
"""


# ── Route handlers ────────────────────────────────────────────────────────────

async def oauth_authorize_get(request: Request) -> Response:
    """Serve embedded Frontegg login for OAuth PKCE authorization."""
    params = request.query_params
    response_type = params.get("response_type", "")
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")

    if response_type != "code" or not redirect_uri or not code_challenge:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "response_type=code, redirect_uri, and code_challenge are required"},
            status_code=400,
        )

    # If user has a valid cookie, skip the login page
    cookie_token = request.cookies.get("__fnt_dd_", "")
    if cookie_token:
        try:
            verify_jwt(cookie_token)
            state = params.get("state", "")
            code = _generate_auth_code(cookie_token, code_challenge, redirect_uri)
            query: dict[str, str] = {"code": code}
            if state:
                query["state"] = state
            return RedirectResponse(f"{redirect_uri}?{urlencode(query)}", status_code=302)
        except Exception:
            pass

    frontegg_base_url = os.getenv("FRONTEGG_BASE_URL", "")
    frontegg_client_id = os.getenv("FRONTEGG_MCP_CLIENT_ID", "")

    if not frontegg_base_url or not frontegg_client_id:
        return JSONResponse(
            {"error": "server_error", "error_description": "Frontegg not configured"},
            status_code=500,
        )

    body = _EMBEDDED_LOGIN_HTML.format(
        redirect_uri=html.escape(redirect_uri, quote=True),
        code_challenge=html.escape(code_challenge, quote=True),
        state=html.escape(params.get("state", ""), quote=True),
        frontegg_base_url=html.escape(frontegg_base_url, quote=True),
        frontegg_client_id=html.escape(frontegg_client_id, quote=True),
    )
    return HTMLResponse(body)


async def oauth_authorize_post(request: Request) -> Response:
    """Complete OAuth after Frontegg embedded login.

    Receives the JWT from the client-side Frontegg SDK, validates it,
    generates an auth code, and redirects to the MCP client's redirect_uri.
    """
    form = await request.form()
    access_token = str(form.get("access_token", "")).strip()
    redirect_uri = str(form.get("redirect_uri", "")).strip()
    code_challenge = str(form.get("code_challenge", "")).strip()
    state = str(form.get("state", "")).strip()

    if not access_token or not redirect_uri or not code_challenge:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "Missing required parameters"},
            status_code=400,
        )

    try:
        verify_jwt(access_token)
    except Exception:
        return JSONResponse(
            {"error": "invalid_token", "error_description": "Invalid or expired Frontegg token"},
            status_code=401,
        )

    code = _generate_auth_code(access_token, code_challenge, redirect_uri)

    query: dict[str, str] = {"code": code}
    if state:
        query["state"] = state
    location = f"{redirect_uri}?{urlencode(query)}"
    return RedirectResponse(location, status_code=302)


async def oauth_token(request: Request) -> JSONResponse:
    """Token endpoint: exchange auth code + PKCE verifier for access token."""
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
        access_token = _consume_auth_code(code, code_verifier)
    except ValueError as exc:
        return JSONResponse({"error": "invalid_grant", "error_description": str(exc)}, status_code=400)

    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 3600,
        }
    )


async def oauth_register(request: Request) -> JSONResponse:
    """Dynamic Client Registration stub."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    redirect_uris = body.get("redirect_uris", [])
    return JSONResponse(
        {
            "client_id": "billy",
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


async def oauth_protected_resource(request: Request) -> JSONResponse:
    """RFC 9728 OAuth 2.0 Protected Resource Metadata."""
    base_url = os.getenv("BILLY_BASE_URL", "").rstrip("/")
    return JSONResponse(
        {
            "resource": f"{base_url}/mcp",
            "authorization_servers": [base_url] if base_url else [],
        }
    )


async def oauth_authorization_server(request: Request) -> JSONResponse:
    """OAuth 2.0 authorization server metadata (RFC 8414)."""
    base_url = os.getenv("BILLY_BASE_URL", "").rstrip("/")
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
