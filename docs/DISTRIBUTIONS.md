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

### Local Docker end-to-end test (hosted mode)

```bash
# Build image
docker build -f Dockerfile.mcp-hosted-public -t finout-mcp-hosted-public:local .

# Run hosted service
docker run --rm -p 8080:8080 finout-mcp-hosted-public:local
```

In a second terminal:

```bash
# Health
curl -sS http://localhost:8080/health

# MCP auth gate check (expected: 401)
curl -i -X POST http://localhost:8080/mcp -H 'content-type: application/json' -d '{}'

# MCP call with credentials (auth passes; response shape depends on message payload)
curl -i -X POST http://localhost:8080/mcp \
  -H 'content-type: application/json' \
  -H 'x-finout-client-id: YOUR_CLIENT_ID' \
  -H 'x-finout-secret-key: YOUR_SECRET_KEY' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"local-test","version":"1.0.0"}}}'
```

### Manual ECR push for hosted image

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=277411487094
export ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
export ECR_REPO="finout-mcp-hosted-public"
export TAG="$(git rev-parse --short HEAD)"

aws ecr describe-repositories --repository-names "${ECR_REPO}" >/dev/null 2>&1 || \
  aws ecr create-repository --repository-name "${ECR_REPO}" >/dev/null

aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${ECR_REGISTRY}"

docker build -f Dockerfile.mcp-hosted-public \
  -t "${ECR_REGISTRY}/${ECR_REPO}:${TAG}" \
  -t "${ECR_REGISTRY}/${ECR_REPO}:latest" .

docker push "${ECR_REGISTRY}/${ECR_REPO}:${TAG}"
docker push "${ECR_REGISTRY}/${ECR_REPO}:latest"
```

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
