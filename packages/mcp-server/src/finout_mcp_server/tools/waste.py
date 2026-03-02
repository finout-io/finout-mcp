"""Waste recommendations tool."""

import json

from .cost import format_currency


async def get_waste_recommendations_impl(args: dict) -> dict:
    """Implementation of get_waste_recommendations tool"""
    from ..server import finout_client

    assert finout_client is not None

    scan_type = args.get("scan_type")
    service = args.get("service")
    min_saving = args.get("min_saving")

    recommendations = await finout_client.get_waste_recommendations(
        scan_type=scan_type, service=service, min_saving=min_saving
    )

    # Format recommendations
    formatted = []
    total_savings = 0

    for rec in recommendations[:50]:  # Limit to top 50
        # CostGuard payloads vary by scan type; normalize defensively.
        saving = (
            rec.get("monthly_savings")
            or rec.get("projected_savings")
            or rec.get("potential_savings")
            or 0
        )
        if not saving and rec.get("yearly_savings"):
            saving = rec.get("yearly_savings", 0) / 12
        total_savings += saving

        resource_metadata = rec.get("resource_metadata", {})
        if not isinstance(resource_metadata, dict):
            resource_metadata = {}

        recommendation_text = (
            rec.get("recommendation")
            or rec.get("scan_name")
            or rec.get("title")
            or "Review this resource for optimization opportunity."
        )
        details = rec.get("details")
        if not details and resource_metadata:
            details = json.dumps(resource_metadata, ensure_ascii=False)

        formatted.append(
            {
                "resource": (
                    rec.get("resource_name")
                    or resource_metadata.get("resourceName")
                    or resource_metadata.get("name")
                    or rec.get("resource_id", "Unknown")
                ),
                "service": rec.get("service") or rec.get("cost_center", "Unknown"),
                "type": rec.get("scan_type") or rec.get("recommendation_type", "Unknown"),
                "current_monthly_cost": format_currency(
                    rec.get("current_cost") or rec.get("resource_waste", 0)
                ),
                "potential_monthly_savings": format_currency(saving),
                "recommendation": recommendation_text,
                "details": details or "",
            }
        )

    return {
        "filters": {"scan_type": scan_type, "service": service, "min_saving": min_saving},
        "recommendation_count": len(recommendations),
        "showing": len(formatted),
        "total_potential_savings": format_currency(total_savings),
        "annual_savings_potential": format_currency(total_savings * 12),
        "recommendations": formatted,
        "_presentation_hint": (
            "Present as numbered action list sorted by savings. "
            "Include total potential savings at top."
        ),
    }
