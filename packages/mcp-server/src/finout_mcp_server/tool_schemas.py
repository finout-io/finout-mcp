"""Tool schema definitions for the Finout MCP server."""

from mcp.types import Tool

COST_TYPE_ENUM = [
    "netAmortizedCost",
    "blendedCost",
    "unblendedCost",
    "amortizedCost",
    "netUnblendedCost",
    "listCost",
    "fairShareCost",
    "netFairShareCost",
]


def _allowed_tools_for_runtime() -> set[str]:
    from .server import BILLY_INTERNAL_TOOLS, PUBLIC_TOOLS, MCPMode, get_runtime_mode

    if get_runtime_mode() == MCPMode.BILLY_INTERNAL.value:
        return BILLY_INTERNAL_TOOLS
    return PUBLIC_TOOLS


async def list_tools() -> list[Tool]:
    """List all available Finout MCP tools"""
    all_tools = [
        Tool(
            name="query_costs",
            description=(
                "Query cloud costs, usage, and operational metrics with flexible filters and grouping.\n\n"
                "WHEN TO USE: When the user asks about spending, costs, bills, expenses, "
                "usage, savings plans, runtime hours, or resource counts.\n\n"
                "WORKFLOW:\n"
                "- For broad questions (e.g., 'top costs last month', 'total spend by service', "
                "'break down by region'): call query_costs DIRECTLY — no search_filters needed.\n"
                "- For questions filtering or grouping by a named entity (specific service, team tag, "
                "account, environment, etc.): call search_filters first to get filter metadata, then:\n"
                "  1) Copy the EXACT filter object from search_filters 'filters' list (costCenter, key, path, type)\n"
                "  2) Call get_filter_values to discover the correct value (values are unintuitive!)\n"
                "  3) Add operator ('is' or 'oneOf') and the verified value, then query\n\n"
                "RESPONSE FORMAT: Flat rows with human-readable column names. "
                "Example: {'Services': 'AmazonEC2', 'Sum(Net Amortized Cost)': 55216.95}. "
                "The server auto-selects the right granularity — omit x_axis_group_by unless the user "
                "explicitly requests a different one.\n\n"
                "PRESENTING RESULTS: Give 2-4 sentences of key insights: total, biggest driver, "
                "notable trend. No table or raw data dump needed. "
                "To visualize results, call render_chart with curated data.\n\n"
                "MULTI-METRIC QUERIES (single call):\n"
                "- extra_measurements: Add cost types like unblendedCost, blendedCost alongside the primary\n"
                "- billing_metrics: Add savingsPlanEffectiveCost, reservationEffectiveCost\n"
                "- predefined_queries: Add runtimeProportionResources, ebsRunningHours, countS3Objects\n"
                "- count_distinct: Count unique values of a dimension (e.g., how many regions?)\n"
                "- All of these return additional columns in the SAME response row\n\n"
                "CROSS-DIMENSION ANALYSIS: Pass multiple items in group_by to analyze two "
                "dimensions simultaneously (e.g., service × region). This creates a row per combination.\n\n"
                "CUSTOM AGGREGATIONS: extra_measurements supports avg, min, max — not just sum. "
                "Use avg for 'average daily cost', max for 'peak cost day', min for 'cheapest period'.\n\n"
                "AMORTIZATION ANALYSIS: Query both netAmortizedCost (primary) and unblendedCost "
                "(via extra_measurements) to see how RIs/SPs reduce your effective cost per service.\n\n"
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
                            "- Flexible relative: last_N_days, last_N_weeks, last_N_months "
                            "(e.g., 'last_14_days', 'last_3_months', 'last_6_weeks')\n"
                            "- Custom range: 'YYYY-MM-DD to YYYY-MM-DD' (e.g., '2026-01-24 to 2026-01-31')"
                        ),
                        "default": "last_30_days",
                    },
                    "cost_type": {
                        "type": "string",
                        "enum": COST_TYPE_ENUM,
                        "description": (
                            "Cost metric to use. Defaults to the account's configured default "
                            "(usually netAmortizedCost). Common types: netAmortizedCost (RI/SP adjusted), "
                            "unblendedCost (on-demand rates), blendedCost (org-averaged rates)."
                        ),
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
                        "enum": ["hourly", "daily", "weekly", "monthly", "quarterly"],
                        "description": (
                            "Override the auto-selected granularity. The server picks the coarsest "
                            "bucket that fits the period exactly (weekly for named-week periods, "
                            "monthly for named-month/quarter periods, daily otherwise). "
                            "Only set this when the user explicitly requests a different granularity: "
                            "'hourly breakdown for today' → 'hourly'; "
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
                    "extra_measurements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": (
                                        "Cost metric type: netAmortizedCost, amortizedCost, "
                                        "unblendedCost, blendedCost, netUnblendedCost, "
                                        "listCost, fairShareCost, netFairShareCost"
                                    ),
                                },
                                "aggregation": {
                                    "type": "string",
                                    "enum": ["sum", "avg", "min", "max"],
                                    "default": "sum",
                                    "description": (
                                        "Aggregation: sum (total), avg (average per row), "
                                        "min (lowest), max (peak)"
                                    ),
                                },
                            },
                            "required": ["type"],
                        },
                        "description": (
                            "Additional cost metrics in the same query. "
                            "The primary metric (from cost_type param) is always included. "
                            "Use this to compare cost types or get min/max/avg.\n"
                            'Examples: [{"type": "unblendedCost"}] or '
                            '[{"type": "amortizedCost", "aggregation": "max"}]'
                        ),
                    },
                    "billing_metrics": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "savingsPlanEffectiveCost",
                                "reservationEffectiveCost",
                            ],
                        },
                        "description": (
                            "Billing metrics to include alongside cost. "
                            "Returns savings plan or reservation effective cost columns."
                        ),
                    },
                    "count_distinct": {
                        "type": "object",
                        "properties": {
                            "costCenter": {"type": "string"},
                            "key": {"type": "string"},
                            "path": {"type": "string"},
                            "type": {"type": "string"},
                        },
                        "required": ["costCenter", "key", "path", "type"],
                        "description": (
                            "Count unique values of a dimension. Uses the same metadata "
                            "as group_by (from search_filters). "
                            "Example: count distinct regions → adds 'Count Distinct(Region)' column."
                        ),
                    },
                    "predefined_queries": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "runtimeProportionResources",
                                "vcpuRuntimeProportionResources",
                                "ebsRunningHours",
                                "countS3Objects",
                                "normalizedStorageUsage",
                            ],
                        },
                        "description": (
                            "Predefined operational metrics to include alongside cost.\n"
                            "- runtimeProportionResources: Normalized runtime hours\n"
                            "- vcpuRuntimeProportionResources: vCPU-weighted runtime\n"
                            "- ebsRunningHours: EBS volume hours\n"
                            "- countS3Objects: S3 object count\n"
                            "- normalizedStorageUsage: Normalized storage"
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
                "PARTIAL PERIOD WARNING: When current_period is partial (this_month, this_week, "
                "this_quarter, this_year), the result includes _partial_period_warning. "
                "ALWAYS surface this warning — comparing 12 days to 28 days is misleading. "
                "When you see it, either re-run with the suggested normalized comparison_period "
                "or explain the limitation before presenting numbers.\n\n"
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
                            "- Flexible relative: last_N_days, last_N_weeks, last_N_months\n"
                            "- Custom range: 'YYYY-MM-DD to YYYY-MM-DD'"
                        ),
                    },
                    "comparison_period": {
                        "type": "string",
                        "description": (
                            "Period to compare against. Supports:\n"
                            "- Predefined: yesterday, last_7_days, this_week, last_week, "
                            "two_weeks_ago, last_30_days, this_month, last_month, last_quarter\n"
                            "- Flexible relative: last_N_days, last_N_weeks, last_N_months\n"
                            "- Custom range: 'YYYY-MM-DD to YYYY-MM-DD'"
                        ),
                    },
                    "cost_type": {
                        "type": "string",
                        "enum": COST_TYPE_ENUM,
                        "description": (
                            "Cost metric to use for both periods. Defaults to the account's "
                            "configured default (usually netAmortizedCost)."
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
                    "extra_measurements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": (
                                        "Cost metric type: netAmortizedCost, amortizedCost, "
                                        "unblendedCost, blendedCost, netUnblendedCost, "
                                        "listCost, fairShareCost, netFairShareCost"
                                    ),
                                },
                                "aggregation": {
                                    "type": "string",
                                    "enum": ["sum", "avg", "min", "max"],
                                    "default": "sum",
                                },
                            },
                            "required": ["type"],
                        },
                        "description": (
                            "Additional cost metrics to compare across both periods. "
                            "Example: compare amortized vs unblended cost changes."
                        ),
                    },
                    "billing_metrics": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "savingsPlanEffectiveCost",
                                "reservationEffectiveCost",
                            ],
                        },
                        "description": (
                            "Billing metrics to compare alongside cost "
                            "(e.g., track savings plan coverage changes)."
                        ),
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
                "Get financial plans with budget, actual cost, run rate, and forecast.\n\n"
                "WHEN TO USE: When the user asks about 'budget', 'financial plan', 'forecast', "
                "'planned spend', 'budget vs actual', 'are we on track', 'burn rate', "
                "'will we exceed the budget', 'budget utilization', or any question "
                "comparing spend to planned amounts.\n\n"
                "WORKFLOW:\n"
                "1. Call WITHOUT name first to list available plan names.\n"
                "2. Call WITH name to get detailed budget vs actual data for one plan.\n\n"
                "PRESENTING RESULTS: Lead with status (on_track/at_risk/over_budget). "
                "Show budget vs actual cost, run rate, and remaining budget. "
                "Highlight plans at risk or over budget."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Plan name to look up (partial, case-insensitive). "
                            "Omit to list all plan names. "
                            "Provide to get detailed budget vs actual data for one plan."
                        ),
                    },
                    "period": {
                        "type": "string",
                        "description": (
                            "Month in 'YYYY-M' format (no zero-padding). "
                            "Examples: '2026-4' for Apr 2026, '2025-12' for Dec 2025. "
                            "If omitted, auto-selects the latest month with budget + actual data. "
                            "Only used when name is provided."
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
                        "enum": COST_TYPE_ENUM,
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
                                    "enum": COST_TYPE_ENUM,
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
                "Look up filter and group_by metadata for a named entity or dimension.\n\n"
                "WHEN TO USE: When you need costCenter/key/path/type metadata for a specific entity "
                "(a service, tag, region, account, team, custom dimension, etc.) to use in filters or group_by. "
                "SKIP THIS for broad unfiltered questions like 'top costs last month' or 'total spend by service' "
                "— call the terminal tool directly.\n\n"
                "IMPORTANT — DO NOT STOP HERE: search_filters only discovers metadata. "
                "Always proceed to the appropriate terminal tool:\n"
                "- query_costs: cost totals, breakdowns, trends\n"
                "- get_top_movers: cost changes, biggest movers, what drove increase/decrease\n"
                "- get_unit_economics: cost per hour/GB/request/resource\n"
                "- get_savings_coverage: RI/savings plan coverage\n"
                "- get_tag_coverage: tagging governance and gaps\n"
                "- get_cost_patterns: peak hours, weekday/weekend patterns\n\n"
                "Results include sample values for top matches. "
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
        Tool(
            name="get_top_movers",
            description=(
                "Identify which dimensions had the biggest cost changes between two periods.\n\n"
                "WHEN TO USE: When the user asks 'what changed?', 'what drove the increase?', "
                "'biggest cost changes', 'what spiked?', 'where did costs go up/down?', "
                "or any question about cost movement by dimension.\n\n"
                "WORKFLOW:\n"
                "1. Call search_filters with the dimension you want to rank by — e.g., search_filters('service') "
                "for service movers, search_filters('region') for region movers.\n"
                "2. Take the first matching filter object from the results (it has costCenter, key, path, type).\n"
                "3. Call get_top_movers with that object in group_by.\n"
                "DO NOT stop at search_filters — always follow through to get_top_movers.\n\n"
                "EXAMPLE: For 'what drove cost increase this month by service?'\n"
                "  Step 1: search_filters('service')\n"
                "  Step 2: get_top_movers(group_by=[<service filter from step 1>], time_period='this_month')\n\n"
                "HOW IT WORKS: Queries both periods grouped by the specified dimension, "
                "computes the delta and % change for each value, and ranks by absolute change. "
                "Also flags new items (appeared this period) and removed items. "
                "When comparison_period is omitted, automatically infers the equivalent prior "
                "period — including last_quarter → the quarter before it. "
                "PARTIAL PERIOD NORMALIZATION: When time_period is a partial period "
                "(this_month, this_week, this_quarter, this_year), the comparison period is "
                "automatically constrained to the same number of elapsed days for a fair "
                "apples-to-apples comparison. A _normalization_note in the result explains "
                "the adjustment. ALWAYS mention this to the user.\n\n"
                "PRESENTING RESULTS: Lead with overall trend, then top 3 movers. "
                "Use render_chart with a bar chart showing positive (increases) and negative (decreases) deltas."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "description": (
                            "Current time period to analyze. Supports predefined periods, "
                            "flexible relative (last_N_days), and custom ranges."
                        ),
                        "default": "last_30_days",
                    },
                    "comparison_period": {
                        "type": "string",
                        "description": (
                            "Period to compare against. If omitted, automatically uses "
                            "the equivalent previous period (e.g., last_30_days → the 30 days before that)."
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
                                    "description": "MUST copy from search_filters results.",
                                },
                            },
                            "required": ["costCenter", "key", "path", "type"],
                        },
                        "description": (
                            "REQUIRED: Dimension to rank movers by (e.g., service, region, team). "
                            "Copy from search_filters results."
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
                                "type": {"type": "string"},
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
                        "description": "Optional: Filters to scope the analysis",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Max movers to return per direction (increases and decreases)",
                    },
                },
                "required": ["group_by"],
            },
        ),
        Tool(
            name="get_unit_economics",
            description=(
                "Compute cost-per-unit using usage metrics or resource counts.\n\n"
                "WHEN TO USE: When the user asks 'cost per hour', 'cost per GB', 'cost per request', "
                "'cost per instance', 'cost per Lambda function', 'unit economics', "
                "'how efficient is my spend', or any question about cost divided by usage or quantity.\n\n"
                "USE THIS INSTEAD OF query_costs when the question involves cost divided by anything.\n\n"
                "WORKFLOW:\n"
                "1. Call search_filters with the service or resource name to get dimension metadata.\n"
                "2. Call get_unit_economics with filters or group_by from step 1.\n"
                "DO NOT stop at search_filters — always follow through to get_unit_economics.\n\n"
                "EXAMPLE: For 'average cost per EC2 instance?'\n"
                "  Step 1: search_filters('EC2') or search_filters('service')\n"
                "  Step 2: get_unit_economics(filters=[<EC2 filter>], usage_configuration=...)\n\n"
                "TWO MODES:\n"
                "A) USAGE MODE (cost ÷ hours/GB/requests): Pass usage_configuration.\n"
                "   Best for efficiency/unit-cost questions. Each service has its own natural unit "
                "   (Hour for EC2, GB for S3, Requests for Lambda, etc.).\n"
                "   1) Apply a service filter\n"
                "   2) Call get_usage_unit_types to discover available units\n"
                "   3) Pass the right unit as usage_configuration\n"
                "   For cross-service efficiency ('cost per resource by service'), make separate "
                "   usage-mode calls per service — each service needs its own unit.\n"
                "B) COUNT MODE (cost ÷ number of resources): Pass count_distinct.\n"
                "   Best for inventory questions about discrete countable things: 'how many Lambda "
                "   functions do I have and what does each cost?', 'cost per RDS database'.\n"
                "   WARNING: Do NOT use count_distinct grouped by service — different services have "
                "   different resource granularities (S3 counts buckets, EC2 counts instance IDs) "
                "   making cross-service comparisons meaningless. Use usage mode instead.\n\n"
                "If neither is provided, the tool auto-discovers usage units.\n\n"
                "EXAMPLES:\n"
                "- Cost per EC2 hour: filter=EC2, usage_configuration={costCenter: amazon-cur, units: Hour}\n"
                "- Cost per Lambda function: filter=Lambda, count_distinct={costCenter: amazon-cur, "
                "key: lambda_name, path: AWS/Resources Name/lambda_name, type: resource}\n"
                "- Cost efficiency by service: call this tool once per service with the right usage unit "
                "(e.g., EC2→Hour, S3→GB, Lambda→Requests)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "description": "Time period to analyze.",
                        "default": "last_30_days",
                    },
                    "usage_configuration": {
                        "type": "object",
                        "properties": {
                            "costCenter": {"type": "string"},
                            "units": {"type": "string"},
                        },
                        "required": ["costCenter", "units"],
                        "description": (
                            "USAGE MODE: Unit to measure against cost. "
                            "Call get_usage_unit_types first to discover valid values. "
                            'Example: {"costCenter": "amazon-cur", "units": "Hour"}. '
                            "If omitted and count_distinct is also omitted, auto-discovers units."
                        ),
                    },
                    "count_distinct": {
                        "type": "object",
                        "properties": {
                            "costCenter": {"type": "string"},
                            "key": {"type": "string"},
                            "path": {"type": "string"},
                            "type": {"type": "string"},
                        },
                        "required": ["costCenter", "key", "path", "type"],
                        "description": (
                            "COUNT MODE: Resource dimension to count distinct values of. "
                            "Computes cost ÷ avg(distinct count). Use for discrete inventory "
                            "questions within a single service (e.g., cost per Lambda function). "
                            "Do NOT group by service — use usage mode for cross-service comparisons. "
                            "Use search_filters to find the right dimension. "
                            'Example: {"costCenter": "amazon-cur", "key": "lambda_name", '
                            '"path": "AWS/Resources Name/lambda_name", "type": "resource"}'
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
                                "type": {"type": "string"},
                            },
                            "required": ["costCenter", "key", "path", "type"],
                        },
                        "description": (
                            "Optional: Group results by dimension (e.g., service, region). "
                            "Returns cost-per-unit for each group."
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
                                "type": {"type": "string"},
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
                        "description": "Optional: Filters to scope the analysis",
                    },
                    "cost_type": {
                        "type": "string",
                        "enum": COST_TYPE_ENUM,
                        "default": "netAmortizedCost",
                        "description": "Cost metric to use for unit economics calculation",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_cost_patterns",
            description=(
                "Analyze temporal cost patterns — weekday/weekend splits and hourly peaks.\n\n"
                "WHEN TO USE: When the user asks about 'cost patterns', 'peak hours', "
                "'when are costs highest?', 'weekday vs weekend', 'peak vs off-peak', "
                "or any time-based cost analysis.\n\n"
                "WORKFLOW: Call get_cost_patterns directly — no search_filters needed for basic patterns. "
                "Optionally call search_filters first if the user wants patterns filtered by a specific entity.\n\n"
                "HOW IT WORKS: Tries hourly granularity first; falls back to daily if the "
                "account's billing data is only available at daily granularity (very common). "
                "Computes weekday/weekend averages and day-of-week breakdown in both cases. "
                "The result includes granularity='hourly' or 'daily' — mention which was used.\n\n"
                "PRESENTING RESULTS: Lead with weekday_vs_weekend. Show day_of_week_average. "
                "If hourly data is available, also highlight peak and off-peak hours. "
                "Use render_chart with a bar chart of day_of_week_average."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "description": "Time period to analyze (shorter periods work best).",
                        "default": "last_7_days",
                    },
                    "filters": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional: Filters to scope the analysis",
                    },
                    "group_by": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional: Group by dimension for per-group patterns",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_savings_coverage",
            description=(
                "Analyze savings plan and reservation coverage.\n\n"
                "WHEN TO USE: When the user asks about 'savings plan coverage', "
                "'RI utilization', 'on-demand vs reserved', 'commitment coverage', "
                "'how much is covered by savings plans', or SP/RI optimization.\n\n"
                "WORKFLOW:\n"
                "- For overall coverage (no grouping needed): call get_savings_coverage DIRECTLY.\n"
                "- To group by a dimension (e.g., 'coverage by service'): call search_filters first to get "
                "group_by metadata, THEN call get_savings_coverage.\n"
                "Never call search_filters after get_savings_coverage.\n\n"
                "HOW IT WORKS: Queries cost with billing metrics (savingsPlanEffectiveCost, "
                "reservationEffectiveCost) and computes coverage ratio per group.\n\n"
                "PRESENTING RESULTS: Show overall coverage %, then highlight services "
                "with low coverage as optimization opportunities."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "description": "Time period to analyze.",
                        "default": "last_30_days",
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
                        "description": (
                            "Optional: Group coverage by dimension (e.g., service). "
                            "Shows coverage per group."
                        ),
                    },
                    "filters": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional: Filters to scope the analysis",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_tag_coverage",
            description=(
                "Analyze what percentage of spend is tagged by a given dimension.\n\n"
                "WHEN TO USE: When the user asks about 'tag coverage', 'untagged spend', "
                "'governance', 'what percentage is tagged', 'tagging gaps', "
                "or cost allocation completeness.\n\n"
                "WORKFLOW:\n"
                "1. Call search_filters with the tag name — e.g., search_filters('team'), search_filters('environment').\n"
                "2. Take the matching filter object (costCenter, key, path, type) from results.\n"
                "3. Pass it as tag_dimension in get_tag_coverage.\n"
                "DO NOT stop at search_filters — always follow through to get_tag_coverage.\n\n"
                "EXAMPLE: For 'what % of spend is tagged by team?'\n"
                "  Step 1: search_filters('team')\n"
                "  Step 2: get_tag_coverage(tag_dimension=<team filter from step 1>)\n\n"
                "HOW IT WORKS: Runs two queries — total cost and cost grouped by the tag. "
                "Only rows with a real tag value count as tagged spend; empty, null, or "
                "placeholder values (N/A, none, unknown) are treated as untagged. "
                "The difference between total and tagged = untagged spend.\n\n"
                "PRESENTING RESULTS: Lead with overall coverage %. "
                "Highlight groups with lowest coverage as governance gaps."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "description": "Time period to analyze.",
                        "default": "last_30_days",
                    },
                    "tag_dimension": {
                        "type": "object",
                        "properties": {
                            "costCenter": {"type": "string"},
                            "key": {"type": "string"},
                            "path": {"type": "string"},
                            "type": {"type": "string"},
                        },
                        "required": ["costCenter", "key", "path", "type"],
                        "description": (
                            "REQUIRED: The tag/dimension to measure coverage for. "
                            "Use search_filters to find the right metadata "
                            "(e.g., team tag, environment tag, cost-center tag)."
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
                                "type": {"type": "string"},
                            },
                            "required": ["costCenter", "key", "path", "type"],
                        },
                        "description": (
                            "Optional: Group results by dimension (e.g., service) to see "
                            "which groups have the worst tag coverage."
                        ),
                    },
                    "filters": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional: Filters to scope the analysis",
                    },
                },
                "required": ["tag_dimension"],
            },
        ),
        Tool(
            name="get_cost_statistics",
            description=(
                "Compute daily cost statistics — mean, median, peak, trough, volatility.\n\n"
                "WHEN TO USE: When the user asks about 'average daily cost', 'cost volatility', "
                "'peak day', 'most expensive day', 'which day cost the most', 'cost variability', "
                "'cost distribution', 'how volatile', or statistical analysis of spending.\n\n"
                "WORKFLOW: For broad statistics (no grouping), call directly. "
                "To group by a dimension (e.g., 'by service'), call search_filters first to get group_by metadata, "
                "then call get_cost_statistics. DO NOT stop at search_filters.\n\n"
                "HOW IT WORKS: Queries with daily granularity, aggregates all groups into "
                "daily totals, then computes mean, median, min, max, standard deviation, "
                "and coefficient of variation. Returns peak_day and trough_day with both "
                "date and cost — these are derived from actual per-day totals.\n\n"
                "PRESENTING RESULTS: Lead with daily average and highlight volatility. "
                "Call out peak and trough days with their dates and costs. "
                "Compare variability across groups if grouped."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_period": {
                        "type": "string",
                        "description": "Time period to analyze.",
                        "default": "last_30_days",
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
                        "description": "Optional: Group statistics by dimension",
                    },
                    "filters": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional: Filters to scope the analysis",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="list_data_explorers",
            description=(
                "List saved data explorer configurations in the account.\n\n"
                "WHEN TO USE: When the user asks 'what data explorers exist?', "
                "'show me saved queries', 'list explorers', or wants to find "
                "a previously saved data explorer.\n\n"
                "Returns name, columns, and filter presence for each explorer."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional: Filter explorers by name or description keyword.",
                    },
                },
                "required": [],
            },
        ),
    ]
    allowed = _allowed_tools_for_runtime()
    return [tool for tool in all_tools if tool.name in allowed]
