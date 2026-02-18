#!/usr/bin/env python3
"""
VECTIQOR
Web server that provides chat interface to Finout MCP Server.
"""
import asyncio
import json
import os
import subprocess
import secrets
import shutil
import sys
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Response, Request, Cookie
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

        # Start internal MCP runtime using the dedicated launcher when available.
        # Fallback to direct module startup (no uv requirement) for local/dev environments.
        mcp_server_path = repo_root
        if shutil.which("vectiqor-mcp-internal"):
            mcp_cmd = ["vectiqor-mcp-internal"]
        else:
            mcp_src_path = repo_root / "packages" / "mcp-server" / "src"
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                f"{mcp_src_path}{os.pathsep}{existing_pythonpath}"
                if existing_pythonpath
                else str(mcp_src_path)
            )
            mcp_cmd = [
                sys.executable,
                "-c",
                "from finout_mcp_server.server import main_vectiqor_internal; main_vectiqor_internal()",
            ]
        print(f"Starting MCP command: {' '.join(mcp_cmd)}")

        self.process = subprocess.Popen(
            mcp_cmd,
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
                    "name": "vectiqor",
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

# Session management
@dataclass
class SessionData:
    """Data for each user session"""
    session_id: str
    mcp_bridge: MCPBridge
    account_id: str
    last_activity: datetime

# Session storage and configuration
sessions: Dict[str, SessionData] = {}
MAX_CONCURRENT_SESSIONS = 10
SESSION_TIMEOUT = timedelta(minutes=30)
SESSION_COOKIE_NAME = "vectiqor_session_id"

def get_or_create_session_id(request: Request, response: Response) -> str:
    """Get session ID from cookie or create new one"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)

    if not session_id:
        session_id = secrets.token_urlsafe(32)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=SESSION_TIMEOUT.total_seconds(),
            httponly=True,
            samesite="lax"
        )

    return session_id

async def get_session_mcp(session_id: str) -> Optional[MCPBridge]:
    """Get MCP bridge for session, return None if not exists"""
    session = sessions.get(session_id)
    if session:
        session.last_activity = datetime.now()
        return session.mcp_bridge
    return None

async def cleanup_idle_sessions():
    """Background task to cleanup idle sessions"""
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes

            now = datetime.now()
            to_remove = []

            for session_id, session in sessions.items():
                if (now - session.last_activity) > SESSION_TIMEOUT:
                    print(f"Cleaning up idle session: {session_id[:8]}... (account: {session.account_id})")
                    await session.mcp_bridge.stop()
                    to_remove.append(session_id)

            for session_id in to_remove:
                del sessions[session_id]

            if to_remove:
                print(f"Cleaned up {len(to_remove)} idle sessions. Active sessions: {len(sessions)}")

        except Exception as e:
            print(f"Error in cleanup task: {e}")

async def evict_oldest_session():
    """Evict oldest idle session to make room"""
    if not sessions:
        return

    oldest = min(sessions.values(), key=lambda s: s.last_activity)
    print(f"Evicting oldest session: {oldest.session_id[:8]}... (account: {oldest.account_id})")
    await oldest.mcp_bridge.stop()
    del sessions[oldest.session_id]

# Global MCP bridge (DEPRECATED - kept for backward compatibility during migration)
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
    # Initialize database connection
    await db.connect()
    print("Database connected")

    # Start background cleanup task
    cleanup_task = asyncio.create_task(cleanup_idle_sessions())
    print("Session cleanup task started")

    yield

    # Shutdown
    # Stop cleanup task
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # Stop all active MCP sessions
    for session in list(sessions.values()):
        await session.mcp_bridge.stop()
    sessions.clear()
    print(f"Stopped {len(sessions)} active sessions")

    # Close database connection
    await db.disconnect()
    print("Database disconnected")

# Create FastAPI app
app = FastAPI(title="VECTIQOR", lifespan=lifespan)

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

# Approximate model pricing in USD per 1M tokens.
MODEL_PRICING_PER_MTOKEN = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
}


def _empty_usage_totals() -> Dict[str, int]:
    """Create an empty usage accumulator."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def _accumulate_usage(usage_totals: Dict[str, int], usage_obj: Any) -> None:
    """Accumulate usage values from an Anthropic response usage object."""
    for field in usage_totals:
        usage_totals[field] += int(getattr(usage_obj, field, 0) or 0)


def _get_pricing_for_model(model: str) -> Optional[Dict[str, float]]:
    """Return pricing for the configured model, if known."""
    return MODEL_PRICING_PER_MTOKEN.get(model)


def _estimate_usage_cost_usd(model: str, usage_totals: Dict[str, int]) -> Optional[float]:
    """Estimate request cost from token usage and model pricing."""
    pricing = _get_pricing_for_model(model)
    if not pricing:
        return None

    # Approximation: cached token pricing is ignored for simplicity.
    input_tokens = usage_totals["input_tokens"] + usage_totals["cache_creation_input_tokens"]
    output_tokens = usage_totals["output_tokens"]
    total_cost = (
        (input_tokens * pricing["input"]) + (output_tokens * pricing["output"])
    ) / 1_000_000
    return round(total_cost, 6)


def _build_usage_summary(model: str, usage_totals: Dict[str, int]) -> Dict[str, Any]:
    """Build a compact usage payload for frontend display."""
    total_tokens = (
        usage_totals["input_tokens"]
        + usage_totals["output_tokens"]
        + usage_totals["cache_creation_input_tokens"]
        + usage_totals["cache_read_input_tokens"]
    )

    return {
        "model": model,
        "input_tokens": usage_totals["input_tokens"],
        "output_tokens": usage_totals["output_tokens"],
        "cache_creation_input_tokens": usage_totals["cache_creation_input_tokens"],
        "cache_read_input_tokens": usage_totals["cache_read_input_tokens"],
        "total_tokens": total_tokens,
        "estimated_cost_usd": _estimate_usage_cost_usd(model, usage_totals),
    }


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

@app.get("/share/{share_token}")
@app.get("/manage")
async def spa_routes(share_token: str = ""):
    """Serve the SPA for client-side routes (React Router handles rendering)"""
    index_path = Path(__file__).parent / "static" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=503, detail="Frontend not built")
    return HTMLResponse(content=index_path.read_text())

