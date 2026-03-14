"""
Finout MCP Server - Model Context Protocol server for Finout cloud cost platform.
Exposes tools, resources, and prompts for AI assistants to interact with Finout data.
"""

# Load environment variables from .env file if present
from dotenv import load_dotenv

load_dotenv()

# ruff: noqa: E402
import contextvars
import json
import logging
from datetime import datetime
from enum import StrEnum
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    TextContent,
    Tool,
)

from .finout_client import FinoutClient, InternalAuthMode
from .validation import _find_closest_values as _find_closest_values  # re-export
from .validation import (  # re-export
    _validate_filter_metadata as _validate_filter_metadata,
)
from .validation import (
    _validate_filter_values as _validate_filter_values,
)

# Initialize MCP server
server = Server("finout-mcp")

# Global client instance (will be initialized on startup)
finout_client: FinoutClient | None = None
runtime_mode: str | None = None

# ContextVar overrides — set per-request in hosted multi-user mode.
# When unset, get_client() / get_runtime_mode() fall back to the globals above.
_client_var: contextvars.ContextVar[FinoutClient | None] = contextvars.ContextVar(
    "finout_client_ctx", default=None
)
_runtime_mode_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "runtime_mode_ctx", default=None
)


def get_client() -> FinoutClient:
    """Return the active FinoutClient (contextvar first, then global)."""
    client = _client_var.get(None) or finout_client
    if client is None:
        raise RuntimeError("No FinoutClient available")
    return client


def set_request_client(client: FinoutClient) -> contextvars.Token[FinoutClient | None]:
    """Set the per-request FinoutClient via contextvar."""
    return _client_var.set(client)


def get_runtime_mode() -> str | None:
    """Return the active runtime mode (contextvar first, then global)."""
    return _runtime_mode_var.get(None) or runtime_mode


def set_request_runtime_mode(mode: str) -> contextvars.Token[str | None]:
    """Set the per-request runtime mode via contextvar."""
    return _runtime_mode_var.set(mode)


# In-memory feedback storage
feedback_log: list[dict[str, Any]] = []


class MCPMode(StrEnum):
    """Runtime mode for MCP deployment."""

    PUBLIC = "public"
    BILLY_INTERNAL = "billy-internal"


PUBLIC_TOOLS: set[str] = {
    "query_costs",
    "compare_costs",
    "list_available_filters",
    "search_filters",
    "get_filter_values",
    "get_usage_unit_types",
    "get_waste_recommendations",
    "get_anomalies",
    "get_financial_plans",
    "get_object_usages",
    "check_delete_safety",
    "get_top_movers",
    "get_unit_economics",
    "get_cost_patterns",
    "get_savings_coverage",
    "get_tag_coverage",
    "get_budget_status",
    "get_cost_statistics",
    "analyze_virtual_tags",
    "list_data_explorers",
}

BILLY_INTERNAL_EXTRA_TOOLS: set[str] = {
    "create_view",
    "debug_filters",
    "discover_context",
    "get_account_context",
    "submit_feedback",
    "create_dashboard",
    "render_chart",
}

BILLY_INTERNAL_TOOLS: set[str] = PUBLIC_TOOLS | BILLY_INTERNAL_EXTRA_TOOLS

INTERNAL_API_TOOLS: set[str] = {
    "query_costs",
    "compare_costs",
    "list_available_filters",
    "search_filters",
    "get_filter_values",
    "get_usage_unit_types",
    "debug_filters",
    "discover_context",
    "get_account_context",
    "get_anomalies",
    "get_financial_plans",
    "create_view",
    "create_dashboard",
    "analyze_virtual_tags",
    "get_top_movers",
    "get_unit_economics",
    "get_cost_patterns",
    "get_savings_coverage",
    "get_tag_coverage",
    "get_budget_status",
    "get_cost_statistics",
    "list_data_explorers",
}

KEY_SECRET_TOOLS: set[str] = {
    "get_waste_recommendations",
}


