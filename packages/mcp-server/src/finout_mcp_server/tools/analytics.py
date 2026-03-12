"""Analytical tools built on top of cost queries."""

import statistics
from typing import Any

from .cost import _find_cost_column, _find_dimension_column, format_currency


async def get_top_movers_impl(args: dict) -> dict:
    """Identify dimensions with the largest cost changes between two periods."""
    from ..server import finout_client

    assert finout_client is not None

    time_period = args.get("time_period", "last_30_days")
    comparison_period = args.get("comparison_period")
    filters = args.get("filters", [])
    group_by = args.get("group_by")
    limit = args.get("limit", 10)

    if not group_by:
        raise ValueError(
            "group_by is required — specify the dimension to rank by "
            "(e.g., service, region, team). Use search_filters to find the right metadata."
        )

    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": "Set FINOUT_API_URL environment variable.",
        }

    # Default comparison: infer previous equivalent period
    if not comparison_period:
        comparison_period = _infer_previous_period(time_period)

    # Auto-normalize when comparing a partial period (this_month, this_week, etc.) to a full
    # one — otherwise the absolute totals are misleading (12 days vs 28 days looks like a drop).
    normalization_note: str | None = None
    if _is_partial_period(time_period):
        elapsed = _elapsed_days_in_period(time_period)
        constrained = _constrain_comparison_period(comparison_period, elapsed)
        if constrained:
            normalization_note = (
                f"Comparison auto-normalized: {comparison_period} constrained to its first "
                f"{elapsed} day(s) ({constrained}) for a fair apples-to-apples comparison "
                f"with the partial {time_period}. Raw totals would be misleading."
            )
            comparison_period = constrained

    from ..validation import _validate_filter_metadata, _validate_filter_values

    validation_warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        validation_warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        validation_warnings.extend(value_warnings)

    if group_by:
        group_by, gb_warnings = await _validate_filter_metadata(finout_client, group_by)
        validation_warnings.extend(gb_warnings)

    # Query both periods grouped by the dimension
    current_data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
    )

    comparison_data = await finout_client.query_costs_with_filters(
        time_period=comparison_period,
        filters=filters if filters else None,
        group_by=group_by,
    )

    # Build lookup dicts by dimension value
    cost_col = _find_cost_column(current_data[0]) if current_data else None
    dim_col = _find_dimension_column(current_data[0]) if current_data else None

    if not cost_col or not dim_col:
        # Fallback: try comparison data
        if comparison_data:
            cost_col = cost_col or _find_cost_column(comparison_data[0])
            dim_col = dim_col or _find_dimension_column(comparison_data[0])

    if not cost_col:
        return {
            "error": "No cost column found in response",
            "current_rows": len(current_data),
            "comparison_rows": len(comparison_data),
        }

    current_map: dict[str, float] = {}
    for row in current_data:
        name = row.get(dim_col, "Unknown") if dim_col else "Total"
        current_map[name] = row.get(cost_col, 0)

    comparison_map: dict[str, float] = {}
    for row in comparison_data:
        name = row.get(dim_col, "Unknown") if dim_col else "Total"
        comparison_map[name] = row.get(cost_col, 0)

    # Compute deltas for all dimension values (union of both periods)
    all_names = set(current_map.keys()) | set(comparison_map.keys())
    movers: list[dict[str, Any]] = []

    for name in all_names:
        curr = current_map.get(name, 0)
        prev = comparison_map.get(name, 0)
        delta = curr - prev
        pct = ((delta / prev) * 100) if prev != 0 else (100.0 if curr > 0 else 0.0)

        mover: dict[str, Any] = {
            "name": name,
            "current_cost": round(curr, 2),
            "previous_cost": round(prev, 2),
            "delta": round(delta, 2),
            "percent_change": round(pct, 1),
        }

        if name not in comparison_map:
            mover["status"] = "new"
        elif name not in current_map:
            mover["status"] = "removed"
        elif delta > 0:
            mover["status"] = "increased"
        elif delta < 0:
            mover["status"] = "decreased"
        else:
            mover["status"] = "unchanged"

        movers.append(mover)

    # Sort by absolute delta (biggest movers first)
    movers.sort(key=lambda m: abs(m["delta"]), reverse=True)

    # Split into increases and decreases
    top_increases = [m for m in movers if m["delta"] > 0][:limit]
    top_decreases = [m for m in movers if m["delta"] < 0][:limit]
    new_items = [m for m in movers if m.get("status") == "new"]
    removed_items = [m for m in movers if m.get("status") == "removed"]

    current_total = sum(current_map.values())
    previous_total = sum(comparison_map.values())
    total_delta = current_total - previous_total
    total_pct = ((total_delta / previous_total) * 100) if previous_total != 0 else 0

    result: dict[str, Any] = {
        "current_period": time_period,
        "comparison_period": comparison_period,
        "total_current": format_currency(current_total),
        "total_previous": format_currency(previous_total),
        "total_delta": format_currency(total_delta),
        "total_percent_change": round(total_pct, 1),
        "top_increases": top_increases,
        "top_decreases": top_decreases,
        "_presentation_hint": (
            "Lead with the overall trend, then highlight the top 3 movers by absolute delta. "
            "Mention any new or removed items. Use render_chart with a bar chart showing "
            "the top movers with positive (red) and negative (green) deltas. "
            "If _normalization_note is present, mention it upfront so the user understands "
            "the comparison was adjusted for a fair apples-to-apples result."
        ),
    }

    if normalization_note:
        result["_normalization_note"] = normalization_note
    if new_items:
        result["new_items"] = new_items[:5]
    if removed_items:
        result["removed_items"] = removed_items[:5]
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result


