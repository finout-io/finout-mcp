#!/usr/bin/env python3
"""
BILLY
Web server that provides chat interface to Finout MCP Server.
"""
import asyncio
import json
import os
import subprocess
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from uuid import UUID, uuid4
from typing import Optional, List, Dict, Any, Callable, Awaitable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from pathlib import Path
from urllib.parse import quote
from .changelog import CHANGELOG_ENTRIES
from .tools_reference import TOOLS_REFERENCE
from .db import db
from .auth import get_jwt_user
from .oauth import (
    oauth_authorize_get,
    oauth_authorize_post,
    oauth_token,
    oauth_register,
    oauth_protected_resource,
    oauth_authorization_server,
)

# Load .env from package directory
package_root = Path(__file__).parent.parent.parent
load_dotenv(package_root / ".env")

# Repository root for finding MCP server
repo_root = package_root.parent.parent

# Langfuse observability — auto-instrument Anthropic SDK calls.
_langfuse: Any = None


def _langfuse_env(name: str) -> str | None:
    return os.getenv(f"LANGFUSE_BILLY_{name}") or os.getenv(f"LANGFUSE_{name}")


if _langfuse_env("PUBLIC_KEY") and _langfuse_env("SECRET_KEY"):
    try:
        from langfuse import Langfuse as _Langfuse
        from langfuse import propagate_attributes as _langfuse_propagate_attributes

        candidate = _Langfuse(
            public_key=_langfuse_env("PUBLIC_KEY"),
            secret_key=_langfuse_env("SECRET_KEY"),
            host=_langfuse_env("HOST"),
        )  # Registers OTel TracerProvider
        if hasattr(candidate, "start_as_current_observation"):
            _langfuse = candidate
        else:
            print(
                "Langfuse client missing required tracing API; disabling Billy tracing."
            )

        from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor

        AnthropicInstrumentor().instrument()
    except Exception:
        pass  # Langfuse/OTel not available — continue without tracing

# Models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: List[ChatMessage] = []
    account_id: Optional[str] = None
    model: Optional[str] = "claude-sonnet-4-6"  # Model to use for this request
    user_email: Optional[str] = None
    conversation_id: Optional[str] = None


class MCPBridge:
    """Bridge between HTTP API and MCP Server (stdio)"""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.request_id = 0
        self._lock = asyncio.Lock()
        self.current_account_id: Optional[str] = None

    async def start(self, account_id: str):
        """Start the MCP server as subprocess with specific account ID"""
        self.current_account_id = account_id

        print(f"Starting MCP server for account: {self.current_account_id}...")

        # Prepare environment with account ID
        env = os.environ.copy()
        env["FINOUT_ACCOUNT_ID"] = self.current_account_id
        env["LANGFUSE_TRACE_ORIGIN"] = "billy"

        # Start internal MCP runtime using the dedicated launcher when available.
        # Fallback to uv-run launcher so mcp-server dependencies are resolved automatically.
        # Last-resort fallback keeps direct module startup for environments without uv.
        mcp_server_path = repo_root
        if shutil.which("billy-mcp-internal"):
            mcp_cmd = ["billy-mcp-internal"]
        elif shutil.which("uv"):
            mcp_cmd = [
                "uv",
                "run",
                "--directory",
                str(repo_root / "packages" / "billy-mcp-internal"),
                "billy-mcp-internal",
            ]
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
                "from finout_mcp_server.server import main_billy_internal; main_billy_internal()",
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
                    "name": "billy",
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

            request_str = json.dumps(request) + "\n"

            def _send_and_receive() -> str:
                # Blocking stdio operations must not run on the event loop thread.
                self.process.stdin.write(request_str)
                self.process.stdin.flush()
                return self.process.stdout.readline()

            # Read response
            response_str = await asyncio.to_thread(_send_and_receive)
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

# MCP pool: one subprocess per active account
@dataclass
class AccountSession:
    account_id: str
    mcp_bridge: MCPBridge
    last_activity: datetime

mcp_pool: Dict[str, AccountSession] = {}
MAX_CONCURRENT_ACCOUNTS = 10
SESSION_TIMEOUT = timedelta(minutes=30)
def _read_timeout_seconds(env_var: str, default: float) -> Optional[float]:
    raw = os.getenv(env_var)
    if raw is None or raw.strip() == "":
        return default

    value = raw.strip().lower()
    if value in {"0", "-1", "none", "off", "disabled", "infinite", "inf"}:
        return None

    try:
        parsed = float(raw)
    except ValueError:
        print(f"Invalid {env_var}={raw!r}; falling back to {default}s")
        return default

    if parsed <= 0:
        return None
    return parsed


CHAT_REQUEST_TIMEOUT_SECONDS = _read_timeout_seconds("BILLY_CHAT_TIMEOUT_SECONDS", 540.0)
PUBLIC_MODE = os.getenv("BILLY_PUBLIC_MODE", "").lower() in ("1", "true", "yes")


async def get_or_create_account_mcp(account_id: str) -> Optional[MCPBridge]:
    """Return the MCP bridge for an account, starting one if needed."""
    entry = mcp_pool.get(account_id)
    if entry:
        if not entry.mcp_bridge.process or entry.mcp_bridge.process.poll() is not None:
            try:
                print(f"MCP dead for account {account_id[:8]}, restarting...")
                await entry.mcp_bridge.restart_with_account(account_id)
            except Exception as e:
                print(f"Failed to restart MCP for account {account_id[:8]}: {e}")
                return None
        entry.last_activity = datetime.now()
        return entry.mcp_bridge

    if len(mcp_pool) >= MAX_CONCURRENT_ACCOUNTS:
        await evict_oldest_account()

    try:
        print(f"Starting MCP for account {account_id[:8]}...")
        mcp = MCPBridge()
        await mcp.start(account_id)
        mcp_pool[account_id] = AccountSession(
            account_id=account_id,
            mcp_bridge=mcp,
            last_activity=datetime.now(),
        )
        return mcp
    except Exception as e:
        print(f"Failed to start MCP for account {account_id[:8]}: {e}")
        return None


def _is_valid_account_id(value: Optional[str]) -> bool:
    """Validate account id format (UUID string)."""
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


async def evict_oldest_account():
    """Evict the least-recently-used account MCP to stay within MAX_CONCURRENT_ACCOUNTS."""
    if not mcp_pool:
        return
    oldest_id = min(mcp_pool, key=lambda k: mcp_pool[k].last_activity)
    print(f"Evicting MCP for account {oldest_id[:8]}...")
    await mcp_pool[oldest_id].mcp_bridge.stop()
    del mcp_pool[oldest_id]