def _auto_granularity(time_period: str) -> str:
    """Choose the coarsest time bucket that fits the period exactly."""
    if time_period in (
        "this_week",
        "last_week",
        "two_weeks_ago",
        "week_before_last",
    ):
        return "weekly"
    if time_period in ("this_month", "last_month", "month_to_date"):
        return "monthly"
    if time_period == "last_quarter":
        return "monthly"
    if " to " in time_period:
        try:
            start_str, end_str = time_period.split(" to ", 1)
            start = datetime.strptime(start_str.strip(), "%Y-%m-%d")
            end = datetime.strptime(end_str.strip(), "%Y-%m-%d")
            duration_days = (end - start).days + 1
            if duration_days == 7:
                return "weekly"
            if duration_days >= 28:
                return "monthly"
        except ValueError:
            pass
    return "daily"


logger = logging.getLogger(__name__)


def _allowed_tools_for_runtime() -> set[str]:
    """Used by call_tool to check access. Also re-exported in tool_schemas."""
    if get_runtime_mode() == MCPMode.BILLY_INTERNAL.value:
        return BILLY_INTERNAL_TOOLS
    return PUBLIC_TOOLS


def _init_client_for_mode(mode: MCPMode) -> FinoutClient:
    """Initialize Finout client for a fixed runtime mode."""
    import os

    internal_api_url = os.getenv("FINOUT_API_URL") or "https://app.finout.io"

    if mode == MCPMode.PUBLIC:
        return FinoutClient(
            internal_api_url=internal_api_url,
            internal_auth_mode=InternalAuthMode.KEY_SECRET,
            allow_missing_credentials=False,
        )

    return FinoutClient(
        internal_api_url=internal_api_url,
        account_id=os.getenv("FINOUT_ACCOUNT_ID"),
        internal_auth_mode=InternalAuthMode.AUTHORIZED_HEADERS,
        allow_missing_credentials=True,
    )


# Tool Definitions