async def get_unit_economics_impl(args: dict) -> dict:
    """Compute cost-per-unit by combining cost with count_distinct."""
    from ..server import finout_client

    assert finout_client is not None

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")
    count_dimension = args.get("count_dimension")
    cost_type = args.get("cost_type", "netAmortizedCost")

    if not count_dimension:
        raise ValueError(
            "count_dimension is required — specify the dimension to count unique values of "
            "(e.g., resource ID, instance ID). Use search_filters to find the right metadata."
        )

    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": "Set FINOUT_API_URL environment variable.",
        }

    from ..validation import _validate_filter_metadata, _validate_filter_values

    validation_warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        validation_warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        validation_warnings.extend(value_warnings)

    if group_by:
        group_by, gb_warnings = await _validate_filter_metadata(finout_client, group_by)
        validation_warnings.extend(gb_warnings)

    # Single query: cost + count_distinct in one call
    from ..finout_client import CostType

    ct = CostType(cost_type) if cost_type in [e.value for e in CostType] else CostType.NET_AMORTIZED

    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        cost_type=ct,
        count_distinct=count_dimension,
    )

    if not data:
        return {
            "time_period": time_period,
            "data": [],
            "message": "No data returned for the given filters and time period.",
        }

    # Find the cost column and count-distinct column
    cost_col = _find_cost_column(data[0])
    count_col = _find_count_distinct_column(data[0])
    dim_col = _find_dimension_column(data[0])

    if not cost_col:
        return {"error": "No cost column found in response", "raw_columns": list(data[0].keys())}

    if not count_col:
        return {
            "error": "No count-distinct column found in response",
            "hint": "Verify the count_dimension metadata is correct (costCenter, key, path, type).",
            "raw_columns": list(data[0].keys()),
        }

    # Compute cost-per-unit for each row
    results: list[dict[str, Any]] = []
    for row in data:
        cost = _to_number(row.get(cost_col, 0))
        count = _to_number(row.get(count_col, 0))
        cost_per_unit = (cost / count) if count > 0 else 0

        entry: dict[str, Any] = {
            "total_cost": round(cost, 2),
            "unique_count": int(count),
            "cost_per_unit": round(cost_per_unit, 2),
        }

        if dim_col:
            entry["name"] = row.get(dim_col, "Unknown")

        results.append(entry)

    # Sort by total cost descending
    results.sort(key=lambda r: r["total_cost"], reverse=True)

    total_cost = sum(r["total_cost"] for r in results)
    total_count = sum(r["unique_count"] for r in results)
    overall_cpu = (total_cost / total_count) if total_count > 0 else 0

    result: dict[str, Any] = {
        "time_period": time_period,
        "count_dimension": count_dimension.get("key", "unknown"),
        "summary": {
            "total_cost": format_currency(total_cost),
            "total_unique_count": total_count,
            "overall_cost_per_unit": format_currency(overall_cpu),
        },
        "data": results[:50],
        "_presentation_hint": (
            "Lead with the overall cost-per-unit, then highlight outliers — "
            "which groups have the highest and lowest cost per unit. "
            "Use render_chart with a bar chart showing cost_per_unit by group."
        ),
    }
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result


