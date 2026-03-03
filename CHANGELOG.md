# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added - Repository Restructuring (2026-02-12)

**Monorepo Structure**
- Created proper monorepo structure separating product from internal tools
- Added `tools/` directory for internal diagnostic tools
- Added `deployments/` directory for deployment configurations
- Added `scripts/` directory for utility scripts
- Added `docs/` directory for documentation

**Documentation**
- Created comprehensive root `README.md` with project overview
- Created `STRUCTURE.md` explaining repository organization
- Created `.env.example` with all required environment variables
- Updated BILLY documentation to reflect new structure
- Moved deployment documentation to `docs/internal/`

**Scripts**
- `scripts/start-billy.sh` - Start BILLY diagnostic tool locally
- `scripts/build-mcp.sh` - Build MCP server package for distribution
- `scripts/build-billy.sh` - Build BILLY Docker image for internal deployment
- `scripts/deploy-billy-docker.sh` - Deploy BILLY using Docker Compose
- `scripts/deploy-billy-k8s.sh` - Deploy BILLY to Kubernetes cluster
- `scripts/test-all.sh` - Run all tests across the repository

**Infrastructure**
- Created `.gitignore` with comprehensive exclusions
- Updated Docker configurations for new structure
- Updated `docker-compose.yml` with correct paths
- Updated `Dockerfile.billy` to reference new locations

**Kubernetes Deployment (Internal)**
- Created Kubernetes manifests for BILLY deployment
  - `deployments/kubernetes/billy-deployment.yaml` - Deployment with 2 replicas
  - `deployments/kubernetes/billy-service.yaml` - ClusterIP service
  - `deployments/kubernetes/billy-ingress.yaml` - Ingress with TLS support
  - `deployments/kubernetes/billy-configmap.yaml` - Configuration
  - `deployments/kubernetes/billy-secret.yaml.example` - Secret template
  - `deployments/kubernetes/namespace.yaml` - Namespace definition
  - `deployments/kubernetes/kustomization.yaml` - Kustomize configuration
- Created comprehensive Kubernetes deployment guide
  - Health checks (liveness and readiness probes)
  - Resource limits and requests
  - Auto-scaling configuration examples
  - Security best practices
  - Monitoring and troubleshooting guides

**Code Changes**
- Updated `billy_server.py` to load `.env` from repository root
- Updated `billy_server.py` to reference MCP server at `../../finout-mcp-server`
- Updated BILLY README with new paths and script usage

### Changed

**Directory Structure**
- Moved `billy/` → `tools/billy/` (internal tool)
- Moved `billy/Dockerfile` → `deployments/docker/Dockerfile.billy`
- Moved `billy/docker-compose.yml` → `deployments/docker/docker-compose.yml`
- Moved `billy/DEPLOYMENT.md` → `docs/internal/billy-deployment.md`
- Kept `finout-mcp-server/` at root (main product)

**Configuration**
- Consolidated environment variables to root `.env.example`
- Updated Docker Compose to reference root directory
- Updated Dockerfile paths for new structure

### Fixed

**MCP Server**
- Fixed filter type enums to allow all API types (not just col/tag/resource)
- Updated filter type to accept `namespace_object` for Kubernetes resources
- Added comprehensive examples showing correct type usage
- Updated `get_filter_values` to support all filter types
- Added guidance for searching values with substrings

**BILLY**
- Fixed export conversation button (added event parameter)
- Moved account selector to sidebar bottom
- Added model selector with Haiku 4.5, Sonnet 4.5, Opus 4.6
- Added dynamic avatars based on selected model
- Added real-time progress tracking with phase indicators
- Added performance metrics (model, tool count, duration)

---

## [0.1.0] - Initial Development

### MCP Server Features
- Multi-cloud cost querying (AWS, GCP, Azure, Kubernetes)
- 150+ cost filters with smart caching
- Natural language cost analysis
- Anomaly detection integration
- Waste recommendations
- Time-based cost comparisons
- Filter search and discovery

### BILLY Features
- Web-based chat interface
- MCP server integration via subprocess
- Tool call tracking and display
- Conversation history management
- Multi-account support with instant switching
- Account search and filtering (159+ accounts)
- Diagnostic conversation export

---

## Release Process

To create a new release:

1. Update version in `finout-mcp-server/pyproject.toml`
2. Update this CHANGELOG with release date
3. Create git tag: `git tag -a v0.1.0 -m "Release v0.1.0"`
4. Build package: `./scripts/build-mcp.sh`
5. Publish: `cd finout-mcp-server && uv publish`

---

## Versioning

- **Major version** (X.0.0): Breaking changes to MCP server API
- **Minor version** (0.X.0): New features, backwards compatible
- **Patch version** (0.0.X): Bug fixes, no new features

Internal tools (BILLY) are not versioned separately - they track the monorepo version.

---

[Unreleased]: https://github.com/finout/finout-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/finout/finout-mcp/releases/tag/v0.1.0
