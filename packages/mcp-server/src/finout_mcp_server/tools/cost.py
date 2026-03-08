"""Cost querying and comparison tools."""

from datetime import datetime
from typing import Any

from ..validation import _validate_filter_metadata, _validate_filter_values


def format_currency(amount: float) -> str:
    """Format currency with thousands separator"""
    return f"${amount:,.2f}"


def summarize_cost_data(data: dict | list, max_items: int = 25) -> dict | list:
    """
    Reduce cost data to what Claude actually needs for analysis.

    For list responses (cost-service row array):
      - Keeps Total row + top max_items service rows by totalCost
      - Collapses the tail into a single "Other" row so totals still balance
      - Strips display-only fields (dateRange, comparedRangeDate, percentOfTotalCost)

    For legacy dict responses with a "breakdown" key: groups small items as before.
    """
    strip_keys = {"dateRange", "comparedRangeDate", "percentOfTotalCost"}

    if isinstance(data, list):
        total_rows = [r for r in data if isinstance(r, dict) and r.get("name") == "Total"]
        service_rows = [r for r in data if isinstance(r, dict) and r.get("name") != "Total"]

        service_rows.sort(key=lambda x: x.get("totalCost", 0), reverse=True)

        if len(service_rows) > max_items:
            other_cost = sum(r.get("totalCost", 0) for r in service_rows[max_items:])
            service_rows = service_rows[:max_items]
            if other_cost > 0:
                service_rows.append({"name": "Other", "totalCost": other_cost})

        result = total_rows + service_rows
        for row in result:
            if isinstance(row, dict):
                for key in strip_keys:
                    row.pop(key, None)
        return result

    if "breakdown" in data and isinstance(data["breakdown"], list):
        breakdown = data["breakdown"]
        if len(breakdown) <= max_items:
            return data
        sorted_breakdown = sorted(breakdown, key=lambda x: x.get("cost", 0), reverse=True)
        top_items = sorted_breakdown[:max_items]
        other_items = sorted_breakdown[max_items:]
        other_total = sum(item.get("cost", 0) for item in other_items)
        if other_total > 0:
            top_items.append({"name": f"Other ({len(other_items)} items)", "cost": other_total})
        data["breakdown"] = top_items
        data["_summarized"] = True
        data["_total_items"] = len(breakdown)

    return data


async def query_costs_impl(args: dict) -> dict:
    """Implementation of query_costs tool"""
    from ..server import _auto_granularity, finout_client

    assert finout_client is not None

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")
    x_axis_group_by = args.get("x_axis_group_by") or _auto_granularity(time_period)
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

    # Validate filter metadata (key/type/path) and values
    validation_warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        validation_warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        validation_warnings.extend(value_warnings)

    # Validate group_by structure and metadata
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
        group_by, gb_warnings = await _validate_filter_metadata(finout_client, group_by)
        validation_warnings.extend(gb_warnings)

    # Cross-provider exclusion coverage warning
    if filters:
        exclusion_operators = {"not", "notOneOf", "isNot"}
        exclusion_cost_centers = {
            f.get("costCenter", "").lower()
            for f in filters
            if f.get("operator") in exclusion_operators
        }
        if exclusion_cost_centers:
            all_cost_centers = {f.get("costCenter", "").lower() for f in filters}
            unprotected = all_cost_centers - exclusion_cost_centers
            if unprotected:
                validation_warnings.append(
                    f"Exclusion filters only target [{', '.join(sorted(exclusion_cost_centers))}]. "
                    f"Other cost centers in this query ([{', '.join(sorted(unprotected))}]) "
                    f"have no equivalent exclusions. "
                    f"Use search_filters to find equivalent filters for those providers."
                )

    # Query costs using internal API
    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        x_axis_group_by=x_axis_group_by,
        usage_configuration=usage_configuration,
    )

    # Summarize to avoid context overload
    summarized = summarize_cost_data(data, max_items=50)

    # Format response
    result: dict[str, Any] = {
        "time_period": time_period,
        "filters": filters,
        "group_by": group_by,
        "data": summarized,
        "query_timestamp": datetime.now().isoformat(),
        "_presentation_hint": (
            "Give 2-4 sentences: total cost, biggest driver, notable trend. "
            "No table needed. Call render_chart to visualize key data points."
        ),
    }
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings
    return result


async def compare_costs_impl(args: dict) -> dict:
    """Implementation of compare_costs tool"""
    from ..server import finout_client

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

    # Validate filter metadata (key/type/path) and values
    validation_warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        validation_warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        validation_warnings.extend(value_warnings)

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
    def extract_total(data: Any) -> float:
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
            return float(data.get("totalCost") or data.get("total") or 0)
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

    result: dict[str, Any] = {
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
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result
