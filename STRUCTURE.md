# Repository Structure

This document explains the organization of the Finout MCP monorepo.

## Overview

This is a monorepo containing:
1. **Finout MCP Server** (main product for customers)
2. **BILLY** (internal diagnostic tool, not distributed)
3. **Deployment configurations**
4. **Utility scripts**
5. **Documentation**

---

## Directory Structure

```
finout-mcp/                         # Repository root
│
├── finout-mcp-server/              # 🎯 MAIN PRODUCT
│   ├── src/                        # Source code
│   │   └── finout_mcp_server/
│   │       ├── server.py           # MCP server implementation
│   │       ├── finout_client.py    # Finout API client
│   │       ├── filter_cache.py     # Caching layer
│   │       └── filter_utils.py     # Filter utilities
│   ├── tests/                      # Unit tests
│   │   ├── test_filter_cache.py
│   │   └── test_internal_api.py
│   ├── pyproject.toml              # Package metadata
│   ├── README.md                   # Customer-facing documentation
│   ├── LICENSE                     # MIT License
│   └── .env                        # Environment variables (gitignored)
│
├── tools/                          # 🔧 INTERNAL TOOLS (not distributed)
│   └── billy/                       # Web-based diagnostic tool
│       ├── billy_server.py          # FastAPI backend
│       ├── index.html              # Web UI
│       ├── requirements.txt        # Python dependencies
│       ├── README.md               # BILLY documentation
│       ├── QUICKSTART.md
│       ├── MULTI_ACCOUNT.md
│       └── .env                    # BILLY config (gitignored)
│
├── deployments/                    # 🚀 DEPLOYMENT CONFIGURATIONS
│   └── docker/
│       ├── Dockerfile.billy         # BILLY container definition
│       ├── docker-compose.yml      # Orchestration for BILLY
│       └── .dockerignore           # Docker build exclusions
│
├── scripts/                        # 🛠️ UTILITY SCRIPTS
│   ├── start-billy.sh              # Start BILLY locally
│   ├── build-mcp.sh               # Build MCP package
│   ├── test-all.sh                # Run all tests
│   └── deploy-billy-docker.sh      # Deploy BILLY with Docker
│
├── docs/                           # 📚 DOCUMENTATION
│   └── internal/
│       └── billy-deployment.md      # BILLY deployment guide
│
├── .env.example                    # Environment template
├── .gitignore                      # Git exclusions
├── README.md                       # Main project documentation
└── STRUCTURE.md                    # This file
```

---

## What Gets Distributed to Customers

### ✅ Distributed to External Customers (PyPI Package)

- `finout-mcp-server/src/` - Source code
- `finout-mcp-server/tests/` - Tests
- `finout-mcp-server/README.md` - Documentation
- `finout-mcp-server/LICENSE` - License
- `finout-mcp-server/pyproject.toml` - Package metadata

### 🏢 Deployed Internally (Within Organization)

- `tools/billy/` - Web diagnostic tool (Docker/Kubernetes)
- `deployments/` - Docker and Kubernetes configurations
- `scripts/build-billy.sh` - Build BILLY container
- `scripts/deploy-billy-k8s.sh` - Deploy to Kubernetes

### ❌ Never Distributed

- `.env` files - Secrets
- `docs/internal/` - Internal development docs
- Development artifacts

---

## Key Files

### Root Level

| File | Purpose |
|------|---------|
| `README.md` | Main project documentation, quick start guide |
| `.env.example` | Template for environment variables |
| `.gitignore` | Git exclusions (secrets, build artifacts, etc.) |
| `STRUCTURE.md` | This file - explains repository organization |

### MCP Server (finout-mcp-server/)

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package metadata for PyPI distribution |
| `README.md` | Customer-facing documentation |
| `LICENSE` | MIT License |
| `.env` | Environment variables (gitignored) |
| `src/finout_mcp_server/server.py` | Main MCP server implementation |

### BILLY (tools/billy/)

| File | Purpose |
|------|---------|
| `billy_server.py` | FastAPI backend server |
| `index.html` | Web UI (single-page app) |
| `requirements.txt` | Python dependencies |
| `README.md` | BILLY-specific documentation |
| `.env` | BILLY configuration (gitignored) |

---

## Environment Configuration

### Single .env File

The repository uses a single `.env` file at the root for consistency:

```bash
# Required for MCP Server
FINOUT_CLIENT_ID=...
FINOUT_SECRET_KEY=...
FINOUT_API_URL=...
FINOUT_ACCOUNT_ID=...

# Required for BILLY only
ANTHROPIC_API_KEY=...
```

