#!/usr/bin/env python3
"""
ASAF - Ask the Super AI of Finout
Web server that provides chat interface to Finout MCP Server
"""
import asyncio
import json
import os
import subprocess
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from pathlib import Path
from .db import db

# Load .env from package directory
package_root = Path(__file__).parent.parent.parent
load_dotenv(package_root / ".env")

# Repository root for finding MCP server
repo_root = package_root.parent.parent

# Models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: List[ChatMessage] = []
    model: Optional[str] = "claude-sonnet-4-5-20250929"  # Model to use for this request

class MCPBridge:
    """Bridge between HTTP API and MCP Server (stdio)"""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.request_id = 0
        self._lock = asyncio.Lock()
        self.current_account_id: Optional[str] = None

    async def start(self, account_id: Optional[str] = None):
        """Start the MCP server as subprocess with specific account ID"""
        # Use provided account_id or fall back to environment variable
        if account_id:
            self.current_account_id = account_id
        else:
            self.current_account_id = os.getenv("FINOUT_ACCOUNT_ID")

        print(f"Starting MCP server for account: {self.current_account_id}...")

        # Prepare environment with account ID
        env = os.environ.copy()
        if self.current_account_id:
            env["FINOUT_ACCOUNT_ID"] = self.current_account_id

        # Start MCP server - use repo_root to find packages/mcp-server
        mcp_server_path = repo_root / "packages" / "mcp-server"

        self.process = subprocess.Popen(
            ["uv", "run", "finout-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # Let stderr go to parent (visible in logs)
            cwd=str(mcp_server_path),
            env=env,
            text=True,
            bufsize=1
        )

        print(f"MCP server started with PID {self.process.pid}")

        # Initialize the MCP connection
        await self._send_initialize()

    async def restart_with_account(self, account_id: str):
        """Restart MCP server with a different account ID"""
        print(f"Switching to account: {account_id}")

        # Stop current server
        await self.stop()

        # Start with new account
        await self.start(account_id)

    async def _send_initialize(self):
        """Send initialize request to MCP server"""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "asaf",
                    "version": "1.0.0"
                }
            }
        }

        response = await self._send_request(request)
        print(f"MCP initialized: {response}")

    def _next_id(self) -> int:
        """Generate next request ID"""
        self.request_id += 1
        return self.request_id

    async def _send_request(self, request: dict) -> dict:
        """Send JSON-RPC request and get response"""
        async with self._lock:
            if not self.process or self.process.poll() is not None:
                raise Exception("MCP server is not running")

            # Send request
            request_str = json.dumps(request) + "\n"
            self.process.stdin.write(request_str)
            self.process.stdin.flush()

            # Read response
            response_str = self.process.stdout.readline()
            if not response_str:
                raise Exception("MCP server closed connection")

            return json.loads(response_str)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools from MCP server"""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {}
        }

        response = await self._send_request(request)

        if "error" in response:
            raise Exception(f"MCP error: {response['error']}")

        return response.get("result", {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool on the MCP server"""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }

        response = await self._send_request(request)

        if "error" in response:
            raise Exception(f"Tool call error: {response['error']}")

        # Extract content from response
        result = response.get("result", {})
        content = result.get("content", [])

        if content and len(content) > 0:
            return content[0].get("text", "")

        return str(result)

    async def stop(self):
        """Stop the MCP server"""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            print("MCP server stopped")

# Global MCP bridge
mcp_bridge: Optional[MCPBridge] = None

# Global account cache
_account_cache: Optional[Dict[str, Any]] = None
_account_cache_time: Optional[datetime] = None
_account_cache_ttl = timedelta(hours=3)  # Cache for 3 hours

# Last selected account persistence
_last_account_file = package_root / ".last_account"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage MCP server and database lifecycle"""
    global mcp_bridge

    # Startup - create bridge but don't start MCP yet
    # MCP will be started when user selects an account
    mcp_bridge = MCPBridge()

    # Initialize database connection
    await db.connect()
    print("Database connected")

    yield

    # Shutdown
    if mcp_bridge:
        await mcp_bridge.stop()

    # Close database connection
    await db.disconnect()
    print("Database disconnected")

# Create FastAPI app
app = FastAPI(title="ASAF - Ask the Super AI of Finout", lifespan=lifespan)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Anthropic client
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def save_last_account(account_id: str) -> None:
    """Save the last selected account ID to file"""
    try:
        _last_account_file.write_text(account_id)
    except Exception as e:
        print(f"Warning: Could not save last account: {e}")

def load_last_account() -> Optional[str]:
    """Load the last selected account ID from file"""
    try:
        if _last_account_file.exists():
            return _last_account_file.read_text().strip()
    except Exception as e:
        print(f"Warning: Could not load last account: {e}")
    return None

def convert_mcp_tools_to_claude_format(mcp_tools: List[Dict]) -> List[Dict]:
    """Convert MCP tool definitions to Claude API format"""
    claude_tools = []

    for tool in mcp_tools:
        claude_tool = {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["inputSchema"]
        }
        claude_tools.append(claude_tool)

    return claude_tools

@app.get("/")
async def root():
    """Serve the web UI"""
    return HTMLResponse(content=open(os.path.join(os.path.dirname(__file__), "static", "index.html")).read())

@app.get("/share/{share_token}")
async def share_view(share_token: str):
    """Serve the share view page"""
    # For now, redirect to main page with token in hash
    # Frontend will load the shared conversation
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="0;url=/#share={share_token}">
        <title>Shared Conversation - ASAF</title>
    </head>
    <body>
        <p>Loading shared conversation...</p>
    </body>
    </html>
    """)

