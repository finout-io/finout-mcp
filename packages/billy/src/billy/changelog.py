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
