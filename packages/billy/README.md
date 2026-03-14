# BILLY - Ask the Smart AI of Finout

**⚠️ Internal Diagnostic Tool** - Not distributed to customers

Web-based chat interface for testing the Finout MCP Server with multi-account support and advanced features.

## Features

- 💬 **Clean Chat Interface** - Simple, intuitive web UI
- 🤖 **Multi-Model Support** - Switch between Haiku 4.5, Sonnet 4.6, and Opus 4.6
- 🏢 **Multi-Account** - Instant account switching (159+ accounts supported)
- 🔧 **Full MCP Integration** - Uses the same MCP server as Claude Desktop
- ⚡ **Real-Time Progress** - See what the model is doing with phase tracking
- 📊 **Performance Metrics** - Track response times and tool usage
- 📋 **Diagnostic Export** - Copy full conversations for debugging
- 🚀 **Easy Deployment** - Docker & Docker Compose support

## Quick Start

> **Note**: Use the convenience scripts from the repository root for easier setup!

### Option 1: Using Script (Recommended)

```bash
# From repository root
./scripts/start-billy.sh
```

### Option 2: Direct Run (Development)

```bash
# From this directory (tools/billy/)
pip install -r requirements.txt

# Configure environment (use root .env)
# Edit ../../.env with your credentials

# Start the server
python billy_server.py
```

Navigate to: http://localhost:8000

### Option 3: Docker Compose

```bash
# From repository root
./scripts/deploy-billy-docker.sh

# Or manually:
docker-compose -f deployments/docker/docker-compose.yml up -d

# View logs
docker-compose -f deployments/docker/docker-compose.yml logs -f

# Stop
docker-compose -f deployments/docker/docker-compose.yml down
```

Navigate to: http://localhost:8000

### Option 4: Docker (Manual)

```bash
# Build from repository root
cd /path/to/finout-mcp
docker build -f deployments/docker/Dockerfile.billy -t billy:latest .

# Run with environment file
docker run -d \
  --name billy \
  -p 8000:8000 \
  --env-file .env \
  billy:latest

# View logs
docker logs -f billy
```

## Configuration

### Required Environment Variables

Create a `.env` file in the `billy/` directory:

```bash
# Anthropic API Key (get from: https://console.anthropic.com/)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Finout Credentials
FINOUT_CLIENT_ID=your_finout_client_id
FINOUT_SECRET_KEY=your_finout_secret_key

# Finout Internal API URL
FINOUT_API_URL=http://finout-app.prod-mirror.internal.finout.io

# Default Account ID (can be switched in UI)
FINOUT_ACCOUNT_ID=your_default_account_id
```

See `.env.example` for a template.

## Features Deep Dive

### 🤖 Multi-Model Support

Switch between three Claude models on the fly:

- **Haiku 4.5** (⚡) - Fast & cost-effective for simple queries
- **Sonnet 4.6** (🤖) - Balanced performance (default)
- **Opus 4.6** (👑) - Most capable for complex analysis

Each model has a unique avatar in the chat. No need to restart - just select and go!

### 🏢 Multi-Account Management

- **159+ Accounts** - Searchable dropdown with instant filtering
- **No Restart** - Switch accounts instantly, mid-conversation
- **Account Caching** - 5-minute cache for fast loading
- **Persistent Selection** - Account stays selected across queries

### ⚡ Real-Time Progress

Enhanced loading animation shows:
- **Phase tracking**: "Thinking...", "Using tools...", "Waiting for data..."
- **Live timer**: Real-time elapsed time (updates every 0.1s)
- **Model indicator**: See which model is processing

### 📊 Performance Metrics

After each response, see:
- **Model used** (e.g., "Sonnet 4.6")
- **Tool count** (e.g., "3 tools")
- **Total duration** (e.g., "8.7s")

Helps you understand cost vs. performance tradeoffs.

### 📋 Diagnostic Export

Click "📋 Export Chat" to copy the entire conversation including:
- All user messages
- All assistant responses
- All tool calls with inputs/outputs
- Timestamps and account info

Perfect for debugging or sharing with the team.

## Architecture

```
User Browser
    ↓
BILLY Web UI (index.html)
    ↓
FastAPI Backend (billy_server.py)
    ↓  ↓  ↓
    ↓  ↓  └─→ Finout Internal API (account list)
    ↓  └────→ MCP Server (stdio subprocess)
    ↓           ↓
    ↓           └─→ Finout API (cost data, filters)
    └─────────→ Claude API (Anthropic)
```

## How It Works

1. **User sends message** via web UI with selected model & account
2. **Backend receives** message, model, and account ID
3. **Calls Claude API** with selected model and available MCP tools
4. **Claude decides** which tools to use
5. **Backend injects** account ID into tool calls
6. **MCP server executes** tools against specified account
7. **Claude processes** results and generates response
8. **Backend returns** final answer with timing metrics
9. **UI displays** response with model avatar and performance stats

## Production Deployment

### Docker Compose (Recommended)

```bash
# 1. Clone repository
git clone <repo-url>
cd finout-mcp/billy

# 2. Configure environment
cp .env.example .env
nano .env  # Add production credentials

# 3. Deploy
docker-compose up -d

# 4. Verify health
curl http://localhost:8000/api/health
```

### Cloud Platforms

