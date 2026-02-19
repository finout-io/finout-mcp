# Finout MCP for Claude Desktop

This guide is for end users who want to connect Claude Desktop to Finout using the public MCP server.

## Prerequisites

- Claude Desktop installed
- Python 3.10+ available in terminal
- Finout API credentials:
  - `FINOUT_CLIENT_ID`
  - `FINOUT_SECRET_KEY`

`FINOUT_API_URL` is optional and defaults to `https://app.finout.io`.

## 1. Install the MCP package

Recommended:

```bash
python3 -m pip install --user --upgrade finout-mcp-server
```

If `finout-mcp` is not found later, add your user bin directory to `PATH`.

## 2. Configure Claude Desktop

Edit Claude Desktop config:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Use:

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

Optional API URL override:

```json
{
  "FINOUT_API_URL": "https://app.finout.io"
}
```

If you include the override, add it inside the same `env` object.

## 3. Restart Claude Desktop

Quit Claude Desktop completely and open it again.

## 4. Verify in Claude

Ask:

- `Show my cloud cost for last 7 days`
- `List available filters`
- `Find anomalies in the last 30 days`

If tools are connected, Claude will call the Finout MCP server automatically.

## Troubleshooting

`command not found: finout-mcp`

- Reinstall with `python3 -m pip install --user --upgrade finout-mcp-server`
- Ensure your user Python bin path is in `PATH`

`Unauthorized`

- Recheck `FINOUT_CLIENT_ID` and `FINOUT_SECRET_KEY`
- Confirm the credentials are active in Finout

No tools appear in Claude

- Confirm JSON is valid
- Confirm file path is correct for your OS
- Fully restart Claude Desktop
