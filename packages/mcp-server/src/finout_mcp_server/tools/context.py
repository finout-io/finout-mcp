"""Context discovery tools — dashboards, views, data explorers."""

from typing import Any


async def discover_context_impl(args: dict) -> dict:
    """Implementation of discover_context tool"""
    from ..server import get_client

    finout_client = get_client()

    query = args.get("query", "").lower()
    include_dashboards = args.get("include_dashboards", True)
    include_views = args.get("include_views", True)
    include_data_explorers = args.get("include_data_explorers", True)
    max_results = args.get("max_results", 5)

    dashboards_list: list[dict[str, Any]] = []
    views_list: list[dict[str, Any]] = []
    data_explorers_list: list[dict[str, Any]] = []

    results: dict[str, Any] = {
        "query": args.get("query"),
        "dashboards": dashboards_list,
        "views": views_list,
        "data_explorers": data_explorers_list,
        "summary": "",
    }

    # Search dashboards
    if include_dashboards:
        dashboards = await finout_client.get_dashboards()
        matching_dashboards = [d for d in dashboards if query in d.get("name", "").lower()][
            :max_results
        ]

        # Enrich with widget details for matching dashboards
        for dashboard in matching_dashboards:
            widget_ids = [
                w["widgetId"] for w in dashboard.get("widgets", [])[:3]
            ]  # First 3 widgets
            widgets: list[dict[str, Any]] = []
            for wid in widget_ids:
                try:
                    widget = await finout_client.get_widget(wid)

                    # Extract configuration (filters are directly under configuration)
                    config = widget.get("configuration", {})

                    # Extract filter (single object, not array)
                    filter_obj = config.get("filters", {})
                    simplified_filters = []
                    if filter_obj and isinstance(filter_obj, dict):
                        simplified_filters.append(
                            {
                                "key": filter_obj.get("key"),
                                "value": filter_obj.get("value"),
                                "operator": filter_obj.get("operator", "eq"),
                                "type": filter_obj.get("type"),
                            }
                        )

                    # Extract groupBy (singular, not array)
                    group_by_obj = config.get("groupBy", {})
                    group_bys = []
                    if group_by_obj and isinstance(group_by_obj, dict):
                        group_bys.append(
                            {
                                "key": group_by_obj.get("key"),
                                "path": group_by_obj.get("path"),
                                "type": group_by_obj.get("type"),
                            }
                        )

                    widgets.append(
                        {
                            "name": widget.get("name"),
                            "filters": simplified_filters if simplified_filters else None,
                            "groupBys": group_bys if group_bys else None,
                            "date": config.get("date"),
                        }
                    )
                except Exception as e:
                    import sys

                    print(f"Error fetching widget {wid}: {e}", file=sys.stderr)
                    import traceback

                    traceback.print_exc(file=sys.stderr)
                    pass

            d_url = f"https://app.finout.io/app/dashboards/{dashboard['id']}"
            if finout_client.account_id:
                d_url += f"?accountId={finout_client.account_id}"
            dashboards_list.append(
                {
                    "id": dashboard["id"],
                    "name": dashboard["name"],
                    "url": d_url,
                    "widgets": widgets,
                    "defaultDate": dashboard.get("defaultDate"),
                }
            )

    # Search views
    if include_views:
        views = await finout_client.get_views()
        matching_views = [v for v in views if query in v.get("name", "").lower()][:max_results]

        for view in matching_views:
            # Try configuration first, fallback to data for backwards compatibility
            config = view.get("configuration") or view.get("data", {})
            query_config = config.get("query", {})

            views_list.append(
                {
                    "id": view["id"],
                    "name": view["name"],
                    "type": view.get("type"),
                    "filters": query_config.get("filters"),
                    "groupBys": query_config.get("groupBys"),
                    "date": config.get("date"),
                }
            )

    # Search data explorers
    if include_data_explorers:
        explorers = await finout_client.get_data_explorers()
        matching_explorers = [
            e
            for e in explorers
            if (
                (isinstance(e.get("name"), str) and query in e.get("name", "").lower())
                or (
                    isinstance(e.get("description"), str)
                    and query in e.get("description", "").lower()
                )
            )
        ][:max_results]

        for explorer in matching_explorers:
            data_explorers_list.append(
                {
                    "id": explorer["id"],
                    "name": explorer["name"],
                    "description": explorer.get("description"),
                    "filters": explorer.get("filters"),
                    "columns": explorer.get("columns"),
                }
            )

    # Generate summary with actionable guidance
    total_results = len(dashboards_list) + len(views_list) + len(data_explorers_list)
    if total_results == 0:
        results["summary"] = (
            f"No context found for '{args.get('query')}'. "
            "Try a different search term or use search_filters to explore available dimensions."
        )
    else:
        summary_parts = [
            f"Found {len(dashboards_list)} dashboard(s), {len(views_list)} view(s), "
            f"{len(data_explorers_list)} data explorer(s) for '{args.get('query')}'"
        ]

        # Extract common filters from discovered context
        all_filters: list[dict[str, Any]] = []
        for dashboard in dashboards_list:
            for widget in dashboard.get("widgets", []):
                if widget.get("filters"):
                    all_filters.extend(widget["filters"])
        for view in views_list:
            if view.get("filters"):
                all_filters.extend(view["filters"])

        # Provide actionable guidance
        if all_filters:
            filter_summary: dict[str, list[Any]] = {}
            for f in all_filters:
                key = f.get("key")
                if key:
                    if key not in filter_summary:
                        filter_summary[key] = []
                    value = f.get("value")
                    if value and value not in filter_summary[key]:
                        filter_summary[key].append(value)

            if filter_summary:
                summary_parts.append(
                    "\n\n⚠️ IMPORTANT: The dashboards/views above show how to identify these resources."
                )
                summary_parts.append("\n\nFilters that define this context:")
                for key, values in list(filter_summary.items())[:5]:  # Top 5 filters
                    values_str = ", ".join(map(str, values[:3]))
                    summary_parts.append(f"  • {key}: {values_str}")

                # Provide example query
                first_key = list(filter_summary.keys())[0]
                first_value = filter_summary[first_key][0]
                summary_parts.append(
                    "\n\n✅ NEXT STEP: Build a validated query from discovered context."
                    f"\nExample workflow: search_filters('{first_key}') → "
                    "copy the exact filter object (costCenter/key/path/type) → "
                    f"get_filter_values(filter_key='{first_key}') → "
                    f"query_costs(time_period='last_30_days', filters=[{{...,'operator':'is','value':'{first_value}'}}])"
                )

        results["summary"] = "".join(summary_parts)

    return results


