"""Cost querying and comparison tools."""

import re
from datetime import date, datetime, timedelta
from typing import Any

from ..validation import _validate_filter_metadata, _validate_filter_values


def format_currency(amount: float) -> str:
    """Format currency with thousands separator"""
    return f"${amount:,.2f}"


def _find_cost_column(row: dict[str, Any]) -> str | None:
    """Find the primary cost measurement column in a data-explorer row."""
    for key in row:
        lower = key.lower()
        if "cost" in lower and ("sum" in lower or "average" in lower):
            return key
    return None


def summarize_cost_data(data: list[dict[str, Any]], max_items: int = 25) -> list[dict[str, Any]]:
    """
    Reduce data-explorer rows to top items by cost.

    Keeps top max_items rows sorted by the cost column,
    collapsing the tail into a single "Other" row.
    """
    if not isinstance(data, list) or len(data) <= max_items:
        return data

    cost_col = _find_cost_column(data[0]) if data else None
    if not cost_col:
        return data[:max_items]

    sorted_data = sorted(data, key=lambda x: x.get(cost_col, 0), reverse=True)
    top = sorted_data[:max_items]
    tail = sorted_data[max_items:]

    if tail:
        other_cost = sum(r.get(cost_col, 0) for r in tail)
        if other_cost > 0:
            top.append({"_name": f"Other ({len(tail)} items)", cost_col: other_cost})

    return top


