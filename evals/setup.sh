#!/usr/bin/env bash
# One-time setup for promptfoo evals (Node 24 requires rebuilding better-sqlite3)
set -e

pnpm install
cd node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3
npx node-gyp rebuild
echo "Done. Run from evals/:"
echo "  PROMPTFOO_CONFIG_DIR=/tmp/promptfoo PROMPTFOO_DISABLE_WAL_MODE=true ANTHROPIC_API_KEY=... npx promptfoo eval -c promptfoo.yaml"