async def cleanup_idle_sessions():
    """Background task to stop MCP subprocesses for accounts idle beyond SESSION_TIMEOUT."""
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes

            now = datetime.now()
            to_remove = [
                account_id for account_id, entry in mcp_pool.items()
                if (now - entry.last_activity) > SESSION_TIMEOUT
            ]
            for account_id in to_remove:
                print(f"Cleaning up idle MCP for account {account_id[:8]}...")
                await mcp_pool[account_id].mcp_bridge.stop()
                del mcp_pool[account_id]

            if to_remove:
                print(f"Cleaned up {len(to_remove)} idle accounts. Active: {len(mcp_pool)}")

            # Expire old tool output entries
            expired = [
                k for k, v in _tool_output_store.items()
                if (now - v["created_at"]) > _TOOL_OUTPUT_TTL
            ]
            for k in expired:
                del _tool_output_store[k]
            if expired:
                print(f"Expired {len(expired)} tool output entries")

        except Exception as e:
            print(f"Error in cleanup task: {e}")

# Out-of-band tool output store: request_id → {calls, created_at}
# Outputs are excluded from the SSE final event and fetched separately by the frontend.
_tool_output_store: Dict[str, Dict[str, Any]] = {}
_TOOL_OUTPUT_TTL = timedelta(minutes=30)
_LIVE_JUDGE_METRICS = (
    "answers_question",
    "states_key_result",
    "grounded_in_tool_output",
    "directness",
    "actionability",
    "interaction_quality",
    "response_quality",
)

# Global account cache
_account_cache: Optional[Dict[str, Any]] = None
_account_cache_time: Optional[datetime] = None
_account_cache_ttl = timedelta(hours=3)  # Cache for 3 hours

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

    # Stop all active MCP subprocesses
    for entry in list(mcp_pool.values()):
        await entry.mcp_bridge.stop()
    mcp_pool.clear()
    print("Stopped all MCP subprocesses")

    # Close database connection
    await db.disconnect()
    print("Database disconnected")

# Create FastAPI app
app = FastAPI(title="BILLY", lifespan=lifespan)


def _get_app_version() -> str:
    if CHANGELOG_ENTRIES:
        return CHANGELOG_ENTRIES[0]["version"]

    try:
        return package_version("billy")
    except PackageNotFoundError:
        return os.getenv("BILLY_VERSION", "0.0.0-dev")

# CORS middleware — configurable via BILLY_ALLOWED_ORIGINS (comma-separated)
_allowed_origins_env = os.getenv("BILLY_ALLOWED_ORIGINS", "")
_allowed_origins: list[str] = (
    [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
    if _allowed_origins_env
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if PUBLIC_MODE:
    print("PUBLIC_MODE=true: JWT authentication required for all /api/* routes")

    @app.middleware("http")
    async def jwt_auth_middleware(request: Request, call_next):
        unauthenticated_paths = {"/api/login-redirect", "/api/health"}
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path.startswith("/api/") and request.url.path not in unauthenticated_paths:
            try:
                await get_jwt_user(request)
            except HTTPException as e:
                return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
        return await call_next(request)


# Initialize Anthropic client
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Approximate model pricing in USD per 1M tokens.
MODEL_PRICING_PER_MTOKEN = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
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


REMEMBER_USER_FACT_TOOL = {
    "name": "remember_user_fact",
    "description": (
        "Save a personal fact about the user for future conversations. "
        "Use this when the user shares something memorable — their role, team, "
        "projects they own, preferences, upcoming events, pet peeves about costs, etc. "
        "Keep facts concise (one sentence). Don't save trivial or overly specific query details."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "A concise personal fact about the user (e.g. 'Leads the payments team', 'Hates S3 costs', 'Going on parental leave in April')",
            }
        },
        "required": ["fact"],
    },
}


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

    # Add Billy-level virtual tools
    claude_tools.append(REMEMBER_USER_FACT_TOOL)

    return claude_tools

