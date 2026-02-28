# finout-mcp-hosted

OAuth-capable hosted MCP server for regular Finout users. Internal deployment only — not published to PyPI.

## Architecture

```
MCP Client (Claude Desktop / mcp-inspector)
    │  OAuth PKCE flow
    ▼
finout-mcp-hosted  (this package)
    │  Serves Finout-branded login form
    │  Authenticates against Frontegg behind the scenes
    │  Issues auth code → exchanges for Frontegg JWT
    │  Verifies JWT on /mcp requests
    ▼
Finout API (app.finout.io)
```

The server also supports key/secret auth (`x-finout-client-id` / `x-finout-secret-key` headers) for backward compatibility.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MCP_BASE_URL` | Yes | Public URL of this server (e.g. `https://mcp.finout.io`) |
| `FRONTEGG_AUTH_URL` | Yes | Frontegg password auth endpoint (e.g. `https://app-abc123.frontegg.com/identity/resources/auth/v1/user`) |
| `FRONTEGG_CLIENT_ID` | SSO only | Frontegg OAuth app client ID. Required if any users authenticate via SSO. Register `{MCP_BASE_URL}/oauth/callback` as a redirect URI in the Frontegg app. |
| `FINOUT_JWT_ISSUER` | Yes | `iss` claim from Frontegg JWT |
| `FINOUT_JWT_AUDIENCE` | No | `aud` claim from Frontegg JWT. If omitted, audience validation is skipped (common in Frontegg embedded mode). |
| `FINOUT_JWT_PUBLIC_KEY` | Yes | Base64-encoded RSA public key from Frontegg |
| `FINOUT_LOGIN_JWT_PUBLIC_KEY` | Cookie auth | Base64-encoded RSA public key for `__fnt_dd_` cookie (`AUTH_LOGIN.PUBLIC` from api-gateway). When set, SSO users on `*.finout.io` are authenticated automatically from their existing browser session — no login form shown. |
| `FINOUT_INTERNAL_API_URL` | Cookie auth | Internal Finout API URL that trusts `authorized-*` headers (bypasses the api-gateway). Required when `FINOUT_LOGIN_JWT_PUBLIC_KEY` is set. |
| `FINOUT_API_URL` | No | Finout API base URL for password/Frontegg JWT auth (default: `https://app.finout.io`) |
| `MCP_HOST` | No | Bind host (default: `0.0.0.0`) |
| `MCP_PORT` | No | Bind port (default: `8080`) |

## Frontegg Setup

1. **Get the RSA public key** (Env Settings → Security → JWT):
   ```bash
   base64 -i frontegg_public.pem
   ```
   Set as `FINOUT_JWT_PUBLIC_KEY`.

2. **Find issuer and audience** by decoding a Frontegg token:
   ```bash
   python3 -c "
   import base64, json
   token = '<paste token here>'
   payload = token.split('.')[1]
   payload += '=' * (-len(payload) % 4)
   print(json.dumps(json.loads(base64.urlsafe_b64decode(payload)), indent=2))
   "
   ```
   - `iss` claim → `FINOUT_JWT_ISSUER`
   - `aud` claim → `FINOUT_JWT_AUDIENCE`

3. **Get the auth URL** — typically:
   `https://app-<id>.frontegg.com/identity/resources/auth/v1/user`
   Set as `FRONTEGG_AUTH_URL`.

## Running Locally

```bash
cd packages/mcp-server-hosted
uv sync

export MCP_BASE_URL=http://localhost:8080
export FRONTEGG_AUTH_URL=https://app-abc123.frontegg.com/identity/resources/auth/v1/user
export FINOUT_JWT_ISSUER=<issuer>
export FINOUT_JWT_AUDIENCE=<audience>
export FINOUT_JWT_PUBLIC_KEY=<base64-key>

uv run finout-mcp-hosted
```

Health check: `curl http://localhost:8080/health`

## Docker

```bash
docker build -f Dockerfile.mcp-hosted-public -t finout-mcp-hosted .

docker run -p 8080:8080 \
  -e MCP_BASE_URL=https://mcp.finout.io \
  -e FRONTEGG_AUTH_URL=https://app-abc123.frontegg.com/identity/resources/auth/v1/user \
  -e FINOUT_JWT_ISSUER=<issuer> \
  -e FINOUT_JWT_AUDIENCE=<audience> \
  -e FINOUT_JWT_PUBLIC_KEY=<base64-key> \
  finout-mcp-hosted
```

## Testing with mcp-inspector

```bash
npx @modelcontextprotocol/inspector
```

1. Set server URL: `http://localhost:8080/mcp`
2. Set auth type: **OAuth 2.0**
3. The inspector calls `/register` (DCR), then redirects to the Finout login form at `/authorize`
4. Submit your Finout credentials — the server authenticates against Frontegg
5. After login, the inspector exchanges the code for a token via `/token`
6. All MCP requests are authenticated with the Bearer token

## Running Tests

```bash
cd packages/mcp-server-hosted
uv run pytest
```
