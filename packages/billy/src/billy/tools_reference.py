"""Structured reference for all available MCP tools, served via /api/tools."""

from typing import List, Optional
from typing_extensions import TypedDict


class ToolEntry(TypedDict):
    name: str
    category: str  # cost_query | filters | visualization | context | waste | admin
    availability: str  # public | internal
    description: str
    when_to_use: List[str]
    example_prompts: List[str]
    key_params: List[str]
    workflow: Optional[str]


TOOLS_REFERENCE: List[ToolEntry] = [
    {
        "name": "query_costs",
        "category": "cost_query",
        "availability": "public",
        "description": "Query cloud costs and usage with filters and grouping.",
        "when_to_use": [
            "spending, costs, bills, expenses",
            "usage for any cloud service or resource",
            "how much does X cost?",
            "show me costs by service / region / team",
        ],
        "example_prompts": [
            "How much did we spend on EC2 last month?",
            "Show me AWS costs by service for last 30 days",
            "What are our Kubernetes pod costs this week?",
            "Break down our GCP costs by project",
        ],
        "key_params": [
            "time_period (default: last_30_days)",
            "cost_type — cost metric (defaults to account setting)",
            "filters — copy from search_filters",
            "group_by — copy from search_filters",
            "usage_configuration — for usage alongside cost",
        ],
        "workflow": "search_filters → get_filter_values → query_costs",
    },
    {
        "name": "compare_costs",
        "category": "cost_query",
        "availability": "public",
        "description": "Compare cloud costs between two time periods.",
        "when_to_use": [
            "compare, vs, change, trend",
            "grew, shrank, increased, decreased",
            "cost difference between periods",
            "how did X change from last month to this month?",
        ],
        "example_prompts": [
            "How do this month's EC2 costs compare to last month?",
            "Did our AWS spend increase week over week?",
            "Compare production vs staging costs",
        ],
        "key_params": [
            "current_period",
            "comparison_period",
            "cost_type — cost metric (defaults to account setting)",
            "filters — copy from search_filters",
            "group_by",
        ],
        "workflow": "search_filters → get_filter_values → compare_costs",
    },
    {
        "name": "get_anomalies",
        "category": "cost_query",
        "availability": "public",
        "description": "Retrieve detected cost anomalies and spending spikes.",
        "when_to_use": [
            "spike, anomaly, unusual, unexpected cost",
            "sudden increase, irregular spending",
            "what went wrong with costs?",
        ],
        "example_prompts": [
            "Are there any cost spikes this week?",
            "Show me unusual spending in the last 7 days",
            "What caused the cost anomaly yesterday?",
        ],
        "key_params": [
            "time_period (today | yesterday | last_7_days | last_30_days)",
            "severity (high | medium | low)",
        ],
        "workflow": None,
    },
    {
        "name": "get_financial_plans",
        "category": "cost_query",
        "availability": "public",
        "description": "Get financial plans with budget, actual cost, run rate, and forecast.",
        "when_to_use": [
            "budget, financial plan, forecast",
            "planned spend, budget vs actual",
            "are we on track? budget utilization",
            "burn rate, will we exceed budget?",
        ],
        "example_prompts": [
            "What's our AWS budget for this month?",
            "Show me all active financial plans",
            "Are we on track with the Q1 budget?",
            "What's our burn rate vs the planned budget?",
        ],
        "key_params": [
            "name — omit to list plan names, provide to get details for one plan",
            "period — month in YYYY-M format (default: current month)",
        ],
        "workflow": None,
    },
    {
        "name": "get_waste_recommendations",
        "category": "waste",
        "availability": "public",
        "description": "Get CostGuard waste detection and optimization recommendations.",
        "when_to_use": [
            "savings, waste, idle, optimize",
            "reduce costs, shut down, unused resources",
            "rightsizing, over-provisioned",
        ],
        "example_prompts": [
            "What resources can we shut down to save money?",
            "Show me idle EC2 instances",
            "What are our top cost optimization opportunities?",
            "Which RDS instances are over-provisioned?",
        ],
        "key_params": [
            "scan_type (idle | rightsizing | commitment)",
            "service (ec2 | rds | ebs | lambda | s3)",
            "min_saving — minimum monthly $ threshold",
        ],
        "workflow": None,
    },
    {
        "name": "search_filters",
        "category": "filters",
        "availability": "public",
        "description": "FIRST STEP for any cost query — find filter metadata by keyword. Searches filter keys, paths, and values.",
        "when_to_use": [
            "before any cost query or comparison",
            "looking up a service, region, tag, team, or dimension",
            "finding filters by value (e.g. 'marketplace' finds filters containing that value)",
        ],
        "example_prompts": [
            "(internal — called automatically before cost queries)",
        ],
        "key_params": [
            "query — keyword to search (e.g. 'service', 'environment', 'pod')",
            "cost_center — limit search to specific cost center (optional)",
        ],
        "workflow": "search_filters → get_filter_values → query_costs",
    },
    {
        "name": "get_filter_values",
        "category": "filters",
        "availability": "public",
        "description": "Get the actual values for a filter key (e.g. list all services).",
        "when_to_use": [
            "what X do we have? (services, environments, regions…)",
            "verifying exact values before querying",
        ],
        "example_prompts": [
            "What services do we have in AWS?",
            "List all environments in our cost data",
            "What Kubernetes namespaces exist?",
        ],
        "key_params": [
            "filter_key — from search_filters result",
            "cost_center — from search_filters result",
            "filter_type — must match search_filters 'type' field",
            "limit (default: 100, max: 500)",
        ],
        "workflow": "search_filters → get_filter_values → query_costs",
    },
    {
        "name": "list_available_filters",
        "category": "filters",
        "availability": "public",
        "description": "List all available filters by cost center (large response — last resort).",
        "when_to_use": [
            "what filters exist?",
            "what can I filter by?",
            "show me all available filters",
        ],
        "example_prompts": [
            "What filters are available for AWS?",
            "Show me everything I can filter by",
        ],
        "key_params": [
            "cost_center — limit to specific provider (optional)",
        ],
        "workflow": None,
    },
    {
        "name": "get_usage_unit_types",
        "category": "filters",
        "availability": "public",
        "description": "Discover valid usage units for a cost center (e.g. Hrs, GB, Count).",
        "when_to_use": [
            "before any usage query",
            "what units are available for AWS/GCP/Azure?",
        ],
        "example_prompts": [
            "(internal — called before usage queries to discover valid units)",
        ],
        "key_params": [
            "time_period (default: last_30_days)",
            "filters — narrow to specific provider",
        ],
        "workflow": "get_usage_unit_types → query_costs with usage_configuration",
    },
    {
        "name": "get_object_usages",
        "category": "context",
        "availability": "public",
        "description": "Find all places where a named Finout object is referenced.",
        "when_to_use": [
            "where is X used?",
            "what uses my virtual tag / view / dashboard?",
            "show me dependencies of Z",
        ],
        "example_prompts": [
            "Where is the 'Production' virtual tag used?",
            "What dashboards reference my EC2 view?",
            "Show me everything that depends on this tag",
        ],
        "key_params": [
            "name — object name to look up",
            "entity_type (virtual_tag | view | dashboard | widget | explorer | alert | financial_plan)",
        ],
        "workflow": None,
    },
    {
        "name": "check_delete_safety",
        "category": "context",
        "availability": "public",
        "description": "Check if a Finout object is safe to delete (not referenced anywhere).",
        "when_to_use": [
            "can I delete X?",
            "is X still in use?",
            "is it safe to remove Y?",
        ],
        "example_prompts": [
            "Can I delete the 'Dev costs' view?",
            "Is the 'Staging' virtual tag still in use?",
            "Is it safe to remove this dashboard?",
        ],
        "key_params": [
            "name — object name to check",
            "entity_type — optional, narrows search",
        ],
        "workflow": None,
    },
    {
        "name": "discover_context",
        "category": "context",
        "availability": "internal",
        "description": "Search dashboards and views to understand how the org structures cost data.",
        "when_to_use": [
            "unfamiliar team name, project, or custom grouping",
            "how does the org track X?",
        ],
        "example_prompts": [
            "How do we track costs for the Vikings team?",
            "What does the production environment look like in Finout?",
        ],
        "key_params": [
            "query — concept to search (e.g. 'vikings', 'production', 'kafka')",
            "include_dashboards / include_views / include_data_explorers",
        ],
        "workflow": None,
    },
    {
        "name": "get_account_context",
        "category": "context",
        "availability": "internal",
        "description": "Get account name, connected cost centers, and available filter counts.",
        "when_to_use": [
            "start of conversation — understand what data is available",
            "which cloud providers are connected?",
        ],
        "example_prompts": [
            "(internal — called once at start of conversation)",
        ],
        "key_params": [],
        "workflow": None,
    },
    {
        "name": "create_view",
        "category": "context",
        "availability": "internal",
        "description": "Save a query as a reusable view in Finout.",
        "when_to_use": [
            "save this query, create a view",
            "I want to bookmark this analysis",
        ],
        "example_prompts": [
            "Save this as a view called 'EC2 by region'",
            "Can you save this cost query for later?",
        ],
        "key_params": [
            "name (required)",
            "filters, group_by, time_period, cost_type",
        ],
        "workflow": None,
    },
    {
        "name": "create_dashboard",
        "category": "context",
        "availability": "internal",
        "description": "Create a multi-widget dashboard in Finout.",
        "when_to_use": [
            "create a dashboard, build a dashboard",
            "I want an overview dashboard for X",
        ],
        "example_prompts": [
            "Create a dashboard with EC2, RDS, and S3 costs",
            "Build a monthly overview dashboard",
        ],
        "key_params": [
            "name (required)",
            "widgets — array of widget definitions",
        ],
        "workflow": None,
    },
    {
        "name": "analyze_virtual_tags",
        "category": "context",
        "availability": "public",
        "description": "Analyze virtual tag relationships, dependencies, and allocation chains.",
        "when_to_use": [
            "virtual tag relationships, dependencies, hierarchies",
            "cost allocation strategies, reallocation setup",
            "how do tags reference each other?",
        ],
        "example_prompts": [
            "Show me the virtual tag dependency graph",
            "How does the 'Team' tag get its values?",
            "What does our cost allocation chain look like?",
        ],
        "key_params": [
            "tag_name — focus on specific tag (optional, omit for global view)",
        ],
        "workflow": None,
    },
    {
        "name": "render_chart",
        "category": "visualization",
        "availability": "internal",
        "description": "Render a chart (bar, line, pie, column) in the Billy UI.",
        "when_to_use": [
            "show me a chart, visualize this",
            "called automatically after cost answers to show key data",
        ],
        "example_prompts": [
            "Show me a chart of costs by service",
            "Visualize the cost trend for last quarter",
        ],
        "key_params": [
            "title, chart_type (bar | line | pie | column)",
            "categories — x-axis labels",
            "series — data arrays (must match categories length)",
        ],
        "workflow": None,
    },
    {
        "name": "get_top_movers",
        "category": "cost_query",
        "availability": "public",
        "description": "Identify dimensions with the biggest cost changes between two periods.",
        "when_to_use": [
            "what changed? what drove the increase?",
            "biggest cost changes, what spiked?",
            "where did costs go up/down?",
            "cost movement by service/region/team",
        ],
        "example_prompts": [
            "What drove our cost increase this month?",
            "Which services had the biggest cost changes?",
            "What spiked in the last 7 days compared to before?",
            "Show me the top cost movers by region",
        ],
        "key_params": [
            "group_by (REQUIRED) — dimension to rank by",
            "time_period (default: last_30_days)",
            "comparison_period (auto-inferred if omitted)",
            "filters, limit (default: 10)",
        ],
        "workflow": "search_filters → get_top_movers",
    },
    {
        "name": "get_unit_economics",
        "category": "cost_query",
        "availability": "public",
        "description": "Compute cost-per-unit using usage metrics (hours, GB) or resource counts.",
        "when_to_use": [
            "cost per instance, cost per resource",
            "average cost per X, unit economics",
            "cost per hour, cost per GB, cost per request",
            "cost efficiency by service (usage mode, one call per service)",
        ],
        "example_prompts": [
            "What's the cost per EC2 running hour?",
            "How much does each Lambda function cost on average?",
            "What's our cost per GB for S3?",
            "Show me unit economics for my top services",
        ],
        "key_params": [
            "usage_configuration — for cost ÷ usage (hours, GB, requests)",
            "count_distinct — for cost ÷ resource count (single service only)",
            "time_period (default: last_30_days)",
            "group_by, filters, cost_type",
        ],
        "workflow": "search_filters → get_usage_unit_types → get_unit_economics",
    },
    {
        "name": "get_cost_patterns",
        "category": "cost_query",
        "availability": "public",
        "description": "Analyze hourly cost patterns — peak hours, off-peak, weekday vs weekend.",
        "when_to_use": [
            "peak hours, off-peak, hourly pattern",
            "when is spending highest?",
            "weekday vs weekend costs",
        ],
        "example_prompts": [
            "When are our costs highest during the day?",
            "Show me the hourly cost pattern for this week",
            "Is our weekend spend different from weekdays?",
        ],
        "key_params": [
            "time_period (default: last_7_days)",
            "filters, group_by",
        ],
        "workflow": "search_filters → get_cost_patterns",
    },
    {
        "name": "get_savings_coverage",
        "category": "cost_query",
        "availability": "public",
        "description": "Analyze savings plan and reservation coverage rates.",
        "when_to_use": [
            "savings plan coverage, RI utilization",
            "on-demand vs reserved",
            "commitment coverage optimization",
        ],
        "example_prompts": [
            "What's our savings plan coverage by service?",
            "How much are we paying on-demand vs reserved?",
            "Which services have low RI coverage?",
        ],
        "key_params": [
            "time_period (default: last_30_days)",
            "group_by — break down coverage by dimension",
            "filters",
        ],
        "workflow": "search_filters → get_savings_coverage",
    },
    {
        "name": "get_tag_coverage",
        "category": "cost_query",
        "availability": "public",
        "description": "Measure what percentage of spend is tagged by a dimension.",
        "when_to_use": [
            "tag coverage, untagged spend",
            "governance, tagging gaps",
            "cost allocation completeness",
        ],
        "example_prompts": [
            "What percentage of our spend is tagged by team?",
            "Which services have the worst tag coverage?",
            "How much untagged spend do we have?",
        ],
        "key_params": [
            "tag_dimension (REQUIRED) — tag to measure coverage for",
            "time_period, group_by, filters",
        ],
        "workflow": "search_filters → get_tag_coverage",
    },
    {
        "name": "get_cost_statistics",
        "category": "cost_query",
        "availability": "public",
        "description": "Daily cost statistics — mean, median, peak, trough, volatility.",
        "when_to_use": [
            "average daily cost, cost volatility",
            "peak day, most expensive day",
            "cost variability, distribution",
        ],
        "example_prompts": [
            "What's our average daily AWS cost?",
            "Which day had the highest cost last month?",
            "How volatile is our daily spend?",
        ],
        "key_params": [
            "time_period (default: last_30_days)",
            "group_by, filters",
        ],
        "workflow": "search_filters → get_cost_statistics",
    },
    {
        "name": "list_data_explorers",
        "category": "context",
        "availability": "public",
        "description": "List saved data explorer configurations in the account.",
        "when_to_use": [
            "what data explorers exist?",
            "show me saved queries",
            "find a data explorer",
        ],
        "example_prompts": [
            "What data explorers do we have?",
            "Show me saved data explorers about compute costs",
        ],
        "key_params": [
            "query — filter by name/description keyword (optional)",
        ],
        "workflow": None,
    },
    {
        "name": "list_telemetry_centers",
        "category": "context",
        "availability": "internal",
        "description": "List telemetry centers that feed custom metrics into virtual tags and cost allocation.",
        "when_to_use": [
            "telemetry centers, KPI centers, custom metrics",
            "what data feeds my virtual tags?",
            "where does this reallocation metric come from?",
            "data pipeline for cost allocation",
        ],
        "example_prompts": [
            "What telemetry centers do I have?",
            "Show me my Datadog metrics",
            "Which telemetry center feeds the anthropic_ratio virtual tag?",
            "List all S3-based telemetry sources",
        ],
        "key_params": [
            "type — filter by source type (s3-csv, megabill-ratio, costexplorer, cloudwatch, datadog)",
            "name — filter by name (substring match)",
        ],
        "workflow": None,
    },
    {
        "name": "debug_filters",
        "category": "filters",
        "availability": "internal",
        "description": "Inspect raw filter metadata — for debugging unexpected search results.",
        "when_to_use": [
            "filter searches return unexpected results",
            "filter cache may be stale",
        ],
        "example_prompts": [
            "(internal — diagnostic use only)",
        ],
        "key_params": [
            "cost_center — limit to specific cost center (optional)",
            "filter_type — limit to specific type (optional)",
        ],
        "workflow": None,
    },
    {
        "name": "submit_feedback",
        "category": "admin",
        "availability": "internal",
        "description": "Submit feedback about the quality of a Billy response.",
        "when_to_use": [
            "called automatically at the end of every interaction",
        ],
        "example_prompts": [
            "(internal — automatic feedback collection)",
        ],
        "key_params": [
            "rating (1–5)",
            "query_type, tools_used, friction_points, suggestion",
        ],
        "workflow": None,
    },
]
