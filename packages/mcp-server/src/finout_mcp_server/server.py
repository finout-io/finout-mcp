"""
Finout MCP Server - Model Context Protocol server for Finout cloud cost platform.
Exposes tools, resources, and prompts for AI assistants to interact with Finout data.
"""

# Load environment variables from .env file if present
from dotenv import load_dotenv

load_dotenv()

# ruff: noqa: E402
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    AnyUrl,
    Resource,
    TextContent,
    Tool,
)

from .finout_client import CostType, FinoutClient, InternalAuthMode

# Initialize MCP server
server = Server("finout-mcp-server")

# Global client instance (will be initialized on startup)
finout_client: FinoutClient | None = None
runtime_mode: str | None = None

# In-memory feedback storage
feedback_log: list[dict[str, Any]] = []


class MCPMode(StrEnum):
    """Runtime mode for MCP deployment."""

    PUBLIC = "public"
    VECTIQOR_INTERNAL = "vectiqor-internal"


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
    "create_view",
}

VECTIQOR_INTERNAL_EXTRA_TOOLS: set[str] = {
    "debug_filters",
    "discover_context",
    "get_account_context",
    "submit_feedback",
    "create_dashboard",
}

VECTIQOR_INTERNAL_TOOLS: set[str] = PUBLIC_TOOLS | VECTIQOR_INTERNAL_EXTRA_TOOLS

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
}

KEY_SECRET_TOOLS: set[str] = {
    "get_waste_recommendations",
}


def _allowed_tools_for_runtime() -> set[str]:
    if runtime_mode == MCPMode.VECTIQOR_INTERNAL.value:
        return VECTIQOR_INTERNAL_TOOLS
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


def format_currency(amount: float) -> str:
    """Format currency with thousands separator"""
    return f"${amount:,.2f}"


def summarize_cost_data(data: dict, max_items: int = 50) -> dict:
    """
    Summarize cost data to avoid overwhelming the LLM with too much detail.
    Groups small items into "Other" category.

    Args:
        data: Raw cost query response
        max_items: Maximum number of items to return explicitly

    Returns:
        Summarized cost data
    """
    # This is a simplified implementation
    # In production, you'd parse Finout's actual response structure

    if "breakdown" in data and isinstance(data["breakdown"], list):
        breakdown = data["breakdown"]

        if len(breakdown) <= max_items:
            return data

        # Sort by cost descending
        sorted_breakdown = sorted(breakdown, key=lambda x: x.get("cost", 0), reverse=True)

        # Keep top items, sum the rest
        top_items = sorted_breakdown[:max_items]
        other_items = sorted_breakdown[max_items:]
        other_total = sum(item.get("cost", 0) for item in other_items)

        if other_total > 0:
            top_items.append({"name": f"Other ({len(other_items)} items)", "cost": other_total})

        data["breakdown"] = top_items
        data["_summarized"] = True
        data["_total_items"] = len(breakdown)

    return data


