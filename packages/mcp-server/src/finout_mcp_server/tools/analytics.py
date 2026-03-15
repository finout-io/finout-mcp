"""Analytical tools built on top of cost queries."""

import asyncio
import statistics
from datetime import datetime
from typing import Any

from ..finout_client import CostType
from ..validation import _validate_filter_metadata, _validate_filter_values
from .cost import (
    _constrain_comparison_period,
    _elapsed_days_in_period,
    _find_cost_column,
    _find_dimension_column,
    _infer_previous_period,
    _is_partial_period,
    format_currency,
)

_VALID_COST_TYPES = {e.value for e in CostType}


async def _validate_filters_and_groupby(
    finout_client: Any,
    filters: list,
    group_by: list | None,
) -> tuple[list, list | None, list[str]]:
    """Validate filters and group_by, returning corrected values and any warnings."""
    warnings: list[str] = []
    if filters:
        filters, meta_warnings = await _validate_filter_metadata(finout_client, filters)
        warnings.extend(meta_warnings)
        filters, value_warnings = await _validate_filter_values(finout_client, filters)
        warnings.extend(value_warnings)
    if group_by:
        group_by, gb_warnings = await _validate_filter_metadata(finout_client, group_by)
        warnings.extend(gb_warnings)
    return filters, group_by, warnings


