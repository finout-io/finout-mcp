# Finout MCP Server

Model Context Protocol server for Finout cloud cost observability. Query costs, detect anomalies, and find waste using natural language.

## Quick Start

```bash
# Install
pip install finout-mcp-server

# Configure
cat > ~/.config/claude/claude_desktop_config.json <<EOF
{
  "mcpServers": {
    "finout": {
      "command": "finout-mcp",
      "args": [],
      "env": {
        "FINOUT_API_URL": "https://app.finout.io",
        "FINOUT_CLIENT_ID": "your-client-id",
        "FINOUT_SECRET_KEY": "your-secret-key"
      }
    }
  }
}
EOF

# Restart Claude Desktop
```

## Hosted Public Service

Run MCP over Streamable HTTP (separate from VECTIQOR):

```bash
finout-mcp-hosted-public
```

Authentication for hosted requests:

- Send `x-finout-client-id` and `x-finout-secret-key` headers on MCP `POST` calls.
- Optional override: `x-finout-api-url` (defaults to `https://app.finout.io`).

Defaults:

- `MCP_HOST=0.0.0.0`
- `MCP_PORT=8080`
- MCP endpoint: `POST/GET /mcp`
- Health endpoint: `GET /health`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FINOUT_API_URL` | No | API endpoint (`https://app.finout.io` for public mode) |
| `FINOUT_CLIENT_ID` | Yes in `public` mode | API client ID |
| `FINOUT_SECRET_KEY` | Yes in `public` mode | API secret key |

Get credentials from your Finout account settings.

## Tools

**Cost Analysis:**
- `query_costs` - Query costs with filters and grouping
- `compare_costs` - Period-over-period comparison

**Filter Discovery:**
- `list_available_filters` - Browse available filters
- `search_filters` - Search filters by keyword
- `get_filter_values` - Get values for a specific filter

**Optimization:**
- `get_anomalies` - Detect cost spikes
- `get_waste_recommendations` - Find idle resources

## Example Queries

```
"What was my AWS spend last month?"
"Show me EC2 costs in us-east-1 for last week"
"Compare this month's Kubernetes costs to last month"
"Find idle resources that could save money"
"Show cost anomalies from the past 7 days"
```

## Usage Pattern

Most cost queries follow this pattern:

1. Search for relevant filters: `search_filters("service")`
2. Get filter values if needed: `get_filter_values(...)`
3. Query costs with filters: `query_costs(time_period, filters, group_by)`

Example:
```python
# Find service filter
filters = search_filters("service")

# Query EC2 costs
costs = query_costs(
    time_period="last_30_days",
    filters=[{
        "costCenter": "aws",
        "key": "service",
        "type": "tag",
        "operator": "is",
        "value": "ec2"
    }]
)
```

## Filter Structure

Filters require these fields from search results:

```python
{
    "costCenter": "aws",      # From search results
    "key": "service",          # From search results
    "type": "tag",             # From search results
    "path": "AWS/Services",    # From search results
    "operator": "is",          # "is" for single value, "oneOf" for array
    "value": "ec2"             # Your filter value
}
```

**IMPORTANT:** Always use `search_filters` first to get the exact `type` value. Don't guess.

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Start locally
uv run python -m finout_mcp_server
```

## Troubleshooting

**"Internal API URL not configured"**
- Set `FINOUT_API_URL` in your environment (optional; defaults to `https://app.finout.io`)

**"No matches found" when searching filters**
- Use broader search terms (e.g., "service" instead of "ec2")
- Try different cost centers: "aws", "gcp", "kubernetes", "virtual-tag"

**Filter values not showing up**
- Use `get_filter_values()` to fetch values on-demand
- Values are lazy-loaded to avoid overwhelming context

**Query returns no data**
- Check date range is valid
- Verify filter values exist using `get_filter_values()`
- Check operator: use "is" for single value, "oneOf" for array

## Resources

- [Finout Documentation](https://docs.finout.io)
- [MCP Protocol Spec](https://modelcontextprotocol.io)
- [Report Issues](https://github.com/finout/finout-mcp/issues)

## License

MIT