@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "mcp_running": mcp_bridge is not None}

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Handle chat requests with Claude API and MCP tools
    """
    if not mcp_bridge:
        raise HTTPException(status_code=500, detail="MCP server not initialized")

    # Check if MCP process is running
    if not mcp_bridge.process or mcp_bridge.process.poll() is not None:
        raise HTTPException(
            status_code=400,
            detail="No account selected. Please select an account first."
        )

    try:
        # Get available tools from MCP
        mcp_tools = await mcp_bridge.list_tools()
        claude_tools = convert_mcp_tools_to_claude_format(mcp_tools)

        # Build messages for Claude
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.conversation_history
        ]
        messages.append({"role": "user", "content": request.message})

        # Call Claude with tools (use model from request)
        response = anthropic_client.messages.create(
            model=request.model,
            max_tokens=4096,
            tools=claude_tools,
            messages=messages
        )

        # Track tool calls for display
        all_tool_calls = []
        total_tool_time = 0.0

        # Handle tool calls
        while response.stop_reason == "tool_use":
            # Extract tool calls
            tool_results = []

            for content_block in response.content:
                if content_block.type == "tool_use":
                    tool_name = content_block.name
                    tool_input = content_block.input
                    tool_id = content_block.id

                    print(f"Calling tool: {tool_name} with {tool_input}")

                    try:
                        # Time tool execution
                        tool_start = datetime.now()
                        # Call MCP tool (account context is set at MCP startup)
                        result = await mcp_bridge.call_tool(tool_name, tool_input)
                        tool_duration = (datetime.now() - tool_start).total_seconds()
                        total_tool_time += tool_duration

                        # Track for display
                        all_tool_calls.append({
                            "name": tool_name,
                            "input": tool_input,
                            "output": result
                        })

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result
                        })
                    except Exception as e:
                        error_msg = f"Error calling tool: {str(e)}"

                        # Track error for display
                        all_tool_calls.append({
                            "name": tool_name,
                            "input": tool_input,
                            "output": error_msg,
                            "error": True
                        })

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": error_msg,
                            "is_error": True
                        })

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            response = anthropic_client.messages.create(
                model=request.model,
                max_tokens=4096,
                tools=claude_tools,
                messages=messages
            )

        # Extract final text response
        response_text = ""
        for content_block in response.content:
            if hasattr(content_block, "text"):
                response_text += content_block.text

        return {
            "response": response_text,
            "tool_calls": all_tool_calls,  # Include tool call details
            "tool_time": round(total_tool_time, 2),  # Time spent in tool execution
            "conversation_history": messages + [{"role": "assistant", "content": response_text}]
        }

    except Exception as e:
        print(f"Error in chat: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tools")
async def list_tools():
    """List available tools from MCP server"""
    if not mcp_bridge:
        raise HTTPException(status_code=500, detail="MCP server not initialized")

    # Check if MCP process is running
    if not mcp_bridge.process or mcp_bridge.process.poll() is not None:
        return {"tools": [], "message": "No account selected"}

    try:
        tools = await mcp_bridge.list_tools()
        return {"tools": tools}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accounts")
async def get_accounts():
    """Fetch available accounts from Finout internal API (with caching)"""
    global _account_cache, _account_cache_time

    try:
        # Check if cache is valid
        now = datetime.now()
        if (_account_cache is not None and
            _account_cache_time is not None and
            now - _account_cache_time < _account_cache_ttl):
            print(f"Using cached accounts ({len(_account_cache)} accounts, age: {(now - _account_cache_time).seconds}s)")
            # Return last selected account if MCP not running, otherwise current MCP account
            current_id = (mcp_bridge.current_account_id
                         if (mcp_bridge and mcp_bridge.process and mcp_bridge.process.poll() is None)
                         else load_last_account())
            return {
                "accounts": _account_cache,
                "current_account_id": current_id,
                "cached": True
            }

        import httpx

        # Get internal API URL from environment
        internal_api_url = os.getenv("FINOUT_INTERNAL_API_URL")

        if not internal_api_url:
            raise HTTPException(
                status_code=500,
                detail="FINOUT_INTERNAL_API_URL not configured"
            )

        print(f"Fetching accounts from: {internal_api_url}/account-service/account?isActive=true")

        # Create httpx client
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            # Fetch accounts from INTERNAL API
            # Internal API only needs authorized-user-roles header (no auth token!)
            headers = {
                "authorized-user-roles": "sysAdmin"
                # Note: NO authorized-account-id header - this allows getting all accounts
                # Note: NO x-finout-access-token - internal API doesn't need it
            }

            accounts_response = await http_client.get(
                f"{internal_api_url}/account-service/account",
                headers=headers,
                params={"isActive": "true"}
            )

            print(f"Account API Status: {accounts_response.status_code}")
            print(f"Account API Response: {accounts_response.text[:500]}")

            accounts_response.raise_for_status()
            accounts = accounts_response.json()

            # Extract name and accountId
            account_list = []
            if isinstance(accounts, list):
                for account in accounts:
                    account_list.append({
                        "name": account.get("name", "Unknown"),
                        "accountId": account.get("accountId", "")
                    })
            elif isinstance(accounts, dict) and "accounts" in accounts:
                for account in accounts["accounts"]:
                    account_list.append({
                        "name": account.get("name", "Unknown"),
                        "accountId": account.get("accountId", "")
                    })

            print(f"Loaded {len(account_list)} accounts (cached for {_account_cache_ttl.seconds}s)")

            # Update cache
            _account_cache = account_list
            _account_cache_time = now

            # Return last selected account if MCP not running, otherwise current MCP account
            current_id = (mcp_bridge.current_account_id
                         if (mcp_bridge and mcp_bridge.process and mcp_bridge.process.poll() is None)
                         else load_last_account())

            return {
                "accounts": account_list,
                "current_account_id": current_id,
                "cached": False
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching accounts: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/switch-account")
async def switch_account(request: dict):
    """
    Switch to a different account by restarting the MCP server.
    Each MCP instance operates within a single account context.
    """
    if not mcp_bridge:
        raise HTTPException(status_code=500, detail="MCP server not initialized")

    account_id = request.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id is required")

    # Start or restart MCP server with account context
    if not mcp_bridge.process or mcp_bridge.process.poll() is not None:
        # MCP not running - start it
        await mcp_bridge.start(account_id)
    else:
        # MCP running - restart with new account
        await mcp_bridge.restart_with_account(account_id)

    # Save as last selected account
    save_last_account(account_id)

    return {
        "success": True,
        "account_id": account_id,
        "message": f"Switched to account {account_id}"
    }

# Conversation Management Endpoints

@app.post("/api/conversations/save")
async def save_conversation(request: dict):
    """Save a conversation for later retrieval"""
    try:
        name = request.get("name")
        account_id = request.get("account_id")
        model = request.get("model")
        messages = request.get("messages")
        tool_calls = request.get("tool_calls")

        if not all([name, account_id, model, messages]):
            raise HTTPException(status_code=400, detail="Missing required fields")

        conversation = await db.save_conversation(
            name=name,
            account_id=account_id,
            model=model,
            messages=messages,
            tool_calls=tool_calls,
        )

        return {
            "success": True,
            "conversation_id": str(conversation["id"]),
            "share_token": conversation["share_token"],
        }

    except Exception as e:
        print(f"Error saving conversation: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/conversations/list")
async def list_conversations(account_id: Optional[str] = None, search: Optional[str] = None):
    """List saved conversations with optional filtering"""
    try:
        conversations = await db.list_conversations(account_id=account_id, search=search)
        return {"conversations": conversations}
    except Exception as e:
        print(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get a conversation by ID"""
    try:
        conversation = await db.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/conversations/{conversation_id}/note")
async def update_conversation_note(conversation_id: str, request: dict):
    """Update user note for a conversation"""
    try:
        note = request.get("note", "")
        success = await db.update_note(conversation_id, note)

        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating note: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/share/{share_token}")
async def get_shared_conversation(share_token: str):
    """Get a conversation by share token (for public sharing)"""
    try:
        conversation = await db.get_conversation_by_token(share_token)
        if not conversation:
            raise HTTPException(status_code=404, detail="Shared conversation not found")
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting shared conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def main():
    """Main entry point for ASAF server"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