@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "active_sessions": len(sessions),
        "max_sessions": MAX_CONCURRENT_SESSIONS
    }

@app.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request, response: Response):
    """
    Handle chat requests with Claude API and MCP tools (session-based)
    """
    # Get session ID
    session_id = get_or_create_session_id(http_request, response)

    # Get session MCP
    session_mcp = await get_session_mcp(session_id)

    if not session_mcp:
        raise HTTPException(
            status_code=400,
            detail="No account selected. Please select an account first."
        )

    # Check if MCP process is running
    if not session_mcp.process or session_mcp.process.poll() is not None:
        raise HTTPException(
            status_code=500,
            detail="MCP server not running. Please try switching accounts again."
        )

    try:
        # Get available tools from MCP
        mcp_tools = await session_mcp.list_tools()
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
            system=(
                "You are a cloud cost analysis assistant for Finout. "
                "You have access to tools to query costs, detect anomalies, find waste, and explore filters.\n\n"
                "After every interaction where you used tools to answer the user's question, "
                "you MUST call submit_feedback before finishing your response. "
                "Rate your ability to answer (1=couldn't answer, 5=excellent), "
                "pick the query_type that best matches what was asked, "
                "and note any friction points you encountered."
            ),
            tools=claude_tools,
            messages=messages
        )
        usage_totals = _empty_usage_totals()
        if getattr(response, "usage", None):
            _accumulate_usage(usage_totals, response.usage)

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
                        # Call MCP tool (session-isolated MCP instance)
                        result = await session_mcp.call_tool(tool_name, tool_input)
                        tool_duration = (datetime.now() - tool_start).total_seconds()
                        total_tool_time += tool_duration

                        # Track for display
                        all_tool_calls.append({
                            "name": tool_name,
                            "input": tool_input,
                            "output": result
                        })

                        # Save feedback to database if this is a feedback submission
                        if tool_name == "submit_feedback":
                            try:
                                await db.save_feedback(
                                    account_id=session_mcp.current_account_id,
                                    rating=tool_input.get("rating"),
                                    query_type=tool_input.get("query_type"),
                                    tools_used=tool_input.get("tools_used"),
                                    friction_points=tool_input.get("friction_points"),
                                    suggestion=tool_input.get("suggestion"),
                                    session_id=session_id,
                                )
                            except Exception as e:
                                print(f"Failed to save feedback to database: {e}")

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
            if getattr(response, "usage", None):
                _accumulate_usage(usage_totals, response.usage)

        # Extract final text response
        response_text = ""
        for content_block in response.content:
            if hasattr(content_block, "text"):
                response_text += content_block.text

        return {
            "response": response_text,
            "tool_calls": all_tool_calls,  # Include tool call details
            "tool_time": round(total_tool_time, 2),  # Time spent in tool execution
            "usage": _build_usage_summary(request.model, usage_totals),
            "conversation_history": messages + [{"role": "assistant", "content": response_text}]
        }

    except Exception as e:
        print(f"Error in chat: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tools")