# Tool Definitions


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available Finout MCP tools"""
    all_tools = [
        Tool(
            name="query_costs",
            description=(
                "Query cloud costs AND usage with flexible filters and grouping.\n\n"
                "WHEN TO USE: When the user asks about spending, costs, bills, expenses, "
                "or usage for any cloud service or resource.\n\n"
                "WORKFLOW (follow this order):\n"
                "1) ALWAYS call search_filters first to find relevant filters (unless you already have filter metadata)\n"
                "2) Copy the FULL filter object from search results (costCenter, key, path, type)\n"
                "3) Preserve EXACT capitalization - cost centers are case-sensitive!\n"
                "4) Add operator ('is' for equals) and value (single string), then query\n\n"
                "TIME-SERIES: The API always returns daily time-series data automatically. "
                "Every result includes a nested 'data' array with daily cost points. "
                "To get 'daily cost by service': use group_by with a service dimension — "
                "each service row will have daily cost points. No extra parameter needed.\n\n"
                "PRESENTING RESULTS: The UI auto-renders a chart from the result data. "
                "Give 2-4 sentences of key insights: total, biggest driver, notable trend. "
                "No table or raw data dump needed.\n\n"
                "COST + USAGE IN ONE QUERY:\n"
                "- Cost is ALWAYS returned in results\n"
                "- To ALSO get usage: Provide usage_configuration\n"
                "- Call get_usage_unit_types BEFORE any usage query to discover valid units\n"
                "- Chain: get_usage_unit_types → query_costs with usage_configuration\n\n"
                "USAGE EXAMPLES:\n"
                '- AWS EC2 hours: {"usageType": "usageAmount", "costCenter": "amazon-cur", "units": "Hrs"}\n'
                '- Azure hours: {"usageType": "usageAmount", "costCenter": "Azure", "units": "1 Hour"}\n'
                '- GCP hours: {"usageType": "usageAmount", "costCenter": "GCP", "units": "Hour"}\n\n'
                "FILTER EXAMPLES:\n\n"
                "Standard column (service):\n"
                "filters: [{'costCenter': 'amazon-cur', 'key': 'finrichment_product_name', "
                "'path': 'AMAZON-CUR/Product', 'type': 'col', 'operator': 'is', 'value': 'ec2'}]\n\n"
                "Kubernetes deployment:\n"
                "filters: [{'costCenter': 'kubernetes', 'key': 'deployment', "
                "'path': 'Kubernetes/Resources/deployment', 'type': 'namespace_object', "
                "'operator': 'oneOf', 'value': ['refresh-web', 'refresh-notifications']}]\n\n"
                "Custom tag:\n"
                "filters: [{'costCenter': 'amazon-cur', 'key': 'environment', "
                "'path': 'AWS/Tags/environment', 'type': 'tag', 'operator': 'is', 'value': 'production'}]\n\n"
                "CRITICAL RULES:\n"
                "- NEVER guess the filter type - ALWAYS use search_filters first\n"
                "- COPY the exact 'type' value from search results\n"
                "- operator: 'is' for single value, 'oneOf' for multiple values (OR)\n"
                "- value: String for 'is', array for 'oneOf'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "description": (
                            "Time period to analyze. Supports:\n"
                            "- Predefined: today, yesterday, last_7_days, this_week, last_week, "
                            "two_weeks_ago, last_30_days, this_month, last_month, last_quarter\n"
                            "- Custom range: 'YYYY-MM-DD to YYYY-MM-DD' (e.g., '2026-01-24 to 2026-01-31')\n"
                            "- This allows comparing specific date ranges like 'last 7 days of each month'"
                        ),
                        "default": "last_30_days",
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "costCenter": {
                                    "type": "string",
                                    "description": "Cost center (from search_filters result)",
                                },
                                "key": {
                                    "type": "string",
                                    "description": "Filter key (from search_filters result)",
                                },
                                "path": {
                                    "type": "string",
                                    "description": "Filter path (from search_filters result)",
                                },
                                "type": {
                                    "type": "string",
                                    "description": (
                                        "Filter type - MUST copy EXACT value from search_filters! "
                                        "Common types: 'col' (columns), 'tag' (tags), "
                                        "'namespace_object' (K8s resources like deployment/pod/service). "
                                        "DO NOT guess - always use the exact type from search results!"
                                    ),
                                },
                                "operator": {
                                    "type": "string",
                                    "description": "Filter operator: 'is' for single value, 'oneOf' for multiple values",
                                    "default": "is",
                                    "enum": ["is", "oneOf", "not", "notOneOf"],
                                },
                                "value": {
                                    "description": "Filter value: string for 'is' operator, array of strings for 'oneOf' operator",
                                    "oneOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "string"}},
                                    ],
                                },
                            },
                            "required": ["costCenter", "key", "path", "type", "value"],
                        },
                        "description": (
                            "Optional: Filters from search_filters. "
                            "MUST include costCenter, key, path, type from search results!"
                        ),
                    },
                    "group_by": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "costCenter": {"type": "string"},
                                "key": {"type": "string"},
                                "path": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "description": "Filter type: 'col' for columns, 'resource' for resources (RDS/SQS/K8s/ECR), 'tag' for tags",
                                    "default": "col",
                                    "enum": ["col", "resource", "tag"],
                                },
                            },
                            "required": ["costCenter", "key", "path", "type"],
                        },
                        "description": (
                            "Optional: Dimensions to group by. "
                            "Must include full metadata from search_filters!"
                        ),
                    },
                    "usage_configuration": {
                        "type": "object",
                        "properties": {
                            "usageType": {
                                "type": "string",
                                "description": (
                                    "Usage type:\n"
                                    "- 'usageAmount': Raw usage quantity (default)\n"
                                    "- 'normalizedUsageAmount': Normalized usage for cross-resource comparison"
                                ),
                                "enum": ["usageAmount", "normalizedUsageAmount"],
                                "default": "usageAmount",
                            },
                            "costCenter": {
                                "type": "string",
                                "description": "Cost center for usage (e.g., 'amazon-cur' for AWS, 'Azure', 'GCP')",
                            },
                            "units": {
                                "type": "string",
                                "description": (
                                    "Units for usage - use get_usage_unit_types to discover valid units.\n"
                                    "Examples: 'Hrs', '1 Hour', 'Hour', 'Gibibyte', 'Count', 'Gibibyte month'"
                                ),
                            },
                        },
                        "required": ["usageType", "costCenter", "units"],
                        "description": (
                            "Optional: Usage configuration for querying usage ALONG WITH cost. "
                            "When provided with 'units', results include BOTH cost AND usage data. "
                            'Example: {"usageType": "usageAmount", "costCenter": "amazon-cur", "units": "Hrs"} '
                            "returns both EC2 cost AND hours used in the same query."
                        ),
                    },
                },
                "required": ["time_period"],
            },
        ),
        Tool(
            name="compare_costs",
            description=(
                "Compare cloud costs between two time periods with optional filters.\n\n"
                "WHEN TO USE: When the user says 'compare', 'vs', 'change', 'trend', "
                "'grew', 'shrank', 'increased', 'decreased', or asks about cost differences "
                "between periods (e.g., 'How do this month's EC2 costs compare to last month?').\n\n"
                "WORKFLOW: Same as query_costs - call search_filters first for filter metadata.\n\n"
                "PRESENTING RESULTS: Always include the percentage change AND absolute delta. "
                "Lead with the trend direction (up/down), then the delta, then the breakdown. "
                "Use a table for grouped comparisons."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "current_period": {
                        "type": "string",
                        "description": (
                            "Current/recent time period. Supports:\n"
                            "- Predefined: today, yesterday, last_7_days, this_week, last_week, "
                            "two_weeks_ago, last_30_days, this_month, last_month, last_quarter\n"
                            "- Custom range: 'YYYY-MM-DD to YYYY-MM-DD'"
                        ),
                    },
                    "comparison_period": {
                        "type": "string",
                        "description": (
                            "Period to compare against. Supports:\n"
                            "- Predefined: yesterday, last_7_days, this_week, last_week, "
                            "two_weeks_ago, last_30_days, this_month, last_month, last_quarter\n"
                            "- Custom range: 'YYYY-MM-DD to YYYY-MM-DD'"
                        ),
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "costCenter": {"type": "string"},
                                "key": {"type": "string"},
                                "path": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "description": (
                                        "Filter type - MUST copy EXACT value from search_filters! "
                                        "Common types: 'col' (columns), 'tag' (tags), "
                                        "'namespace_object' (K8s resources like deployment/pod/service). "
                                        "DO NOT guess - always use the exact type from search results!"
                                    ),
                                },
                                "operator": {
                                    "type": "string",
                                    "default": "is",
                                    "enum": ["is", "oneOf", "not", "notOneOf"],
                                },
                                "value": {
                                    "oneOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "string"}},
                                    ]
                                },
                            },
                            "required": ["costCenter", "key", "path", "type", "value"],
                        },
                        "description": "Optional: Filters to apply to both periods (must include full metadata)",
                    },
                    "group_by": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "costCenter": {"type": "string"},
                                "key": {"type": "string"},
                                "path": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "description": "Filter type: 'col' for columns, 'resource' for resources (RDS/SQS/K8s/ECR), 'tag' for tags",
                                    "default": "col",
                                    "enum": ["col", "resource", "tag"],
                                },
                            },
                            "required": ["costCenter", "key", "path", "type"],
                        },
                        "description": "Optional: Dimensions to group comparison by (full metadata from search_filters)",
                    },
                },
                "required": ["current_period", "comparison_period"],
            },
        ),
        Tool(
            name="debug_filters",
            description=(
                "Internal diagnostic tool for inspecting raw filter metadata.\n\n"
                "WHEN TO USE: Only when filter searches return unexpected results or "
                "you suspect the filter cache is stale/incomplete.\n\n"
                "DO NOT use for normal queries - use search_filters instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "cost_center": {
                        "type": "string",
                        "description": "Optional: Show filters for specific cost center only",
                    },
                    "filter_type": {
                        "type": "string",
                        "description": "Optional: Show only specific type (col, tag, etc.)",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_anomalies",
            description=(
                "Retrieve detected cost anomalies and spikes.\n\n"
                "WHEN TO USE: When the user mentions 'spike', 'anomaly', 'unusual', "
                "'unexpected cost', 'sudden increase', or asks about irregular spending.\n\n"
                "PRESENTING RESULTS: Highlight the biggest impact first. "
                "Show severity, affected service, cost impact, and date. "
                "Suggest investigating the top anomalies with compare_costs for root cause analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "enum": ["today", "yesterday", "last_7_days", "last_30_days"],
                        "description": "Time period to check for anomalies",
                        "default": "last_7_days",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Filter by severity level (optional)",
                    },
                },
                "required": ["time_period"],
            },
        ),
        Tool(
            name="get_financial_plans",
            description=(
                "Get financial plans (budgets and forecasts) for the account.\n\n"
                "WHEN TO USE: When the user asks about 'budget', 'financial plan', 'forecast', "
                "'planned spend', 'budget vs actual', or 'are we on track'.\n\n"
                "Each plan has line items (one per dimension value) with monthly budget and "
                "optional forecast amounts.\n\n"
                "PRESENTING RESULTS: Show the plan name, period, total budget, and top line items "
                "sorted by budget. If forecast is available, compare budget vs forecast."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Optional: Filter plans by name (partial, case-insensitive)",
                    },
                    "period": {
                        "type": "string",
                        "description": (
                            "Month to show budgets for in 'YYYY-M' format (no zero-padding). "
                            "Examples: '2026-2' for Feb 2026, '2025-12' for Dec 2025. "
                            "Defaults to current month."
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="create_view",
            description=(
                "Save the current query as a reusable view in Finout.\n\n"
                "CRITICAL: You MUST call this tool to save a view. "
                "NEVER present a view as saved without actually calling this tool. "
                "The view URL is assigned by the API — you cannot know it in advance.\n\n"
                "USER CONSENT: Ask for confirmation before saving "
                "(e.g., 'Do you want me to save this as a view?').\n\n"
                "WHEN TO USE: After answering a query_costs question, proactively offer to save it. "
                "'Would you like me to save this as a view?'\n\n"
                "Inputs: name (required), filters, group_by, time_period, cost_type"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the saved view (e.g., 'EC2 by region — last 30 days')",
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "costCenter": {"type": "string"},
                                "key": {"type": "string"},
                                "path": {"type": "string"},
                                "type": {"type": "string"},
                                "operator": {"type": "string", "default": "is"},
                                "value": {
                                    "oneOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "string"}},
                                    ]
                                },
                            },
                            "required": ["costCenter", "key", "path", "type", "value"],
                        },
                        "description": "Optional: Filters from query_costs (same format)",
                    },
                    "group_by": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "costCenter": {"type": "string"},
                                "key": {"type": "string"},
                                "path": {"type": "string"},
                                "type": {"type": "string"},
                            },
                            "required": ["costCenter", "key", "path", "type"],
                        },
                        "description": "Optional: Group-by dimensions from query_costs (same format)",
                    },
                    "time_period": {
                        "type": "string",
                        "description": "Time period (same values as query_costs)",
                        "default": "last_30_days",
                    },
                    "cost_type": {
                        "type": "string",
                        "enum": [
                            "netAmortizedCost",
                            "blendedCost",
                            "unblendedCost",
                            "amortizedCost",
                        ],
                        "description": "Cost metric type",
                        "default": "netAmortizedCost",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="create_dashboard",
            description=(
                "Create a multi-widget dashboard in Finout for complex multi-dimensional analysis.\n\n"
                "CRITICAL: You MUST call this tool to create a dashboard. "
                "NEVER describe or present a dashboard as created without actually calling this tool. "
                "The dashboard URL and widget IDs are assigned by the API — you cannot know them in advance.\n\n"
                "USER CONSENT: NEVER create dashboards automatically. "
                "Create only if the user explicitly asks or confirms creation.\n\n"
                "WHEN TO USE:\n"
                "- Simple analysis (one dimension) → use create_view instead\n"
                "  e.g., 'EC2 costs by region' → one view\n"
                "- Complex analysis (multiple dimensions or trend) → use create_dashboard\n"
                "  e.g., 'EC2 by region AND by instance type, with trend' → 3+ widgets\n\n"
                "COMPOSE WIDGETS:\n"
                "- One costUsage widget per breakdown dimension\n"
                "- One costUsage widget with x_axis_group_by='daily' for trend over time\n"
                "- One anomaly widget to show cost anomaly count (great for overview dashboards)\n"
                "- One freeText widget for a brief plain-text label or summary\n\n"
                "freeText WARNING: The widget renders PLAIN TEXT only — no markdown. "
                "Do NOT use **, #, -, *, bullet points, or any markdown formatting in text widgets. "
                "Keep freeText short (2-3 sentences max).\n\n"
                "KEEP IT SIMPLE: Dashboards with 3-5 widgets using relative time periods "
                "(e.g., last_30_days, last_7_days) are more useful and reusable than "
                "many widgets with hardcoded date ranges. Prefer relative time periods unless "
                "the user explicitly asked for a specific historical comparison.\n\n"
                "NOTE: group_by per widget is a SINGLE object (one dimension per widget), "
                "not an array. To show multiple dimensions, create multiple costUsage widgets.\n\n"
                "If an existing relevant dashboard was found via discover_context, share that "
                "URL instead of creating a new one."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Dashboard title",
                    },
                    "widgets": {
                        "type": "array",
                        "description": "List of widgets to create in this dashboard",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["costUsage", "anomaly", "freeText"],
                                    "description": (
                                        "Widget type: "
                                        "costUsage (cost chart, requires filters/group_by/date), "
                                        "anomaly (count of detected cost anomalies, just needs time_period), "
                                        "freeText (plain-text annotation)"
                                    ),
                                },
                                "name": {
                                    "type": "string",
                                    "description": "Widget title",
                                },
                                "filters": {
                                    "type": "array",
                                    "description": "costUsage: filters (same format as query_costs)",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "costCenter": {"type": "string"},
                                            "key": {"type": "string"},
                                            "path": {"type": "string"},
                                            "type": {"type": "string"},
                                            "operator": {"type": "string", "default": "is"},
                                            "value": {
                                                "oneOf": [
                                                    {"type": "string"},
                                                    {"type": "array", "items": {"type": "string"}},
                                                ]
                                            },
                                        },
                                        "required": ["costCenter", "key", "path", "type", "value"],
                                    },
                                },
                                "group_by": {
                                    "type": "object",
                                    "description": "costUsage: single group-by dimension (NOT array)",
                                    "properties": {
                                        "costCenter": {"type": "string"},
                                        "key": {"type": "string"},
                                        "path": {"type": "string"},
                                        "type": {"type": "string"},
                                    },
                                    "required": ["costCenter", "key", "path", "type"],
                                },
                                "x_axis_group_by": {
                                    "type": "string",
                                    "enum": ["daily", "monthly"],
                                    "description": "costUsage: time-based x-axis grouping for trend charts",
                                },
                                "time_period": {
                                    "type": "string",
                                    "description": "costUsage: time period (default: last_30_days)",
                                    "default": "last_30_days",
                                },
                                "cost_type": {
                                    "type": "string",
                                    "enum": [
                                        "netAmortizedCost",
                                        "blendedCost",
                                        "unblendedCost",
                                        "amortizedCost",
                                    ],
                                    "description": "costUsage: cost metric type",
                                    "default": "netAmortizedCost",
                                },
                                "text": {
                                    "type": "string",
                                    "description": "freeText: plain text content (NO markdown — the widget does not render it)",
                                },
                            },
                            "required": ["type", "name"],
                        },
                    },
                },
                "required": ["name", "widgets"],
            },
        ),
        Tool(
            name="get_waste_recommendations",
            description=(
                "Get CostGuard waste detection and optimization recommendations.\n\n"
                "WHEN TO USE: When the user asks about 'savings', 'waste', 'idle', 'optimize', "
                "'reduce costs', 'shut down', 'unused resources', or 'rightsizing'.\n\n"
                "PRESENTING RESULTS: Present as a prioritized numbered action list sorted by savings. "
                "Show total potential savings at the top. Include annual projection. "
                "For each recommendation, show resource, current cost, and potential savings."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_type": {
                        "type": "string",
                        "enum": ["idle", "rightsizing", "commitment"],
                        "description": (
                            "Type of waste to look for: "
                            "idle = unused resources, "
                            "rightsizing = over-provisioned resources, "
                            "commitment = RI/SP coverage gaps"
                        ),
                    },
                    "service": {
                        "type": "string",
                        "enum": ["ec2", "rds", "ebs", "lambda", "s3"],
                        "description": "Filter by specific cloud service (optional)",
                    },
                    "min_saving": {
                        "type": "number",
                        "description": (
                            "Minimum monthly savings threshold in dollars. "
                            "Only show recommendations above this amount."
                        ),
                        "minimum": 0,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="list_available_filters",
            description=(
                "List all available cost filters organized by cost center.\n\n"
                "WHEN TO USE: ONLY when the user explicitly asks 'what filters exist?', "
                "'what can I filter by?', or 'show me all available filters'.\n\n"
                "DO NOT use for normal cost queries - use search_filters instead. "
                "This returns a large response and should be a last resort."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "cost_center": {
                        "type": "string",
                        "description": (
                            "Optional: Filter by cost center (e.g., 'aws', 'gcp', 'k8s'). "
                            "If not specified, returns filters for all cost centers."
                        ),
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="search_filters",
            description=(
                "Your FIRST STEP for any cost question. Extract entities from the user's question "
                "and search for matching filters.\n\n"
                "WHEN TO USE: Before ANY call to query_costs or compare_costs. "
                "This discovers the filter metadata (costCenter, key, path, type) needed for queries.\n\n"
                "CHAIN: search_filters → get_filter_values (if needed to verify exact values) → query_costs\n\n"
                "Searches BOTH columns (service, region, account) AND tags (environment, team, custom labels).\n\n"
                "Examples:\n"
                "- search_filters('service') → AWS/GCP services\n"
                "- search_filters('environment') → Environment tags\n"
                "- search_filters('pod') → Kubernetes pods\n\n"
                "DO NOT show raw search results to the user. Use them to build the next query.\n\n"
                "Returns up to 50 matches sorted by relevance."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (case-insensitive, supports partial matching)",
                    },
                    "cost_center": {
                        "type": "string",
                        "description": "Optional: Limit search to specific cost center",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_filter_values",
            description=(
                "Get the actual values for a specific filter (lazy-loaded on demand).\n\n"
                "WHEN TO USE: After search_filters, when you need to verify exact values "
                "or the user asks 'what X do we have?' (e.g., 'what services do we have?', "
                "'what environments exist?').\n\n"
                "CHAIN: search_filters → get_filter_values → query_costs\n\n"
                "Increase limit (300-500) when searching for values containing a substring.\n\n"
                "EXAMPLES:\n"
                "- get_filter_values(filter_key='service', cost_center='amazon-cur', filter_type='col', limit=50)\n"
                "- get_filter_values(filter_key='deployment', cost_center='kubernetes', "
                "filter_type='namespace_object', limit=500)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filter_key": {
                        "type": "string",
                        "description": "The filter key to get values for (e.g., 'service', 'region')",
                    },
                    "cost_center": {
                        "type": "string",
                        "description": "Optional: Cost center the filter belongs to (case-insensitive)",
                    },
                    "filter_type": {
                        "type": "string",
                        "description": (
                            "Optional: Type of filter - MUST match the exact type from search_filters result! "
                            "Common: 'col' (standard), 'tag' (custom tags), 'namespace_object' (K8s resources)"
                        ),
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of values to return (default: 100)",
                        "minimum": 1,
                        "maximum": 500,
                        "default": 100,
                    },
                },
                "required": ["filter_key"],
            },
        ),
        Tool(
            name="get_usage_unit_types",
            description=(
                "Discover available usage units for a cost center (AWS, Azure, GCP, etc.).\n\n"
                "WHEN TO USE: Call this BEFORE any usage query to discover valid units. "
                "Without this, you won't know what unit types are available.\n\n"
                "CHAIN: get_usage_unit_types → query_costs with usage_configuration\n\n"
                "EXAMPLE:\n"
                "get_usage_unit_types(filters=[{'costCenter': 'global', 'key': 'cost_center_type', "
                "'path': 'Global/Cost Center', 'type': 'col', 'operator': 'is', 'value': 'AWS'}])\n"
                "→ Returns: [{'costCenter': 'amazon-cur', 'units': 'Hrs'}, ...]"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "description": "Time period for discovery (default: last_30_days)",
                        "default": "last_30_days",
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "costCenter": {"type": "string"},
                                "key": {"type": "string"},
                                "path": {"type": "string"},
                                "type": {"type": "string"},
                                "operator": {"type": "string"},
                                "value": {
                                    "oneOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "string"}},
                                    ]
                                },
                            },
                            "required": ["costCenter", "key", "path", "type", "value"],
                        },
                        "description": (
                            "Filters to narrow down cost center. "
                            "Use cost_center_type filter to get units for AWS/GCP/Azure/etc."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="discover_context",
            description=(
                "Search for how the account organizes cost/usage data related to a concept.\n\n"
                "WHEN TO USE: When the user mentions a named concept you don't recognize "
                "(team name, project name, custom grouping, application name). "
                "This reveals how the org structures their data by searching dashboards, "
                "views, and data explorers.\n\n"
                "Discovers business context including filters, virtual tags, dimensions, "
                "and groupings commonly used for the queried topic.\n\n"
                "EXAMPLES:\n"
                '- "vikings" → finds "Vikings dashboard", shows filters/groupings\n'
                '- "production" → finds production views, shows env=prod filters\n'
                '- "kafka" → finds Kafka-related dashboards and their configurations\n\n'
                "DO NOT use for standard cost queries where you already know the filter. "
                "Use search_filters instead.\n\n"
                "PRESENTING RESULTS: When dashboards are found, always share the URL so the user "
                "can open them directly. If a relevant dashboard already exists, share that link "
                "before offering to create a new one with create_dashboard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - matches against dashboard names, view names, widget configurations, data explorer names/descriptions",
                    },
                    "include_dashboards": {
                        "type": "boolean",
                        "description": "Include dashboards in search",
                        "default": True,
                    },
                    "include_views": {
                        "type": "boolean",
                        "description": "Include views (saved queries) in search",
                        "default": True,
                    },
                    "include_data_explorers": {
                        "type": "boolean",
                        "description": "Include data explorers in search",
                        "default": True,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results per category",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_account_context",
            description=(
                "Get account context: name, connected cost centers, and available filter counts.\n\n"
                "WHEN TO USE: Call this at the START of a conversation to understand "
                "what data is available. Helps you give better answers by knowing "
                "which cloud providers are connected and how much data exists.\n\n"
                "DO NOT call repeatedly - the result is stable within a session."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="submit_feedback",
            description=(
                "Submit feedback about your experience answering the user's question. "
                "Rate how well you were able to answer and note any friction points.\n\n"
                "WHEN TO CALL: Call this as your final tool call alongside wrapping up the "
                "interaction — not as a standalone response. Always pair it with your text "
                "answer; never let it be the only thing you do.\n\n"
                "WHAT TO NOTE: anything that was harder than expected, any API errors, "
                "filters that were missing or ambiguous, or things that worked especially well. "
                "Include a concrete suggestion when relevant."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "rating": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "1=couldn't answer, 2=poor, 3=adequate, 4=good, 5=excellent",
                    },
                    "query_type": {
                        "type": "string",
                        "enum": [
                            "cost_query",
                            "comparison",
                            "anomaly",
                            "waste",
                            "filter_discovery",
                            "context",
                            "other",
                        ],
                    },
                    "tools_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tools used to answer",
                    },
                    "friction_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "What made answering difficult "
                            "(e.g., 'filter not found', 'ambiguous user question', 'slow API')"
                        ),
                    },
                    "suggestion": {
                        "type": "string",
                        "description": "How the MCP could be improved to handle this better",
                    },
                },
                "required": ["rating", "query_type", "tools_used"],
            },
        ),
    ]
    allowed = _allowed_tools_for_runtime()
    return [tool for tool in all_tools if tool.name in allowed]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool execution"""
    global finout_client, runtime_mode

    # Hosted transport can load multiple module references in some runtimes.
    # Recover shared state from the canonical module before failing auth.
    if finout_client is None:
        try:
            import finout_mcp_server.server as canonical_server

            if canonical_server.finout_client is not None:
                finout_client = canonical_server.finout_client
            if runtime_mode is None and canonical_server.runtime_mode is not None:
                runtime_mode = canonical_server.runtime_mode
        except Exception:
            # Keep normal unauthorized flow below.
            pass

    if not finout_client:
        return [
            TextContent(
                type="text",
                text="Unauthorized.",
            )
        ]

    # Recover from stale/closed HTTP clients in long-lived hosted processes.
    # Keep this attribute-safe for test doubles that are not full FinoutClient instances.
    public_client = getattr(finout_client, "client", None)
    internal_client = getattr(finout_client, "internal_client", None)
    public_closed = bool(public_client is not None and getattr(public_client, "is_closed", False))
    internal_closed = bool(
        internal_client is not None and getattr(internal_client, "is_closed", False)
    )
    if public_closed or internal_closed:
        finout_client = FinoutClient(
            client_id=finout_client.client_id,
            secret_key=finout_client.secret_key,
            internal_api_url=finout_client.internal_api_url,
            account_id=finout_client.account_id,
            internal_auth_mode=finout_client.internal_auth_mode,
            allow_missing_credentials=(runtime_mode == MCPMode.VECTIQOR_INTERNAL.value),
        )

    assert finout_client is not None  # Type checker hint

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

    if name in INTERNAL_API_TOOLS and not finout_client.internal_api_url:
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

    if name in KEY_SECRET_TOOLS and (not finout_client.client_id or not finout_client.secret_key):
        return [
            TextContent(
                type="text",
                text="Unauthorized.",
            )
        ]

    try:
        # Clear stale curls before each tool call
        finout_client.collect_curls()

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
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        # Attach debug curl commands only for internal VECTIQOR mode.
        curls = finout_client.collect_curls()
        if runtime_mode == MCPMode.VECTIQOR_INTERNAL.value and curls and isinstance(result, dict):
            result["_debug_curl"] = curls

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except ValueError as e:
        # User-friendly error for validation issues
        error_msg = str(e)
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


