# ASAF Quick Start Guide

## What is ASAF?

**ASAF** (Ask the Super AI of Finout) is a web-based chat interface for your Finout MCP Server.

- 🌐 **Web-based** - No Claude Desktop installation needed
- 🤖 **Same AI** - Uses Claude Sonnet 4.5 via Anthropic API
- 🔧 **Same Tools** - Uses your exact MCP server code
- ✅ **Test & Ship** - What works here, works in Claude Desktop

## 5-Minute Setup

### Step 1: Get Anthropic API Key

1. Go to: https://console.anthropic.com/
2. Sign up or log in
3. Navigate to "API Keys"
4. Create a new key
5. Copy it (starts with `sk-ant-`)

### Step 2: Add API Key

```bash
cd /Users/idan.bauer/projects/finout-mcp/asaf

# Edit .env file
nano .env

# Replace this line:
# ANTHROPIC_API_KEY=your_anthropic_api_key_here
# With your actual key:
# ANTHROPIC_API_KEY=sk-ant-api03-xxx...
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Start ASAF

```bash
./start.sh

# Or manually:
python asaf_server.py
```

### Step 5: Open Browser

Navigate to: **http://localhost:8000**

That's it! 🎉

## First Questions to Try

Once ASAF is running, try these:

1. **"What were my AWS costs last month?"**
   - Tests filter discovery and cost queries

2. **"Compare this week to last week"**
   - Tests the new compare_costs tool

3. **"Show me costs grouped by service"**
   - Tests grouping functionality

4. **"Compare the last 7 days of each of the last 4 months"**
   - Tests custom date ranges

## How It Works

```
You → Web Browser → ASAF Server → Claude API
                         ↓
                   MCP Server (stdio)
                         ↓
                    Finout API
```

1. You ask a question in the web UI
2. ASAF sends it to Claude API
3. Claude decides which tools to use
4. ASAF calls your MCP server (same one you built)
5. MCP server queries Finout
6. Results go back through Claude
7. You get a natural language answer

## Sharing with Your Team

### On Local Network

```bash
# Find your IP
ifconfig | grep "inet " | grep -v 127.0.0.1

# Start server
python asaf_server.py

# Share with team
# http://YOUR_IP:8000
```

### Deploy to Cloud

See `README.md` for Docker deployment instructions.

## Common Issues

### "MCP server not initialized"

**Solution:** Make sure you're running from the `asaf` directory and the MCP server can be found at `../finout-mcp-server`

```bash
# Check path
ls ../finout-mcp-server/src/finout_mcp_server/server.py

# Should see the file
```

### "ANTHROPIC_API_KEY not set"

**Solution:** Edit `.env` and add your Anthropic API key

```bash
nano .env
# Add: ANTHROPIC_API_KEY=sk-ant-...
```

### "Tool call error"

**Solution:** Check Finout credentials in `.env`

```bash
# Test MCP server directly
cd ../finout-mcp-server
uv run finout-mcp
# Should connect without errors
```

### Port 8000 already in use

**Solution:** Use a different port

```bash
python asaf_server.py
# Or specify port:
uvicorn asaf_server:app --port 8080
```

## Development Tips

### Auto-reload on code changes

```bash
uvicorn asaf_server:app --reload
```

### View logs

The server prints logs to console:
- Tool calls
- Claude responses
- Errors

### Test MCP server independently

```bash
cd ../finout-mcp-server
uv run finout-mcp

# In another terminal, test with inspector
npx @modelcontextprotocol/inspector uv run finout-mcp
```

## Next Steps

### 1. Test with Your Team

Share the URL and gather feedback on:
- Which questions work well
- Which tools need improvement
- What new features are needed

### 2. Iterate on MCP Server

Make changes to `../finout-mcp-server/src/finout_mcp_server/server.py`

Restart ASAF to see changes.

### 3. Ship to Claude Desktop

Once you're happy with the behavior, everyone can install the same MCP server in Claude Desktop:

```json
{
  "mcpServers": {
    "finout": {
      "command": "uv",
      "args": ["--directory", "/path/to/finout-mcp-server", "run", "finout-mcp"]
    }
  }
}
```

**Identical behavior guaranteed!** ✅

## Support

- Issues with ASAF: Check `README.md`
- Issues with MCP: Check `../finout-mcp-server/README.md`
- Issues with Finout API: Contact Finout support

## Architecture Benefits

✅ **Single Source of Truth** - One MCP server codebase
✅ **Rapid Testing** - Everyone tests same version
✅ **No Installation Required** - Just share URL
✅ **Production Preview** - Exact behavior before rollout
✅ **Easy Updates** - Change once, affects all users

---

**Enjoy ASAF!** 🤖✨
