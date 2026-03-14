"""Filter discovery, search, and value retrieval tools."""

import asyncio
from typing import Any


async def list_available_filters_impl(args: dict) -> dict:
    """Implementation of list_available_filters tool"""
    from ..server import get_client

    finout_client = get_client()

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

    from ..filter_utils import format_filter_metadata_for_llm, organize_filters_by_cost_center

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
    from ..server import get_client

    finout_client = get_client()

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

    from ..filter_utils import format_search_results

    # Search filters
    results = await finout_client.search_filters(query, cost_center, limit=50)

    # Fetch sample values for top 5 results in parallel
    sample_values: dict[str, list[str]] = {}
    top_results = results[:5]
    if top_results:

        async def _fetch_samples(r: dict) -> tuple[str, list[str]]:
            key = f"{r.get('costCenter', '')}:{r.get('type', '')}:{r.get('key', '')}"
            try:
                vals = await finout_client.get_filter_values(
                    r.get("key", ""),
                    r.get("costCenter"),
                    r.get("type"),
                    limit=8,
                )
                return key, [str(v) for v in vals]
            except Exception:
                return key, []

        fetched = await asyncio.gather(*[_fetch_samples(r) for r in top_results])
        for sv_key, vals in fetched:
            if vals:
                sample_values[sv_key] = vals

    # Format for LLM
    formatted = format_search_results(results, max_results=50, sample_values=sample_values)

    # Build copy-pasteable filter objects for top results
    copy_paste_filters = []
    for r in results[:10]:
        cost_center_value = r.get("costCenter")
        key_value = r.get("key")
        path_value = r.get("path")
        type_value = r.get("type")
        if all([cost_center_value, key_value, path_value, type_value]):
            copy_paste_filters.append(
                {
                    "costCenter": cost_center_value,
                    "key": key_value,
                    "path": path_value,
                    "type": type_value,
                }
            )

    response: dict[str, Any] = {
        "instruction": (
            "Pick a filter from 'filters' and call the appropriate tool:\n"
            "• Cost movers/changes → get_top_movers(group_by=[<filter>])\n"
            "• Cost totals/breakdown → query_costs(group_by=[<filter>])\n"
            "• Cost per unit → get_unit_economics\n"
            "• SP/RI coverage → get_savings_coverage(group_by=[<filter>])\n"
            "• Tag coverage → get_tag_coverage(tag_dimension=<filter>)\n"
            "• Cost patterns → get_cost_patterns\n"
            "• Statistics/volatility → get_cost_statistics(group_by=[<filter>])\n"
            "For group_by: use the filter object as-is. "
            "For filters with a specific value: add operator + value "
            "(call get_filter_values first — values are unintuitive). "
            "Do NOT modify costCenter, key, path, or type."
        ),
        "query": query,
        "cost_center": cost_center,
        "result_count": len(results),
        "results": formatted,
        "filters": copy_paste_filters,
    }

    # Cross-provider gap detection (only for broad searches without cost_center)
    if not cost_center and results:
        primary_providers = {"amazon-cur", "gcp", "azure"}
        matched_providers = {r.get("costCenter", "").lower() for r in results}
        matched_primary = matched_providers & primary_providers

        if matched_primary and len(matched_primary) < len(primary_providers):
            try:
                metadata = await finout_client.get_filters_metadata()
                known_providers = {cc.lower() for cc in metadata}
                known_primary = known_providers & primary_providers
                missing = known_primary - matched_primary
                if missing:
                    matched_list = sorted(matched_primary)
                    missing_list = sorted(missing)
                    suggestions = ", ".join(
                        f"search_filters('{query}', cost_center='{p}')" for p in missing_list
                    )
                    response["cross_provider_note"] = (
                        f"Found '{query}' in [{', '.join(matched_list)}] "
                        f"but NOT in [{', '.join(missing_list)}]. "
                        f"Each provider uses different filter names. "
                        f"Try: {suggestions} to find equivalent filters."
                    )
            except Exception:
                pass

    return response


async def debug_filters_impl(args: dict) -> dict:
    """Debug tool to inspect raw filter metadata"""
    from ..server import get_client

    finout_client = get_client()

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
    summary: dict[str, Any] = {"total_cost_centers": len(metadata), "cost_centers": {}}

    for cc, types in metadata.items():
        if cost_center_filter and cc.lower() != cost_center_filter.lower():
            continue

        type_counts: dict[str, int] = {}
        sample_filters: dict[str, list[dict[str, Any]]] = {}

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
            summary_cost_centers: dict[str, Any] = summary["cost_centers"]
            summary_cost_centers[cc] = {"type_counts": type_counts, "samples": sample_filters}

    return {
        "summary": summary,
        "note": "This shows what's in the filter cache. If tags are missing, the API may not be returning them.",
    }


async def get_filter_values_impl(args: dict) -> dict:
    """Implementation of get_filter_values tool"""
    from ..server import get_client

    finout_client = get_client()

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

    from ..filter_utils import format_filter_values, truncate_filter_values

    # Get values
    values = await finout_client.get_filter_values(
        filter_key, cost_center, filter_type, limit=limit
    )

    # Look up path from filter metadata so the LLM has the complete filter object
    filter_path = None
    try:
        metadata = await finout_client.get_filters_metadata()
        if cost_center and cost_center in metadata:
            types = metadata[cost_center]
            for ft, filter_list in types.items():
                if filter_type and ft != filter_type:
                    continue
                if isinstance(filter_list, list):
                    for f in filter_list:
                        if f.get("key") == filter_key:
                            filter_path = f.get("path")
                            if not filter_type:
                                filter_type = ft
                            break
                if filter_path:
                    break
    except Exception:
        pass

    # Truncate and format
    truncated = truncate_filter_values(values, limit=limit, include_stats=True)
    formatted = format_filter_values(filter_key, truncated, cost_center)

    result: dict[str, Any] = {
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

    # Include ready-to-use filter object for query_costs
    if filter_path and cost_center and filter_type:
        result["filter_object"] = {
            "costCenter": cost_center,
            "key": filter_key,
            "path": filter_path,
            "type": filter_type,
        }
        result["instruction"] = (
            "Copy filter_object into query_costs filters, then add 'operator' and 'value'."
        )

    return result


async def get_usage_unit_types_impl(args: dict) -> dict:
    """Implementation of get_usage_unit_types tool"""
    from ..server import get_client

    finout_client = get_client()

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
