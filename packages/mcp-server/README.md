# Finout MCP Server

Model Context Protocol server for Finout cloud cost observability. Query costs, detect anomalies, and find waste using natural language.

## Quick Start

Obtain and API Client ID and Secret Key from your Finout account.

```bash
# Install
pip install finout-mcp

# Configure
cat > ~/.config/claude/claude_desktop_config.json <<EOF
{
  "mcpServers": {
    "finout": {
      "command": "finout-mcp",
      "args": [],
      "env": {
        "FINOUT_CLIENT_ID": "your-client-id",
        "FINOUT_SECRET_KEY": "your-secret-key"
      }
    }
  }
}
EOF

# Restart Claude Desktop

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



## Resources

- [Finout Documentation](https://docs.finout.io)

## License

MIT