# Tool Implementations


async def query_costs_impl(args: dict) -> dict:
    """Implementation of query_costs tool"""
    assert finout_client is not None

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")
    usage_configuration = args.get("usage_configuration")

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": (
                "This tool requires the internal cost-service API. "
                "Set FINOUT_API_URL environment variable. "
                "For legacy view-based queries, use the public API instead."
            ),
        }

    # Validate filters structure
    if filters:
        for i, f in enumerate(filters):
            required_fields = ["costCenter", "key", "path", "type", "value"]
            missing = [field for field in required_fields if field not in f]
            if missing:
                raise ValueError(
                    f"Filter {i} is missing required fields: {missing}\n\n"
                    "Filters must include: costCenter, key, path, type, value\n"
                    "These come from search_filters results. Example:\n"
                    "  {\n"
                    "    'costCenter': 'amazon-cur',\n"
                    "    'key': 'finrichment_product_name',\n"
                    "    'path': 'AMAZON-CUR/Product',\n"
                    "    'type': 'col',  ← Must be 'col' (not 'filter')\n"
                    "    'operator': 'is',\n"
                    "    'value': 'ec2'  ← Single string (not array)\n"
                    "  }"
                )

            # Validate type field
            if f.get("type") == "filter":
                raise ValueError(
                    f"Filter {i} has type='filter' but should be type='col'\n\n"
                    "⚠️ Common mistake: type should be 'col' for standard filters, not 'filter'"
                )

    # Validate group_by structure
    if group_by:
        for i, g in enumerate(group_by):
            required_fields = ["costCenter", "key", "path", "type"]
            missing = [field for field in required_fields if field not in g]
            if missing:
                raise ValueError(
                    f"group_by {i} is missing required fields: {missing}\n\n"
                    "group_by must include: costCenter, key, path, type\n"
                    "Copy these from search_filters results (same as filter structure minus operator/value)"
                )

    # Query costs using internal API
    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        usage_configuration=usage_configuration,
    )

    # Summarize to avoid context overload
    summarized = summarize_cost_data(data, max_items=50)

    # Format response
    return {
        "time_period": time_period,
        "filters": filters,
        "group_by": group_by,
        "data": summarized,
        "query_timestamp": datetime.now().isoformat(),
        "_presentation_hint": (
            "The UI renders a chart automatically. Give 2-4 sentences: "
            "total cost, biggest driver, notable trend. No table needed."
        ),
    }


