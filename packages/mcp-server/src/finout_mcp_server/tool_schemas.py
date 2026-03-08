"""Tool schema definitions for the Finout MCP server."""

from mcp.types import Tool


def _allowed_tools_for_runtime() -> set[str]:
    from .server import BILLY_INTERNAL_TOOLS, PUBLIC_TOOLS, MCPMode, runtime_mode

    if runtime_mode == MCPMode.BILLY_INTERNAL.value:
        return BILLY_INTERNAL_TOOLS
    return PUBLIC_TOOLS


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
                "1) ALWAYS call search_filters first — it returns a 'filters' list with ready-to-use objects\n"
                "2) Copy the EXACT filter object from the 'filters' list (costCenter, key, path, type)\n"
                "3) Call get_filter_values to discover the correct value (values are unintuitive!)\n"
                "4) Add operator ('is' or 'oneOf') and the verified value, then query\n\n"
                "TIME-SERIES: The API always returns time-series data (nested 'data' array per row). "
                "The server auto-selects the right granularity — omit x_axis_group_by unless the user "
                "explicitly requests a different one. NEVER manually aggregate or sum numbers — "
                "read totals directly from the API response.\n\n"
                "PRESENTING RESULTS: Give 2-4 sentences of key insights: total, biggest driver, "
                "notable trend. No table or raw data dump needed. "
                "To visualize results, call render_chart with curated data.\n\n"
                "COST + USAGE IN ONE QUERY:\n"
                "- Cost is ALWAYS returned in results\n"
                "- To ALSO get usage: Provide usage_configuration\n"
                "- Call get_usage_unit_types BEFORE any usage query to discover valid units\n"
                "- Chain: get_usage_unit_types → query_costs with usage_configuration\n\n"
                "USAGE EXAMPLES:\n"
                '- AWS EC2 hours: {"usageType": "usageAmount", "costCenter": "amazon-cur", "units": "Hrs"}\n'
                '- Azure hours: {"usageType": "usageAmount", "costCenter": "Azure", "units": "1 Hour"}\n'
                '- GCP hours: {"usageType": "usageAmount", "costCenter": "GCP", "units": "Hour"}\n\n'
                "FILTER EXAMPLES (note: type varies — col, tag, finrichment, namespace_object, etc.):\n\n"
                "Finrichment column (product name):\n"
                "filters: [{'costCenter': 'amazon-cur', 'key': 'finrichment_product_name', "
                "'path': 'AWS/Product Name', 'type': 'finrichment', 'operator': 'is', "
                "'value': 'Amazon Elastic Compute Cloud'}]\n\n"
                "Kubernetes deployment:\n"
                "filters: [{'costCenter': 'kubernetes', 'key': 'deployment', "
                "'path': 'Kubernetes/Resources/deployment', 'type': 'namespace_object', "
                "'operator': 'oneOf', 'value': ['refresh-web', 'refresh-notifications']}]\n\n"
                "Custom tag:\n"
                "filters: [{'costCenter': 'amazon-cur', 'key': 'environment', "
                "'path': 'AWS/Tags/environment', 'type': 'tag', 'operator': 'is', 'value': 'production'}]\n\n"
                "CRITICAL RULES:\n"
                "- NEVER construct filters from memory. ALWAYS copy from search_filters 'filters' list.\n"
                "- The 'type' field is NOT always 'col' — it can be 'finrichment', 'tag', 'namespace_object', etc.\n"
                "- COPY costCenter, key, path, type EXACTLY from search_filters results. Do NOT modify them.\n"
                "- operator: 'is' for single value, 'oneOf' for multiple values (OR)\n"
                "- value: String for 'is', array for 'oneOf'\n"
                "- Filter metadata AND values are VALIDATED server-side. Wrong type/path/value WILL fail.\n"
                "- Values are often unintuitive (e.g., 'AmazonEC2' not 'ec2'). Always verify with get_filter_values."
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
                                        "Filter type - MUST copy EXACT value from search_filters 'filters' list! "
                                        "Types include: 'col' (standard columns), 'tag' (custom tags), "
                                        "'finrichment' (enriched dimensions like product name), "
                                        "'namespace_object' (K8s resources). "
                                        "DO NOT default to 'col' — the correct type depends on the filter. "
                                        "ALWAYS copy from search_filters results."
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
                                    "description": (
                                        "Filter type - MUST copy from search_filters 'filters' list. "
                                        "Same types as filters: 'col', 'tag', 'finrichment', "
                                        "'namespace_object', etc. DO NOT default to 'col'."
                                    ),
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
                        "enum": ["daily", "weekly", "monthly", "quarterly"],
                        "description": (
                            "Override the auto-selected granularity. The server picks the coarsest "
                            "bucket that fits the period exactly (weekly for named-week periods, "
                            "monthly for named-month/quarter periods, daily otherwise). "
                            "Only set this when the user explicitly requests a different granularity: "
                            "'daily breakdown for last month' → 'daily'; "
                            "'weekly view for last quarter' → 'weekly'; "
                            "any trend question on a month/quarter period → 'daily'."
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
                "Use a table for grouped comparisons. "
                "To visualize results, call render_chart with curated data."
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
                                        "Filter type - MUST copy EXACT value from search_filters 'filters' list! "
                                        "Types include: 'col' (standard columns), 'tag' (custom tags), "
                                        "'finrichment' (enriched dimensions like product name), "
                                        "'namespace_object' (K8s resources). "
                                        "DO NOT default to 'col' — the correct type depends on the filter. "
                                        "ALWAYS copy from search_filters results."
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
                                    "description": (
                                        "Filter type - MUST copy from search_filters 'filters' list. "
                                        "Same types as filters: 'col', 'tag', 'finrichment', "
                                        "'namespace_object', etc. DO NOT default to 'col'."
                                    ),
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
                "CHAIN: search_filters → get_filter_values (MANDATORY to verify exact values) → query_costs\n\n"
                "Results include sample values for top matches to help identify correct filter values. "
                "Values are often unintuitive (e.g., 'AmazonEC2' not 'ec2', 'AmazonS3' not 's3').\n\n"
                "Searches BOTH columns (service, region, account) AND tags (environment, team, custom labels).\n\n"
                "Examples:\n"
                "- search_filters('service') → AWS/GCP services\n"
                "- search_filters('environment') → Environment tags\n"
                "- search_filters('pod') → Kubernetes pods\n\n"
                "DO NOT show raw search results to the user. Use them to build the next query.\n\n"
                "When results span multiple providers, check the cross_provider_note field for coverage gaps.\n\n"
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
        Tool(
            name="render_chart",
            description=(
                "Render a chart in the UI with exactly the data you want to visualize.\n\n"
                "WHEN TO USE: After answering a cost question, call this to visualize "
                "the key data point. Don't chart everything — chart what matters.\n\n"
                "RULES:\n"
                "- Call AFTER your text summary, not instead of it\n"
                "- Use curated/synthesized data, not raw API output\n"
                "- One chart per answer is usually enough\n"
                "- If the user asks 'show me a chart', call this\n"
                "- categories length MUST equal every series.data length\n"
                "- pie chart MUST have exactly one series\n"
                "- series.data values MUST be numeric\n\n"
                "CHART TYPES:\n"
                "- bar: horizontal bars, good for ranking/comparison\n"
                "- column: vertical bars, good for categorical comparison\n"
                "- line: trend over time\n"
                "- pie: proportion/share breakdown\n\n"
                "ADVANCED:\n"
                "- Optional colors: provide chart-level `colors` or per-series `color`\n"
                "- Multi-axis line charts: define `y_axes` and set `series[].y_axis` index"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Chart title",
                    },
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "line", "pie", "column"],
                        "description": "Chart type",
                    },
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "X-axis labels",
                    },
                    "series": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "data": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "number"},
                                },
                                "color": {
                                    "type": "string",
                                    "description": "Optional color for this series (e.g. '#38B28E')",
                                },
                                "y_axis": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "description": (
                                        "Optional y-axis index for line charts (requires y_axes). "
                                        "Example: 0 for cost axis, 1 for usage axis."
                                    ),
                                },
                            },
                            "required": ["name", "data"],
                        },
                        "description": "Data series to plot",
                    },
                    "colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional chart palette. Used when series colors are not provided. "
                            "Example: ['#38B28E', '#4B9BFF']"
                        ),
                    },
                    "y_axes": {
                        "type": "array",
                        "description": "Optional y-axis definitions for multi-axis line charts",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "Axis label (e.g., 'Cost ($)', 'Usage (hrs)')",
                                },
                                "opposite": {
                                    "type": "boolean",
                                    "description": "Place axis on right side when true",
                                    "default": False,
                                },
                                "min": {
                                    "type": "number",
                                    "description": "Optional minimum value for this axis",
                                },
                                "max": {
                                    "type": "number",
                                    "description": "Optional maximum value for this axis",
                                },
                            },
                            "required": ["label"],
                        },
                    },
                    "x_label": {
                        "type": "string",
                        "description": "Optional x-axis label",
                    },
                    "y_label": {
                        "type": "string",
                        "description": "Optional y-axis label (defaults to 'Cost ($)')",
                    },
                },
                "required": ["title", "chart_type", "categories", "series"],
            },
        ),
        Tool(
            name="analyze_virtual_tags",
            description=(
                "Analyze virtual tags: their type, position in the dependency chain, "
                "what cost services power them, and how they relate to other tags.\n\n"
                "WHEN TO USE: When the user asks about virtual tag relationships, dependencies, "
                "hierarchies, cost allocation strategies, reallocation setup, how tags reference "
                "each other, or wants to understand their tag topology.\n\n"
                "FOCUSED MODE (tag_name given) — result contains:\n"
                "  focused_tag: the tag's type, position (source/bridge/output/isolated), "
                "direct_dependencies (what it depends on), direct_consumers (what depends on it), "
                "cost_dimensions (underlying cost services it filters on), "
                "values (the actual cost categories it allocates to, e.g. team/project names — present when non-empty)\n"
                "  subgraph_analysis: source_tags (entry points), output_tags (final outputs), "
                "chain_depth (longest hop count), by_type (mix of tag types), "
                "cost_dimensions (all cost services in the chain)\n"
                "  tag_details: per-tag breakdown of every tag in the chain\n\n"
                "GLOBAL MODE (no tag_name) — result contains:\n"
                "  account_summary: total counts and type breakdown\n"
                "  ecosystem.chains: each independent allocation chain with its output_tag, "
                "chain_size, chain_depth, by_type mix, cost_dimensions, and output_values "
                "(the actual values the output tag assigns costs to, e.g. team names)\n"
                "  ecosystem.isolated_tags: tags with no relationships\n"
                "  notable_tags: most connected/complex tags\n\n"
                "PRESENTING RESULTS: The UI renders the diagram automatically — "
                "never output mermaid_diagram as text. "
                "Use the structured fields to narrate a meaningful analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tag_name": {
                        "type": "string",
                        "description": "Focus on a specific tag and its connected subgraph. Case-insensitive partial match.",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_object_usages",
            description=(
                "Find all places where a named Finout object is used.\n\n"
                "WHEN TO USE: When the user asks 'where is X used', 'what uses my virtual tag Y',\n"
                "'show me dependencies of Z'.\n\n"
                "Returns a list of entities that reference the object, with context showing how\n"
                "(e.g., as a filter, groupBy dimension, or allocation rule)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the object to look up (e.g. 'My Virtual Tag')",
                    },
                    "entity_type": {
                        "type": "string",
                        "enum": [
                            "virtual_tag",
                            "view",
                            "dashboard",
                            "widget",
                            "explorer",
                            "alert",
                            "financial_plan",
                        ],
                        "description": "Optional: narrow search to a specific entity type",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="check_delete_safety",
            description=(
                "Check if a Finout object is safe to delete (not referenced anywhere).\n\n"
                "WHEN TO USE: When the user asks 'can I delete X', 'is X still in use', "
                "'is it safe to remove Y'.\n\n"
                "Returns safe_to_delete: true/false, and if false, lists what is blocking deletion."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the object to check",
                    },
                    "entity_type": {
                        "type": "string",
                        "enum": [
                            "virtual_tag",
                            "view",
                            "dashboard",
                            "widget",
                            "explorer",
                            "alert",
                            "financial_plan",
                        ],
                        "description": "Optional: narrow search to a specific entity type",
                    },
                },
                "required": ["name"],
            },
        ),
    ]
    allowed = _allowed_tools_for_runtime()
    return [tool for tool in all_tools if tool.name in allowed]
