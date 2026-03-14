"""Anomaly detection and financial plans tools."""

from datetime import datetime
from typing import Any

from .cost import format_currency


async def get_anomalies_impl(args: dict) -> dict:
    """Implementation of get_anomalies tool"""
    from ..server import get_client

    finout_client = get_client()

    time_period = args.get("time_period", "last_7_days")
    severity = args.get("severity")

    anomalies = await finout_client.get_anomalies(time_period=time_period, severity=severity)

    total_impact = sum(a.get("cost_impact", 0) for a in anomalies)

    formatted_anomalies = []
    for anomaly in anomalies:
        raw_date = anomaly.get("date")
        try:
            ts = int(raw_date) / 1000 if raw_date is not None else 0
        except (TypeError, ValueError):
            ts = 0
        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "Unknown"
        percent_over_expected = float(anomaly.get("percent_over_expected", 0) or 0)
        formatted_anomalies.append(
            {
                "date": date_str,
                "alert_name": anomaly.get("alert_name"),
                "dimension": f"{anomaly.get('dimension_type', '')}: {anomaly.get('dimension_value', '')}",
                "severity": anomaly.get("severity"),
                "cost_impact": format_currency(anomaly.get("cost_impact", 0)),
                "expected_cost": format_currency(anomaly.get("expected_cost", 0)),
                "actual_cost": format_currency(anomaly.get("actual_cost", 0)),
                "percent_over_expected": f"{percent_over_expected:+.1f}%",
            }
        )

    return {
        "time_period": time_period,
        "severity_filter": severity,
        "anomaly_count": len(formatted_anomalies),
        "anomalies": formatted_anomalies,
        "total_impact": format_currency(total_impact),
        "_presentation_hint": (
            "Present anomalies sorted by cost impact. "
            "Group by date if there are many. "
            "Highlight the largest surprises with their percent over expected."
        ),
    }


async def get_financial_plans_impl(args: dict) -> dict:
    """Implementation of get_financial_plans tool"""
    from ..server import get_client

    finout_client = get_client()

    name = args.get("name")
    period = args.get("period")

    plans = await finout_client.get_financial_plans(name=name, period=period)

    formatted = []
    for plan in plans:
        items = plan.get("top_line_items", [])
        formatted_items = [
            {
                "key": item["key"],
                "budget": format_currency(item["budget"]),
                "forecast": format_currency(item["forecast"])
                if item.get("forecast") is not None
                else None,
            }
            for item in items
        ]

        entry: dict[str, Any] = {
            "name": plan["name"],
            "period": plan["period"],
            "cost_type": plan["cost_type"],
            "total_budget": format_currency(plan["total_budget"]),
            "active_line_items": plan["active_line_item_count"],
            "top_line_items": formatted_items,
        }
        if plan.get("total_forecast") is not None:
            entry["total_forecast"] = format_currency(plan["total_forecast"])

        formatted.append(entry)

    return {
        "plan_count": len(formatted),
        "plans": formatted,
        "_presentation_hint": (
            "Show plan name, period, total budget and top line items. "
            "If forecast is present, compare budget vs forecast."
        ),
    }