def _find_count_distinct_column(row: dict[str, Any]) -> str | None:
    """Find the count-distinct column in a data-explorer row."""
    for key in row:
        if key.startswith("Count Distinct(") or key.startswith("Count("):
            return key
    return None


def _to_number(val: Any) -> float:
    """Coerce a value to float. The API sometimes returns numeric values as strings."""
    if isinstance(val, int | float):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return 0.0
    return 0.0


def _is_partial_period(time_period: str) -> bool:
    """Return True if this period ends today (i.e., it is a partial, in-progress period)."""
    return time_period in ("today", "this_week", "this_month", "this_quarter", "this_year")


def _elapsed_days_in_period(time_period: str) -> int:
    """Number of days elapsed so far in the current partial period, including today."""
    from datetime import date

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
    from datetime import date, timedelta

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


_EMPTY_TAG_SENTINELS = {"", "n/a", "none", "null", "unknown", "untagged", "(empty)", "(none)"}


def _is_empty_tag_value(val: Any) -> bool:
    """Return True if a tag value represents 'no tag' — empty, null, or a placeholder."""
    if val is None:
        return True
    if isinstance(val, str) and val.strip().lower() in _EMPTY_TAG_SENTINELS:
        return True
    return False


def _find_tag_value_column(row: dict[str, Any], exclude_col: str | None) -> str | None:
    """Find the tag-value column, excluding the outer group-by dimension column."""
    from .cost import _DATE_COLUMNS, _is_metric_column

    for key, val in row.items():
        if key == exclude_col:
            continue
        if key in _DATE_COLUMNS:
            continue
        if isinstance(val, str) and not _is_metric_column(key):
            return key
    return None