#### AWS ECS/Fargate

```bash
# Build and push
docker build -f billy/Dockerfile -t billy:latest .
docker tag billy:latest <ecr-repo>/billy:latest
docker push <ecr-repo>/billy:latest

# Deploy via ECS console or Terraform
# Set environment variables in task definition
```

#### Google Cloud Run

```bash
# Build and push
gcloud builds submit --tag gcr.io/<project>/billy

# Deploy
gcloud run deploy billy \
  --image gcr.io/<project>/billy \
  --platform managed \
  --region us-central1 \
  --set-env-vars ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY,FINOUT_CLIENT_ID=$FINOUT_CLIENT_ID
```

#### Railway / Render

1. Connect your GitHub repository
2. Select `billy/Dockerfile` as build target
3. Add environment variables in dashboard
4. Deploy!

### Health Checks

The application exposes a health endpoint:

```bash
GET /api/health

Response:
{
  "status": "healthy",
  "mcp_running": true
}
```

Use this for:
- Load balancer health checks
- Container orchestration probes
- Monitoring alerts

### Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name billy.yourcompany.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

## Development

### Project Structure

```
billy/
├── billy_server.py          # FastAPI backend + MCP bridge
├── index.html              # Web UI (chat interface)
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container image definition
├── docker-compose.yml     # Orchestration config
├── .dockerignore          # Docker build exclusions
├── .env.example           # Environment template
├── start.sh               # Startup script
└── README.md              # This file
```

### Adding New MCP Tools

The MCP server is at: `../finout-mcp-server/`

To add new tools:
1. Add tool definition to `finout-mcp-server/src/finout_mcp_server/server.py`
2. Restart BILLY server (or MCP subprocess will auto-restart)
3. New tool automatically available in web UI

No changes needed to BILLY code!

### Local Development

```bash
# Install in development mode
pip install -r requirements.txt

# Run with auto-reload
uvicorn billy_server:app --reload --host 0.0.0.0 --port 8000

# Test MCP server separately
cd ../finout-mcp-server
uv run finout-mcp
```

## Security Considerations

⚠️ **For Internal Use Only**

Before external deployment:

- [ ] Add authentication (OAuth, SSO, or basic auth)
- [ ] Enable HTTPS (Let's Encrypt, Cloudflare, or ALB)
- [ ] Implement rate limiting (per user/IP)
- [ ] Secure environment variables (AWS Secrets Manager, etc.)
- [ ] Add CORS restrictions (remove `allow_origins=["*"]`)
- [ ] Enable audit logging
- [ ] Add user session management
- [ ] Consider API key rotation

**Current State**: Designed for internal network use where access is already controlled.

## Monitoring

### Application Logs

```bash
# Docker Compose
docker-compose logs -f billy

# Docker
docker logs -f billy

# Direct run
# Logs printed to stdout
```

### Key Metrics to Monitor

- **Response times** (shown in UI timing summary)
- **Tool call counts** (shown in UI)
- **Model usage distribution** (track via logs)
- **Account switch frequency** (track via logs)
- **Error rates** (500 responses)
- **MCP server health** (subprocess crashes)

## Troubleshooting

### MCP Server Won't Start

```bash
# Check MCP server independently
cd ../finout-mcp-server
uv run finout-mcp

# Verify credentials
cat .env | grep FINOUT
```

### Claude API Errors

```bash
# Verify API key
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-3-haiku-20240307","max_tokens":1024,"messages":[{"role":"user","content":"test"}]}'

# Check rate limits at: https://console.anthropic.com/
```

### Account Loading Issues

```bash
# Test internal API access
curl -H "authorized-user-roles: sysAdmin" \
  "$FINOUT_API_URL/account-service/account?isActive=true"

# Check network access to internal API
ping finout-app.prod-mirror.internal.finout.io
```

### Docker Build Fails

```bash
# Clean build
docker-compose down -v
docker-compose build --no-cache
docker-compose up

# Check context
docker build -f billy/Dockerfile -t billy:test . --progress=plain
```

### Performance Issues

- **Slow account loading**: Check network latency to internal API
- **Slow responses**: Try faster model (Haiku vs Opus)
- **High tool latency**: Check Finout API response times
- **Memory issues**: Increase container memory limits

## API Reference

### POST /api/chat

Send a chat message and get response.

**Request:**
```json
{
  "message": "What were my AWS costs last month?",
  "conversation_history": [],
  "account_id": "account-123",
  "model": "claude-sonnet-4-6"
}
```

**Response:**
```json
{
  "response": "Your AWS costs last month were...",
  "tool_calls": [
    {
      "name": "query_costs",
      "input": {...},
      "output": "..."
    }
  ],
  "conversation_history": [...]
}
```

### GET /api/accounts

Get list of available Finout accounts.

**Response:**
```json
{
  "accounts": [
    {"name": "Production", "accountId": "abc123"},
    {"name": "Staging", "accountId": "def456"}
  ],
  "current_account_id": "abc123",
  "cached": true
}
```

### GET /api/health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "mcp_running": true
}
```

## License

Same as Finout MCP Server

## Support

For issues or questions:
1. Check this README
2. Check `QUICKSTART.md` for setup help
3. Check `MULTI_ACCOUNT.md` for account switching details
4. Open an issue in the repository
