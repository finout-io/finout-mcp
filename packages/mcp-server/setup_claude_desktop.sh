#!/bin/bash
# Setup script for Claude Desktop integration

set -e

echo "🔧 Finout MCP Server - Claude Desktop Setup"
echo "============================================"
echo ""

# Get current directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    CONFIG_DIR="$HOME/Library/Application Support/Claude"
    OS_NAME="macOS"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    CONFIG_DIR="$APPDATA/Claude"
    OS_NAME="Windows"
else
    echo "❌ Unsupported OS: $OSTYPE"
    exit 1
fi

CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

echo "Detected OS: $OS_NAME"
echo "Config file: $CONFIG_FILE"
echo ""

# Check if .env exists
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "❌ .env file not found!"
    echo ""
    echo "Please create .env file with your Finout credentials:"
    echo "  cp .env.example .env"
    echo "  # Edit .env and add your FINOUT_CLIENT_ID and FINOUT_SECRET_KEY"
    exit 1
fi

# Load credentials from .env
source "$SCRIPT_DIR/.env"

if [ -z "$FINOUT_CLIENT_ID" ] || [ -z "$FINOUT_SECRET_KEY" ]; then
    echo "❌ Missing credentials in .env file!"
    echo ""
    echo "Make sure .env contains:"
    echo "  FINOUT_CLIENT_ID=your_client_id"
    echo "  FINOUT_SECRET_KEY=your_secret_key"
    exit 1
fi

echo "✓ Credentials loaded from .env"
echo ""

# Create config directory if it doesn't exist
mkdir -p "$CONFIG_DIR"

# Check if config file exists
if [ -f "$CONFIG_FILE" ]; then
    echo "⚠️  Config file already exists"
    echo ""
    echo "Current config:"
    cat "$CONFIG_FILE"
    echo ""
    read -p "Do you want to overwrite it? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Please manually edit: $CONFIG_FILE"
        exit 0
    fi
    # Backup existing config
    cp "$CONFIG_FILE" "$CONFIG_FILE.backup.$(date +%s)"
    echo "✓ Backed up existing config"
fi

# Create config
cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "finout": {
      "command": "uv",
      "args": [
        "--directory",
        "$SCRIPT_DIR",
        "run",
        "finout-mcp"
      ],
      "env": {
        "FINOUT_CLIENT_ID": "$FINOUT_CLIENT_ID",
        "FINOUT_SECRET_KEY": "$FINOUT_SECRET_KEY"
      }
    }
  }
}
EOF

echo ""
echo "✅ Configuration written to: $CONFIG_FILE"
echo ""
echo "📋 Configuration contents:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat "$CONFIG_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if Claude Desktop is installed
echo "🔍 Checking for Claude Desktop installation..."
if [[ "$OS_NAME" == "macOS" ]]; then
    if [ -d "/Applications/Claude.app" ]; then
        echo "✓ Claude Desktop found"
        echo ""
        echo "📱 Next steps:"
        echo "  1. Quit Claude Desktop if it's running"
        echo "  2. Open Claude Desktop"
        echo "  3. Look for the 🔨 hammer icon in the bottom-right"
        echo "  4. Click it to see the Finout tools"
        echo ""
        read -p "Would you like to restart Claude Desktop now? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Restarting Claude Desktop..."
            killall Claude 2>/dev/null || true
            sleep 1
            open -a Claude
            echo "✓ Claude Desktop restarted"
        fi
    else
        echo "⚠️  Claude Desktop not found at /Applications/Claude.app"
        echo ""
        echo "Please download it from: https://claude.ai/download"
    fi
else
    echo "Please restart Claude Desktop manually"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "🧪 Test queries to try in Claude Desktop:"
echo "  - What was my cloud spend over the last 7 days?"
echo "  - Show me idle resources that could save $100+/month"
echo "  - List all my Finout cost views"
echo "  - Compare this week's costs to last week"
echo ""
