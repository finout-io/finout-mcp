# finout-mcp-hosted

OAuth-capable hosted MCP server for regular Finout users. Internal deployment only — not published to PyPI.

## Architecture

```
MCP Client (Claude Desktop / mcp-inspector)
    │  OAuth PKCE flow + Bearer JWT
    ▼
finout-mcp-hosted  (this package)
    │  Verifies Frontegg JWT, extracts tenantId
    │  Creates FinoutClient per session
    ▼
Finout API (app.finout.io)
```

The server also supports key/secret auth (`x-finout-client-id` / `x-finout-secret-key` headers) for backward compatibility.

## Frontegg Setup

1. **Enable hosted login** in the Frontegg portal (Env Settings → Authentication → Hosted Login).

2. **Create an OAuth app** (Env Settings → OAuth):
   - Grant type: Authorization Code + PKCE
   - Redirect URIs:
     - `http://localhost:6274/oauth/callback` (mcp-inspector)
     - `http://localhost:6277/oauth/callback` (alternate mcp-inspector port)
   - Copy the **Client ID** → `FRONTEGG_MCP_CLIENT_ID`

3. **Get the RSA public key** (Env Settings → Security → JWT):
   - Copy the PEM, base64-encode it: `base64 -i frontegg_public.pem`
   - Set as `FINOUT_JWT_PUBLIC_KEY`

4. **Find issuer and audience** by decoding a Frontegg token:
   ```bash
   # Paste a token from a logged-in Frontegg session
   python3 -c "
   import base64, json, sys
   token = '<paste token here>'
   payload = token.split('.')[1]
   payload += '=' * (-len(payload) % 4)
   print(json.dumps(json.loads(base64.urlsafe_b64decode(payload)), indent=2))
   "
   ```
   - `iss` claim → `FINOUT_JWT_ISSUER`
   - `aud` claim → `FINOUT_JWT_AUDIENCE`

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MCP_BASE_URL` | Yes | Public URL of this server (e.g. `https://mcp.finout.io`) |
| `FRONTEGG_BASE_URL` | Yes | Frontegg OAuth base URL (e.g. `https://app-abc123.frontegg.com/oauth`) |
| `FRONTEGG_MCP_CLIENT_ID` | Yes | Frontegg OAuth app client ID |
| `FINOUT_JWT_ISSUER` | Yes | `iss` claim from Frontegg JWT |
| `FINOUT_JWT_AUDIENCE` | Yes | `aud` claim from Frontegg JWT |
| `FINOUT_JWT_PUBLIC_KEY` | Yes | Base64-encoded RSA public key from Frontegg |
| `FINOUT_API_URL` | No | Finout API base URL (default: `https://app.finout.io`) |
| `MCP_HOST` | No | Bind host (default: `0.0.0.0`) |
| `MCP_PORT` | No | Bind port (default: `8080`) |

## Running Locally

```bash
cd packages/mcp-server-hosted

# Install with workspace dep resolved
uv sync

# Set env vars
export MCP_BASE_URL=http://localhost:8080
export FRONTEGG_BASE_URL=https://app-abc123.frontegg.com/oauth
export FRONTEGG_MCP_CLIENT_ID=<client-id>
export FINOUT_JWT_ISSUER=<issuer>
export FINOUT_JWT_AUDIENCE=<audience>
export FINOUT_JWT_PUBLIC_KEY=<base64-key>

uv run finout-mcp-hosted
```

Health check: `curl http://localhost:8080/health`

## Docker

```bash
# From repo root
docker build -f Dockerfile.mcp-hosted-public -t finout-mcp-hosted .

docker run -p 8080:8080 \
  -e MCP_BASE_URL=https://mcp.finout.io \
  -e FRONTEGG_BASE_URL=https://app-abc123.frontegg.com/oauth \
  -e FRONTEGG_MCP_CLIENT_ID=<client-id> \
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
3. The inspector will call `/register` (DCR), then redirect you to Frontegg login
4. After login, the inspector exchanges the code for a token via `/token`
5. All MCP requests are authenticated with the Bearer token

## Running Tests

```bash
cd packages/mcp-server-hosted
uv run pytest
```
