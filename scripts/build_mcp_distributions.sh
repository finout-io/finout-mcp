#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"

echo "[1/4] Preparing output directories..."
mkdir -p "${DIST_DIR}/mcp-server" "${DIST_DIR}/vectiqor" "${DIST_DIR}/vectiqor-mcp-internal"

echo "[2/4] Ensuring build tooling is installed..."
python3 -m pip install --upgrade build hatchling >/dev/null

echo "[3/4] Building Python package distributions..."
python3 -m build "${ROOT_DIR}/packages/mcp-server" --outdir "${DIST_DIR}/mcp-server" --no-isolation
python3 -m build "${ROOT_DIR}/packages/vectiqor" --outdir "${DIST_DIR}/vectiqor" --no-isolation
python3 -m build "${ROOT_DIR}/packages/vectiqor-mcp-internal" --outdir "${DIST_DIR}/vectiqor-mcp-internal" --no-isolation

echo "[4/4] Build complete."
echo
echo "Artifacts:"
echo "  Public MCP wheel:      ${DIST_DIR}/mcp-server"
echo "  VECTIQOR wheel:        ${DIST_DIR}/vectiqor"
echo "  Internal MCP wheel:    ${DIST_DIR}/vectiqor-mcp-internal"
echo
echo "Quick smoke tests:"
echo "  Public:   python3 -m venv /tmp/public-mcp && /tmp/public-mcp/bin/pip install ${DIST_DIR}/mcp-server/*.whl && /tmp/public-mcp/bin/finout-mcp --help"
echo "  Internal: python3 -m venv /tmp/internal-mcp && /tmp/internal-mcp/bin/pip install ${DIST_DIR}/mcp-server/*.whl ${DIST_DIR}/vectiqor-mcp-internal/*.whl && /tmp/internal-mcp/bin/vectiqor-mcp-internal --help"