async def list_data_explorers_impl(args: dict) -> dict:
    """List saved data explorer configurations."""
    from ..server import get_client

    finout_client = get_client()

    query = args.get("query", "").lower()

    explorers = await finout_client.get_data_explorers()

    results: list[dict[str, Any]] = []
    for explorer in explorers:
        name = explorer.get("name", "")
        description = explorer.get("description", "")

        if query and query not in name.lower() and query not in (description or "").lower():
            continue

        # Extract column types for a concise summary
        columns = explorer.get("columns", [])
        col_summary = []
        for col in columns:
            col_type = col.get("columnType", "")
            if col_type == "measurement":
                col_summary.append(f"{col.get('aggregation', 'sum')}({col.get('type', '?')})")
            elif col_type == "dimension":
                dim = col.get("dimension", {})
                col_summary.append(dim.get("key", "?"))
            elif col_type == "dateAggregation":
                col_summary.append(f"date:{col.get('aggregation', '?')}")
            elif col_type == "billingMetric":
                col_summary.append(col.get("type", "?"))
            elif col_type == "predefinedQuery":
                col_summary.append(col.get("queryType", "?"))

        entry: dict[str, Any] = {
            "id": explorer.get("id"),
            "name": name,
            "columns": col_summary,
        }
        if description:
            entry["description"] = description
        if explorer.get("filters"):
            entry["has_filters"] = True

        results.append(entry)

    return {
        "total": len(results),
        "explorers": results[:30],
        "_presentation_hint": (
            "Show each explorer's name and columns. If the user wants details, "
            "they can use discover_context with the explorer name."
        ),
    }


async def get_account_context_impl() -> dict:
    """Implementation of get_account_context tool"""
    from ..server import get_client

    finout_client = get_client()

    return await finout_client.get_account_context()
