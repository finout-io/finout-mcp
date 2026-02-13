# Finout MCP Server - Quick Start Guide

Get up and running with the Finout MCP Server in 5 minutes.

## Prerequisites

- Python 3.11+
- Finout account with API credentials
- `uv` installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Step 1: Install Dependencies

```bash
cd finout-mcp-server
uv sync
```

## Step 2: Configure Credentials

Create a `.env` file with your Finout API credentials:

```bash
cp .env.example .env
```

Edit `.env`:
```env
FINOUT_CLIENT_ID=your_actual_client_id
FINOUT_SECRET_KEY=your_actual_secret_key
```

**Get credentials from Finout:**
1. Log into https://app.finout.io
2. Navigate to Settings → API Keys
3. Create a new API key or copy existing one

## Step 3: Test the Server

### Quick verification (no credentials needed):

```bash
uv run python test_inspector.py
```

This verifies everything loads correctly.

### Test with MCP Inspector:

**Without credentials (explore only):**
```bash
npx @modelcontextprotocol/inspector uv run finout-mcp
```

**With credentials (full functionality):**

Since you created `.env` in Step 2, the server will automatically load it!

```bash
npx @modelcontextprotocol/inspector uv run finout-mcp
```

This opens a web UI at http://localhost:5173 where you can:
- See all 6 tools available (✓ even without credentials)
- View tool schemas and descriptions (✓ even without credentials)
- Test `get_cost_summary` with `time_period: "last_30_days"` (requires credentials)
- Test `get_anomalies` with `time_period: "last_7_days"` (requires credentials)
- View resources and prompts (✓ even without credentials)

## Step 4: Connect to Claude Desktop

### macOS

Edit: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "finout": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/YOUR_USERNAME/path/to/finout-mcp-server",
        "run",
        "finout-mcp"
      ],
      "env": {
        "FINOUT_CLIENT_ID": "your_client_id",
        "FINOUT_SECRET_KEY": "your_secret_key"
      }
    }
  }
}
```

### Windows

Edit: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "finout": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\finout-mcp-server",
        "run",
        "finout-mcp"
      ],
      "env": {
        "FINOUT_CLIENT_ID": "your_client_id",
        "FINOUT_SECRET_KEY": "your_secret_key"
      }
    }
  }
}
```

**Restart Claude Desktop** after saving the config.

## Step 5: Try It Out!

In Claude Desktop, try these questions:

### Cost Analysis
- "What was my cloud spend last month?"
- "Show me my AWS costs for the last 30 days grouped by service"
- "Compare this month's costs to last month"

### Anomaly Detection
- "Were there any cost anomalies this week?"
- "Show me cost spikes from the last 7 days"

### Optimization
- "What idle resources can I shut down to save money?"
- "Find EC2 instances that could save more than $100/month"
- "Show me all cost optimization recommendations"

### Advanced Queries
- "Give me a monthly cost review" (uses the monthly_cost_review prompt)
- "Find waste and calculate annual savings potential" (uses find_waste prompt)

## Verification

If everything is working, you should see:

1. ✅ A hammer icon (🔨) next to Finout in Claude's tool list
2. ✅ Claude can answer cost questions using your actual Finout data
3. ✅ Responses include specific dollar amounts and service names from your account

## Troubleshooting

### Tools not showing in Claude

**Check logs:**
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp*.log

# Windows
type %APPDATA%\Claude\Logs\mcp*.log
```

**Common issues:**
- Path in config must be absolute (not relative)
- JSON syntax error (missing comma, quote, etc.)
- Credentials not set or invalid

### Test credentials directly

```bash
export FINOUT_CLIENT_ID=your_id
export FINOUT_SECRET_KEY=your_key

uv run python -c "
from finout_mcp_server.finout_client import FinoutClient
import asyncio

async def test():
    async with FinoutClient() as client:
        views = await client.get_views()
        print(f'✅ Connected! Found {len(views)} views')
        for v in views[:3]:
            print(f'  - {v[\"name\"]}')

asyncio.run(test())
"
```

If this works, your credentials are valid and the issue is with MCP configuration.

### Server crashes on startup

**Check Python version:**
```bash
python --version  # Should be 3.11+
```

**Reinstall dependencies:**
```bash
uv sync --reinstall
```

## Next Steps

- Read the full [README.md](README.md) for architecture details
- Explore all tools in MCP Inspector
- Try the built-in prompts (monthly_cost_review, find_waste, investigate_spike)
- Customize queries with different time periods and groupings

## Example Conversation

```
You: What was my AWS spend last month?

Claude: Let me check your AWS costs for last month.
[Uses get_cost_summary tool with time_period="last_month"]

Your AWS spend for last month was $45,231.50. Here's the breakdown by service:

1. EC2: $28,450.20 (62.9%)
2. RDS: $8,920.15 (19.7%)
3. S3: $4,215.80 (9.3%)
4. CloudWatch: $2,102.35 (4.6%)
5. Other (12 services): $1,543.00 (3.4%)

Would you like to compare this to the previous month or investigate any specific service?

You: Are there any cost anomalies?

Claude: Let me check for recent anomalies.
[Uses get_anomalies tool with time_period="last_7_days"]

Yes, I found 2 cost anomalies in the last 7 days:

1. **RDS - High Severity** (Dec 28)
   - Expected: $287/day
   - Actual: $1,420/day
   - Impact: +$1,133 unexpected cost

2. **Lambda - Medium Severity** (Dec 26)
   - Expected: $45/day
   - Actual: $180/day
   - Impact: +$135 unexpected cost

The RDS spike is significant. Would you like me to investigate what changed?
```

## Support

- GitHub Issues: [Your repo URL]
- Finout Support: support@finout.io
- MCP Documentation: https://modelcontextprotocol.io
