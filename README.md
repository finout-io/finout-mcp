# Finout MCP Server

**Model Context Protocol (MCP) server for Finout cloud cost management**

Enable AI assistants like Claude to query and analyze cloud costs through natural language.

---

## 🚀 Quick Start

### For End Users (Claude Desktop)

```bash
# Install MCP server
cd packages/mcp-server
uv sync
uv pip install -e .

# Configure Claude Desktop (~/.config/claude/claude_desktop_config.json)
{
  "mcpServers": {
    "finout": {
      "command": "uv",
      "args": ["--directory", "/path/to/finout-mcp/packages/mcp-server", "run", "finout-mcp"],
      "env": {
        "FINOUT_CLIENT_ID": "your_client_id",
        "FINOUT_SECRET_KEY": "your_secret_key"
      }
    }
  }
}
```

### For Developers (Testing with BILLY)

```bash
# Install workspace
uv sync

# Configure
cp .env.example .env
# Edit .env with your credentials

# Run BILLY
uv run --directory packages/billy billy

# Open http://localhost:8000
```

---

## 📋 Common Commands

All commands use `uv` - no additional tools needed!

### Installation
```bash
# Install everything (from root)
uv sync

# Install MCP server only
cd packages/mcp-server && uv sync

# Install BILLY only
cd packages/billy && uv sync
```

### Running

```bash
# Run BILLY (from root)
uv run --directory packages/billy billy

# Run BILLY with auto-reload (development)
cd packages/billy
uv run uvicorn billy.server:app --reload --host 0.0.0.0 --port 8000

# Run MCP server (stdio mode for testing)
cd packages/mcp-server
uv run finout-mcp
```

### Testing

```bash
# Run MCP server tests
cd packages/mcp-server
uv run pytest tests/ -v
```

### Building

```bash
# Build MCP server for PyPI
cd packages/mcp-server
uv build

# Build all redistributables (public + internal)
./scripts/build_mcp_distributions.sh

# Build BILLY Docker image
docker build -f Dockerfile.billy -t billy:latest .
```

### Docker

```bash
# Run BILLY with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Kubernetes

```bash
# Deploy BILLY
kubectl apply -k deployments/kubernetes/

# View logs
kubectl logs -n finout-tools -l app=billy -f

# Delete
kubectl delete -k deployments/kubernetes/
```

---

## 📦 Project Structure

```
finout-mcp/                      # uv workspace root
├── pyproject.toml              # Workspace configuration
├── packages/
│   ├── mcp-server/              # 🎯 Main product
│   │   ├── src/finout_mcp_server/
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── billy/                    # 🔧 Internal tool
│       ├── src/billy/
│       │   ├── server.py
│       │   └── static/index.html
│       └── pyproject.toml
├── deployments/kubernetes/      # K8s manifests
├── docker-compose.yml
├── Dockerfile.billy
└── .env.example
```

## 🧩 Redistributables

- Public MCP package: `packages/mcp-server` (CLI: `finout-mcp`)
  - Auth mode: API key/secret
  - Intended for external/customer usage
- Internal MCP package: `packages/billy-mcp-internal` (CLI: `billy-mcp-internal`)
  - Auth mode: internal authorized headers
  - Intended only for BILLY-hosted/internal usage

---

## 🎯 Use Cases

**Cost Queries:**
- "What were my AWS costs last month?"
- "Show me top 5 services by cost"
- "Kubernetes costs by namespace"

**Comparisons:**
- "Compare this month to last month"
- "Production vs staging costs"

**Filtering:**
- "Costs for ml-training project"
- "EC2 in us-east-1"

**Optimization:**
- "Show anomalies"
- "Waste recommendations"

---

## 🔑 Configuration

Create `.env` in root:

```bash
# Finout API (required)
FINOUT_CLIENT_ID=your_client_id
FINOUT_SECRET_KEY=your_secret_key

# Finout API URL (optional, defaults to https://app.finout.io)
FINOUT_API_URL=https://app.finout.io

# Anthropic API (for BILLY only)
ANTHROPIC_API_KEY=your_anthropic_api_key
```

---

## 📚 Documentation

- **[MCP Server](packages/mcp-server/README.md)** - Customer docs
- **[BILLY](packages/billy/README.md)** - Internal tool
- **[Distributions](docs/DISTRIBUTIONS.md)** - Public vs internal packaging and install flows
- **[Kubernetes](deployments/kubernetes/README.md)** - K8s deployment
- **[CHANGELOG.md](CHANGELOG.md)** - Version history

---

## 🧪 Development Workflow

```bash
# 1. Install
uv sync

# 2. Run BILLY
uv run --directory packages/billy billy

# 3. Make changes to MCP server
# Edit packages/mcp-server/src/...

# 4. Test changes
cd packages/mcp-server
uv run pytest tests/ -v

# 5. Test in BILLY
# BILLY automatically picks up local MCP changes
```

---

## 🚢 Deployment

### Docker (Development)

```bash
docker-compose up -d
# Access: http://localhost:8000
```

### Kubernetes (Production)

```bash
# Build and push
docker build -f Dockerfile.billy -t your-registry/billy:v1.0.0 .
docker push your-registry/billy:v1.0.0

# Deploy
kubectl apply -k deployments/kubernetes/
```

See [deployments/kubernetes/README.md](deployments/kubernetes/README.md)

---

## ⚙️ CI/CD

Pipeline: `.circleci/config.yml`

On every PR and push, CI:
- validates MCP (`ruff`, `mypy`, `pytest`)
- builds BILLY frontend and Python compile checks
- builds Python package artifacts for:
  - `finout-mcp`
  - `billy`
  - `billy-mcp-internal` (internal-only, bundled with BILLY workflows)
- builds BILLY Docker image

Optional publish steps:
- GHCR image push: when Circle env vars are set:
  - `GHCR_USERNAME`
  - `GHCR_TOKEN`
  - `GHCR_ORG`
- ECR image push: when Circle env vars are set:
  - `ECR_REGISTRY` (for example `277411487094.dkr.ecr.us-east-1.amazonaws.com`)
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION` (for example `us-east-1`)
- PyPI package publish (main only): enabled with `PYPI_API_TOKEN`
  - Only `finout-mcp` is published. Internal packages are never published.

---

## 📦 Publishing MCP Server

```bash
cd packages/mcp-server

# Build
uv build

# Publish to PyPI
uv publish

# Customers install with
pip install finout-mcp
```

---

## 🤝 Contributing

1. Fork and clone
2. Install: `uv sync`
3. Make changes
4. Test: `cd packages/mcp-server && uv run pytest`
5. Submit PR

---

## 📄 License

MIT - see [LICENSE](packages/mcp-server/LICENSE)

---

## 🆘 Support

- **Docs**: [packages/mcp-server/README.md](packages/mcp-server/README.md)
- **Issues**: GitHub Issues
- **Email**: support@finout.io

---

**Made with ❤️ by Finout**
