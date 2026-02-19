# MCP Distributions

This repository ships two MCP redistributables with different security models.

## Public MCP (Customer-Facing)

- Package: `packages/mcp-server`
- CLI: `finout-mcp`
- Auth model: Finout API key/secret
- Intended usage: downloadable/local MCP for customers

### Build

```bash
./scripts/build_mcp_distributions.sh
```

### Install and test locally

```bash
python3 -m venv /tmp/public-mcp
source /tmp/public-mcp/bin/activate
pip install dist/mcp-server/*.whl
finout-mcp --help
```

### Hosted public endpoint

```bash
finout-mcp-hosted-public
```

Service endpoints:

- `GET /health`
- `POST/GET /mcp` (Streamable HTTP MCP transport)

Hosted auth headers:

- `x-finout-client-id`
- `x-finout-secret-key`
- Optional: `x-finout-api-url` (default `https://app.finout.io`)

### Required runtime environment

```bash
export FINOUT_CLIENT_ID="YOUR_CLIENT_ID"
export FINOUT_SECRET_KEY="YOUR_SECRET_KEY"
```

Optional:

```bash
export FINOUT_API_URL="https://app.finout.io"
```

## Internal MCP (VECTIQOR-Only)

- Package: `packages/vectiqor-mcp-internal`
- CLI: `vectiqor-mcp-internal`
- Auth model: internal authorized headers
- Intended usage: hosted/internal only, launched by VECTIQOR

### Install and test locally

```bash
python3 -m venv /tmp/internal-mcp
source /tmp/internal-mcp/bin/activate
pip install dist/mcp-server/*.whl dist/vectiqor-mcp-internal/*.whl
vectiqor-mcp-internal --help
```

Notes:

- Internal MCP depends on `finout-mcp-server`, so both wheels are required in a clean venv.
- Public users should only receive `finout-mcp-server`.