async def list_tools(http_request: Request, response: Response):
    """List available tools from MCP server (session-based)"""
    # Get session ID
    session_id = get_or_create_session_id(http_request, response)

    # Get session MCP
    session_mcp = await get_session_mcp(session_id)

    if not session_mcp:
        return {"tools": [], "message": "No account selected"}

    # Check if MCP process is running
    if not session_mcp.process or session_mcp.process.poll() is not None:
        return {"tools": [], "message": "MCP server not running"}

    try:
        tools = await session_mcp.list_tools()
        return {"tools": tools}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accounts")
async def get_accounts(http_request: Request, response: Response):
    """Fetch available accounts from Finout internal API (with caching)"""
    global _account_cache, _account_cache_time

    # Get session to determine current account
    session_id = get_or_create_session_id(http_request, response)
    session = sessions.get(session_id)

    try:
        # Check if cache is valid
        now = datetime.now()
        if (_account_cache is not None and
            _account_cache_time is not None and
            now - _account_cache_time < _account_cache_ttl):
            print(f"Using cached accounts ({len(_account_cache)} accounts, age: {(now - _account_cache_time).seconds}s)")
            # Return session account if exists, otherwise last selected account
            current_id = session.account_id if session else load_last_account()
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

            # Extract name and accountId, filter by AI features enabled
            account_list = []
            if isinstance(accounts, list):
                for account in accounts:
                    # Only include accounts with AI features enabled
                    general_config = account.get("generalConfig", {})
                    if general_config.get("aiFeaturesEnabled", False):
                        account_list.append({
                            "name": account.get("name", "Unknown"),
                            "accountId": account.get("accountId", "")
                        })
            elif isinstance(accounts, dict) and "accounts" in accounts:
                for account in accounts["accounts"]:
                    # Only include accounts with AI features enabled
                    general_config = account.get("generalConfig", {})
                    if general_config.get("aiFeaturesEnabled", False):
                        account_list.append({
                            "name": account.get("name", "Unknown"),
                            "accountId": account.get("accountId", "")
                        })

            print(f"Loaded {len(account_list)} accounts (cached for {_account_cache_ttl.seconds}s)")

            # Update cache
            _account_cache = account_list
            _account_cache_time = now

            # Return session account if exists, otherwise last selected account
            current_id = session.account_id if session else load_last_account()

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
async def switch_account(request: dict, http_request: Request, response: Response):
    """
    Switch to a different account by creating/restarting session MCP server.
    Each session has its own isolated MCP instance.
    """
    account_id = request.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id is required")

    # Get or create session ID
    session_id = get_or_create_session_id(http_request, response)

    # Check if we need to evict oldest session
    if session_id not in sessions and len(sessions) >= MAX_CONCURRENT_SESSIONS:
        await evict_oldest_session()

    # Get or create session
    session = sessions.get(session_id)

    if session:
        # Session exists - check if account changed
        if session.account_id != account_id:
            print(f"Session {session_id[:8]}: Switching from {session.account_id} to {account_id}")
            await session.mcp_bridge.restart_with_account(account_id)
            session.account_id = account_id
        session.last_activity = datetime.now()
    else:
        # New session - create MCP bridge
        print(f"Session {session_id[:8]}: Creating new MCP for account {account_id}")
        mcp = MCPBridge()
        await mcp.start(account_id)

        sessions[session_id] = SessionData(
            session_id=session_id,
            mcp_bridge=mcp,
            account_id=account_id,
            last_activity=datetime.now()
        )

    print(f"Active sessions: {len(sessions)}/{MAX_CONCURRENT_SESSIONS}")

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
            conversation_id=request.get("conversation_id"),
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

# Feedback Management Endpoints

@app.get("/api/feedback/list")
async def list_feedback(
    account_id: Optional[str] = None,
    min_rating: Optional[int] = None,
    max_rating: Optional[int] = None,
    query_type: Optional[str] = None,
    limit: int = 100
):
    """List feedback with optional filters"""
    try:
        feedback = await db.list_feedback(
            account_id=account_id,
            min_rating=min_rating,
            max_rating=max_rating,
            query_type=query_type,
            limit=limit
        )
        return {"feedback": feedback}
    except Exception as e:
        print(f"Error listing feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/feedback/stats")
async def get_feedback_stats(account_id: Optional[str] = None):
    """Get aggregate feedback statistics"""
    try:
        stats = await db.get_feedback_stats(account_id=account_id)
        return stats
    except Exception as e:
        print(f"Error getting feedback stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Serve frontend SPA (must be last — API routes above take priority)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="frontend")


def main():
    """Main entry point for VECTIQOR server"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)

if __name__ == "__main__":
    main()