async def compare_costs_impl(args: dict) -> dict:
    """Implementation of compare_costs tool"""
    assert finout_client is not None

    current_period = args["current_period"]
    comparison_period = args["comparison_period"]
    filters = args.get("filters", [])
    group_by = args.get("group_by")

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": (
                "This tool requires the internal cost-service API. "
                "Set FINOUT_API_URL environment variable."
            ),
        }

    # Query both periods with same filters
    current_data = await finout_client.query_costs_with_filters(
        time_period=current_period,
        filters=filters if filters else None,
        group_by=group_by,
    )

    comparison_data = await finout_client.query_costs_with_filters(
        time_period=comparison_period,
        filters=filters if filters else None,
        group_by=group_by,
    )

    # Extract totals from API response
    # API returns a list of items, each with totalCost
    def extract_total(data):
        """Extract total cost from API response"""
        if isinstance(data, list):
            if not data:
                return 0
            # If ungrouped, first item has the total
            if len(data) == 1:
                return data[0].get("totalCost", 0)
            # If grouped, sum all items except "Total" row
            return sum(item.get("totalCost", 0) for item in data if item.get("name") != "Total")
        elif isinstance(data, dict):
            # Fallback for dict format
            return data.get("totalCost", data.get("total", 0))
        return 0

    current_total = extract_total(current_data)
    comparison_total = extract_total(comparison_data)

    delta = current_total - comparison_total
    pct_change = ((delta / comparison_total) * 100) if comparison_total > 0 else 0

    # Format breakdown if grouped
    breakdown = None
    if group_by and isinstance(current_data, list) and isinstance(comparison_data, list):
        breakdown = []
        # Create a dict for easy lookup
        comparison_dict = {
            item.get("name", "Unknown"): item.get("totalCost", 0)
            for item in comparison_data
            if item.get("name") != "Total"
        }

        for curr_item in current_data:
            name = curr_item.get("name", "Unknown")
            if name == "Total":
                continue

            curr_cost = curr_item.get("totalCost", 0)
            comp_cost = comparison_dict.get(name, 0)
            item_delta = curr_cost - comp_cost
            item_pct = ((item_delta / comp_cost) * 100) if comp_cost > 0 else 0

            breakdown.append(
                {
                    "name": name,
                    "current_cost": format_currency(curr_cost),
                    "comparison_cost": format_currency(comp_cost),
                    "delta": format_currency(item_delta),
                    "percent_change": round(item_pct, 2),
                    "trend": "↑" if item_delta > 0 else "↓" if item_delta < 0 else "→",
                }
            )

        # Sort by delta (largest changes first)
        breakdown.sort(key=lambda x: abs(x["percent_change"]), reverse=True)

    result = {
        "current_period": current_period,
        "current_total": format_currency(current_total),
        "comparison_period": comparison_period,
        "comparison_total": format_currency(comparison_total),
        "delta": format_currency(delta),
        "percent_change": round(pct_change, 2),
        "trend": "↑" if delta > 0 else "↓" if delta < 0 else "→",
        "summary": (
            f"{current_period} costs are {format_currency(abs(delta))} "
            f"({'higher' if delta > 0 else 'lower'} than {comparison_period} "
            f"({abs(pct_change):.1f}% {'increase' if delta > 0 else 'decrease'})"
        ),
        "filters": filters,
    }

    if breakdown:
        result["breakdown_by_group"] = breakdown[:10]  # Top 10 changes

    result["_presentation_hint"] = (
        "Lead with the trend (up/down), then the delta, then the breakdown. "
        "Always include both percentage and absolute dollar change."
    )

    return result