def _frontend_dir() -> Optional[Path]:
    """Resolve frontend assets directory, supporting both legacy and new image layouts."""
    package_root = Path(__file__).resolve().parents[2]
    candidates = [
        package_root / "frontend" / "dist",          # New layout
        Path(__file__).resolve().parent / "static",  # Legacy/bundled layout
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return None


def _live_judge_enabled() -> bool:
    raw = os.getenv("BILLY_TRACE_JUDGE_ENABLED", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return bool(_langfuse and os.getenv("ANTHROPIC_API_KEY"))


def _usage_details_for_langfuse(usage: Dict[str, Any] | None) -> Dict[str, int] | None:
    if not usage:
        return None
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
    }


def _cost_details_for_langfuse(usage: Dict[str, Any] | None) -> Dict[str, float] | None:
    if not usage:
        return None
    estimated_cost = usage.get("estimated_cost_usd")
    if estimated_cost is None:
        return None
    try:
        return {"estimated_cost_usd": float(estimated_cost)}
    except (TypeError, ValueError):
        return None


def _record_final_answer_observation(
    *,
    question: str,
    response_text: str,
    request_id: str,
    tool_calls: list[dict[str, Any]],
    model: str,
    usage: Dict[str, Any] | None,
    response_mode: str,
    tool_time: float | None,
) -> None:
    if not _langfuse:
        return

    from .evaluation import build_judge_output_payload

    compact_output = build_judge_output_payload(
        response_text=response_text,
        tool_calls=tool_calls,
    )
    with _langfuse.start_as_current_observation(
        name="billy_final_answer",
        as_type="generation",
        input={
            "question": question,
            "request_id": request_id,
        },
        output=compact_output,
        metadata={
            "source": "billy",
            "request_id": request_id,
            "response_mode": response_mode,
            "tool_time": tool_time,
            "tool_count": len(compact_output.get("tool_names", [])),
        },
        model=model,
        usage_details=_usage_details_for_langfuse(usage),
        cost_details=_cost_details_for_langfuse(usage),
    ) as final_answer:
        final_answer.score(
            name="final_text_present",
            value=1.0 if response_text.strip() else 0.0,
            data_type="NUMERIC",
            metadata={"source": "billy"},
        )
        final_answer.score(
            name="chart_answer_present",
            value=1.0 if "render_chart" in compact_output.get("tool_names", []) else 0.0,
            data_type="NUMERIC",
            metadata={"source": "billy"},
        )


async def _score_trace_with_judge(
    *,
    trace_id: str,
    session_id: str,
    question: str,
    response_text: str,
    request_id: str,
) -> None:
    if not _langfuse or not _live_judge_enabled():
        return

    tool_calls = list((_tool_output_store.get(request_id) or {}).get("calls") or [])
    if not response_text and not tool_calls:
        return

    try:
        from .evaluation import judge_live_interaction

        judged = await asyncio.to_thread(
            judge_live_interaction,
            question=question,
            response_text=response_text,
            tool_calls=tool_calls,
        )

        reason = str(judged.get("reason", "")).strip() or "Billy async judge"
        judge_model = os.getenv("EVAL_JUDGE_MODEL", "claude-haiku-4-5-20251001")
        evaluator_input = {
            "question": question,
            "response": response_text,
            "request_id": request_id,
            "tool_names": [tc.get("name") for tc in tool_calls if tc.get("name")],
        }
        evaluator_output = {
            "reason": reason,
            "metrics": {
                metric_name: judged.get(metric_name)
                for metric_name in _LIVE_JUDGE_METRICS
                if judged.get(metric_name) is not None
            },
        }
        with _langfuse.start_as_current_observation(
            trace_context={"trace_id": trace_id},
            name="billy_async_judge",
            as_type="evaluator",
            input=evaluator_input,
            metadata={
                "source": "billy_async_judge",
                "request_id": request_id,
                "judge_model": judge_model,
            },
        ) as evaluator:
            evaluator.update(output=evaluator_output)
            for metric_name in _LIVE_JUDGE_METRICS:
                raw_value = judged.get(metric_name)
                try:
                    score = float(max(1, min(5, int(raw_value))))
                except (TypeError, ValueError):
                    continue
                evaluator.score(
                    name=metric_name,
                    value=score,
                    data_type="NUMERIC",
                    comment=reason,
                    metadata={
                        "source": "billy_async_judge",
                        "request_id": request_id,
                        "judge_model": judge_model,
                    },
                )

        for metric_name in _LIVE_JUDGE_METRICS:
            raw_value = judged.get(metric_name)
            try:
                score = float(max(1, min(5, int(raw_value))))
            except (TypeError, ValueError):
                continue
            _langfuse.create_score(
                trace_id=trace_id,
                session_id=session_id,
                name=metric_name,
                value=score,
                data_type="NUMERIC",
                comment=reason,
                metadata={
                    "source": "billy_async_judge",
                    "request_id": request_id,
                    "judge_model": judge_model,
                },
            )
    except Exception as exc:
        print(f"Failed to score Billy trace with async judge: {exc}")


@app.get("/share/{share_token}")
@app.get("/manage")
async def spa_routes(share_token: str = ""):
    """Serve the SPA for client-side routes (React Router handles rendering)."""
    frontend_dir = _frontend_dir()
    if frontend_dir is None:
        raise HTTPException(status_code=503, detail="Frontend not built")
    index_path = frontend_dir / "index.html"
    return HTMLResponse(content=index_path.read_text())

@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "active_accounts": len(mcp_pool),
        "max_accounts": MAX_CONCURRENT_ACCOUNTS,
    }


@app.get("/api/whats-new")
async def whats_new():
    """Return versioned changelog entries for the frontend what's-new modal."""
    return {
        "app": "billy",
        "current_version": _get_app_version(),
        "entries": CHANGELOG_ENTRIES,
    }


@app.get("/api/tools")
async def get_tools():
    """Return structured reference for all available MCP tools."""
    return {"tools": TOOLS_REFERENCE}


@app.get("/api/me")
async def get_me(http_request: Request):
    """Return authenticated user info (public mode only)."""
    jwt_user = await get_jwt_user(http_request)
    return {"email": jwt_user.get("email"), "account_id": jwt_user.get("tenantId")}


@app.get("/api/login-redirect")
async def login_redirect(next: str = "/"):
    """Redirect to Finout login page."""
    login_url = os.getenv("FINOUT_LOGIN_URL", "https://app.finout.io/login")
    return RedirectResponse(url=f"{login_url}?redirect={quote(next)}")

def _chat_timeout_detail() -> str:
    if CHAT_REQUEST_TIMEOUT_SECONDS is None:
        return "Chat request timed out. Please retry with a narrower query."
    return (
        f"Chat request timed out after {int(CHAT_REQUEST_TIMEOUT_SECONDS)}s. "
        "Please retry with a narrower query."
    )


@asynccontextmanager
async def _maybe_timeout(timeout_seconds: Optional[float]):
    if timeout_seconds is None:
        yield
        return
    async with asyncio.timeout(timeout_seconds):
        yield


async def _call_claude_messages_create(
    *,
    status_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    status_phase: Optional[str] = None,
    status_message: Optional[str] = None,
    token_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    **kwargs: Any,
):
    loop = asyncio.get_running_loop()

    def _create():
        if not token_callback:
            return anthropic_client.messages.create(**kwargs)

        with anthropic_client.messages.stream(**kwargs) as stream:
            for text_chunk in stream.text_stream:
                if not text_chunk:
                    continue
                future = asyncio.run_coroutine_threadsafe(token_callback(text_chunk), loop)
                try:
                    future.result(timeout=5)
                except Exception:
                    # Don't fail the request if token emission to SSE was interrupted.
                    pass
            return stream.get_final_message()

    task = asyncio.create_task(asyncio.to_thread(_create))
    if not status_callback or not status_phase or not status_message:
        return await task

    started = datetime.now()
    while True:
        try:
            # Keep the Claude call alive while emitting periodic status ticks.
            # wait_for() cancels awaited tasks on timeout unless shielded.
            return await asyncio.wait_for(asyncio.shield(task), timeout=8.0)
        except asyncio.TimeoutError:
            elapsed = int((datetime.now() - started).total_seconds())
            await status_callback(
                {
                    "phase": status_phase,
                    "message": f"{status_message} ({elapsed}s)",
                }
            )
        except asyncio.CancelledError:
            task.cancel()
            raise


