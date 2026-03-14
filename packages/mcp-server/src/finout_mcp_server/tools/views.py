"""View and dashboard creation tools."""

from ..finout_client import CostType


async def create_view_impl(args: dict) -> dict:
    """Implementation of create_view tool"""
    from ..server import get_client

    finout_client = get_client()

    name = args["name"]
    filters = args.get("filters")
    group_by = args.get("group_by")
    time_period = args.get("time_period", "last_30_days")
    cost_type_str = args.get("cost_type", CostType.NET_AMORTIZED.value)
    cost_type = CostType(cost_type_str)

    view = await finout_client.create_view(
        name=name,
        filters=filters,
        group_by=group_by,
        time_period=time_period,
        cost_type=cost_type,
    )
    view_id = view.get("id")
    account_id = finout_client.account_id
    url = f"https://app.finout.io/app/total-cost?view={view_id}"
    if account_id:
        url += f"&accountId={account_id}"
    return {
        "id": view_id,
        "name": view.get("name"),
        "url": url,
        "_presentation_hint": "Tell the user the view was saved and share the link.",
    }


async def create_dashboard_impl(args: dict) -> dict:
    """Implementation of create_dashboard tool"""
    from ..server import get_client

    finout_client = get_client()
    name = args["name"]
    widgets = args["widgets"]

    dashboard = await finout_client.create_dashboard(name=name, widgets=widgets)
    dashboard_id = dashboard.get("id")
    account_id = finout_client.account_id
    url = f"https://app.finout.io/app/dashboards/{dashboard_id}"
    if account_id:
        url += f"?accountId={account_id}"
    return {
        "id": dashboard_id,
        "name": dashboard.get("name"),
        "url": url,
        "widget_count": len(widgets),
        "_presentation_hint": (
            f"Tell the user the dashboard was created with {len(widgets)} widgets "
            "and share the link."
        ),
    }