@server.list_tools()
async def list_tools() -> list[Tool]:
    from .tool_schemas import list_tools as _list_tools

    return await _list_tools()


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool execution"""
    global finout_client, runtime_mode

    # Resolve the active client — contextvar (hosted) or global (stdio/billy).
    try:
        active_client = get_client()
    except RuntimeError:
        # Hosted transport can load multiple module references in some runtimes.
        # Recover shared state from the canonical module before failing auth.
        try:
            import finout_mcp_server.server as canonical_server

            if canonical_server.finout_client is not None:
                finout_client = canonical_server.finout_client
            if runtime_mode is None and canonical_server.runtime_mode is not None:
                runtime_mode = canonical_server.runtime_mode
            active_client = get_client()
        except Exception:
            return [
                TextContent(
                    type="text",
                    text="Unauthorized.",
                )
            ]

    active_mode = get_runtime_mode()

    # Recover from stale/closed HTTP clients in long-lived hosted processes.
    # Keep this attribute-safe for test doubles that are not full FinoutClient instances.
    public_client = getattr(active_client, "client", None)
    internal_client = getattr(active_client, "internal_client", None)
    public_closed = bool(public_client is not None and getattr(public_client, "is_closed", False))
    internal_closed = bool(
        internal_client is not None and getattr(internal_client, "is_closed", False)
    )
    if public_closed or internal_closed:
        active_client = FinoutClient(
            client_id=active_client.client_id,
            secret_key=active_client.secret_key,
            internal_api_url=active_client.internal_api_url,
            account_id=active_client.account_id,
            internal_auth_mode=active_client.internal_auth_mode,
            allow_missing_credentials=(active_mode == MCPMode.BILLY_INTERNAL.value),
        )
        # Update whichever storage layer is active
        if _client_var.get(None) is not None:
            _client_var.set(active_client)
        else:
            finout_client = active_client

    allowed_tools = _allowed_tools_for_runtime()
    if name not in allowed_tools:
        return [
            TextContent(
                type="text",
                text=(
                    "Error: Tool not available in this deployment mode.\n\n"
                    "This MCP deployment intentionally limits tools by runtime mode."
                ),
            )
        ]

    if name in INTERNAL_API_TOOLS and not active_client.internal_api_url:
        return [
            TextContent(
                type="text",
                text=(
                    "Error: Internal API URL not configured.\n\n"
                    "To use this tool, set:\n"
                    "  FINOUT_API_URL=https://app.finout.io"
                ),
            )
        ]

    if name in KEY_SECRET_TOOLS and (not active_client.client_id or not active_client.secret_key):
        return [
            TextContent(
                type="text",
                text="Unauthorized.",
            )
        ]

    from .observability import trace_tool

    async with trace_tool(
        name, arguments or {}, user_id=getattr(active_client, "account_id", None)
    ) as trace_ctx:
        try:
            # Clear stale curls before each tool call
            active_client.collect_curls()

            if name == "query_costs":
                result = await query_costs_impl(arguments)
            elif name == "compare_costs":
                result = await compare_costs_impl(arguments)
            elif name == "get_anomalies":
                result = await get_anomalies_impl(arguments)
            elif name == "get_financial_plans":
                result = await get_financial_plans_impl(arguments)
            elif name == "get_waste_recommendations":
                result = await get_waste_recommendations_impl(arguments)
            elif name == "list_available_filters":
                result = await list_available_filters_impl(arguments)
            elif name == "search_filters":
                result = await search_filters_impl(arguments)
            elif name == "get_filter_values":
                result = await get_filter_values_impl(arguments)
            elif name == "get_usage_unit_types":
                result = await get_usage_unit_types_impl(arguments)
            elif name == "debug_filters":
                result = await debug_filters_impl(arguments)
            elif name == "discover_context":
                result = await discover_context_impl(arguments or {})
            elif name == "get_account_context":
                result = await get_account_context_impl()
            elif name == "submit_feedback":
                result = await submit_feedback_impl(arguments)
            elif name == "create_view":
                result = await create_view_impl(arguments)
            elif name == "create_dashboard":
                result = await create_dashboard_impl(arguments)
            elif name == "render_chart":
                result = await render_chart_impl(arguments)
            elif name == "analyze_virtual_tags":
                result = await analyze_virtual_tags_impl(arguments or {})
            elif name == "get_object_usages":
                result = await get_object_usages_impl(arguments)
            elif name == "check_delete_safety":
                result = await check_delete_safety_impl(arguments)
            elif name == "get_top_movers":
                result = await get_top_movers_impl(arguments)
            elif name == "get_unit_economics":
                result = await get_unit_economics_impl(arguments)
            elif name == "get_cost_patterns":
                result = await get_cost_patterns_impl(arguments)
            elif name == "get_savings_coverage":
                result = await get_savings_coverage_impl(arguments)
            elif name == "get_tag_coverage":
                result = await get_tag_coverage_impl(arguments)
            elif name == "get_budget_status":
                result = await get_budget_status_impl(arguments)
            elif name == "get_cost_statistics":
                result = await get_cost_statistics_impl(arguments)
            elif name == "list_data_explorers":
                result = await list_data_explorers_impl(arguments or {})
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            # Attach debug curl commands only for internal BILLY mode.
            curls = active_client.collect_curls()
            if active_mode == MCPMode.BILLY_INTERNAL.value and curls and isinstance(result, dict):
                result["_debug_curl"] = curls

            trace_ctx["output"] = {"status": "success"}
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except ValueError as e:
            # User-friendly error for validation issues
            error_msg = str(e)
            trace_ctx["output"] = {
                "status": "error",
                "error": error_msg,
                "error_type": "ValueError",
            }
            if "authentication failed" in error_msg.lower() or "credentials" in error_msg.lower():
                return [TextContent(type="text", text="Unauthorized.")]
            if "Internal API URL not configured" in error_msg:
                return [
                    TextContent(
                        type="text",
                        text=(
                            "❌ Internal API not configured\n\n"
                            "To use this tool, set the following environment variable:\n"
                            "  FINOUT_API_URL=https://app.finout.io\n\n"
                            f"Original error: {error_msg}"
                        ),
                    )
                ]
            else:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Validation Error: {error_msg}\n\nPlease check your parameters and try again.",
                    )
                ]
        except Exception as e:
            # Include exception type and traceback for debugging
            import traceback

            error_trace = traceback.format_exc()
            trace_ctx["output"] = {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }
            return [
                TextContent(
                    type="text",
                    text=(
                        f"❌ Error executing {name}: {str(e)}\n\n"
                        f"Exception type: {type(e).__name__}\n\n"
                        "Debug info:\n"
                        f"{error_trace[-1000:]}"  # Last 1000 chars of trace
                    ),
                )
            ]


# Tool implementations live in tools/ subpackage.
# Re-export for backward compatibility (tests import from server).
from .tools import (  # noqa: E402
    _compute_summary as _compute_summary,
)
from .tools import (
    _fetch_virtual_tag_live_values as _fetch_virtual_tag_live_values,
)
from .tools import (
    _get_reallocation_info as _get_reallocation_info,
)
from .tools import (
    _infer_tag_type as _infer_tag_type,
)
from .tools import (
    _notable_tags as _notable_tags,
)
from .tools import (
    analyze_virtual_tags_impl as analyze_virtual_tags_impl,
)
from .tools import (
    check_delete_safety_impl as check_delete_safety_impl,
)
from .tools import (
    compare_costs_impl as compare_costs_impl,
)
from .tools import (
    create_dashboard_impl as create_dashboard_impl,
)
from .tools import (
    create_view_impl as create_view_impl,
)
from .tools import (
    debug_filters_impl as debug_filters_impl,
)
from .tools import (
    discover_context_impl as discover_context_impl,
)
from .tools import (
    get_account_context_impl as get_account_context_impl,
)
from .tools import (
    get_anomalies_impl as get_anomalies_impl,
)
from .tools import (  # noqa: E402
    get_budget_status_impl as get_budget_status_impl,
)
from .tools import (
    get_cost_patterns_impl as get_cost_patterns_impl,
)
from .tools import (
    get_cost_statistics_impl as get_cost_statistics_impl,
)
from .tools import (
    get_filter_values_impl as get_filter_values_impl,
)
from .tools import (
    get_financial_plans_impl as get_financial_plans_impl,
)
from .tools import (
    get_object_usages_impl as get_object_usages_impl,
)
from .tools import (
    get_savings_coverage_impl as get_savings_coverage_impl,
)
from .tools import (
    get_tag_coverage_impl as get_tag_coverage_impl,
)
from .tools import (
    get_top_movers_impl as get_top_movers_impl,
)
from .tools import (
    get_unit_economics_impl as get_unit_economics_impl,
)
from .tools import (
    get_usage_unit_types_impl as get_usage_unit_types_impl,
)
from .tools import (
    get_waste_recommendations_impl as get_waste_recommendations_impl,
)
from .tools import (
    list_available_filters_impl as list_available_filters_impl,
)
from .tools import (
    list_data_explorers_impl as list_data_explorers_impl,
)
from .tools import (
    query_costs_impl as query_costs_impl,
)
from .tools import (
    render_chart_impl as render_chart_impl,
)
from .tools import (
    search_filters_impl as search_filters_impl,
)
from .tools import (
    submit_feedback_impl as submit_feedback_impl,
)
from .tools import (
    summarize_cost_data as summarize_cost_data,
)
from .tools.cost import format_currency as format_currency  # noqa: E402

# Resource and Prompt Definitions


@server.list_resources()
async def list_resources() -> list[Resource]:
    from .resources import list_resources as _list_resources

    return await _list_resources()


@server.read_resource()
async def read_resource(uri: str) -> str:
    from .resources import read_resource as _read_resource

    return await _read_resource(uri)


@server.list_prompts()
async def list_prompts() -> list[dict]:
    from .prompts import list_prompts as _list_prompts

    return await _list_prompts()


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None) -> dict:
    from .prompts import get_prompt as _get_prompt

    return await _get_prompt(name, arguments)


def _main_with_mode(mode: MCPMode) -> None:
    """Main entry point for the MCP server with fixed mode."""
    global finout_client, runtime_mode

    try:
        runtime_mode = mode.value
        finout_client = _init_client_for_mode(mode)

        import sys

        print(f"✓ Finout MCP Server started in mode: {mode.value}", file=sys.stderr)
    except Exception as e:
        import sys

        print(f"✗ Failed to initialize Finout client: {e}", file=sys.stderr)
        raise

    # Run the server
    import asyncio

    from .observability import shutdown as observability_shutdown

    async def run_server():
        """Run the MCP server using stdio transport"""
        try:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())
        finally:
            observability_shutdown()

    asyncio.run(run_server())


def main() -> None:
    """Public MCP entry point (customer-facing)."""
    import sys

    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(
            "finout-mcp - Finout public MCP server\n\n"
            "Required env vars at runtime:\n"
            "  FINOUT_CLIENT_ID\n"
            "  FINOUT_SECRET_KEY\n"
        )
        return

    _main_with_mode(MCPMode.PUBLIC)


def main_billy_internal() -> None:
    """Internal MCP entry point used by BILLY only."""
    _main_with_mode(MCPMode.BILLY_INTERNAL)


if __name__ == "__main__":
    main()