def _infer_previous_period(time_period: str) -> str:
    """Infer the previous equivalent period for comparison.

    For 'last_N_days', computes the N days immediately before that window.
    For named periods, uses natural previous equivalents.
    """
    import re
    from datetime import date, timedelta

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
        # Current window: (today - n) to (today - 1)
        # Previous window: (today - 2n) to (today - n - 1)
        prev_end = today - timedelta(days=n + 1)
        prev_start = today - timedelta(days=2 * n)
        return f"{prev_start.isoformat()} to {prev_end.isoformat()}"

    # last_N_weeks / last_N_months — use double lookback as approximation
    flex_match = re.match(r"^last_(\d+)_(weeks?|months?)$", time_period)
    if flex_match:
        n = int(flex_match.group(1))
        unit = flex_match.group(2).rstrip("s")
        if unit == "week":
            days = n * 7
        else:
            days = n * 30
        today = date.today()
        prev_end = today - timedelta(days=days + 1)
        prev_start = today - timedelta(days=2 * days)
        return f"{prev_start.isoformat()} to {prev_end.isoformat()}"

    # last_14_days / last_60_days will be caught by the flex_match above since
    # they match last_N_days pattern, so for the named ones we compute properly:
    if time_period == "last_7_days":
        today = date.today()
        prev_end = today - timedelta(days=8)
        prev_start = today - timedelta(days=14)
        return f"{prev_start.isoformat()} to {prev_end.isoformat()}"
    if time_period == "last_30_days":
        today = date.today()
        prev_end = today - timedelta(days=31)
        prev_start = today - timedelta(days=60)
        return f"{prev_start.isoformat()} to {prev_end.isoformat()}"
    if time_period == "last_quarter":
        today = date.today()
        # Compute start of current quarter (month 1, 4, 7, or 10)
        current_q_month = ((today.month - 1) // 3) * 3 + 1
        # last_quarter started 3 months before current quarter
        last_q_month = current_q_month - 3
        last_q_year = today.year
        if last_q_month <= 0:
            last_q_month += 12
            last_q_year -= 1
        # two quarters ago (the period before last_quarter):
        prev_q_month = last_q_month - 3
        prev_q_year = last_q_year
        if prev_q_month <= 0:
            prev_q_month += 12
            prev_q_year -= 1
        prev_start = date(prev_q_year, prev_q_month, 1)
        prev_end = date(last_q_year, last_q_month, 1) - timedelta(days=1)
        return f"{prev_start.isoformat()} to {prev_end.isoformat()}"

    return "last_30_days"


async def get_cost_patterns_impl(args: dict) -> dict:
    """Analyze hourly cost patterns — peak hours, weekday/weekend splits."""
    from ..server import finout_client

    assert finout_client is not None

    time_period = args.get("time_period", "last_7_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")

    if not finout_client.internal_api_url:
        return {"error": "Internal API not configured"}

    from ..validation import _validate_filter_metadata, _validate_filter_values

    validation_warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        validation_warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        validation_warnings.extend(value_warnings)
    if group_by:
        group_by, gb_warnings = await _validate_filter_metadata(finout_client, group_by)
        validation_warnings.extend(gb_warnings)

    # Try hourly granularity first; many accounts only have daily billing data
    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        x_axis_group_by="hourly",
    )

    granularity = "hourly"
    if not data:
        # Fall back to daily — still allows weekday/weekend analysis
        data = await finout_client.query_costs_with_filters(
            time_period=time_period,
            filters=filters if filters else None,
            group_by=group_by,
            x_axis_group_by="daily",
        )
        granularity = "daily"

    if not data:
        return {"time_period": time_period, "message": "No cost data returned for this period."}

    cost_col = _find_cost_column(data[0])
    if not cost_col:
        return {"error": "No cost column found", "raw_columns": list(data[0].keys())}

    from datetime import datetime

    timed_costs: list[dict[str, Any]] = []
    for row in data:
        cost = row.get(cost_col, 0)
        day_val = row.get("Day") or row.get("Hour") or row.get("day")
        ts = None
        if isinstance(day_val, str):
            for fmt in (
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%d",
            ):
                try:
                    ts = datetime.strptime(day_val, fmt)
                    break
                except ValueError:
                    continue
        elif isinstance(day_val, int | float):
            try:
                ts = datetime.fromtimestamp(day_val / 1000 if day_val > 1e10 else day_val)
            except (OSError, ValueError):
                pass

        timed_costs.append({"cost": cost, "timestamp": ts})

    costs = [h["cost"] for h in timed_costs if h["cost"] > 0]
    if not costs:
        return {"time_period": time_period, "message": "No non-zero cost data found."}

    total = sum(costs)
    avg = statistics.mean(costs)
    std_dev = statistics.stdev(costs) if len(costs) > 1 else 0
    peak_cost = max(costs)
    trough_cost = min(costs)

    # Weekday/weekend split (works for both hourly and daily data)
    weekday_costs: list[float] = []
    weekend_costs: list[float] = []
    weekday_by_day: dict[int, list[float]] = {}  # 0=Mon … 6=Sun

    for h in timed_costs:
        if h["timestamp"] and h["cost"] > 0:
            wd = h["timestamp"].weekday()
            if wd < 5:
                weekday_costs.append(h["cost"])
            else:
                weekend_costs.append(h["cost"])
            weekday_by_day.setdefault(wd, []).append(h["cost"])

    # Hour-of-day analysis (only meaningful for hourly data)
    hour_buckets: dict[int, list[float]] = {}
    if granularity == "hourly":
        for h in timed_costs:
            if h["timestamp"] and h["cost"] > 0:
                hour_buckets.setdefault(h["timestamp"].hour, []).append(h["cost"])

    hour_averages = {
        hour: round(statistics.mean(vals), 2) for hour, vals in sorted(hour_buckets.items())
    }
    peak_hour = max(hour_averages, key=lambda h: hour_averages[h]) if hour_averages else None
    off_peak_hour = min(hour_averages, key=lambda h: hour_averages[h]) if hour_averages else None

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_averages = {
        day_names[wd]: round(statistics.mean(vals), 2)
        for wd, vals in sorted(weekday_by_day.items())
    }

    unit = "hourly" if granularity == "hourly" else "daily"
    result: dict[str, Any] = {
        "time_period": time_period,
        "granularity": granularity,
        f"total_{unit}_periods_analyzed": len(costs),
        "total_cost": format_currency(total),
        f"{unit}_average": format_currency(avg),
        f"{unit}_std_dev": format_currency(std_dev),
        f"peak_{unit}_cost": format_currency(peak_cost),
        f"trough_{unit}_cost": format_currency(trough_cost),
        "_presentation_hint": (
            f"Granularity is {granularity}. "
            "Lead with weekday vs weekend comparison if available. "
            "Show day_of_week_average and highlight the most/least expensive day. "
            "If hourly data is available, also show peak/off-peak hours. "
            "Use render_chart with a bar chart of day_of_week_average."
        ),
    }

    if day_averages:
        result["day_of_week_average"] = day_averages

    if weekday_costs and weekend_costs:
        wd_avg = statistics.mean(weekday_costs)
        we_avg = statistics.mean(weekend_costs)
        result["weekday_vs_weekend"] = {
            f"weekday_{unit}_avg": format_currency(wd_avg),
            f"weekend_{unit}_avg": format_currency(we_avg),
            "weekend_to_weekday_ratio": round(we_avg / wd_avg, 2) if wd_avg > 0 else None,
            "weekend_savings_opportunity": format_currency(max(0.0, wd_avg - we_avg)),
        }

    if hour_averages and peak_hour is not None and off_peak_hour is not None:
        result["hour_of_day_average"] = hour_averages
        result["peak_hour"] = f"{peak_hour}:00"
        result["off_peak_hour"] = f"{off_peak_hour}:00"
        result["peak_to_trough_ratio"] = (
            round(hour_averages[peak_hour] / hour_averages[off_peak_hour], 2)
            if hour_averages.get(off_peak_hour, 0) > 0
            else None
        )

    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result