async def get_top_movers_impl(args: dict) -> dict:
    """Identify dimensions with the largest cost changes between two periods."""
    from ..server import get_client

    finout_client = get_client()

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

    filters, group_by, validation_warnings = await _validate_filters_and_groupby(
        finout_client, filters, group_by
    )

    # Query both periods grouped by the dimension in parallel
    current_data, comparison_data = await asyncio.gather(
        finout_client.query_costs_with_filters(
            time_period=time_period,
            filters=filters if filters else None,
            group_by=group_by,
        ),
        finout_client.query_costs_with_filters(
            time_period=comparison_period,
            filters=filters if filters else None,
            group_by=group_by,
        ),
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
    """Compute cost-per-unit using usage data or resource counts."""
    from ..server import get_client

    finout_client = get_client()

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")
    usage_configuration = args.get("usage_configuration")
    count_distinct = args.get("count_distinct")
    cost_type = args.get("cost_type", "netAmortizedCost")

    if not finout_client.internal_api_url:
        return {
            "error": "Internal API not configured",
            "message": "Set FINOUT_API_URL environment variable.",
        }

    filters, group_by, validation_warnings = await _validate_filters_and_groupby(
        finout_client, filters, group_by
    )

    # count_distinct mode: cost ÷ number of distinct resources
    if count_distinct:
        return await _unit_economics_count_distinct(
            finout_client=finout_client,
            time_period=time_period,
            filters=filters,
            group_by=group_by,
            count_distinct=count_distinct,
            cost_type=cost_type,
            validation_warnings=validation_warnings,
        )

    # Usage-metric mode: cost ÷ usage (hours, GB, requests)
    if not usage_configuration:
        available_units = await finout_client.get_usage_unit_types(
            time_period=time_period,
            filters=filters if filters else None,
        )
        if not available_units:
            return {
                "time_period": time_period,
                "error": "No usage data available",
                "message": (
                    "No usage unit types found for this combination of filters and time period. "
                    "Apply a service filter first, or try a different time period."
                ),
            }
        if len(available_units) > 1:
            return {
                "time_period": time_period,
                "available_units": available_units,
                "message": (
                    f"Found {len(available_units)} usage unit types. "
                    "Specify usage_configuration to select one and re-run. "
                    'Example: {"costCenter": "'
                    + available_units[0]["costCenter"]
                    + '", "units": "'
                    + available_units[0]["units"]
                    + '"}'
                ),
            }
        # Exactly one unit — auto-select it
        unit = available_units[0]
        usage_configuration = {"costCenter": unit["costCenter"], "units": unit["units"]}

    ct = CostType(cost_type) if cost_type in _VALID_COST_TYPES else CostType.NET_AMORTIZED

    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        cost_type=ct,
        usage_configuration=usage_configuration,
    )

    if not data:
        return {
            "time_period": time_period,
            "data": [],
            "message": "No data returned for the given filters and time period.",
        }

    cost_col = _find_cost_column(data[0])
    usage_col = _find_usage_column(data[0])
    dim_col = _find_dimension_column(data[0])

    if not cost_col:
        return {"error": "No cost column found in response", "raw_columns": list(data[0].keys())}

    if not usage_col:
        return {
            "error": "No usage column found in response",
            "hint": "Verify usage_configuration is correct. Call get_usage_unit_types to discover valid units.",
            "raw_columns": list(data[0].keys()),
        }

    units_label = usage_configuration.get("units", "unit")

    results: list[dict[str, Any]] = []
    no_usage: list[dict[str, Any]] = []

    for row in data:
        cost = _to_number(row.get(cost_col, 0))
        usage = _to_number(row.get(usage_col, 0))
        name = row.get(dim_col, "Unknown") if dim_col else None

        if usage <= 0:
            entry: dict[str, Any] = {"total_cost": round(cost, 2), "usage": 0}
            if name:
                entry["name"] = name
            no_usage.append(entry)
            continue

        cost_per_unit = cost / usage
        entry = {
            "total_cost": round(cost, 2),
            f"total_{units_label}": round(usage, 4),
            f"cost_per_{units_label}": round(cost_per_unit, 4),
        }
        if name:
            entry["name"] = name
        results.append(entry)

    results.sort(key=lambda r: r[f"cost_per_{units_label}"], reverse=True)
    no_usage.sort(key=lambda r: r["total_cost"], reverse=True)

    total_cost = sum(r["total_cost"] for r in results)
    total_usage = sum(r[f"total_{units_label}"] for r in results)
    overall_cpu = total_cost / total_usage if total_usage > 0 else 0

    result: dict[str, Any] = {
        "time_period": time_period,
        "units": units_label,
        "usage_configuration": usage_configuration,
        "summary": {
            "total_cost": format_currency(total_cost),
            f"total_{units_label}": round(total_usage, 2),
            f"overall_cost_per_{units_label}": round(overall_cpu, 4),
        },
        "data": results[:50],
        "_presentation_hint": (
            f"Lead with the overall cost per {units_label}. "
            "Highlight which groups have the highest and lowest cost per unit — "
            "outliers indicate inefficiency or over-provisioning. "
            f"Use render_chart with a bar chart of cost_per_{units_label} by group."
        ),
    }
    if no_usage:
        result["no_usage_items"] = no_usage[:20]
        result["_no_usage_note"] = (
            f"{len(no_usage)} item(s) had no {units_label} usage data and are excluded — "
            "they may be flat-fee services (support, subscriptions) or billing line items "
            f"not measured in {units_label}."
        )
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result


