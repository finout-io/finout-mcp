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
                "Fix evaluation runner to use Langfuse v3 run_experiment API with async task support"
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