async def get_savings_coverage_impl(args: dict) -> dict:
    """Analyze savings plan and reservation coverage."""
    from ..server import finout_client

    assert finout_client is not None

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")

    if not finout_client.internal_api_url:
        return {"error": "Internal API not configured"}

    from ..validation import _validate_filter_metadata, _validate_filter_values

    validation_warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        validation_warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        validation_warnings.extend(value_warnings)
    if group_by:
        group_by, gb_warnings = await _validate_filter_metadata(finout_client, group_by)
        validation_warnings.extend(gb_warnings)

    # Query with both SP and RI billing metrics
    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        billing_metrics=["savingsPlanEffectiveCost", "reservationEffectiveCost"],
    )

    if not data:
        return {"time_period": time_period, "data": [], "message": "No data returned."}

    cost_col = _find_cost_column(data[0])
    dim_col = _find_dimension_column(data[0])

    # Find billing metric columns
    sp_col = None
    ri_col = None
    for key in data[0]:
        lower = key.lower()
        if "savingsplan" in lower or "savings_plan" in lower or "savings plan" in lower:
            sp_col = key
        if "reservation" in lower:
            ri_col = key

    if not cost_col:
        return {"error": "No cost column found", "raw_columns": list(data[0].keys())}

    rows: list[dict[str, Any]] = []
    total_cost = 0.0
    total_sp = 0.0
    total_ri = 0.0

    for row in data:
        cost = row.get(cost_col, 0)
        sp_cost = row.get(sp_col, 0) if sp_col else 0
        ri_cost = row.get(ri_col, 0) if ri_col else 0
        covered = sp_cost + ri_cost
        coverage_pct = (covered / cost * 100) if cost > 0 else 0
        on_demand = cost - covered

        total_cost += cost
        total_sp += sp_cost
        total_ri += ri_cost

        entry: dict[str, Any] = {
            "total_cost": round(cost, 2),
            "savings_plan_cost": round(sp_cost, 2),
            "reservation_cost": round(ri_cost, 2),
            "on_demand_cost": round(on_demand, 2),
            "coverage_percent": round(coverage_pct, 1),
        }
        if dim_col:
            entry["name"] = row.get(dim_col, "Unknown")
        rows.append(entry)

    rows.sort(key=lambda r: r["total_cost"], reverse=True)

    total_covered = total_sp + total_ri
    overall_coverage = (total_covered / total_cost * 100) if total_cost > 0 else 0

    result: dict[str, Any] = {
        "time_period": time_period,
        "summary": {
            "total_cost": format_currency(total_cost),
            "savings_plan_cost": format_currency(total_sp),
            "reservation_cost": format_currency(total_ri),
            "on_demand_cost": format_currency(total_cost - total_covered),
            "overall_coverage_percent": round(overall_coverage, 1),
        },
        "data": rows[:50],
        "_presentation_hint": (
            "Lead with overall coverage %. Highlight services with low coverage "
            "(high on-demand cost) as optimization opportunities. "
            "Use render_chart with a stacked bar showing SP/RI/on-demand per group."
        ),
    }
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result


