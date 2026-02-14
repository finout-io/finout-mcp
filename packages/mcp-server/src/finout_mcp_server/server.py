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
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    AnyUrl,
    Resource,
    TextContent,
    Tool,
)

from .finout_client import FinoutClient

# Initialize MCP server
server = Server("finout-mcp-server")

# Global client instance (will be initialized on startup)
finout_client: FinoutClient | None = None


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
    return [
        Tool(
            name="query_costs",
            description=(
                "Query cloud costs with flexible filters and grouping.\n\n"
                "WORKFLOW:\n"
                "1) Use search_filters to find relevant filters (e.g., search_filters('service'))\n"
                "2) Copy the FULL filter object from search results (costCenter, key, path, type)\n"
                "3) Add operator ('is' for equals) and value (single string), then query\n\n"
                "COMPLETE EXAMPLES:\n\n"
                "Example 1 - Standard column (service):\n"
                "filters: [{\n"
                "  'costCenter': 'amazon-cur',\n"
                "  'key': 'finrichment_product_name',\n"
                "  'path': 'AMAZON-CUR/Product',\n"
                "  'type': 'col',\n"
                "  'operator': 'is',\n"
                "  'value': 'ec2'\n"
                "}]\n\n"
                "Example 2 - Kubernetes deployment (namespace_object type):\n"
                "filters: [{\n"
                "  'costCenter': 'kubernetes',\n"
                "  'key': 'deployment',\n"
                "  'path': 'Kubernetes/Resources/deployment',\n"
                "  'type': 'namespace_object',  ← EXACT type from search_filters!\n"
                "  'operator': 'oneOf',\n"
                "  'value': ['refresh-web', 'refresh-notifications']\n"
                "}]\n\n"
                "Example 3 - Custom tag:\n"
                "filters: [{\n"
                "  'costCenter': 'amazon-cur',\n"
                "  'key': 'environment',\n"
                "  'path': 'AWS/Tags/environment',\n"
                "  'type': 'tag',  ← EXACT type from search_filters!\n"
                "  'operator': 'is',\n"
                "  'value': 'production'\n"
                "}]\n\n"
                "⚠️ CRITICAL - Filter Types:\n"
                "- NEVER guess the type value!\n"
                "- ALWAYS use search_filters FIRST to get the exact type\n"
                "- COPY the exact 'type' value from search results\n"
                "- Common types: 'col' (columns), 'tag' (tags), 'namespace_object' (K8s resources)\n"
                "- Different resources may have different type values - always check search results!\n\n"
                "⚠️ CRITICAL - Operators:\n"
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
                    "x_axis_group_by": {
                        "type": "string",
                        "enum": ["daily", "monthly"],
                        "description": "Optional: Time-based grouping for x-axis",
                    },
                },
                "required": ["time_period"],
            },
        ),
        Tool(
            name="compare_costs",
            description=(
                "Compare cloud costs between two time periods with optional filters. "
                "Useful for questions like 'How do this month's EC2 costs compare to last month?' "
                "Returns delta and percentage change. Supports same filters as query_costs."
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
                "🔍 DEBUG TOOL: Shows raw filter metadata to diagnose issues. "
                "Use this when filters seem to be missing or search isn't working. "
                "Returns a sample of what's in the filter cache."
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
                "Retrieve detected cost anomalies and spikes. "
                "Use this to answer questions like 'Were there any unusual cost spikes?' "
                "or 'What anomalies were detected this week?'"
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
            name="get_waste_recommendations",
            description=(
                "Get CostGuard waste detection and optimization recommendations. "
                "Identifies idle resources, rightsizing opportunities, and commitment gaps. "
                "Use for questions like 'What resources can I shut down to save money?' "
                "or 'Show me idle EC2 instances.'"
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
                "List all available cost filters organized by cost center. "
                "⚠️ WARNING: Returns large response. Only use if user explicitly asks 'what filters are available?' "
                "For normal cost queries, use search_filters instead to find specific filters."
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
                "🎯 PRIMARY TOOL for finding filters (columns AND tags). Search by keyword to discover filters. "
                "Use this when building cost queries from natural language questions.\n\n"
                "SEARCHES BOTH:\n"
                "- 📊 COLUMNS: Standard filters (service, region, account, etc.)\n"
                "- 🏷️ TAGS: Custom labels (environment, team, db_purpose, etc.)\n\n"
                "Examples:\n"
                "- search_filters('service') → AWS/GCP services\n"
                "- search_filters('db_purpose') → Custom database tags\n"
                "- search_filters('environment') → Environment tags\n"
                "- search_filters('pod') → Kubernetes pods\n\n"
                "Returns up to 50 matches sorted by relevance, grouped by type (TAGS vs COLUMNS)."
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
                "Get the values for a specific filter (lazy-loaded on demand). "
                "Returns up to 100 values by default to prevent context overload. "
                "Use this after discovering filters with search_filters.\n\n"
                "⚠️ IMPORTANT: When searching for values containing a substring (e.g., 'deployments containing refresh'), "
                "increase the limit (e.g., limit=300-500) to ensure all matching values are included!\n\n"
                "EXAMPLES:\n"
                "1. Get specific values:\n"
                "   get_filter_values(filter_key='service', cost_center='amazon-cur', filter_type='col', limit=50)\n\n"
                "2. Search for values containing 'refresh' (K8s deployments):\n"
                "   get_filter_values(filter_key='deployment', cost_center='kubernetes', filter_type='namespace_object', limit=500)\n"
                "   Then filter results for values containing 'refresh'"
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
            name="discover_context",
            description=(
                "Search for how the account organizes cost/usage data related to a query.\n\n"
                "Discovers business context by searching across:\n"
                "- **Dashboards**: Named collections of widgets showing cost breakdowns\n"
                "- **Views**: Saved queries with specific filters and groupings (semantic layer)\n"
                "- **Data Explorers**: Complex multi-dimensional analysis queries\n\n"
                "Returns information about filters, virtual tags, dimensions, and groupings commonly used for the queried topic. "
                "This helps understand the business logic and existing organizational patterns before querying costs.\n\n"
                "**When to use:**\n"
                '- User asks about a named concept ("vikings", "production", "team X")\n'
                "- Need to understand how they organize/filter data\n"
                "- Before making cost queries for unfamiliar topics\n\n"
                "**Example queries:**\n"
                '- "vikings" → finds "Vikings dashboard", shows what filters/groupings they use\n'
                '- "production" → finds production views, shows env=prod filters\n'
                '- "kafka" → finds Kafka-related dashboards/views and their configurations'
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool execution"""

    if not finout_client:
        return [
            TextContent(
                type="text", text="Error: Finout client not initialized. Check credentials."
            )
        ]

    assert finout_client is not None  # Type checker hint

    # Check if credentials are available
    if not finout_client.client_id or not finout_client.secret_key:
        return [
            TextContent(
                type="text",
                text=(
                    "Error: Finout API credentials not configured.\n\n"
                    "To use this tool, set the following environment variables:\n"
                    "  FINOUT_CLIENT_ID=your_client_id\n"
                    "  FINOUT_SECRET_KEY=your_secret_key\n\n"
                    "Or create a .env file with these values."
                ),
            )
        ]

    try:
        if name == "query_costs":
            result = await query_costs_impl(arguments)
        elif name == "compare_costs":
            result = await compare_costs_impl(arguments)
        elif name == "get_anomalies":
            result = await get_anomalies_impl(arguments)
        elif name == "get_waste_recommendations":
            result = await get_waste_recommendations_impl(arguments)
        elif name == "list_available_filters":
            result = await list_available_filters_impl(arguments)
        elif name == "search_filters":
            result = await search_filters_impl(arguments)
        elif name == "get_filter_values":
            result = await get_filter_values_impl(arguments)
        elif name == "debug_filters":
            result = await debug_filters_impl(arguments)
        elif name == "discover_context":
            result = await discover_context_impl(arguments or {})
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except ValueError as e:
        # User-friendly error for validation issues
        error_msg = str(e)
        if "Internal API URL not configured" in error_msg:
            return [
                TextContent(
                    type="text",
                    text=(
                        "❌ Internal API not configured\n\n"
                        "To use this tool, set the following environment variable:\n"
                        "  FINOUT_INTERNAL_API_URL=http://your-finout-internal-api\n\n"
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
    x_axis_group_by = args.get("x_axis_group_by")

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": (
                "This tool requires the internal cost-service API. "
                "Set FINOUT_INTERNAL_API_URL environment variable. "
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
        x_axis_group_by=x_axis_group_by,
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
                "Set FINOUT_INTERNAL_API_URL environment variable."
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

    return result


async def get_anomalies_impl(args: dict) -> dict:
    """Implementation of get_anomalies tool"""
    assert finout_client is not None

    time_period = args.get("time_period", "last_7_days")
    severity = args.get("severity")

    try:
        anomalies = await finout_client.get_anomalies(time_period=time_period, severity=severity)
    except NotImplementedError as e:
        return {
            "error": "Anomalies API not yet available",
            "message": str(e),
            "anomalies": [],
            "anomaly_count": 0,
            "note": "Contact Finout support for anomaly detection API access",
        }

    # Format for readability
    formatted_anomalies = []
    for anomaly in anomalies:
        formatted_anomalies.append(
            {
                "date": anomaly.get("date"),
                "service": anomaly.get("service"),
                "severity": anomaly.get("severity"),
                "cost_impact": format_currency(anomaly.get("costImpact", 0)),
                "expected_cost": format_currency(anomaly.get("expectedCost", 0)),
                "actual_cost": format_currency(anomaly.get("actualCost", 0)),
                "description": anomaly.get("description"),
            }
        )

    return {
        "time_period": time_period,
        "severity_filter": severity,
        "anomaly_count": len(formatted_anomalies),
        "anomalies": formatted_anomalies,
        "total_impact": format_currency(sum(a.get("costImpact", 0) for a in anomalies)),
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
        saving = rec["projected_savings"]
        total_savings += saving

        formatted.append(
            {
                "resource": rec["resource_name"] or rec["resource_id"],
                "service": rec["service"],
                "type": rec["scan_type"],
                "current_monthly_cost": format_currency(rec["current_cost"]),
                "potential_monthly_savings": format_currency(saving),
                "recommendation": rec["recommendation"],
                "details": rec.get("details", ""),
            }
        )

    return {
        "filters": {"scan_type": scan_type, "service": service, "min_saving": min_saving},
        "recommendation_count": len(recommendations),
        "showing": len(formatted),
        "total_potential_savings": format_currency(total_savings),
        "annual_savings_potential": format_currency(total_savings * 12),
        "recommendations": formatted,
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
                "Set FINOUT_INTERNAL_API_URL environment variable."
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
                "Set FINOUT_INTERNAL_API_URL environment variable."
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
            "message": "Set FINOUT_INTERNAL_API_URL environment variable.",
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
                "Set FINOUT_INTERNAL_API_URL environment variable."
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

                    # Debug: Print widget structure to understand the schema
                    import sys

                    print(f"\n[DEBUG] Widget {wid} structure:", file=sys.stderr)
                    print(f"Keys: {list(widget.keys())}", file=sys.stderr)
                    if "data" in widget:
                        print(f"Data keys: {list(widget.get('data', {}).keys())}", file=sys.stderr)

                    query_data = widget.get("data", {}).get("query", {})

                    # Extract and simplify filter information
                    filters = query_data.get("filters", [])
                    simplified_filters = []
                    for f in filters:
                        if isinstance(f, dict):
                            # Extract key filter details
                            simplified_filters.append(
                                {
                                    "key": f.get("key"),
                                    "value": f.get("value"),
                                    "operator": f.get("operator", "eq"),
                                }
                            )

                    # Extract groupBys
                    group_bys = query_data.get("groupBys", [])

                    widgets.append(
                        {
                            "name": widget.get("name"),
                            "filters": simplified_filters if simplified_filters else None,
                            "groupBys": group_bys if group_bys else None,
                            "date": query_data.get("date"),
                        }
                    )
                except Exception as e:
                    import sys

                    print(f"Error fetching widget {wid}: {e}", file=sys.stderr)
                    import traceback

                    traceback.print_exc(file=sys.stderr)
                    pass

            dashboards_list.append(
                {
                    "id": dashboard["id"],
                    "name": dashboard["name"],
                    "widgets": widgets,
                    "defaultDate": dashboard.get("defaultDate"),
                }
            )

    # Search views
    if include_views:
        views = await finout_client.get_views()
        matching_views = [v for v in views if query in v.get("name", "").lower()][:max_results]

        for view in matching_views:
            views_list.append(
                {
                    "id": view["id"],
                    "name": view["name"],
                    "type": view.get("type"),
                    "filters": view.get("data", {}).get("query", {}).get("filters"),
                    "groupBys": view.get("data", {}).get("query", {}).get("groupBys"),
                    "date": view.get("data", {}).get("date"),
                }
            )

    # Search data explorers
    if include_data_explorers:
        explorers = await finout_client.get_data_explorers()
        matching_explorers = [
            e
            for e in explorers
            if query in e.get("name", "").lower() or query in e.get("description", "").lower()
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

    # Check if credentials are available
    if not finout_client.client_id or not finout_client.secret_key:
        return json.dumps(
            {
                "error": "Finout API credentials not configured",
                "message": "Set FINOUT_CLIENT_ID and FINOUT_SECRET_KEY environment variables",
            }
        )

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


def main():
    """Main entry point for the MCP server"""
    global finout_client

    # Initialize Finout client
    # Allow missing credentials for testing/inspection - tools will fail if credentials missing
    try:
        finout_client = FinoutClient(allow_missing_credentials=True)

        # Check if credentials are actually available
        import sys

        if finout_client.client_id and finout_client.secret_key:
            print("✓ Finout MCP Server initialized with credentials", file=sys.stderr)
        else:
            print("⚠ Finout MCP Server started WITHOUT credentials", file=sys.stderr)
            print("  Tools will be visible but API calls will fail", file=sys.stderr)
            print(
                "  Set FINOUT_CLIENT_ID and FINOUT_SECRET_KEY to enable functionality",
                file=sys.stderr,
            )
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


if __name__ == "__main__":
    main()