Both the MCP server and BILLY read from this file.

---

## Development Workflow

### 1. Initial Setup

```bash
# Clone repository
git clone <repo-url>
cd finout-mcp

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### 2. Testing MCP Server

```bash
# Option A: Test with Claude Desktop
# Configure claude_desktop_config.json and restart Claude

# Option B: Test with BILLY
./scripts/start-billy.sh
# Open http://localhost:8000
```

### 3. Making Changes

```bash
# Edit MCP server code in finout-mcp-server/src/

# Test immediately with BILLY (auto-reloads)
./scripts/start-billy.sh

# Run tests
./scripts/test-all.sh

# Build package
./scripts/build-mcp.sh
```

### 4. Deploying BILLY

```bash
# Local deployment
./scripts/start-billy.sh

# Docker deployment
./scripts/deploy-billy-docker.sh
```

---

## Git Workflow

### What to Commit

✅ **Always commit:**
- Source code changes
- Documentation updates
- Test files
- Package configuration (`pyproject.toml`, `requirements.txt`)
- Scripts

❌ **Never commit:**
- `.env` files (secrets!)
- Virtual environments (`.venv/`)
- Build artifacts (`dist/`, `build/`)
- Cache files (`__pycache__/`, `.pytest_cache/`)
- IDE settings (`.vscode/`, `.idea/`)

### Branching Strategy

```bash
main                    # Production-ready code
├── develop             # Integration branch
├── feature/xyz         # New features
├── fix/abc             # Bug fixes
└── release/v1.0.0      # Release preparation
```

---

## Publishing MCP Server

### 1. Build Package

```bash
./scripts/build-mcp.sh
# Creates dist/*.whl and dist/*.tar.gz
```

### 2. Test Locally

```bash
pip install dist/finout_mcp_server-*.whl
# Test installation
```

### 3. Publish to PyPI

```bash
cd finout-mcp-server
uv publish
```

### 4. Customers Install

```bash
pip install finout-mcp-server
```

---

## Common Tasks

### Start BILLY for Testing

```bash
./scripts/start-billy.sh
```

### Build MCP Package

```bash
./scripts/build-mcp.sh
```

### Run All Tests

```bash
./scripts/test-all.sh
```

### Deploy BILLY Internally

```bash
# Local (development)
./scripts/start-billy.sh

# Docker Compose (single server)
./scripts/deploy-billy-docker.sh

# Kubernetes (production)
./scripts/build-billy.sh v1.0.0      # Build and push image
./scripts/deploy-billy-k8s.sh         # Deploy to cluster

# See full guide
cat deployments/kubernetes/README.md
```

### Update MCP Server in Claude Desktop

```bash
# After making changes to MCP server
# Restart Claude Desktop - it will use the updated code
```

---

## FAQs

**Q: Why is BILLY in tools/ and not in a top-level directory?**
A: BILLY is an internal diagnostic tool, not part of the product. Placing it in `tools/` makes it clear it's not distributed to customers.

**Q: Can I delete tools/billy/ before publishing?**
A: No need! The MCP server package (`finout-mcp-server/`) is published independently. `tools/` is never included in the package.

**Q: Where should I add new internal tools?**
A: Create a new directory under `tools/` (e.g., `tools/cost-simulator/`).

**Q: Where should customer-facing documentation go?**
A: In `finout-mcp-server/README.md` and related files within that directory.

**Q: How do I add a new deployment target?**
A: Add configuration files to `deployments/` (e.g., `deployments/kubernetes/`).

**Q: Should I commit .env files?**
A: **NEVER!** They contain secrets. Use `.env.example` as a template.

---

## Design Principles

1. **Clear Product Separation**: Main product (`finout-mcp-server/`) is distinct from internal tools
2. **Single Source of Truth**: One `.env.example` at root
3. **Convenience Scripts**: Common tasks automated in `scripts/`
4. **Documentation Co-location**: Docs live with the code they describe
5. **Customer-First**: Customer-facing docs separate from internal docs

---

## Next Steps

1. ✅ Repository is structured and ready for git
2. 📝 Review `.gitignore` to ensure no secrets are committed
3. 🔍 Test the setup:
   - `./scripts/start-billy.sh`
   - `./scripts/build-mcp.sh`
   - `./scripts/test-all.sh`
4. 🚀 Commit and push:
   ```bash
   git add .
   git commit -m "Initial commit: Restructure as monorepo"
   git push origin main
   ```

---

**Questions?** Check the root `README.md` or open an issue!