async def get_tag_coverage_impl(args: dict) -> dict:
    """Analyze what percentage of spend is tagged by a given dimension."""
    from ..server import finout_client

    assert finout_client is not None

    time_period = args.get("time_period", "last_30_days")
    tag_dimension = args.get("tag_dimension")
    filters = args.get("filters", [])
    group_by = args.get("group_by")

    if not tag_dimension:
        raise ValueError(
            "tag_dimension is required — specify the tag/dimension to measure coverage for "
            "(e.g., team tag, environment tag). Use search_filters to find the right metadata."
        )

    if not finout_client.internal_api_url:
        return {"error": "Internal API not configured"}

    from ..validation import _validate_filter_metadata, _validate_filter_values

    validation_warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        validation_warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        validation_warnings.extend(value_warnings)
    if group_by:
        group_by, gb_warnings = await _validate_filter_metadata(finout_client, group_by)
        validation_warnings.extend(gb_warnings)

    # Query 1: total cost (optionally grouped)
    total_data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
    )

    # Query 2: cost grouped by the tag dimension
    # Any row returned = that spend has a tag value. Sum of all rows = tagged spend.
    tag_group = [tag_dimension]
    if group_by:
        tag_group = group_by + [tag_dimension]

    tagged_data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=tag_group,
    )

    if not total_data:
        return {"time_period": time_period, "data": [], "message": "No data returned."}

    cost_col = _find_cost_column(total_data[0])
    if not cost_col:
        return {"error": "No cost column found"}

    # Compute totals
    if group_by:
        # Per-group analysis
        dim_col = _find_dimension_column(total_data[0])
        total_by_group: dict[str, float] = {}
        for row in total_data:
            name = row.get(dim_col, "Unknown") if dim_col else "Total"
            total_by_group[name] = row.get(cost_col, 0)

        # tagged_data has both group_by + tag dimension columns.
        # The tag value column is the string column other than the group_by dimension.
        tag_val_col = _find_tag_value_column(tagged_data[0], dim_col) if tagged_data else None

        # Sum tagged cost per group — skip rows where the tag value is empty/null.
        tagged_by_group: dict[str, float] = {}
        for row in tagged_data:
            if _is_empty_tag_value(row.get(tag_val_col) if tag_val_col else None):
                continue
            name = row.get(dim_col, "Unknown") if dim_col else "Total"
            tagged_by_group[name] = tagged_by_group.get(name, 0) + row.get(cost_col, 0)

        rows: list[dict[str, Any]] = []
        for name, total in sorted(total_by_group.items(), key=lambda x: x[1], reverse=True):
            tagged = tagged_by_group.get(name, 0)
            untagged = total - tagged
            coverage = (tagged / total * 100) if total > 0 else 0
            rows.append(
                {
                    "name": name,
                    "total_cost": round(total, 2),
                    "tagged_cost": round(tagged, 2),
                    "untagged_cost": round(untagged, 2),
                    "coverage_percent": round(coverage, 1),
                }
            )
    else:
        # Overall analysis.
        # The only group-by dimension is the tag itself — find it in tagged_data rows
        # and skip rows where the tag value is empty/null (= untagged spend).
        tag_val_col_single = _find_dimension_column(tagged_data[0]) if tagged_data else None
        total_cost = sum(row.get(cost_col, 0) for row in total_data)
        tagged_cost = sum(
            row.get(cost_col, 0)
            for row in tagged_data
            if not _is_empty_tag_value(row.get(tag_val_col_single) if tag_val_col_single else None)
        )
        untagged_cost = total_cost - tagged_cost
        coverage = (tagged_cost / total_cost * 100) if total_cost > 0 else 0
        rows = [
            {
                "total_cost": round(total_cost, 2),
                "tagged_cost": round(tagged_cost, 2),
                "untagged_cost": round(untagged_cost, 2),
                "coverage_percent": round(coverage, 1),
            }
        ]

    overall_total = sum(r["total_cost"] for r in rows)
    overall_tagged = sum(r["tagged_cost"] for r in rows)
    overall_coverage = (overall_tagged / overall_total * 100) if overall_total > 0 else 0

    result: dict[str, Any] = {
        "time_period": time_period,
        "tag_dimension": tag_dimension.get("key", "unknown"),
        "summary": {
            "total_cost": format_currency(overall_total),
            "tagged_cost": format_currency(overall_tagged),
            "untagged_cost": format_currency(overall_total - overall_tagged),
            "overall_coverage_percent": round(overall_coverage, 1),
        },
        "data": rows[:50],
        "_presentation_hint": (
            "Lead with overall coverage %. Highlight groups with lowest coverage — "
            "these are governance gaps. Use render_chart with a stacked bar showing "
            "tagged vs untagged cost per group."
        ),
    }
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result


