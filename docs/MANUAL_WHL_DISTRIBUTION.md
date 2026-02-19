# Manual Wheel Distribution (No PyPI)

Use this when you want to distribute MCP builds internally before publishing.

## Build Wheels

From repo root:

```bash
./scripts/build_mcp_distributions.sh
```

Artifacts:

- Public wheel: `dist/mcp-server/*.whl`
- Internal wheel: `dist/vectiqor-mcp-internal/*.whl`

## What to Share

### Public users

Share only:

- `finout_mcp_server-<version>-py3-none-any.whl`

### Internal VECTIQOR users

Share both:

- `finout_mcp_server-<version>-py3-none-any.whl`
- `vectiqor_mcp_internal-<version>-py3-none-any.whl`

`vectiqor-mcp-internal` depends on `finout-mcp-server`, so both wheels are required in a clean environment.

## Install (Public MCP)

```bash
python3 -m venv /tmp/finout-mcp-test
source /tmp/finout-mcp-test/bin/activate
pip install /path/to/finout_mcp_server-*.whl
finout-mcp --help
```

Claude Desktop config:

```json
{
  "mcpServers": {
    "finout": {
      "command": "finout-mcp",
      "args": [],
      "env": {
        "FINOUT_CLIENT_ID": "YOUR_CLIENT_ID",
        "FINOUT_SECRET_KEY": "YOUR_SECRET_KEY"
      }
    }
  }
}
```

## Install (Internal MCP)

```bash
python3 -m venv /tmp/internal-mcp-test
source /tmp/internal-mcp-test/bin/activate
pip install /path/to/finout_mcp_server-*.whl /path/to/vectiqor_mcp_internal-*.whl
vectiqor-mcp-internal --help
```

## Upgrade

```bash
pip install --upgrade /path/to/finout_mcp_server-*.whl
```

Internal:

```bash
pip install --upgrade /path/to/finout_mcp_server-*.whl /path/to/vectiqor_mcp_internal-*.whl
```
