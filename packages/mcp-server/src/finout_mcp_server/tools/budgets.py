"""Financial plans (budgets) tool."""

from typing import Any

from .cost import format_currency


async def get_financial_plans_impl(args: dict) -> dict:
    """Implementation of get_financial_plans tool."""
    from ..server import get_client

    finout_client = get_client()

    name = args.get("name")
    period = args.get("period")

    plans = await finout_client.get_financial_plans(name=name, period=period)

    # List mode: no name → return plan names with date ranges and status
    if not name:
        return {
            "plan_count": len(plans),
            "plans": plans,
            "_presentation_hint": (
                "Group plans by status (active, future, past). "
                "Active plans have budget + actuals for the current month. "
                "Future plans haven't started yet — budget is set but no actuals. "
                "Past plans are completed. "
                "Ask the user which plan they want details on."
            ),
        }

    # Detail mode: name provided → format enriched data
    if not plans:
        return {"plan_count": 0, "message": f'No financial plan matching "{name}".'}

    plan = plans[0]
    items = plan.get("line_items", [])
    formatted_items = []
    for item in items:
        li: dict[str, Any] = {
            "key": item["key"],
            "budget": format_currency(item["budget"]),
        }
        if item.get("cost") is not None:
            li["cost"] = format_currency(item["cost"])
        if item.get("run_rate") is not None:
            li["run_rate"] = format_currency(item["run_rate"])
        if item.get("forecast") is not None:
            li["forecast"] = format_currency(item["forecast"])
        if item.get("delta") is not None:
            li["delta"] = format_currency(item["delta"])
        formatted_items.append(li)

    result: dict[str, Any] = {
        "name": plan["name"],
        "period": plan["period"],
        "cost_type": plan["cost_type"],
        "total_budget": format_currency(plan["total_budget"]),
        "active_line_items": plan["active_line_item_count"],
        "line_items": formatted_items,
    }
    if plan.get("total_cost") is not None:
        result["total_cost"] = format_currency(plan["total_cost"])
    if plan.get("total_run_rate") is not None:
        result["total_run_rate"] = format_currency(plan["total_run_rate"])
    if plan.get("total_forecast") is not None:
        result["total_forecast"] = format_currency(plan["total_forecast"])
    if plan.get("total_delta") is not None:
        result["total_delta"] = format_currency(plan["total_delta"])
    if plan.get("status"):
        result["status"] = plan["status"]

    result["_presentation_hint"] = (
        "Lead with status (on_track / at_risk / over_budget) if present. "
        "Show plan name, period, total budget vs actual cost, and run rate. "
        "Show top line items with budget vs cost comparison."
    )
    return result