async def _unit_economics_count_distinct(
    *,
    finout_client: Any,
    time_period: str,
    filters: list,
    group_by: list | None,
    count_distinct: dict,
    cost_type: str,
    validation_warnings: list[str],
) -> dict:
    """Cost-per-resource mode: queries with count_distinct, aggregates daily rows,
    and computes cost ÷ avg(distinct count) per group."""

    ct = CostType(cost_type) if cost_type in _VALID_COST_TYPES else CostType.NET_AMORTIZED

    data = await finout_client.query_costs_with_filters(
        time_period=time_period,
        filters=filters if filters else None,
        group_by=group_by,
        cost_type=ct,
        count_distinct=count_distinct,
    )

    if not data:
        return {
            "time_period": time_period,
            "data": [],
            "message": "No data returned for the given filters and time period.",
        }

    cost_col = _find_cost_column(data[0])
    count_col = _find_count_distinct_column(data[0])
    dim_col = _find_dimension_column(data[0])

    if not cost_col:
        return {"error": "No cost column found in response", "raw_columns": list(data[0].keys())}
    if not count_col:
        return {
            "error": "No count-distinct column found in response",
            "raw_columns": list(data[0].keys()),
        }

    # The API returns daily rows. Aggregate per group: sum cost, average resource count.
    group_agg: dict[str, dict[str, Any]] = {}
    for row in data:
        name = row.get(dim_col, "(all)") if dim_col else "(all)"
        # Skip the "Other (N items)" overflow bucket
        if isinstance(name, str) and name.startswith("Other ("):
            continue
        cost = _to_number(row.get(cost_col, 0))
        count = _to_number(row.get(count_col, 0))

        if name not in group_agg:
            group_agg[name] = {"total_cost": 0.0, "counts": [], "days": 0}
        group_agg[name]["total_cost"] += cost
        if count > 0:
            group_agg[name]["counts"].append(count)
        group_agg[name]["days"] += 1

    count_dim_label = count_distinct.get("key", "resource")
    units_label = f"{count_dim_label}s"

    results: list[dict[str, Any]] = []
    no_count: list[dict[str, Any]] = []

    for name, agg in group_agg.items():
        total_cost = round(agg["total_cost"], 2)
        counts = agg["counts"]
        if not counts:
            no_count.append({"name": name, "total_cost": total_cost, "resource_count": 0})
            continue
        avg_count = sum(counts) / len(counts)
        cost_per = total_cost / avg_count if avg_count > 0 else 0
        results.append(
            {
                "name": name,
                "total_cost": total_cost,
                f"avg_{count_dim_label}_count": round(avg_count, 1),
                f"cost_per_{count_dim_label}": round(cost_per, 2),
            }
        )

    results.sort(key=lambda r: r[f"cost_per_{count_dim_label}"], reverse=True)
    no_count.sort(key=lambda r: r["total_cost"], reverse=True)

    total_cost = sum(r["total_cost"] for r in results)
    total_resources = sum(r[f"avg_{count_dim_label}_count"] for r in results)
    overall_cpu = total_cost / total_resources if total_resources > 0 else 0

    result: dict[str, Any] = {
        "time_period": time_period,
        "mode": "count_distinct",
        "units": units_label,
        "count_distinct": count_distinct,
        "summary": {
            "total_cost": format_currency(total_cost),
            f"total_{count_dim_label}_count": round(total_resources, 1),
            f"overall_cost_per_{count_dim_label}": round(overall_cpu, 2),
        },
        "data": results[:50],
        "_presentation_hint": (
            f"Lead with the overall cost per {count_dim_label}. "
            "Highlight which groups have the highest and lowest cost per resource — "
            "outliers indicate inefficiency or over-provisioning. "
            f"Use render_chart with a bar chart of cost_per_{count_dim_label} by group."
        ),
    }
    if no_count:
        result["no_count_items"] = no_count[:20]
        result["_no_count_note"] = (
            f"{len(no_count)} group(s) had zero tracked resources and are excluded — "
            "they may be flat-fee services (support, subscriptions)."
        )
    if validation_warnings:
        result["_validation_warnings"] = validation_warnings

    return result


def _find_count_distinct_column(row: dict[str, Any]) -> str | None:
    """Find the count-distinct column in a data-explorer row."""
    for key in row:
        if key.startswith("Count Distinct(") or key.startswith("Count("):
            return key
    return None


def _find_usage_column(row: dict[str, Any]) -> str | None:
    """Find the usage amount column — a Sum column that is not cost."""
    for key in row:
        lower = key.lower()
        if lower.startswith("sum(") and "cost" not in lower:
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


_EMPTY_TAG_SENTINELS = {"", "n/a", "none", "null", "unknown", "untagged", "(empty)", "(none)"}


def _is_empty_tag_value(val: Any) -> bool:
    """Return True if a tag value represents 'no tag' — empty, null, or a placeholder."""
    if val is None:
        return True
    if isinstance(val, str) and val.strip().lower() in _EMPTY_TAG_SENTINELS:
        return True
    return False


