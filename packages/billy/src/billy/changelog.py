"""Versioned changelog entries shipped with Billy."""

from typing import TypedDict, List


class ChangelogSections(TypedDict):
    external_mcp: List[str]
    internal_mcp: List[str]
    billy: List[str]


class ChangelogEntry(TypedDict):
    version: str
    date: str
    title: str
    sections: ChangelogSections


# Newest first. Add one entry for every released version.
CHANGELOG_ENTRIES: List[ChangelogEntry] = [
    {
        "version": "0.24.0",
        "date": "2026-03-12",
        "title": "Speed up analytics tools",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "Top movers, tag coverage, and budget status tools now run their data queries in parallel for faster responses"
            ],
            "billy": [
                "No changes"
            ]
        }
    },
    {
        "version": "0.23.0",
        "date": "2026-03-12",
        "title": "Speed up analytics tools",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "Top movers, tag coverage, and budget status tools now run their data queries in parallel for faster responses"
            ],
            "billy": [
                "No changes"
            ]
        }
    },
    {
        "version": "0.22.0",
        "date": "2026-03-12",
        "title": "Fix get_cost_patterns for accounts without hourly billing data",
        "sections": {
            "external_mcp": [
                "get_cost_patterns now works for all accounts \u2014 it falls back to daily granularity when hourly billing data isn't available, and still provides weekday vs weekend breakdown and day-of-week averages"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "No changes"
            ]
        }
    },
    {
        "version": "0.21.0",
        "date": "2026-03-12",
        "title": "Fix misleading partial-period cost comparisons",
        "sections": {
            "external_mcp": [
                "get_top_movers now automatically normalizes mid-month comparisons \u2014 asking 'what changed this month vs last month?' on day 12 now compares the first 12 days of each month, not 12 days vs a full month",
                "compare_costs now warns when one period is partial (this_month, this_week, etc.) and suggests the equivalent normalized comparison period"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "No changes"
            ]
        }
    },
    {
        "version": "0.20.0",
        "date": "2026-03-12",
        "title": "Fix misleading partial-period cost comparisons",
        "sections": {
            "external_mcp": [
                "get_top_movers now automatically normalizes mid-month comparisons \u2014 asking 'what changed this month vs last month?' on day 12 now compares the first 12 days of each month, not 12 days vs a full month",
                "compare_costs now warns when one period is partial (this_month, this_week, etc.) and suggests the equivalent normalized comparison period"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "No changes"
            ]
        }
    },
    {
        "version": "0.19.0",
        "date": "2026-03-12",
        "title": "Advanced cost analytics tools",
        "sections": {
            "external_mcp": [
                "New tool: get_top_movers \u2014 identify which services, regions, or tags drove the biggest cost changes between two periods",
                "New tool: get_unit_economics \u2014 compute cost-per-resource (e.g., cost per EC2 instance, cost per namespace) for any dimension",
                "New tool: get_cost_patterns \u2014 analyze hourly cost patterns, peak vs off-peak hours, and weekday/weekend splits",
                "New tool: get_savings_coverage \u2014 show how much spend is covered by savings plans and reservations vs on-demand",
                "New tool: get_tag_coverage \u2014 measure what percentage of spend is tagged, and surface groups with poor tag coverage",
                "New tool: get_budget_status \u2014 compare actual spend against financial plan budgets with burn rate and month-end projections",
                "New tool: get_cost_statistics \u2014 compute daily cost statistics (mean, median, peak/trough days, volatility) for any scope",
                "compare_costs now supports extra cost measurements (amortized, unblended, blended) and billing metrics (savings plan, reservation) in a single call"
            ],
            "internal_mcp": [
                "New tool: list_data_explorers \u2014 browse saved data explorer configurations to discover available cost views"
            ],
            "billy": [
                "Tools panel updated with all new analytics tools"
            ]
        }
    },
    {
        "version": "0.18.0",
        "date": "2026-03-12",
        "title": "Data explorer costs and sidebar toggle polish",
        "sections": {
            "external_mcp": [
                "Route cost queries through the data-explorer preview API and update grouped cost parsing/tests for flat row responses"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Make the sidebar expand/collapse control smaller, icon-based, and pinned to the upper-right without overlapping the new-conversation action"
            ]
        }
    },
    {
        "version": "0.17.0",
        "date": "2026-03-11",
        "title": "FOBO embedded mode",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Add embedded-mode account syncing with FOBO while ignoring persisted standalone account selection",
                "Load embedded user identity from URL params without persisting it to local storage",
                "Hide header and banner in embedded mode and add an auto-collapsed, collapsible sidebar with a compact new-conversation action",
                "Make Billy CORS origins configurable via BILLY_ALLOWED_ORIGINS"
            ]
        }
    },
    {
        "version": "0.16.0",
        "date": "2026-03-11",
        "title": "Improve dependency detection for virtual tag usages",
        "sections": {
            "external_mcp": [
                "get_object_usages and check_delete_safety now detect financial plan references via structured pattern matching (default.value.key, filter costCenter:virtualTag) and transitive virtual tag dependency chains"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "No changes"
            ]
        }
    },
    {
        "version": "0.15.0",
        "date": "2026-03-08",
        "title": "Personalized welcome screen and user memories",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "Fix virtual tag type inference for multiKeyReallocation tags"
            ],
            "billy": [
                "Add personalized welcome greeting with user name and time of day",
                "Add context-aware suggested queries based on account virtual tags and cost centers",
                "Add user memory system \u2014 Billy remembers personal facts across conversations",
                "Suggested queries rotate across tools (anomalies, waste, budgets, comparisons) to encourage exploration"
            ]
        }
    },
    {
        "version": "0.14.0",
        "date": "2026-03-08",
        "title": "AI disclaimer",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Add AI disclaimer near chat input"
            ]
        }
    },
    {
        "version": "0.13.0",
        "date": "2026-03-08",
        "title": "Usage diagram tests",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Add unit and integration tests for summary/detail usage diagrams"
            ]
        }
    },
    {
        "version": "0.12.0",
        "date": "2026-03-08",
        "title": "Cross-provider filter gap detection",
        "sections": {
            "external_mcp": [
                "search_filters now searches filter values (not just keys/paths), enabling discovery of filters like 'marketplace' across providers",
                "search_filters returns cross_provider_note when results match some but not all cloud providers",
                "query_costs warns when exclusion filters (not/notOneOf) only target a subset of cost centers in the query"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Updated tools reference for search_filters value-based search"
            ]
        }
    },
    {
        "version": "0.11.0",
        "date": "2026-03-08",
        "title": "Billy UI redesign \u2014 Finout-aligned light theme",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Redesigned UI to match Finout app visual style (light theme, dark navy sidebar)",
                "Replaced robot emoji avatar with Billy cat mascot image",
                "Updated sidebar banner to transparent-background version",
                "Fixed chart and Mermaid diagram colors for light mode legibility",
                "Bumped font sizes and updated link color to #1570ef",
                "Locked app to light mode only (removed theme toggle)"
            ]
        }
    },
    {
        "version": "0.10.0",
        "date": "2026-03-08",
        "title": "Tools reference panel in Billy UI",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Add Tools panel to Billy UI listing all available MCP tools with descriptions, example prompts, and category filters",
                "Add tools_reference.py as the source of truth for tool documentation (synced with tool_schemas.py)",
                "Add CLAUDE.md rule: update tools_reference.py whenever tools are added/changed/removed"
            ]
        }
    },
    {
        "version": "0.9.0",
        "date": "2026-03-08",
        "title": "Improve streaming readability",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Fix streaming text: separate each LLM turn with a paragraph break so multi-step reasoning is readable",
                "Instruct Claude not to end narration sentences with a colon before tool calls",
                "Add remark-breaks to render single newlines as line breaks in chat"
            ]
        }
    },
    {
        "version": "0.8.0",
        "date": "2026-03-08",
        "title": "Object usage tracing + Billy OAuth endpoints",
        "sections": {
            "external_mcp": [
                "New `get_object_usages` tool \u2014 find all places where a named Finout object (virtual tag, view, dashboard, etc.) is referenced",
                "New `check_delete_safety` tool \u2014 check if an object is safe to delete by scanning all entity dependencies"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Add OAuth endpoints for MCP client authentication (authorize, token, register, well-known discovery)"
            ]
        }
    },
    {
        "version": "0.7.0",
        "date": "2026-03-05",
        "title": "Release script improvement",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Stage all tracked changes in one release commit instead of splitting into two"
            ]
        }
    },
    {
        "version": "0.6.0",
        "date": "2026-03-05",
        "title": "Evaluation pipeline and release workflow",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Add Langfuse evaluation runner with tool_correctness, no_fabrication, and response_quality (LLM-as-judge) scores",
                "Upgrade release-whats-new command to skill with description frontmatter"
            ]
        }
    },
    {
        "version": "0.5.0",
        "date": "2026-03-05",
        "title": "Langfuse evaluation pipeline",
        "sections": {
            "external_mcp": [
                "No changes"
            ],
            "internal_mcp": [
                "No changes"
            ],
            "billy": [
                "Add evaluation dataset seeder and experiment runner with tool_correctness, no_fabrication, and response_quality (LLM-as-judge) scores",
                "Fix evaluation runner to use the Langfuse experiment API with async task support"
            ]
        }
    },
    {
        "version": "0.4.0",
        "date": "2026-03-03",
        "title": "Frontend user identity capture for trace attribution",
        "sections": {
            "external_mcp": [
                "No public MCP API behavior changes."
            ],
            "internal_mcp": [
                "No internal MCP runtime behavior changes."
            ],
            "billy": [
                "Added local user profile capture (name and email) in the frontend.",
                "Passed user_email in chat requests for Langfuse user trace attribution."
            ]
        }
    },
    {
        "version": "0.3.0",
        "date": "2026-03-03",
        "title": "Langfuse observability across MCP and Billy chat",
        "sections": {
            "external_mcp": [
                "Added optional Langfuse tracing hooks for MCP tool calls.",
                "Added docker-compose Langfuse stack for local observability."
            ],
            "internal_mcp": [
                "Instrumented Billy chat pipeline spans and feedback scoring in Langfuse.",
                "Added optional observability dependency group for mcp-server package."
            ],
            "billy": [
                "Added Langfuse and Anthropic OpenTelemetry instrumentation dependencies.",
                "Added evaluation runner utilities for seeded Langfuse dataset experiments."
            ]
        }
    },
    {
        "version": "0.2.0",
        "date": "2026-03-03",
        "title": "Billy rename and categorized What's New",
        "sections": {
            "external_mcp": [
                "No public MCP tool changes in this release."
            ],
            "internal_mcp": [
                "Renamed internal MCP runtime surfaces and launcher naming to Billy.",
                "Updated Billy internal MCP startup fallback to use uv-run launcher when needed."
            ],
            "billy": [
                "Renamed Vectiqor branding/assets/runtime references to Billy.",
                "Added categorized What's New dialog with unseen-version tracking via localStorage.",
                "Added a persistent What's New link to view full changelog history on demand."
            ]
        }
    },
    {
        "version": "0.1.0",
        "date": "2026-03-02",
        "title": "Renamed to Billy + What's New",
        "sections": {
            "external_mcp": [
                "No public MCP toolset changes in this release."
            ],
            "internal_mcp": [
                "Renamed internal MCP runtime surfaces to Billy naming."
            ],
            "billy": [
                "Renamed the internal assistant and runtime surfaces to Billy.",
                "Added a versioned what's-new feed exposed by the backend.",
                "Added an on-load modal that shows changelog entries the user has not seen yet."
            ]
        }
    }
]