async def get_anomalies_impl(args: dict) -> dict:
    """Implementation of get_anomalies tool"""
    assert finout_client is not None

    time_period = args.get("time_period", "last_7_days")
    severity = args.get("severity")

    anomalies = await finout_client.get_anomalies(time_period=time_period, severity=severity)

    total_impact = sum(a.get("cost_impact", 0) for a in anomalies)

    formatted_anomalies = []
    for anomaly in anomalies:
        raw_date = anomaly.get("date")
        try:
            ts = int(raw_date) / 1000 if raw_date is not None else 0
        except (TypeError, ValueError):
            ts = 0
        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "Unknown"
        percent_over_expected = float(anomaly.get("percent_over_expected", 0) or 0)
        formatted_anomalies.append(
            {
                "date": date_str,
                "alert_name": anomaly.get("alert_name"),
                "dimension": f"{anomaly.get('dimension_type', '')}: {anomaly.get('dimension_value', '')}",
                "severity": anomaly.get("severity"),
                "cost_impact": format_currency(anomaly.get("cost_impact", 0)),
                "expected_cost": format_currency(anomaly.get("expected_cost", 0)),
                "actual_cost": format_currency(anomaly.get("actual_cost", 0)),
                "percent_over_expected": f"{percent_over_expected:+.1f}%",
            }
        )

    return {
        "time_period": time_period,
        "severity_filter": severity,
        "anomaly_count": len(formatted_anomalies),
        "anomalies": formatted_anomalies,
        "total_impact": format_currency(total_impact),
        "_presentation_hint": (
            "Present anomalies sorted by cost impact. "
            "Group by date if there are many. "
            "Highlight the largest surprises with their percent over expected."
        ),
    }


async def get_financial_plans_impl(args: dict) -> dict:
    """Implementation of get_financial_plans tool"""
    assert finout_client is not None

    name = args.get("name")
    period = args.get("period")

    plans = await finout_client.get_financial_plans(name=name, period=period)

    formatted = []
    for plan in plans:
        items = plan.get("top_line_items", [])
        formatted_items = [
            {
                "key": item["key"],
                "budget": format_currency(item["budget"]),
                "forecast": format_currency(item["forecast"])
                if item.get("forecast") is not None
                else None,
            }
            for item in items
        ]

        entry: dict[str, Any] = {
            "name": plan["name"],
            "period": plan["period"],
            "cost_type": plan["cost_type"],
            "total_budget": format_currency(plan["total_budget"]),
            "active_line_items": plan["active_line_item_count"],
            "top_line_items": formatted_items,
        }
        if plan.get("total_forecast") is not None:
            entry["total_forecast"] = format_currency(plan["total_forecast"])

        formatted.append(entry)

    return {
        "plan_count": len(formatted),
        "plans": formatted,
        "_presentation_hint": (
            "Show plan name, period, total budget and top line items. "
            "If forecast is present, compare budget vs forecast."
        ),
    }


async def create_view_impl(args: dict) -> dict:
    """Implementation of create_view tool"""
    assert finout_client is not None

    name = args["name"]
    filters = args.get("filters")
    group_by = args.get("group_by")
    time_period = args.get("time_period", "last_30_days")
    cost_type_str = args.get("cost_type", CostType.NET_AMORTIZED.value)
    cost_type = CostType(cost_type_str)

    view = await finout_client.create_view(
        name=name,
        filters=filters,
        group_by=group_by,
        time_period=time_period,
        cost_type=cost_type,
    )
    view_id = view.get("id")
    account_id = finout_client.account_id
    url = f"https://app.finout.io/app/total-cost?view={view_id}"
    if account_id:
        url += f"&accountId={account_id}"
    return {
        "id": view_id,
        "name": view.get("name"),
        "url": url,
        "_presentation_hint": "Tell the user the view was saved and share the link.",
    }


async def create_dashboard_impl(args: dict) -> dict:
    """Implementation of create_dashboard tool"""
    assert finout_client is not None
    name = args["name"]
    widgets = args["widgets"]

    dashboard = await finout_client.create_dashboard(name=name, widgets=widgets)
    dashboard_id = dashboard.get("id")
    account_id = finout_client.account_id
    url = f"https://app.finout.io/app/dashboards/{dashboard_id}"
    if account_id:
        url += f"?accountId={account_id}"
    return {
        "id": dashboard_id,
        "name": dashboard.get("name"),
        "url": url,
        "widget_count": len(widgets),
        "_presentation_hint": (
            f"Tell the user the dashboard was created with {len(widgets)} widgets "
            "and share the link."
        ),
    }