async def get_cost_patterns_impl(args: dict) -> dict:
    """Analyze hourly cost patterns — peak hours, weekday/weekend splits."""
    from ..server import get_client

    finout_client = get_client()

    time_period = args.get("time_period", "last_7_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")

    if not finout_client.internal_api_url:
        return {"error": "Internal API not configured"}

    filters, group_by, validation_warnings = await _validate_filters_and_groupby(
        finout_client, filters, group_by
    )

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

    is_hourly = granularity == "hourly"
    result: dict[str, Any] = {
        "time_period": time_period,
        "granularity": granularity,
        "total_cost": format_currency(total),
        "_presentation_hint": (
            f"Granularity is {granularity}. "
            "Lead with weekday vs weekend comparison if available. "
            "Show day_of_week_average and highlight the most/least expensive day. "
            "If hourly data is available, also show peak/off-peak hours. "
            "Use render_chart with a bar chart of day_of_week_average."
        ),
    }
    if is_hourly:
        result["total_hourly_periods_analyzed"] = len(costs)
        result["hourly_average"] = format_currency(avg)
        result["hourly_std_dev"] = format_currency(std_dev)
        result["peak_hourly_cost"] = format_currency(peak_cost)
        result["trough_hourly_cost"] = format_currency(trough_cost)
    else:
        result["total_daily_periods_analyzed"] = len(costs)
        result["daily_average"] = format_currency(avg)
        result["daily_std_dev"] = format_currency(std_dev)
        result["peak_daily_cost"] = format_currency(peak_cost)
        result["trough_daily_cost"] = format_currency(trough_cost)

    if day_averages:
        result["day_of_week_average"] = day_averages

    if weekday_costs and weekend_costs:
        wd_avg = statistics.mean(weekday_costs)
        we_avg = statistics.mean(weekend_costs)
        if is_hourly:
            result["weekday_vs_weekend"] = {
                "weekday_hourly_avg": format_currency(wd_avg),
                "weekend_hourly_avg": format_currency(we_avg),
                "weekend_to_weekday_ratio": round(we_avg / wd_avg, 2) if wd_avg > 0 else None,
                "weekend_savings_opportunity": format_currency(max(0.0, wd_avg - we_avg)),
            }
        else:
            result["weekday_vs_weekend"] = {
                "weekday_daily_avg": format_currency(wd_avg),
                "weekend_daily_avg": format_currency(we_avg),
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
    from ..server import get_client

    finout_client = get_client()

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")

    if not finout_client.internal_api_url:
        return {"error": "Internal API not configured"}

    filters, group_by, validation_warnings = await _validate_filters_and_groupby(
        finout_client, filters, group_by
    )

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
    from ..server import get_client

    finout_client = get_client()

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

    filters, group_by, validation_warnings = await _validate_filters_and_groupby(
        finout_client, filters, group_by
    )

    tag_group = (group_by or []) + [tag_dimension]

    # Query total cost and tagged cost in parallel
    total_data, tagged_data = await asyncio.gather(
        finout_client.query_costs_with_filters(
            time_period=time_period,
            filters=filters if filters else None,
            group_by=group_by,
        ),
        finout_client.query_costs_with_filters(
            time_period=time_period,
            filters=filters if filters else None,
            group_by=tag_group,
        ),
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
        tag_val_col = (
            _find_dimension_column(tagged_data[0], exclude_col=dim_col) if tagged_data else None
        )

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


async def get_cost_statistics_impl(args: dict) -> dict:
    """Compute daily cost statistics — mean, median, peak, trough, volatility."""
    from ..server import get_client

    finout_client = get_client()

    time_period = args.get("time_period", "last_30_days")
    filters = args.get("filters", [])
    group_by = args.get("group_by")

    if not finout_client.internal_api_url:
        return {"error": "Internal API not configured"}

    filters, group_by, validation_warnings = await _validate_filters_and_groupby(
        finout_client, filters, group_by
    )

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