async def query_costs_impl(args: dict) -> dict:
    """Implementation of query_costs tool"""
    from ..finout_client import CostType
    from ..server import _auto_granularity, get_client

    finout_client = get_client()

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")
    x_axis_group_by = args.get("x_axis_group_by") or _auto_granularity(time_period)
    usage_configuration = args.get("usage_configuration")
    extra_measurements = args.get("extra_measurements")
    billing_metrics = args.get("billing_metrics")
    count_distinct = args.get("count_distinct")
    predefined_queries = args.get("predefined_queries")

    # Resolve cost type: explicit param → account default → NET_AMORTIZED
    raw_cost_type = args.get("cost_type")
    if raw_cost_type:
        cost_type = CostType(raw_cost_type)
    else:
        cost_type = finout_client.get_default_cost_type()

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

    # Query costs using data-explorer API
    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        x_axis_group_by=x_axis_group_by,
        cost_type=cost_type,
        usage_configuration=usage_configuration,
        extra_measurements=extra_measurements,
        billing_metrics=billing_metrics,
        count_distinct=count_distinct,
        predefined_queries=predefined_queries,
    )

    # Summarize to avoid context overload
    summarized = summarize_cost_data(data, max_items=50)

    # Format response
    result: dict[str, Any] = {
        "time_period": time_period,
        "cost_type": cost_type.value,
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


def _extract_total(data: list[dict[str, Any]]) -> float:
    """Extract total cost from data-explorer response rows."""
    if not data:
        return 0
    cost_col = _find_cost_column(data[0])
    if not cost_col:
        return 0
    return sum(row.get(cost_col, 0) for row in data)


def _is_metric_column(key: str) -> bool:
    """Check if a column name is a metric/measurement (not a dimension)."""
    # Patterns from data-explorer response: "Sum(...)", "Average(...)",
    # "Count Distinct(...)", "Resource Normalized Runtime", etc.
    return bool(
        key.startswith(("Sum(", "Average(", "Min(", "Max(", "Count Distinct(", "Count("))
        or key in {"Resource Normalized Runtime"}
    )


_DATE_COLUMNS = {"Day", "Week", "Month", "Quarter", "Half Year", "Year"}


def _find_dimension_column(row: dict[str, Any], exclude_col: str | None = None) -> str | None:
    """Find the dimension (group-by) column — the non-numeric, non-date column."""
    for key, val in row.items():
        if key == exclude_col:
            continue
        if key in _DATE_COLUMNS:
            continue
        if isinstance(val, str) and not _is_metric_column(key):
            return key
    return None


def _is_partial_period(time_period: str) -> bool:
    """Return True if this period ends today (i.e., it is a partial, in-progress period)."""
    return time_period in ("today", "this_week", "this_month", "this_quarter", "this_year")


def _elapsed_days_in_period(time_period: str) -> int:
    """Number of days elapsed so far in the current partial period, including today."""
    today = date.today()
    if time_period == "today":
        return 1
    if time_period == "this_week":
        return today.weekday() + 1  # Mon=0 → 1 elapsed day
    if time_period == "this_month":
        return today.day
    if time_period == "this_quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        return (today - today.replace(month=q_start_month, day=1)).days + 1
    if time_period == "this_year":
        return (today - today.replace(month=1, day=1)).days + 1
    return 0


def _constrain_comparison_period(comparison_period: str, elapsed_days: int) -> str | None:
    """
    Constrain a named comparison period to its first N days to match a partial current period.
    Returns an absolute date range string, or None if no adjustment applies.
    """
    today = date.today()

    if comparison_period == "last_month":
        start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        end = start + timedelta(days=elapsed_days - 1)
        return f"{start.isoformat()} to {end.isoformat()}"

    if comparison_period == "last_week":
        days_since_monday = today.weekday()
        last_week_monday = today - timedelta(days=days_since_monday + 7)
        end = last_week_monday + timedelta(days=elapsed_days - 1)
        return f"{last_week_monday.isoformat()} to {end.isoformat()}"

    if comparison_period == "last_quarter":
        current_q_month = ((today.month - 1) // 3) * 3 + 1
        last_q_month = current_q_month - 3
        last_q_year = today.year
        if last_q_month <= 0:
            last_q_month += 12
            last_q_year -= 1
        start = date(last_q_year, last_q_month, 1)
        end = start + timedelta(days=elapsed_days - 1)
        return f"{start.isoformat()} to {end.isoformat()}"

    # Absolute ranges or unknown named periods — no adjustment possible
    return None


def _infer_previous_period(time_period: str) -> str:
    """Infer the previous equivalent period for comparison.

    For 'last_N_days', computes the N days immediately before that window.
    For named periods, uses natural previous equivalents.
    """
    # Named period defaults
    simple_map = {
        "today": "yesterday",
        "this_week": "last_week",
        "last_week": "two_weeks_ago",
        "this_month": "last_month",
    }
    if time_period in simple_map:
        return simple_map[time_period]

    # Flexible relative: last_N_days → absolute range for the preceding N days
    flex_match = re.match(r"^last_(\d+)_(days?)$", time_period)
    if flex_match:
        n = int(flex_match.group(1))
        today = date.today()
        prev_end = today - timedelta(days=n + 1)
        prev_start = today - timedelta(days=2 * n)
        return f"{prev_start.isoformat()} to {prev_end.isoformat()}"

    # last_N_weeks / last_N_months — use double lookback as approximation
    flex_match = re.match(r"^last_(\d+)_(weeks?|months?)$", time_period)
    if flex_match:
        n = int(flex_match.group(1))
        unit = flex_match.group(2).rstrip("s")
        days = n * 7 if unit == "week" else n * 30
        today = date.today()
        prev_end = today - timedelta(days=days + 1)
        prev_start = today - timedelta(days=2 * days)
        return f"{prev_start.isoformat()} to {prev_end.isoformat()}"

    if time_period == "last_quarter":
        today = date.today()
        current_q_month = ((today.month - 1) // 3) * 3 + 1
        last_q_month = current_q_month - 3
        last_q_year = today.year
        if last_q_month <= 0:
            last_q_month += 12
            last_q_year -= 1
        prev_q_month = last_q_month - 3
        prev_q_year = last_q_year
        if prev_q_month <= 0:
            prev_q_month += 12
            prev_q_year -= 1
        prev_start = date(prev_q_year, prev_q_month, 1)
        prev_end = date(last_q_year, last_q_month, 1) - timedelta(days=1)
        return f"{prev_start.isoformat()} to {prev_end.isoformat()}"

    return "last_30_days"


async def compare_costs_impl(args: dict) -> dict:
    """Implementation of compare_costs tool"""
    from ..finout_client import CostType
    from ..server import get_client

    finout_client = get_client()

    current_period = args["current_period"]
    comparison_period = args["comparison_period"]
    filters = args.get("filters", [])
    group_by = args.get("group_by")
    extra_measurements = args.get("extra_measurements")
    billing_metrics = args.get("billing_metrics")

    # Resolve cost type: explicit param → account default → NET_AMORTIZED
    raw_cost_type = args.get("cost_type")
    if raw_cost_type:
        cost_type = CostType(raw_cost_type)
    else:
        cost_type = finout_client.get_default_cost_type()

    # Check if internal API is configured
    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": (
                "This tool requires the internal API. Set FINOUT_API_URL environment variable."
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
        cost_type=cost_type,
        extra_measurements=extra_measurements,
        billing_metrics=billing_metrics,
    )

    comparison_data = await finout_client.query_costs_with_filters(
        time_period=comparison_period,
        filters=filters if filters else None,
        group_by=group_by,
        cost_type=cost_type,
        extra_measurements=extra_measurements,
        billing_metrics=billing_metrics,
    )

    current_total = _extract_total(current_data)
    comparison_total = _extract_total(comparison_data)

    delta = current_total - comparison_total
    pct_change = ((delta / comparison_total) * 100) if comparison_total > 0 else 0

    # Format breakdown if grouped
    breakdown = None
    if group_by and current_data and comparison_data:
        cost_col = _find_cost_column(current_data[0])
        dim_col = _find_dimension_column(current_data[0])

        if cost_col and dim_col:
            breakdown = []
            comparison_dict = {
                row.get(dim_col, "Unknown"): row.get(cost_col, 0) for row in comparison_data
            }

            for curr_item in current_data:
                name = curr_item.get(dim_col, "Unknown")
                curr_cost = curr_item.get(cost_col, 0)
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

            breakdown.sort(key=lambda x: abs(x["percent_change"]), reverse=True)

    result: dict[str, Any] = {
        "current_period": current_period,
        "cost_type": cost_type.value,
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
        result["breakdown_by_group"] = breakdown[:10]

    result["_presentation_hint"] = (
        "Lead with the trend (up/down), then the delta, then the breakdown. "
        "Always include both percentage and absolute dollar change. "
        "If _partial_period_warning is present, surface it prominently — the comparison "
        "may be misleading due to unequal period lengths."
    )
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    # Warn when comparing a partial period to a full one — raw totals are misleading
    if _is_partial_period(current_period):
        elapsed = _elapsed_days_in_period(current_period)
        constrained = _constrain_comparison_period(comparison_period, elapsed)
        if constrained:
            result["_partial_period_warning"] = (
                f"⚠️ {current_period} covers only {elapsed} day(s) but {comparison_period} "
                f"may cover a full period — totals are not directly comparable. "
                f"For an apples-to-apples comparison use comparison_period='{constrained}' "
                f"(first {elapsed} day(s) of {comparison_period})."
            )

    return result