async def get_waste_recommendations_impl(args: dict) -> dict:
    """Implementation of get_waste_recommendations tool"""
    assert finout_client is not None

    scan_type = args.get("scan_type")
    service = args.get("service")
    min_saving = args.get("min_saving")

    recommendations = await finout_client.get_waste_recommendations(
        scan_type=scan_type, service=service, min_saving=min_saving
    )

    # Format recommendations
    formatted = []
    total_savings = 0

    for rec in recommendations[:50]:  # Limit to top 50
        # CostGuard payloads vary by scan type; normalize defensively.
        saving = (
            rec.get("monthly_savings")
            or rec.get("projected_savings")
            or rec.get("potential_savings")
            or 0
        )
        if not saving and rec.get("yearly_savings"):
            saving = rec.get("yearly_savings", 0) / 12
        total_savings += saving

        resource_metadata = rec.get("resource_metadata", {})
        if not isinstance(resource_metadata, dict):
            resource_metadata = {}

        recommendation_text = (
            rec.get("recommendation")
            or rec.get("scan_name")
            or rec.get("title")
            or "Review this resource for optimization opportunity."
        )
        details = rec.get("details")
        if not details and resource_metadata:
            details = json.dumps(resource_metadata, ensure_ascii=False)

        formatted.append(
            {
                "resource": (
                    rec.get("resource_name")
                    or resource_metadata.get("resourceName")
                    or resource_metadata.get("name")
                    or rec.get("resource_id", "Unknown")
                ),
                "service": rec.get("service") or rec.get("cost_center", "Unknown"),
                "type": rec.get("scan_type") or rec.get("recommendation_type", "Unknown"),
                "current_monthly_cost": format_currency(
                    rec.get("current_cost") or rec.get("resource_waste", 0)
                ),
                "potential_monthly_savings": format_currency(saving),
                "recommendation": recommendation_text,
                "details": details or "",
            }
        )

    return {
        "filters": {"scan_type": scan_type, "service": service, "min_saving": min_saving},
        "recommendation_count": len(recommendations),
        "showing": len(formatted),
        "total_potential_savings": format_currency(total_savings),
        "annual_savings_potential": format_currency(total_savings * 12),
        "recommendations": formatted,
        "_presentation_hint": (
            "Present as numbered action list sorted by savings. "
            "Include total potential savings at top."
        ),
    }


async def list_available_filters_impl(args: dict) -> dict:
    """Implementation of list_available_filters tool"""
    assert finout_client is not None

    cost_center = args.get("cost_center")

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": (
                "This tool requires the internal cost-service API. "
                "Set FINOUT_API_URL environment variable."
            ),
        }

    from .filter_utils import format_filter_metadata_for_llm, organize_filters_by_cost_center

    # Get metadata (cached)
    metadata = await finout_client.get_filters_metadata()

    # Organize by cost center
    organized = organize_filters_by_cost_center(metadata)

    # Filter by cost center if specified
    if cost_center:
        organized = {
            cc: filters for cc, filters in organized.items() if cc.lower() == cost_center.lower()
        }

    # Format for LLM (limit to 20 filters per cost center to prevent overload)
    formatted = format_filter_metadata_for_llm(
        organized, include_counts=True, max_per_cost_center=20
    )

    # Calculate summary stats
    total_filters = sum(len(f) for f in organized.values())
    cost_center_stats = {cc: len(filters) for cc, filters in organized.items()}

    return {
        "summary": {
            "cost_centers": list(organized.keys()),
            "total_filters": total_filters,
            "filters_per_cost_center": cost_center_stats,
        },
        "filters": formatted,  # Formatted string (limited to 20/cost center)
        "note": "Use search_filters to find specific filters by keyword, or get_filter_values to fetch values for a specific filter",
    }


async def search_filters_impl(args: dict) -> dict:
    """Implementation of search_filters tool"""
    assert finout_client is not None

    query = args["query"]
    cost_center = args.get("cost_center")

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": (
                "This tool requires the internal cost-service API. "
                "Set FINOUT_API_URL environment variable."
            ),
        }

    from .filter_utils import format_search_results

    # Search filters
    results = await finout_client.search_filters(query, cost_center, limit=50)

    # Format for LLM
    formatted = format_search_results(results, max_results=50)

    return {
        "query": query,
        "cost_center": cost_center,
        "result_count": len(results),
        "results": formatted,
        "note": "Use get_filter_values to fetch values for any of these filters",
        "_presentation_hint": ("Don't show raw results to user. Use them to build the next query."),
    }


async def debug_filters_impl(args: dict) -> dict:
    """Debug tool to inspect raw filter metadata"""
    assert finout_client is not None

    cost_center_filter = args.get("cost_center")
    type_filter = args.get("filter_type")

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": "Set FINOUT_API_URL environment variable.",
        }

    # Get raw metadata
    metadata = await finout_client.get_filters_metadata()

    # Build diagnostic info
    summary = {"total_cost_centers": len(metadata), "cost_centers": {}}

    for cc, types in metadata.items():
        if cost_center_filter and cc.lower() != cost_center_filter.lower():
            continue

        type_counts = {}
        sample_filters = {}

        for ft, filters in types.items():
            if type_filter and ft != type_filter:
                continue

            type_counts[ft] = len(filters)
            # Show first 5 filters of each type as samples
            sample_filters[ft] = [
                {"key": f.get("key"), "path": f.get("path"), "type": f.get("type")}
                for f in filters[:5]
            ]

        if type_counts:  # Only include if there are matching types
            summary_cost_centers: dict[str, Any] = summary["cost_centers"]  # type: ignore[assignment]
            summary_cost_centers[cc] = {"type_counts": type_counts, "samples": sample_filters}

    return {
        "summary": summary,
        "note": "This shows what's in the filter cache. If tags are missing, the API may not be returning them.",
    }


async def get_filter_values_impl(args: dict) -> dict:
    """Implementation of get_filter_values tool"""
    assert finout_client is not None

    filter_key = args["filter_key"]
    cost_center = args.get("cost_center")
    filter_type = args.get("filter_type")
    limit = args.get("limit", 100)

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": (
                "This tool requires the internal cost-service API. "
                "Set FINOUT_API_URL environment variable."
            ),
        }

    from .filter_utils import format_filter_values, truncate_filter_values

    # Get values
    values = await finout_client.get_filter_values(
        filter_key, cost_center, filter_type, limit=limit
    )

    # Truncate and format
    truncated = truncate_filter_values(values, limit=limit, include_stats=True)
    formatted = format_filter_values(filter_key, truncated, cost_center)

    return {
        "filter_key": filter_key,
        "cost_center": cost_center,
        "filter_type": filter_type,
        "values": formatted,
        "metadata": {
            "total_count": truncated["total_count"],
            "returned_count": truncated["returned_count"],
            "is_truncated": truncated["is_truncated"],
        },
    }


async def get_usage_unit_types_impl(args: dict) -> dict:
    """Implementation of get_usage_unit_types tool"""
    assert finout_client is not None

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": (
                "This tool requires the internal cost-service API. "
                "Set FINOUT_API_URL environment variable."
            ),
        }

    # Get usage unit types
    units = await finout_client.get_usage_unit_types(
        time_period=time_period, filters=filters if filters else None
    )

    # Format response
    return {
        "usage_units": units,
        "count": len(units),
        "summary": f"Found {len(units)} usage unit types",
        "examples": [
            f"Use in query_costs: usage_configuration={{"
            f'"usageType": "usageAmount", '
            f'"costCenter": "{unit["costCenter"]}", '
            f'"units": "{unit["units"]}"}}'
            for unit in units[:3]  # Show first 3 examples
        ],
    }