async def get_budget_status_impl(args: dict) -> dict:
    """Compare actual spend against financial plan budgets."""
    from ..server import finout_client

    assert finout_client is not None

    plan_name = args.get("plan_name")
    period = args.get("period")
    time_period = args.get("time_period")

    if not finout_client.internal_api_url:
        return {"error": "Internal API not configured"}

    from datetime import datetime

    if not period:
        now = datetime.now()
        period = f"{now.year}-{now.month}"

    # Fetch financial plans
    plans = await finout_client.get_financial_plans(name=plan_name, period=period)
    if not plans:
        return {
            "period": period,
            "message": "No financial plans found"
            + (f' matching "{plan_name}"' if plan_name else "")
            + ".",
        }

    # Derive time_period for cost query from the budget period
    if not time_period:
        # period is "YYYY-M", convert to this_month or last_month equivalent
        parts = period.split("-")
        year, month = int(parts[0]), int(parts[1])
        now = datetime.now()
        if year == now.year and month == now.month:
            time_period = "this_month"
        else:
            # Use absolute range for the budget month
            import calendar

            _, last_day = calendar.monthrange(year, month)
            time_period = f"{year}-{month:02d}-01 to {year}-{month:02d}-{last_day:02d}"

    # Get actual spend per cost_type (plans may differ in cost_type).
    # Group plans by cost_type and run one query per unique cost_type.
    from collections import defaultdict

    from ..finout_client import CostType

    plans_by_cost_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for plan in plans:
        ct = plan.get("cost_type") or "netAmortizedCost"
        plans_by_cost_type[ct].append(plan)

    actual_by_cost_type: dict[str, float] = {}
    for ct_str in plans_by_cost_type:
        ct = CostType(ct_str) if ct_str in [e.value for e in CostType] else CostType.NET_AMORTIZED
        actual_data = await finout_client.query_costs_with_filters(
            time_period=time_period,
            cost_type=ct,
        )
        actual_by_cost_type[ct_str] = sum(
            row.get(col, 0) for row in actual_data for col in [_find_cost_column(row)] if col
        )

    results: list[dict[str, Any]] = []
    for plan in plans:
        ct = plan.get("cost_type") or "netAmortizedCost"
        actual_total = actual_by_cost_type.get(ct, 0)
        budget = plan.get("total_budget", 0)
        forecast = plan.get("total_forecast")
        utilization = (actual_total / budget * 100) if budget > 0 else 0
        remaining = budget - actual_total

        # Estimate days elapsed / total days in period
        now = datetime.now()
        parts = period.split("-")
        year, month = int(parts[0]), int(parts[1])
        import calendar

        _, total_days = calendar.monthrange(year, month)
        if year == now.year and month == now.month:
            days_elapsed = now.day
        elif (year, month) < (now.year, now.month):
            days_elapsed = total_days  # month is complete
        else:
            days_elapsed = 0

        # Burn rate: cost per day → projected month-end
        daily_burn = (actual_total / days_elapsed) if days_elapsed > 0 else 0
        projected_total = daily_burn * total_days

        projected_vs_budget = (projected_total / budget * 100) if budget > 0 else 0

        entry: dict[str, Any] = {
            "plan_name": plan["name"],
            "period": period,
            "budget": format_currency(budget),
            "actual_spend": format_currency(actual_total),
            "remaining": format_currency(remaining),
            "utilization_percent": round(utilization, 1),
            "days_elapsed": days_elapsed,
            "total_days": total_days,
            "daily_burn_rate": format_currency(daily_burn),
            "projected_month_end": format_currency(projected_total),
            "projected_vs_budget_percent": round(projected_vs_budget, 1),
            "status": (
                "on_track"
                if projected_vs_budget <= 100
                else "at_risk"
                if projected_vs_budget <= 110
                else "over_budget"
            ),
        }
        if forecast is not None:
            entry["forecast"] = format_currency(forecast)
        results.append(entry)

    result: dict[str, Any] = {
        "period": period,
        "plans": results,
        "_presentation_hint": (
            "Lead with the status (on_track / at_risk / over_budget). "
            "Show utilization %, remaining budget, and projected month-end. "
            "Highlight plans at risk or over budget."
        ),
    }
    return result