def _tool_calls_metadata(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return tool call list with outputs stripped — safe to embed in the SSE final event."""
    return [
        {"name": tc["name"], "input": tc["input"], "error": tc.get("error", False)}
        for tc in tool_calls
    ]


async def _run_chat_pipeline(
    request: ChatRequest,
    session_mcp: MCPBridge,
    status_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    token_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """Execute chat + MCP tool loop, optionally emitting progress status events."""
    if _langfuse:
        return await _run_chat_pipeline_traced(
            request, session_mcp, status_callback, token_callback
        )
    return await _run_chat_pipeline_inner(
        request, session_mcp, status_callback, token_callback
    )


async def _run_chat_pipeline_traced(
    request: ChatRequest,
    session_mcp: MCPBridge,
    status_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    token_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    account_id = session_mcp.current_account_id or ""
    session_id = request.conversation_id or str(uuid4())
    base_metadata: Dict[str, Any] = {
        "account_id": account_id,
        "conversation_id": session_id,
        "conversation_length": len(request.conversation_history),
        "origin": "billy",
        "channel": "chat",
    }
    propagated_metadata = {
        "account_id": account_id,
        "conversation_id": session_id,
        "origin": "billy",
        "channel": "chat",
    }
    trace_context = {"trace_id": _langfuse.create_trace_id(seed=session_id)}
    with _langfuse.start_as_current_observation(
        trace_context=trace_context,
        name="chat_pipeline",
        as_type="chain",
        input={
            "message": request.message,
            "model": request.model,
            "account_id": account_id,
            "conversation_id": session_id,
        },
        metadata=base_metadata,
    ) as span:
        with _langfuse_propagate_attributes(
            user_id=request.user_email,
            session_id=session_id,
            metadata=propagated_metadata,
            tags=[request.model or "unknown-model", "origin:billy", "channel:chat"],
            trace_name="Billy Chat",
        ):
            result = await _run_chat_pipeline_inner(
                request, session_mcp, status_callback, token_callback
            )
            from .evaluation import build_judge_output_payload

            trace_id = getattr(span, "trace_id", None) or _langfuse.get_current_trace_id()
            tool_names = [tc.get("name") for tc in result.get("tool_calls", []) if tc.get("name")]
            has_chart = "render_chart" in tool_names
            has_text = bool((result.get("response") or "").strip())
            if has_text and has_chart:
                response_mode = "text_and_chart"
            elif has_text:
                response_mode = "text_only"
            elif has_chart:
                response_mode = "chart_only"
            else:
                response_mode = "none"
            judge_ready_output = build_judge_output_payload(
                response_text=result.get("response", ""),
                tool_calls=list((_tool_output_store.get(result.get("request_id", "")) or {}).get("calls") or []),
            )
            _langfuse.set_current_trace_io(
                input={
                    "question": request.message,
                    "model": request.model,
                    "account_id": account_id,
                    "conversation_id": session_id,
                },
                output=judge_ready_output,
            )
            _langfuse.score_current_trace(
                name="visible_answer_present",
                value=1 if (has_text or has_chart) else 0,
                data_type="NUMERIC",
            )
            _langfuse.score_current_trace(
                name="final_text_present",
                value=1 if has_text else 0,
                data_type="NUMERIC",
            )
            _langfuse.score_current_trace(
                name="chart_answer_present",
                value=1 if has_chart else 0,
                data_type="NUMERIC",
            )
            _record_final_answer_observation(
                question=request.message,
                response_text=result.get("response", ""),
                request_id=result.get("request_id", ""),
                tool_calls=list((_tool_output_store.get(result.get("request_id", "")) or {}).get("calls") or []),
                model=request.model,
                usage=result.get("usage"),
                response_mode=response_mode,
                tool_time=result.get("tool_time"),
            )
            span.update(
                output={
                    "tool_count": len(result.get("tool_calls", [])),
                    "tool_time": result.get("tool_time"),
                    "usage": result.get("usage"),
                    "response_mode": response_mode,
                    "request_id": result.get("request_id"),
                },
                metadata={
                    **base_metadata,
                    "request_id": result.get("request_id"),
                    "response_mode": response_mode,
                    "tool_sequence": tool_names,
                    "tool_count": len(tool_names),
                    "response_length": len(result.get("response", "")),
                    "trace_id": trace_id,
                },
            )
            if trace_id and result.get("request_id"):
                asyncio.create_task(
                    _score_trace_with_judge(
                        trace_id=trace_id,
                        session_id=session_id,
                        question=request.message,
                        response_text=result.get("response", ""),
                        request_id=result["request_id"],
                    )
                )
            return result


async def _build_system_prompt(
    user_email: Optional[str],
    account_id: Optional[str],
    is_new_conversation: bool,
) -> str:
    """Build the system prompt, injecting user memories when available."""
    base = (
        "You are Billy, a cheeky and friendly cloud cost analysis assistant for Finout. "
        "You have access to tools to query costs, detect anomalies, find waste, and explore filters.\n\n"
        "PERSONALITY: You're warm, witty, and a bit cheeky — like a knowledgeable colleague "
        "who genuinely enjoys helping people understand their cloud costs. "
        "Use light humor when appropriate but always stay helpful and accurate. "
        "If this is the start of a new conversation, greet the user in a fun, personalized way "
        "using any memories you have about them.\n\n"
        "STYLE: When narrating your steps between tool calls, use complete sentences. "
        "Do not end a sentence with a colon before calling a tool.\n\n"
        "CRITICAL RULE — NEVER FABRICATE: You MUST call tools before answering any question "
        "about costs, resources, filters, anomalies, waste, or financial data. "
        "NEVER state specific cost figures, resource names, service names, or any data "
        "without first calling the appropriate tool. "
        "If you are unsure which filter to use, call search_filters first. "
        "ALWAYS follow through with the appropriate terminal tool after search_filters — "
        "never stop at search_filters alone.\n\n"
        "TOOL ROUTING — pick the right tool for the question:\n"
        "• Cost totals, breakdowns, trends → query_costs\n"
        "• Cost changes, what drove increase/decrease, biggest movers → get_top_movers\n"
        "• Cost per unit, per resource, per hour, efficiency → get_unit_economics\n"
        "• Average daily cost, volatility, peak day → get_cost_statistics\n"
        "• Peak hours, weekday vs weekend patterns → get_cost_patterns\n"
        "• Savings plan / RI coverage → get_savings_coverage\n"
        "• Tag coverage, untagged spend, governance → get_tag_coverage\n"
        "• Period-over-period comparison → compare_costs\n"
        "If you need filter/group_by metadata for any tool, call search_filters first, "
        "then immediately call the terminal tool with the metadata. "
        "Violating this rule — generating numbers or names from memory — is a critical failure.\n\n"
        "CHARTS: The UI automatically renders interactive charts from tool call data — "
        "pie charts for single-dimension breakdowns, stacked bar charts for time-series. "
        "Never generate ASCII charts, text charts, or raw-data tables. "
        "After tool calls, give 2-4 sentences of key insights (total, biggest driver, notable trend). "
        "The chart handles the visual detail.\n\n"
        "DIAGRAMS: The UI also auto-renders Mermaid diagrams from tool call data. "
        "Never output diagram code or code blocks — describe what the diagram shows instead.\n\n"
        "VIRTUAL TAGS: Virtual tags are Finout's cost allocation layer. Inferred types:\n"
        "- reallocation: allocations drive cost splits via KPI metrics (yellow in diagram)\n"
        "- relational: rules reference other virtual tags — a dependency/hierarchy tag (orange)\n"
        "- custom: rules map raw costs to dimensions, no cross-tag references (green)\n"
        "- base: no rules, no allocations — simple pass-through or empty tag (blue)\n\n"
        "When analyze_virtual_tags returns WITHOUT a tag_name (discovery mode), narrate:\n"
        "- Each chain in ecosystem.chains by name, what it allocates (output_values), "
        "how deep it is (chain_depth), what services feed it (cost_dimensions), "
        "and its composition (by_type). Paint a picture of the full allocation architecture.\n"
        "- Mention isolated_tags count and what that implies.\n\n"
        "When analyze_virtual_tags returns WITH a tag_name (focused mode), narrate:\n"
        "1. WHAT IT DOES: use 'values' (the actual cost categories like team/project names) "
        "and 'cost_dimensions' to explain what this tag allocates and from what sources\n"
        "2. ITS ROLE: position (source/bridge/output) tells you where it sits — "
        "source = raw data entry, bridge = mid-chain aggregator, output = final allocation\n"
        "3. THE CHAIN: mention chain_depth, source_tags, output_tags by name\n"
        "4. COMPLEXITY highlights from tag_details — most-connected or most-ruled tags\n"
        "5. Any reallocation tags and what metric drives their split\n"
        "Prioritize meaning over structure — explain WHAT costs flow WHERE and WHY, "
        "not just 'this tag has 8 rules and 3 dependencies'. "
        "Use analyze_virtual_tags proactively when the user asks about cost allocation, "
        "tag hierarchies, shared-cost strategy, or which tags depend on others.\n\n"
        "REMEMBERING USERS: When the user shares personal details — their role, team, "
        "projects they care about, pet peeves, upcoming events — call remember_user_fact "
        "to save it. You'll see these memories in future conversations and can use them "
        "for personalized greetings and context-aware suggestions. "
        "Don't save trivial query details, only genuinely personal or recurring facts.\n\n"
        "After every interaction where you used tools to answer the user's question, "
        "you MUST call submit_feedback before finishing your response. "
        "Rate your ability to answer (1=couldn't answer, 5=excellent), "
        "pick the query_type that best matches what was asked, "
        "and note any friction points you encountered."
    )

    # Inject user memories if available
    if user_email and account_id and is_new_conversation:
        try:
            memories = await db.get_memories(user_email, account_id)
            if memories:
                facts = "\n".join(f"- {m['fact']}" for m in memories)
                base += (
                    f"\n\nUSER MEMORIES (things you know about this user from past conversations):\n"
                    f"User email: {user_email}\n"
                    f"{facts}\n"
                    "Use these to make your greeting personal and cheeky. "
                    "Reference 1-2 relevant memories naturally — don't list them all."
                )
        except Exception as e:
            print(f"Failed to load user memories: {e}")

    return base


async def _call_mcp_tool_traced(
    session_mcp: MCPBridge,
    tool_name: str,
    tool_input: Dict[str, Any],
    *,
    request_id: str,
) -> Any:
    if not _langfuse:
        return await session_mcp.call_tool(tool_name, tool_input)

    span_meta = {
        "origin": "billy",
        "channel": "chat",
        "account_id": session_mcp.current_account_id,
        "request_id": request_id,
    }
    with _langfuse.start_as_current_observation(
        name=f"mcp:{tool_name}",
        as_type="tool",
        input=tool_input,
        metadata=span_meta,
    ) as tool_span:
        try:
            result = await session_mcp.call_tool(tool_name, tool_input)
            tool_span.update(
                output={"status": "success", "preview": str(result)[:400]},
                metadata=span_meta,
            )
            return result
        except Exception as exc:
            tool_span.update(
                output={
                    "status": "error",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                level="ERROR",
                metadata=span_meta,
            )
            raise


async def _run_chat_pipeline_inner(
    request: ChatRequest,
    session_mcp: MCPBridge,
    status_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    token_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """Execute chat + MCP tool loop, optionally emitting progress status events."""
    request_id = str(uuid4())

    if status_callback:
        await status_callback({"phase": "thinking", "message": "Thinking..."})

    # Get available tools from MCP
    mcp_tools = await session_mcp.list_tools()
    claude_tools = convert_mcp_tools_to_claude_format(mcp_tools)

    # Build messages for Claude
    messages = [{"role": msg.role, "content": msg.content} for msg in request.conversation_history]
    messages.append({"role": "user", "content": request.message})

    # Build system prompt with user memories
    is_new_conversation = len(request.conversation_history) == 0
    system_prompt = await _build_system_prompt(
        request.user_email,
        session_mcp.current_account_id,
        is_new_conversation,
    )

    # Call Claude with tools (use model from request)
    llm_response = await _call_claude_messages_create(
        status_callback=status_callback,
        status_phase="thinking",
        status_message="Thinking...",
        token_callback=token_callback,
        model=request.model,
        max_tokens=4096,
        system=system_prompt,
        tools=claude_tools,
        messages=messages,
    )
    usage_totals = _empty_usage_totals()
    if getattr(llm_response, "usage", None):
        _accumulate_usage(usage_totals, llm_response.usage)

    # Track tool calls for display
    all_tool_calls = []
    total_tool_time = 0.0
    all_response_texts: list[str] = []

    # Handle tool calls
    while llm_response.stop_reason == "tool_use":
        tool_results = []
        if status_callback:
            await status_callback({"phase": "tool", "message": "Running tools..."})

        for content_block in llm_response.content:
            if content_block.type != "tool_use":
                continue

            tool_name = content_block.name
            tool_input = content_block.input
            tool_id = content_block.id
            print(f"Calling tool: {tool_name} with {tool_input}")

            if status_callback:
                await status_callback(
                    {
                        "phase": "tool",
                        "message": f"Running {tool_name}...",
                        "tool_name": tool_name,
                    }
                )

            try:
                tool_start = datetime.now()

                # Handle Billy-level virtual tools locally
                if tool_name == "remember_user_fact":
                    fact = tool_input.get("fact", "")
                    user_email = request.user_email
                    acct_id = session_mcp.current_account_id
                    if user_email and acct_id and fact:
                        try:
                            await db.save_memory(user_email, acct_id, fact)
                            result = f"Remembered: {fact}"
                        except Exception as e:
                            result = f"Could not save memory: {e}"
                    else:
                        result = "Memory not saved (missing user email or account)."
                else:
                    result = await _call_mcp_tool_traced(
                        session_mcp,
                        tool_name,
                        tool_input,
                        request_id=request_id,
                    )

                tool_duration = (datetime.now() - tool_start).total_seconds()
                total_tool_time += tool_duration

                all_tool_calls.append({"name": tool_name, "input": tool_input, "output": result})

                if tool_name == "submit_feedback":
                    if _langfuse:
                        try:
                            _langfuse.score_current_trace(
                                name="assistant_self_rating",
                                value=tool_input.get("rating", 0),
                                data_type="NUMERIC",
                                comment="; ".join(tool_input.get("friction_points", [])),
                            )
                            _langfuse.score_current_trace(
                                name="assistant_query_type",
                                value=tool_input.get("query_type", "unknown"),
                                data_type="CATEGORICAL",
                            )
                        except Exception as e:
                            print(f"Failed to score Langfuse trace: {e}")

                tool_results.append(
                    {"type": "tool_result", "tool_use_id": tool_id, "content": result}
                )
            except Exception as e:
                error_msg = f"Error calling tool: {str(e)}"
                all_tool_calls.append(
                    {
                        "name": tool_name,
                        "input": tool_input,
                        "output": error_msg,
                        "error": True,
                    }
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": error_msg,
                        "is_error": True,
                    }
                )

        # Capture text from mixed (text + tool_use) responses before they're lost
        for cb in llm_response.content:
            if hasattr(cb, "text") and cb.text.strip():
                all_response_texts.append(cb.text)

        messages.append({"role": "assistant", "content": llm_response.content})
        messages.append({"role": "user", "content": tool_results})

        if status_callback:
            await status_callback({"phase": "analysis", "message": "Reviewing tool results..."})

        if token_callback:
            await token_callback("\n\n")

        llm_response = await _call_claude_messages_create(
            status_callback=status_callback,
            status_phase="analysis",
            status_message="Reviewing tool results...",
            token_callback=token_callback,
            model=request.model,
            max_tokens=4096,
            tools=claude_tools,
            messages=messages,
        )
        if getattr(llm_response, "usage", None):
            _accumulate_usage(usage_totals, llm_response.usage)

    # Capture text from the final response too
    for cb in llm_response.content:
        if hasattr(cb, "text") and cb.text.strip():
            all_response_texts.append(cb.text)
    response_text = "\n\n".join(all_response_texts)

    # Store full outputs out-of-band so the frontend can fetch them without
    # bloating the SSE final event.
    _tool_output_store[request_id] = {"calls": all_tool_calls, "created_at": datetime.now()}

    return {
        "response": response_text,
        "request_id": request_id,
        "tool_calls": _tool_calls_metadata(all_tool_calls),
        "tool_time": round(total_tool_time, 2),
        "usage": _build_usage_summary(request.model, usage_totals),
    }


async def _get_account_mcp_or_raise(account_id: Optional[str]) -> MCPBridge:
    if not _is_valid_account_id(account_id):
        raise HTTPException(status_code=400, detail="No account selected. Please select an account first.")
    mcp = await get_or_create_account_mcp(account_id)  # type: ignore[arg-type]
    if not mcp:
        raise HTTPException(status_code=400, detail="No account selected. Please select an account first.")
    if not mcp.process or mcp.process.poll() is not None:
        raise HTTPException(status_code=500, detail="MCP server not running. Please try again.")
    return mcp


@app.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request):
    """Handle chat requests with Claude API and MCP tools."""
    account_id = request.account_id
    if PUBLIC_MODE:
        jwt_user = await get_jwt_user(http_request)
        account_id = jwt_user.get("tenantId")
    session_mcp = await _get_account_mcp_or_raise(account_id)

    try:
        async with _maybe_timeout(CHAT_REQUEST_TIMEOUT_SECONDS):
            return await _run_chat_pipeline(request, session_mcp)
    except TimeoutError:
        raise HTTPException(status_code=504, detail=_chat_timeout_detail())
    except Exception as e:
        print(f"Error in chat: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request):
    """Handle chat requests via SSE with progress events and heartbeats."""
    account_id = request.account_id
    if PUBLIC_MODE:
        jwt_user = await get_jwt_user(http_request)
        account_id = jwt_user.get("tenantId")
    session_mcp = await _get_account_mcp_or_raise(account_id)

    async def event_generator():
        queue: asyncio.Queue[str] = asyncio.Queue()
        done = asyncio.Event()

        async def send_event(event: str, payload: Dict[str, Any]) -> None:
            await queue.put(f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n")

        async def worker():
            terminal_sent = False
            try:
                async with _maybe_timeout(CHAT_REQUEST_TIMEOUT_SECONDS):
                    result = await _run_chat_pipeline(
                        request,
                        session_mcp,
                        status_callback=lambda payload: send_event("status", payload),
                        token_callback=lambda chunk: send_event("token", {"text": chunk}),
                    )
                try:
                    payload_len = len(json.dumps(result, default=str))
                    print(f"[chat-stream] final payload bytes={payload_len}")
                except Exception:
                    pass
                await send_event("final", result)
                terminal_sent = True
            except TimeoutError:
                await send_event("error", {"status": 504, "detail": _chat_timeout_detail()})
                terminal_sent = True
            except HTTPException as e:
                await send_event(
                    "error",
                    {"status": e.status_code, "detail": str(e.detail)},
                )
                terminal_sent = True
            except asyncio.CancelledError:
                print("[chat-stream] worker cancelled")
                raise
            except Exception as e:
                print(f"Error in chat stream: {e}")
                await send_event("error", {"status": 500, "detail": str(e)})
                terminal_sent = True
            finally:
                if not terminal_sent:
                    try:
                        await send_event(
                            "error",
                            {
                                "status": 500,
                                "detail": "Stream ended unexpectedly before completion.",
                            },
                        )
                    except Exception:
                        pass
                done.set()

        async def heartbeat():
            while not done.is_set():
                await asyncio.sleep(10)
                # Use a proper SSE event (not comment-only) to avoid intermediary buffering/idle drops.
                await send_event("ping", {"ts": datetime.utcnow().isoformat()})

        worker_task = asyncio.create_task(worker())
        heartbeat_task = asyncio.create_task(heartbeat())

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield item
                except asyncio.TimeoutError:
                    # Drain any late-arriving items after worker completion before closing stream.
                    if done.is_set():
                        while not queue.empty():
                            yield queue.get_nowait()
                        if queue.empty():
                            break
                    continue
        finally:
            for task in (heartbeat_task, worker_task):
                task.cancel()
            await asyncio.gather(heartbeat_task, worker_task, return_exceptions=True)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/api/accounts")
async def get_accounts(http_request: Request):
    """Fetch available accounts from Finout internal API (with caching)."""
    global _account_cache, _account_cache_time

    # In public mode, return a single account derived from the JWT
    if PUBLIC_MODE:
        jwt_user = await get_jwt_user(http_request)
        tenant_id = jwt_user.get("tenantId", "")
        email = jwt_user.get("email", "")
        return {
            "accounts": [{"name": email, "accountId": tenant_id}],
            "current_account_id": None,
            "cached": False,
        }

    try:
        # Check if cache is valid
        now = datetime.now()
        if (_account_cache is not None and
            _account_cache_time is not None and
            now - _account_cache_time < _account_cache_ttl):
            print(f"Using cached accounts ({len(_account_cache)} accounts, age: {(now - _account_cache_time).seconds}s)")
            return {
                "accounts": _account_cache,
                "current_account_id": None,
                "cached": True
            }

        import httpx

        # Resolve Finout API URL
        internal_api_url = (
            os.getenv("FINOUT_API_URL")
            or os.getenv("FINOUT_INTERNAL_API_URL")
            or "https://app.finout.io"
        )

        print(f"Fetching accounts from: {internal_api_url}/account-service/account?isActive=true")

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            headers = {"authorized-user-roles": "sysAdmin"}
            accounts_response = await http_client.get(
                f"{internal_api_url}/account-service/account",
                headers=headers,
                params={"isActive": "true"}
            )

            print(f"Account API Status: {accounts_response.status_code}")
            print(f"Account API Response: {accounts_response.text[:500]}")

            accounts_response.raise_for_status()
            accounts = accounts_response.json()

            account_list = []
            if isinstance(accounts, list):
                for account in accounts:
                    general_config = account.get("generalConfig", {})
                    if general_config.get("aiFeaturesEnabled", False):
                        account_list.append({
                            "name": account.get("name", "Unknown"),
                            "accountId": account.get("accountId", "")
                        })
            elif isinstance(accounts, dict) and "accounts" in accounts:
                for account in accounts["accounts"]:
                    general_config = account.get("generalConfig", {})
                    if general_config.get("aiFeaturesEnabled", False):
                        account_list.append({
                            "name": account.get("name", "Unknown"),
                            "accountId": account.get("accountId", "")
                        })

            print(f"Loaded {len(account_list)} accounts (cached for {_account_cache_ttl.seconds}s)")

            _account_cache = account_list
            _account_cache_time = now

            return {
                "accounts": account_list,
                "current_account_id": None,
                "cached": False
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching accounts: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat/tool-outputs/{request_id}")
async def get_tool_outputs(request_id: str):
    """Return full tool call outputs for a completed chat request (out-of-band fetch)."""
    entry = _tool_output_store.get(request_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Tool outputs not found or expired")
    return {"tool_calls": entry["calls"]}


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
        user_email = request.get("user_email")
        account_name = request.get("account_name")

        if not all([name, account_id, model, messages]):
            raise HTTPException(status_code=400, detail="Missing required fields")

        conversation = await db.save_conversation(
            name=name,
            account_id=account_id,
            model=model,
            messages=messages,
            tool_calls=tool_calls,
            conversation_id=request.get("conversation_id"),
            user_email=user_email,
            account_name=account_name,
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

# ── User Memories Endpoints ───────────────────────────────────────────────────


@app.get("/api/memories")
async def get_memories(user_email: str, account_id: str):
    """Get memories for a user+account pair."""
    try:
        memories = await db.get_memories(user_email, account_id)
        return {"memories": memories}
    except Exception as e:
        print(f"Error getting memories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str):
    """Delete a specific memory."""
    try:
        success = await db.delete_memory(memory_id)
        if not success:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Suggested Queries Endpoint ───────────────────────────────────────────────

_FALLBACK_QUERIES = [
    "What are my top 5 most expensive services this month?",
    "Show me unusual spending spikes from the past week",
    "What are my biggest cost optimization opportunities?",
    "How am I tracking against my budgets this month?",
    "What dashboards and views are set up for this account?",
    "How much did I spend on compute vs storage last month?",
]

# Per-account cache: account_id → (queries, timestamp)
_suggested_queries_cache: Dict[str, tuple] = {}
_SUGGESTIONS_CACHE_TTL = timedelta(minutes=10)

# Each template targets a different tool so users discover the full surface area.
# "{tag}" and "{cc}" are replaced with account-specific values.
_TOOL_QUERY_POOL = [
    # query_costs — cost breakdowns
    {"q": "Break down my costs by {tag} for the last 30 days", "needs": "tag"},
    {"q": "What are my top 5 most expensive {cc} services this month?", "needs": "cc"},
    {"q": "How much did I spend on {cc} last month vs this month?", "needs": "cc"},
    # compare_costs — period comparisons
    {"q": "Compare my {cc} spending this week vs last week", "needs": "cc"},
    {"q": "How has my {tag} cost distribution changed month over month?", "needs": "tag"},
    # get_anomalies — anomaly detection
    {"q": "Are there any cost anomalies in my {cc} spending?", "needs": "cc"},
    {"q": "Show me unusual spending spikes from the past week", "needs": None},
    # get_waste_recommendations — optimization
    {"q": "What waste can I eliminate in {cc}?", "needs": "cc"},
    {"q": "What are my biggest cost optimization opportunities?", "needs": None},
    # analyze_virtual_tags — tag exploration
    {"q": "Show me how my {tag} allocation works", "needs": "tag"},
    {"q": "Which {tag} values are driving the most spend?", "needs": "tag"},
    # get_financial_plans — budgets
    {"q": "How am I tracking against my budgets this month?", "needs": None},
    # discover_context — dashboards/views
    {"q": "What dashboards and views are set up for this account?", "needs": None},
    # compare across providers
    {"q": "Compare my {cc1} vs {cc2} spending this month", "needs": "multi_cc"},
]


def _extract_virtual_tags(filters_md: str) -> List[Dict[str, Any]]:
    """Extract virtual tag names and value counts from filter markdown."""
    import re

    tags: List[Dict[str, Any]] = []
    in_virtualtag_section = False

    for line in filters_md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            in_virtualtag_section = "VIRTUALTAG" in stripped.upper()
            continue
        if stripped.startswith("### ") or stripped.startswith("Total filters"):
            continue
        if not in_virtualtag_section:
            continue

        # Extract path and value_count from: - **uuid** (path: `Virtual Tags/Team`, 42 values)
        path_match = re.search(r"path:\s*`([^`]+)`", line)
        count_match = re.search(r"(\d+)\s+values", line)
        if not path_match:
            continue

        raw_path = path_match.group(1).strip()

        # Skip UUIDs
        if re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            raw_path,
            re.IGNORECASE,
        ):
            continue

        # Use only the last segment of hierarchical paths like "Virtual Tags/FinOps/Team"
        name = raw_path.rsplit("/", 1)[-1].strip()
        if not name:
            continue

        value_count = int(count_match.group(1)) if count_match else 0
        tags.append({"name": name, "value_count": value_count})

    return tags


def _build_queries_from_context(context_text: str, filters_text: str) -> List[str]:
    """Build personalized queries from MCP tool results, rotating across tools."""
    import random

    # Parse the JSON returned by MCP tools
    try:
        context_data = json.loads(context_text) if context_text else {}
    except (json.JSONDecodeError, TypeError):
        context_data = {}

    try:
        filters_data = json.loads(filters_text) if filters_text else {}
    except (json.JSONDecodeError, TypeError):
        filters_data = {}

    # Extract cost centers (skip virtualTag)
    cost_centers: List[str] = [
        cc for cc in context_data.get("cost_centers", {})
        if cc.lower() != "virtualtag"
    ]

    # Extract virtual tags, sorted by value_count descending (higher = more useful)
    filters_md = filters_data.get("filters", "")
    raw_tags = _extract_virtual_tags(filters_md)
    raw_tags.sort(key=lambda t: t["value_count"], reverse=True)
    # Take top tags by value count (most meaningful for cost breakdowns)
    top_tags = [t["name"] for t in raw_tags[:8]]

    # Build candidate queries by filling templates with account data
    candidates: List[str] = []

    # Shuffle to rotate across tools on each cache refresh
    pool = list(_TOOL_QUERY_POOL)
    random.shuffle(pool)

    for tmpl in pool:
        needs = tmpl["needs"]
        q = tmpl["q"]

        if needs == "tag" and top_tags:
            tag = top_tags[len([c for c in candidates if "{tag}" not in c and needs == "tag"]) % len(top_tags)]
            candidates.append(q.replace("{tag}", tag))
        elif needs == "cc" and cost_centers:
            cc = cost_centers[len(candidates) % len(cost_centers)]
            candidates.append(q.replace("{cc}", cc))
        elif needs == "multi_cc" and len(cost_centers) >= 2:
            candidates.append(q.replace("{cc1}", cost_centers[0]).replace("{cc2}", cost_centers[1]))
        elif needs is None:
            candidates.append(q)

    # Deduplicate while preserving order
    seen: set = set()
    unique: List[str] = []
    for q in candidates:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    # Select 6, ensuring tool diversity: pick from different "needs" types
    result: List[str] = []
    # First pass: one from each needs type
    by_type: Dict[Optional[str], List[str]] = {}
    for tmpl, q in zip(pool, candidates):
        by_type.setdefault(tmpl["needs"], []).append(q)

    for needs_type in ["tag", "cc", None, "multi_cc"]:
        available = by_type.get(needs_type, [])
        for q in available:
            if q not in result:
                result.append(q)
                break
        if len(result) >= 6:
            break

    # Second pass: fill remaining slots from unused candidates
    for q in unique:
        if len(result) >= 6:
            break
        if q not in result:
            result.append(q)

    return result[:6]


@app.get("/api/suggested-queries")
async def get_suggested_queries(account_id: Optional[str] = None):
    """Generate context-aware suggested queries based on account data."""
    if not _is_valid_account_id(account_id):
        return {"queries": _FALLBACK_QUERIES[:6]}

    # Check cache first
    cached = _suggested_queries_cache.get(account_id)
    if cached:
        cached_queries, cached_at = cached
        if datetime.now() - cached_at < _SUGGESTIONS_CACHE_TTL:
            return {"queries": cached_queries}

    try:
        mcp_bridge = await get_or_create_account_mcp(account_id)
        if not mcp_bridge or not mcp_bridge.process or mcp_bridge.process.poll() is not None:
            return {"queries": _FALLBACK_QUERIES[:6]}

        # Fetch account context and virtual tag filters in parallel
        context_result, filters_result = await asyncio.gather(
            mcp_bridge.call_tool("get_account_context", {}),
            mcp_bridge.call_tool("list_available_filters", {}),
            return_exceptions=True,
        )

        # Gracefully handle failures
        context_str = context_result if isinstance(context_result, str) else ""
        filters_str = filters_result if isinstance(filters_result, str) else ""

        queries = _build_queries_from_context(context_str, filters_str)
        print(f"[suggested-queries] account={account_id[:8]}, "
              f"generated {len(queries)} queries (context={len(context_str)}b, filters={len(filters_str)}b)")

        # Cache the result
        _suggested_queries_cache[account_id] = (queries, datetime.now())

        return {"queries": queries}

    except Exception as e:
        print(f"Error generating suggested queries: {e}")
        return {"queries": _FALLBACK_QUERIES[:6]}


# ── OAuth endpoints for MCP client authentication ────────────────────────────


@app.get("/authorize")
async def authorize_get(request: Request):
    return await oauth_authorize_get(request)


@app.post("/authorize")
async def authorize_post(request: Request):
    return await oauth_authorize_post(request)


@app.post("/token")
async def token(request: Request):
    return await oauth_token(request)


@app.post("/register")
async def register(request: Request):
    return await oauth_register(request)


@app.get("/.well-known/oauth-protected-resource")
async def well_known_protected_resource(request: Request):
    return await oauth_protected_resource(request)


@app.get("/.well-known/oauth-authorization-server")
async def well_known_auth_server(request: Request):
    return await oauth_authorization_server(request)


# Serve frontend SPA assets (must be last — API routes above take priority)
_frontend_assets_dir = _frontend_dir()
if _frontend_assets_dir is not None:
    app.mount("/", StaticFiles(directory=str(_frontend_assets_dir), html=True), name="frontend")


def main():
    """Main entry point for BILLY server"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)

if __name__ == "__main__":
    main()