async def discover_context_impl(args: dict) -> dict:
    """Implementation of discover_context tool"""
    assert finout_client is not None

    query = args.get("query", "").lower()
    include_dashboards = args.get("include_dashboards", True)
    include_views = args.get("include_views", True)
    include_data_explorers = args.get("include_data_explorers", True)
    max_results = args.get("max_results", 5)

    dashboards_list: list[dict[str, Any]] = []
    views_list: list[dict[str, Any]] = []
    data_explorers_list: list[dict[str, Any]] = []

    results: dict[str, Any] = {
        "query": args.get("query"),
        "dashboards": dashboards_list,
        "views": views_list,
        "data_explorers": data_explorers_list,
        "summary": "",
    }

    # Search dashboards
    if include_dashboards:
        dashboards = await finout_client.get_dashboards()
        matching_dashboards = [d for d in dashboards if query in d.get("name", "").lower()][
            :max_results
        ]

        # Enrich with widget details for matching dashboards
        for dashboard in matching_dashboards:
            widget_ids = [
                w["widgetId"] for w in dashboard.get("widgets", [])[:3]
            ]  # First 3 widgets
            widgets: list[dict[str, Any]] = []
            for wid in widget_ids:
                try:
                    widget = await finout_client.get_widget(wid)

                    # Extract configuration (filters are directly under configuration)
                    config = widget.get("configuration", {})

                    # Extract filter (single object, not array)
                    filter_obj = config.get("filters", {})
                    simplified_filters = []
                    if filter_obj and isinstance(filter_obj, dict):
                        simplified_filters.append(
                            {
                                "key": filter_obj.get("key"),
                                "value": filter_obj.get("value"),
                                "operator": filter_obj.get("operator", "eq"),
                                "type": filter_obj.get("type"),
                            }
                        )

                    # Extract groupBy (singular, not array)
                    group_by_obj = config.get("groupBy", {})
                    group_bys = []
                    if group_by_obj and isinstance(group_by_obj, dict):
                        group_bys.append(
                            {
                                "key": group_by_obj.get("key"),
                                "path": group_by_obj.get("path"),
                                "type": group_by_obj.get("type"),
                            }
                        )

                    widgets.append(
                        {
                            "name": widget.get("name"),
                            "filters": simplified_filters if simplified_filters else None,
                            "groupBys": group_bys if group_bys else None,
                            "date": config.get("date"),
                        }
                    )
                except Exception as e:
                    import sys

                    print(f"Error fetching widget {wid}: {e}", file=sys.stderr)
                    import traceback

                    traceback.print_exc(file=sys.stderr)
                    pass

            d_url = f"https://app.finout.io/app/dashboards/{dashboard['id']}"
            if finout_client.account_id:
                d_url += f"?accountId={finout_client.account_id}"
            dashboards_list.append(
                {
                    "id": dashboard["id"],
                    "name": dashboard["name"],
                    "url": d_url,
                    "widgets": widgets,
                    "defaultDate": dashboard.get("defaultDate"),
                }
            )

    # Search views
    if include_views:
        views = await finout_client.get_views()
        matching_views = [v for v in views if query in v.get("name", "").lower()][:max_results]

        for view in matching_views:
            # Try configuration first, fallback to data for backwards compatibility
            config = view.get("configuration") or view.get("data", {})
            query = config.get("query", {})

            views_list.append(
                {
                    "id": view["id"],
                    "name": view["name"],
                    "type": view.get("type"),
                    "filters": query.get("filters"),
                    "groupBys": query.get("groupBys"),
                    "date": config.get("date"),
                }
            )

    # Search data explorers
    if include_data_explorers:
        explorers = await finout_client.get_data_explorers()
        matching_explorers = [
            e
            for e in explorers
            if (
                (isinstance(e.get("name"), str) and query in e.get("name", "").lower())
                or (
                    isinstance(e.get("description"), str)
                    and query in e.get("description", "").lower()
                )
            )
        ][:max_results]

        for explorer in matching_explorers:
            data_explorers_list.append(
                {
                    "id": explorer["id"],
                    "name": explorer["name"],
                    "description": explorer.get("description"),
                    "filters": explorer.get("filters"),
                    "columns": explorer.get("columns"),
                }
            )

    # Generate summary with actionable guidance
    total_results = len(dashboards_list) + len(views_list) + len(data_explorers_list)
    if total_results == 0:
        results["summary"] = (
            f"No context found for '{args.get('query')}'. "
            "Try a different search term or use search_filters to explore available dimensions."
        )
    else:
        summary_parts = [
            f"Found {len(dashboards_list)} dashboard(s), {len(views_list)} view(s), "
            f"{len(data_explorers_list)} data explorer(s) for '{args.get('query')}'"
        ]

        # Extract common filters from discovered context
        all_filters = []
        for dashboard in dashboards_list:
            for widget in dashboard.get("widgets", []):
                if widget.get("filters"):
                    all_filters.extend(widget["filters"])
        for view in views_list:
            if view.get("filters"):
                all_filters.extend(view["filters"])

        # Provide actionable guidance
        if all_filters:
            filter_summary: dict[str, list[Any]] = {}
            for f in all_filters:
                key = f.get("key")
                if key:
                    if key not in filter_summary:
                        filter_summary[key] = []
                    value = f.get("value")
                    if value and value not in filter_summary[key]:
                        filter_summary[key].append(value)

            if filter_summary:
                summary_parts.append(
                    "\n\n⚠️ IMPORTANT: The dashboards/views above show how to identify these resources."
                )
                summary_parts.append("\n\nFilters that define this context:")
                for key, values in list(filter_summary.items())[:5]:  # Top 5 filters
                    values_str = ", ".join(map(str, values[:3]))
                    summary_parts.append(f"  • {key}: {values_str}")

                # Provide example query
                first_key = list(filter_summary.keys())[0]
                first_value = filter_summary[first_key][0]
                summary_parts.append(
                    f"\n\n✅ NEXT STEP: Query costs using these filters."
                    f"\nExample: query_costs(time_period='last_30_days', "
                    f"filters=[{{'key': '{first_key}', 'value': '{first_value}', 'operator': 'eq'}}])"
                )

        results["summary"] = "".join(summary_parts)

    return results


async def get_account_context_impl() -> dict:
    """Implementation of get_account_context tool"""
    assert finout_client is not None

    return await finout_client.get_account_context()


async def submit_feedback_impl(args: dict) -> dict:
    """Implementation of submit_feedback tool"""
    import sys

    rating = args.get("rating")
    query_type = args.get("query_type")
    tools_used = args.get("tools_used", [])
    friction_points = args.get("friction_points", [])
    suggestion = args.get("suggestion")

    if not isinstance(rating, int) or rating < 1 or rating > 5:
        raise ValueError("rating must be an integer between 1 and 5")

    valid_types = [
        "cost_query",
        "comparison",
        "anomaly",
        "waste",
        "filter_discovery",
        "context",
        "other",
    ]
    if query_type not in valid_types:
        raise ValueError(f"query_type must be one of: {valid_types}")

    entry = {
        "rating": rating,
        "query_type": query_type,
        "tools_used": tools_used,
        "friction_points": friction_points,
        "suggestion": suggestion,
        "timestamp": datetime.now().isoformat(),
    }

    feedback_log.append(entry)
    print(f"[feedback] {json.dumps(entry)}", file=sys.stderr)

    return {
        "status": "recorded",
        "total_feedback_count": len(feedback_log),
    }


# Resource Definitions