async def get_cost_statistics_impl(args: dict) -> dict:
    """Compute daily cost statistics — mean, median, peak, trough, volatility."""
    from ..server import finout_client

    assert finout_client is not None

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")

    if not finout_client.internal_api_url:
        return {"error": "Internal API not configured"}

    from ..validation import _validate_filter_metadata, _validate_filter_values

    validation_warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        validation_warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        validation_warnings.extend(value_warnings)
    if group_by:
        group_by, gb_warnings = await _validate_filter_metadata(finout_client, group_by)
        validation_warnings.extend(gb_warnings)

    # Query with daily granularity to get per-day costs
    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        x_axis_group_by="daily",
    )

    if not data:
        return {"time_period": time_period, "data": [], "message": "No data returned."}

    cost_col = _find_cost_column(data[0])
    if not cost_col:
        return {"error": "No cost column found", "raw_columns": list(data[0].keys())}

    dim_col = _find_dimension_column(data[0])

    if group_by and dim_col:
        # Per-group statistics: aggregate daily costs by group
        group_costs: dict[str, list[float]] = {}
        for row in data:
            name = row.get(dim_col, "Unknown")
            cost = row.get(cost_col, 0)
            if cost > 0:
                group_costs.setdefault(name, []).append(cost)

        rows: list[dict[str, Any]] = []
        for name, costs in sorted(group_costs.items(), key=lambda x: sum(x[1]), reverse=True):
            rows.append(_compute_stats(name, costs))
        result_data = rows[:50]
    else:
        # Overall daily statistics
        costs = [row.get(cost_col, 0) for row in data if row.get(cost_col, 0) > 0]
        if not costs:
            return {"time_period": time_period, "message": "No non-zero cost data."}
        result_data = [_compute_stats("overall", costs)]

    # Aggregate to daily totals before finding peak/trough.
    # When grouped, multiple rows share the same date; summing them gives the true daily total.
    daily_totals: dict[str, float] = {}
    for i, row in enumerate(data):
        date_val = str(row.get("Day") or row.get("day") or f"_row_{i}")
        daily_totals[date_val] = daily_totals.get(date_val, 0) + row.get(cost_col, 0)

    nonzero_dates = [d for d, v in daily_totals.items() if v > 0]
    peak_date: str | None = None
    trough_date: str | None = None
    peak_cost_val: float = 0.0
    trough_cost_val: float = 0.0
    if nonzero_dates:
        peak_date = max(nonzero_dates, key=lambda d: daily_totals[d])
        trough_date = min(nonzero_dates, key=lambda d: daily_totals[d])
        peak_cost_val = daily_totals[peak_date]
        trough_cost_val = daily_totals[trough_date]

    result: dict[str, Any] = {
        "time_period": time_period,
        "days_analyzed": len(daily_totals),
        "statistics": result_data,
        "peak_day": {"date": peak_date, "cost": format_currency(peak_cost_val)},
        "trough_day": {"date": trough_date, "cost": format_currency(trough_cost_val)},
        "_presentation_hint": (
            "Lead with the daily average and highlight volatility (std dev / mean). "
            "Call out the peak and trough days. If grouped, compare variability across groups. "
            "Use render_chart with a line chart showing daily costs over time."
        ),
    }
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result


def _compute_stats(name: str, costs: list[float]) -> dict[str, Any]:
    """Compute summary statistics for a list of cost values."""
    total = sum(costs)
    mean = statistics.mean(costs)
    median = statistics.median(costs)
    std_dev = statistics.stdev(costs) if len(costs) > 1 else 0
    cv = (std_dev / mean * 100) if mean > 0 else 0  # coefficient of variation

    return {
        "name": name,
        "total": round(total, 2),
        "daily_mean": round(mean, 2),
        "daily_median": round(median, 2),
        "daily_min": round(min(costs), 2),
        "daily_max": round(max(costs), 2),
        "std_dev": round(std_dev, 2),
        "coefficient_of_variation": round(cv, 1),
        "days": len(costs),
    }
