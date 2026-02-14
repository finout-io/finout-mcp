"""
Filter Utilities - helper functions for organizing, searching, and formatting filters.

These utilities help prevent context overload by intelligently organizing and limiting
filter data sent to the LLM.
"""

import re
from typing import Any


def organize_filters_by_cost_center(filters: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """
    Organize filters by cost center for easier browsing.

    Args:
        filters: Raw filters data from API

    Returns:
        Dictionary mapping cost center to list of filters
    """
    organized = {}

    for cost_center, filter_types in filters.items():
        if not isinstance(filter_types, dict):
            continue

        cost_center_filters = []

        for filter_type, filter_list in filter_types.items():
            if not isinstance(filter_list, list):
                continue

            for filter_item in filter_list:
                # Extract metadata without values
                filter_info = {
                    "key": filter_item.get("key", ""),
                    "type": filter_type,
                    "costCenter": cost_center,  # Use camelCase to match API format
                    "path": filter_item.get("path", ""),
                    "value_count": len(filter_item.get("values", []))
                    if "values" in filter_item
                    else 0,
                }
                cost_center_filters.append(filter_info)

        if cost_center_filters:
            organized[cost_center] = cost_center_filters

    return organized


def search_filters_by_keyword(
    filters: dict[str, Any], query: str, cost_center: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """
    Search filters by keyword with relevance ranking.

    Args:
        filters: Raw filters data from API
        query: Search query (case-insensitive)
        cost_center: Optional cost center to filter by
        limit: Maximum number of results

    Returns:
        List of matching filters, sorted by relevance
    """
    query_lower = query.lower()
    results = []

    for cc, filter_types in filters.items():
        # Skip if cost center filter specified and doesn't match
        if cost_center and cc.lower() != cost_center.lower():
            continue

        if not isinstance(filter_types, dict):
            continue

        for filter_type, filter_list in filter_types.items():
            if not isinstance(filter_list, list):
                continue

            for filter_item in filter_list:
                key = filter_item.get("key", "")
                path = filter_item.get("path", "")

                # Calculate relevance score
                relevance = 0

                # Exact match in key (highest priority)
                if query_lower == key.lower():
                    relevance = 100
                # Key starts with query
                elif key.lower().startswith(query_lower):
                    relevance = 80
                # Query in key
                elif query_lower in key.lower():
                    relevance = 60
                # Query in path
                elif query_lower in path.lower():
                    relevance = 40
                # Fuzzy match (word boundary)
                elif re.search(rf"\b{re.escape(query_lower)}", key.lower()):
                    relevance = 50
                elif re.search(rf"\b{re.escape(query_lower)}", path.lower()):
                    relevance = 30

                if relevance > 0:
                    results.append(
                        {
                            "key": key,
                            "type": filter_type,
                            "costCenter": cc,  # Use camelCase to match API format
                            "path": path,
                            "relevance": relevance,
                            "value_count": len(filter_item.get("values", []))
                            if "values" in filter_item
                            else 0,
                        }
                    )

    # Sort by relevance (highest first), then by key
    results.sort(key=lambda x: (-x["relevance"], x["key"]))

    return results[:limit]


def format_filter_metadata_for_llm(
    organized_filters: dict[str, list[dict[str, Any]]],
    include_counts: bool = True,
    max_per_cost_center: int | None = None,
) -> str:
    """
    Format filter metadata in a concise, readable format for the LLM.

    Args:
        organized_filters: Filters organized by cost center
        include_counts: Whether to include value counts
        max_per_cost_center: Maximum filters to show per cost center

    Returns:
        Formatted string suitable for LLM consumption
    """
    lines = []
    lines.append("# Available Filters\n")

    for cost_center, filters in sorted(organized_filters.items()):
        lines.append(f"\n## {cost_center.upper()}")
        lines.append(f"Total filters: {len(filters)}\n")

        # Group by type
        by_type: dict[str, list[dict[str, Any]]] = {}
        for f in filters:
            filter_type = f.get("type", "unknown")
            if filter_type not in by_type:
                by_type[filter_type] = []
            by_type[filter_type].append(f)

        for filter_type, type_filters in sorted(by_type.items()):
            lines.append(f"\n### {filter_type}")

            # Limit if specified
            display_filters = type_filters
            if max_per_cost_center:
                display_filters = type_filters[:max_per_cost_center]

            for f in display_filters:
                key = f.get("key", "")
                path = f.get("path", "")
                value_count = f.get("value_count", 0)

                if include_counts:
                    lines.append(f"- **{key}** (path: `{path}`, {value_count} values)")
                else:
                    lines.append(f"- **{key}** (path: `{path}`)")

            # Show truncation message
            if max_per_cost_center and len(type_filters) > max_per_cost_center:
                remaining = len(type_filters) - max_per_cost_center
                lines.append(f"  _(... and {remaining} more)_")

    return "\n".join(lines)


def format_search_results(results: list[dict[str, Any]], max_results: int = 50) -> str:
    """
    Format filter search results for the LLM.

    Args:
        results: Search results from search_filters_by_keyword
        max_results: Maximum results to display

    Returns:
        Formatted string
    """
    if not results:
        return "No filters found matching your query."

    lines = []
    lines.append(f"# Search Results ({len(results)} matches)\n")

    display_results = results[:max_results]

    # Group by type for clarity
    tags = [r for r in display_results if r.get("type") == "tag"]
    columns = [r for r in display_results if r.get("type") == "col"]
    others = [r for r in display_results if r.get("type") not in ["tag", "col"]]

    # Show tags first (often what users are looking for)
    if tags:
        lines.append("\n## 🏷️ TAGS (Custom Labels)")
        for i, result in enumerate(tags, 1):
            key = result.get("key", "")
            cost_center = result.get("costCenter", "")
            path = result.get("path", "")
            value_count = result.get("value_count", 0)

            lines.append(
                f"{i}. **{key}** [{cost_center.upper()}] - path: `{path}` ({value_count} values)"
            )

    # Then columns (standard filters)
    if columns:
        lines.append("\n## 📊 COLUMNS (Standard Filters)")
        for i, result in enumerate(columns, 1):
            key = result.get("key", "")
            cost_center = result.get("costCenter", "")
            path = result.get("path", "")
            value_count = result.get("value_count", 0)

            lines.append(
                f"{i}. **{key}** [{cost_center.upper()}] - path: `{path}` ({value_count} values)"
            )

    # Any other types
    if others:
        lines.append("\n## OTHER")
        for i, result in enumerate(others, 1):
            key = result.get("key", "")
            cost_center = result.get("costCenter", "")
            filter_type = result.get("type", "")
            path = result.get("path", "")
            value_count = result.get("value_count", 0)

            lines.append(
                f"{i}. **{key}** "
                f"[{cost_center.upper()}/{filter_type}] "
                f"- path: `{path}` ({value_count} values)"
            )

    if len(results) > max_results:
        remaining = len(results) - max_results
        lines.append(f"\n_(... and {remaining} more results)_")

    lines.append(
        "\n**💡 TIP:** Use get_filter_values(filter_key, cost_center, filter_type) to see actual values for any filter above."
    )

    return "\n".join(lines)


def truncate_filter_values(
    values: list[Any], limit: int = 100, include_stats: bool = True
) -> dict[str, Any]:
    """
    Truncate filter values to prevent context overload.

    Args:
        values: List of filter values
        limit: Maximum values to return
        include_stats: Whether to include statistics

    Returns:
        Dictionary with truncated values and metadata
    """
    total_count = len(values)
    truncated = values[:limit]
    is_truncated = total_count > limit

    result = {
        "values": truncated,
        "total_count": total_count,
        "returned_count": len(truncated),
        "is_truncated": is_truncated,
    }

    if include_stats and truncated:
        # Try to provide some basic stats if values are numeric
        try:
            numeric_values = [float(v) for v in truncated if isinstance(v, int | float)]
            if numeric_values:
                result["stats"] = {
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "avg": sum(numeric_values) / len(numeric_values),
                }
        except (ValueError, TypeError):
            # Values not numeric, skip stats
            pass

    return result


def format_filter_values(
    filter_key: str, values_data: dict[str, Any], cost_center: str | None = None
) -> str:
    """
    Format filter values for display to the LLM.

    Args:
        filter_key: The filter key
        values_data: Output from truncate_filter_values
        cost_center: Optional cost center for context

    Returns:
        Formatted string
    """
    lines = []

    header = f"# Values for filter: {filter_key}"
    if cost_center:
        header += f" [{cost_center.upper()}]"
    lines.append(header)
    lines.append("")

    total_count = values_data.get("total_count", 0)
    returned_count = values_data.get("returned_count", 0)
    is_truncated = values_data.get("is_truncated", False)

    lines.append(f"Total values: {total_count}")
    lines.append(f"Showing: {returned_count}")

    if is_truncated:
        lines.append(f"**Note:** Results truncated to {returned_count} values")

    # Show stats if available
    if "stats" in values_data:
        stats = values_data["stats"]
        lines.append("\nStatistics:")
        lines.append(f"- Min: {stats['min']}")
        lines.append(f"- Max: {stats['max']}")
        lines.append(f"- Avg: {stats['avg']:.2f}")

    lines.append("\n## Values:")

    values = values_data.get("values", [])
    for i, value in enumerate(values, 1):
        lines.append(f"{i}. {value}")

    return "\n".join(lines)