@server.list_resources()
async def list_resources() -> list[Resource]:
    """List available resources"""
    return [
        Resource(
            uri=AnyUrl("finout://how-to-query"),
            name="How to Query Costs",
            description="Guide for building cost queries from natural language questions",
            mimeType="text/plain",
        ),
        Resource(
            uri=AnyUrl("finout://date-range-examples"),
            name="Custom Date Range Examples",
            description="Examples and formulas for calculating custom date ranges (e.g., last 7 days of each month)",
            mimeType="text/plain",
        ),
        Resource(
            uri=AnyUrl("finout://anomalies/active"),
            name="Active Anomalies",
            description="Currently active cost anomalies (last 7 days)",
            mimeType="application/json",
        ),
        Resource(
            uri=AnyUrl("finout://cost-centers"),
            name="Cost Centers",
            description="Available cost centers and cloud providers",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource by URI"""

    if not finout_client:
        return json.dumps({"error": "Client not initialized"})

    assert finout_client is not None  # Type checker hint

    try:
        if uri == "finout://how-to-query":
            return """# How to Query Finout Costs

## Workflow for Natural Language Cost Questions

When the user asks a cost question like "What was my EC2 cost last month?":

1. **Identify the entities** in the question:
   - Services: "EC2", "S3", "Lambda", "RDS", etc.
   - Regions: "us-east-1", "eu-west-1", etc.
   - Environments: "production", "staging", etc.
   - Resources: "pod", "namespace", "instance", etc.
   - Time period: "last month", "this week", "yesterday", etc.

2. **Search for relevant filters** using search_filters:
   - For "EC2": search_filters("service")
   - For "us-east-1": search_filters("region")
   - For "production": search_filters("environment")
   - For "pod": search_filters("pod")

3. **Build the query** with query_costs:
   - Use filters parameter with discovered filter keys
   - Set appropriate time_period
   - Add group_by if user wants breakdown

4. **Return the answer** in natural language

## Available Cost Centers
- aws: AWS cloud costs
- gcp: Google Cloud costs
- azure: Azure costs
- k8s: Kubernetes costs
- datadog: Datadog monitoring costs
- snowflake: Snowflake data warehouse costs

## Example Mappings

User Question → Filters:
- "EC2 costs" → search_filters("service") → {key: "service", value: ["ec2"]}
- "in us-east-1" → search_filters("region") → {key: "region", value: ["us-east-1"]}
- "production environment" → search_filters("environment") → {key: "environment", value: ["production"]}
- "by namespace" → search_filters("namespace") → group_by=["namespace"]
- "pods in production" → search_filters("pod") + search_filters("namespace")

## Key Principle
NEVER use list_available_filters unless specifically asked "what filters are available?"
ALWAYS use search_filters to find specific filters based on the user's question.
"""

        elif uri == "finout://date-range-examples":
            from calendar import monthrange

            now = datetime.now()
            current_year = now.year
            current_month = now.month

            # Calculate examples for last 4 months
            examples = []
            for i in range(4):
                # Calculate month
                month = current_month - i
                year = current_year
                while month <= 0:
                    month += 12
                    year -= 1

                # Get last 7 days
                last_day_num = monthrange(year, month)[1]
                last_day = datetime(year, month, last_day_num)
                first_day = last_day - timedelta(days=6)

                month_name = last_day.strftime("%B %Y")
                examples.append(
                    {
                        "month": month_name,
                        "date_range": f"{first_day.strftime('%Y-%m-%d')} to {last_day.strftime('%Y-%m-%d')}",
                        "description": f"Last 7 days of {month_name}",
                    }
                )

            return f"""# Custom Date Range Examples

## Overview
The query_costs and compare_costs tools now support custom date ranges in addition to predefined periods.

## Format
Custom date ranges use the format: **"YYYY-MM-DD to YYYY-MM-DD"**

Examples:
- "2026-01-24 to 2026-01-31" (last 7 days of January)
- "2025-12-01 to 2025-12-31" (all of December)
- "2026-02-01 to 2026-02-07" (first week of February)

## Predefined Periods Still Available
- today, yesterday
- last_7_days, last_30_days
- this_week, last_week, two_weeks_ago
- this_month, last_month, last_quarter

## Common Use Cases

### Last 7 Days of Each Month (for cyclical comparisons)
Today is {now.strftime("%Y-%m-%d")}

{chr(10).join([f"- {ex['month']}: **'{ex['date_range']}'**" for ex in examples])}

### Python Formula for Last 7 Days of a Month
```python
from calendar import monthrange
from datetime import datetime, timedelta

def get_last_7_days(year, month):
    last_day_num = monthrange(year, month)[1]
    last_day = datetime(year, month, last_day_num)
    first_day = last_day - timedelta(days=6)
    return f"{{first_day.strftime('%Y-%m-%d')}} to {{last_day.strftime('%Y-%m-%d')}}"
```

### How to Use with query_costs

**Single Month:**
```json
{{
  "time_period": "2026-01-25 to 2026-01-31",
  "filters": [...]
}}
```

**Compare Multiple Months:**
Call query_costs multiple times with different date ranges, then compare results:

```python
# Query each period
jan_costs = query_costs(time_period="2026-01-25 to 2026-01-31", ...)
dec_costs = query_costs(time_period="2025-12-25 to 2025-12-31", ...)
nov_costs = query_costs(time_period="2025-11-24 to 2025-11-30", ...)

# Compare and analyze trends
```

## Why Use Custom Ranges?

**Cyclical Billing Patterns:**
Many cloud costs follow monthly billing cycles. Comparing "last month" to "this month" can be misleading if you're mid-month. Instead, compare the same relative period (e.g., last 7 days) of each month for fairer comparison.

**Example:**
"Compare last 7 days of each of the last 4 months" gives you:
- Same number of days in each period
- Same relative position in billing cycle
- Better trend visibility

## Tips

1. **Always use YYYY-MM-DD format** (ISO 8601)
2. **End date is inclusive** (includes 23:59:59 of that day)
3. **Calculate dates programmatically** for complex queries
4. **Use Python's calendar.monthrange()** to get last day of month
"""

        elif uri == "finout://anomalies/active":
            try:
                anomalies = await finout_client.get_anomalies(time_period="last_7_days")
                return json.dumps(
                    {"active_anomalies": anomalies, "count": len(anomalies)}, indent=2
                )
            except NotImplementedError as e:
                return json.dumps(
                    {
                        "error": "Anomalies API not yet available",
                        "message": str(e),
                        "active_anomalies": [],
                        "count": 0,
                    },
                    indent=2,
                )

        elif uri == "finout://cost-centers":
            # Return static list of supported cost centers
            return json.dumps(
                {
                    "cost_centers": [
                        {"name": "AWS", "type": "cloud_provider"},
                        {"name": "GCP", "type": "cloud_provider"},
                        {"name": "Azure", "type": "cloud_provider"},
                        {"name": "Kubernetes", "type": "container_platform"},
                        {"name": "Datadog", "type": "saas"},
                        {"name": "Snowflake", "type": "saas"},
                    ]
                },
                indent=2,
            )

        else:
            return json.dumps({"error": f"Unknown resource: {uri}"})

    except Exception as e:
        return json.dumps({"error": str(e)})


# Prompt Definitions


@server.list_prompts()
async def list_prompts() -> list[dict]:
    """List available prompt templates"""
    return [
        {
            "name": "monthly_cost_review",
            "description": "Comprehensive monthly cost review and analysis",
            "arguments": [],
        },
        {
            "name": "find_waste",
            "description": "Identify cost optimization opportunities",
            "arguments": [],
        },
        {
            "name": "investigate_spike",
            "description": "Investigate a cost spike or anomaly",
            "arguments": [
                {
                    "name": "service",
                    "description": "Cloud service to investigate (optional)",
                    "required": False,
                }
            ],
        },
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None) -> dict:
    """Get a prompt template"""

    if name == "monthly_cost_review":
        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Please provide a comprehensive monthly cost review:\n\n"
                        "1. Use get_cost_summary for this_month and last_month\n"
                        "2. Use compare_costs to show the trend\n"
                        "3. Check for any anomalies\n"
                        "4. Identify the top 5 cost drivers\n"
                        "5. Suggest any optimization opportunities\n\n"
                        "Present the findings in a clear, executive-friendly format."
                    ),
                }
            ]
        }

    elif name == "find_waste":
        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Analyze our cloud infrastructure for cost optimization opportunities:\n\n"
                        "1. Check get_waste_recommendations for idle resources\n"
                        "2. Look for rightsizing opportunities\n"
                        "3. Calculate total potential savings\n"
                        "4. Prioritize the top 10 recommendations by savings amount\n"
                        "5. Estimate annual impact if all recommendations are implemented\n\n"
                        "Present a prioritized action plan."
                    ),
                }
            ]
        }

    elif name == "investigate_spike":
        service = arguments.get("service") if arguments else None
        service_filter = f" for {service}" if service else ""

        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Investigate recent cost spikes{service_filter}:\n\n"
                        "1. Get anomalies for the last 7 days\n"
                        "2. For each anomaly, compare costs to the previous period\n"
                        "3. Identify what changed (new resources, usage spike, etc.)\n"
                        "4. Assess if this is a one-time event or ongoing trend\n"
                        "5. Recommend actions to address the spike\n\n"
                        "Provide root cause analysis and remediation steps."
                    ),
                }
            ]
        }

    else:
        raise ValueError(f"Unknown prompt: {name}")


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

    async def run_server():
        """Run the MCP server using stdio transport"""
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

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


def main_vectiqor_internal() -> None:
    """Internal MCP entry point used by VECTIQOR only."""
    _main_with_mode(MCPMode.VECTIQOR_INTERNAL)


if __name__ == "__main__":
    main()
