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
        "FINOUT_SECRET_KEY": "your_secret_key",
        "FINOUT_INTERNAL_API_URL": "https://api.finout.io",
        "FINOUT_ACCOUNT_ID": "your_account_id"
      }
    }
  }
}
```

### For Developers (Testing with ASAF)

```bash
# Install workspace
uv sync

# Configure
cp .env.example .env
# Edit .env with your credentials

# Run ASAF
uv run --directory packages/asaf asaf

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

# Install ASAF only
cd packages/asaf && uv sync
```

### Running

```bash
# Run ASAF (from root)
uv run --directory packages/asaf asaf

# Run ASAF with auto-reload (development)
cd packages/asaf
uv run uvicorn asaf.server:app --reload --host 0.0.0.0 --port 8000

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

# Build ASAF Docker image
docker build -f Dockerfile.asaf -t asaf:latest .
```

### Docker

```bash
# Run ASAF with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Kubernetes

```bash
# Deploy ASAF
kubectl apply -k deployments/kubernetes/

# View logs
kubectl logs -n finout-tools -l app=asaf -f

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
│   └── asaf/                    # 🔧 Internal tool
│       ├── src/asaf/
│       │   ├── server.py
│       │   └── static/index.html
│       └── pyproject.toml
├── deployments/kubernetes/      # K8s manifests
├── docker-compose.yml
├── Dockerfile.asaf
└── .env.example
```

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
FINOUT_INTERNAL_API_URL=https://api.finout.io
FINOUT_ACCOUNT_ID=your_default_account_id

# Anthropic API (for ASAF only)
ANTHROPIC_API_KEY=your_anthropic_api_key
```

---

## 📚 Documentation

- **[MCP Server](packages/mcp-server/README.md)** - Customer docs
- **[ASAF](packages/asaf/README.md)** - Internal tool
- **[Kubernetes](deployments/kubernetes/README.md)** - K8s deployment
- **[CHANGELOG.md](CHANGELOG.md)** - Version history

---

## 🧪 Development Workflow

```bash
# 1. Install
uv sync

# 2. Run ASAF
uv run --directory packages/asaf asaf

# 3. Make changes to MCP server
# Edit packages/mcp-server/src/...

# 4. Test changes
cd packages/mcp-server
uv run pytest tests/ -v

# 5. Test in ASAF
# ASAF automatically picks up local MCP changes
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
docker build -f Dockerfile.asaf -t your-registry/asaf:v1.0.0 .
docker push your-registry/asaf:v1.0.0

# Deploy
kubectl apply -k deployments/kubernetes/
```

See [deployments/kubernetes/README.md](deployments/kubernetes/README.md)

---

## 📦 Publishing MCP Server

```bash
cd packages/mcp-server

# Build
uv build

# Publish to PyPI
uv publish

# Customers install with
pip install finout-mcp-server
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
