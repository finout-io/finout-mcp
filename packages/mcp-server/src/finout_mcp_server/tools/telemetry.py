"""Telemetry center listing and summarization."""

from typing import Any


def _sanitize_data(data: dict[str, Any]) -> dict[str, str]:
    """Extract a safe, human-readable summary from the type-specific config."""
    summary: dict[str, str] = {}

    # S3-CSV sources
    if data.get("bucketName"):
        summary["bucket"] = data["bucketName"]
    if data.get("kpiCenterDir"):
        summary["path"] = data["kpiCenterDir"]
    if data.get("kpiSourceType"):
        summary["source_type"] = data["kpiSourceType"]

    # Datadog
    if data.get("query"):
        summary["query"] = data["query"]

    # CloudWatch
    if data.get("namespace"):
        summary["namespace"] = data["namespace"]
    if data.get("metricName"):
        summary["metric"] = data["metricName"]
    if data.get("dimensions"):
        summary["dimensions"] = ", ".join(data["dimensions"])
    if data.get("region_value"):
        summary["region"] = data["region_value"]

    # Cost Explorer
    if data.get("granularity"):
        summary["granularity"] = data["granularity"]
    if data.get("metrics"):
        summary["metrics"] = ", ".join(data["metrics"])
    if data.get("groupBy"):
        summary["group_by"] = ", ".join(data["groupBy"])

    # Megabill-ratio
    if data.get("viewId"):
        summary["view_id"] = data["viewId"]
    if data.get("timeFrameType"):
        summary["time_frame"] = data["timeFrameType"]

    # CSV metadata
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        if metadata.get("dateColumn"):
            summary["date_column"] = metadata["dateColumn"]
        if metadata.get("dateFormat"):
            summary["date_format"] = metadata["dateFormat"]

    return summary


def _build_vtag_usage_index(tags: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """Build a mapping from kpiCenterId → list of virtual tags that reference it."""
    index: dict[str, list[dict[str, str]]] = {}
    for tag in tags:
        tag_name = tag.get("name", "")
        tag_id = tag.get("id", "")
        for alloc in tag.get("allocations") or []:
            if not isinstance(alloc, dict):
                continue
            data = alloc.get("data") or {}
            kpi_id = data.get("kpiCenterId")
            if kpi_id:
                entry: dict[str, str] = {"name": tag_name, "id": tag_id}
                metric = data.get("metricName")
                if metric:
                    entry["metric"] = metric
                index.setdefault(kpi_id, []).append(entry)
    return index


def _format_center(
    center: dict[str, Any],
    vtag_usage: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Format a single telemetry center for output, stripping secrets."""
    result: dict[str, Any] = {
        "id": center.get("id", ""),
        "name": center.get("name", ""),
        "field": center.get("field", ""),
        "type": center.get("type", ""),
        "is_active": center.get("isActive", False),
        "metrics": center.get("metricNames", []),
    }

    if center.get("unit"):
        result["unit"] = center["unit"]

    if center.get("additionalFields"):
        result["additional_fields"] = center["additionalFields"]

    enrichers = center.get("enrichers") or []
    if enrichers:
        result["enricher_count"] = len(enrichers)

    data = center.get("data") or {}
    if data:
        result["source"] = _sanitize_data(data)

    if center.get("createdBy"):
        result["created_by"] = center["createdBy"]

    if center.get("updatedAt"):
        result["updated_at"] = center["updatedAt"]

    # Cross-reference: which virtual tags use this center
    center_id = center.get("id", "")
    if vtag_usage and center_id in vtag_usage:
        # Deduplicate by tag id
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for ref in vtag_usage[center_id]:
            if ref["id"] not in seen:
                seen.add(ref["id"])
                unique.append(ref)
        result["used_by_virtual_tags"] = unique
    else:
        result["used_by_virtual_tags"] = []

    return result


async def list_telemetry_centers_impl(args: dict) -> dict:
    from ..server import get_client

    client = get_client()
    centers = await client.get_telemetry_centers()

    if not centers:
        return {"message": "No telemetry centers found for this account."}

    # Fetch virtual tags for cross-reference (non-critical)
    vtag_usage: dict[str, list[dict[str, str]]] | None = None
    try:
        vtags = await client.get_virtual_tags()
        if vtags:
            vtag_usage = _build_vtag_usage_index(vtags)
    except Exception:
        pass  # Proceed without cross-reference

    # Optional filters
    type_filter = (args.get("type") or "").strip().lower()
    name_filter = (args.get("name") or "").strip().lower()

    filtered = centers
    if type_filter:
        filtered = [c for c in filtered if (c.get("type") or "").lower() == type_filter]
    if name_filter:
        filtered = [c for c in filtered if name_filter in (c.get("name") or "").lower()]

    if not filtered:
        return {
            "message": f"No telemetry centers match the given filters (type={type_filter or 'any'}, name={name_filter or 'any'}).",
            "total_in_account": len(centers),
        }

    # Summary by type
    by_type: dict[str, int] = {}
    for c in centers:
        t = c.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    formatted = [_format_center(c, vtag_usage) for c in filtered]

    # Count how many centers are used vs unused
    used_count = sum(1 for c in formatted if c.get("used_by_virtual_tags"))

    return {
        "total": len(centers),
        "showing": len(filtered),
        "used_by_virtual_tags": used_count,
        "unused": len(filtered) - used_count,
        "by_type": by_type,
        "centers": formatted,
        "_presentation_hint": (
            "Present telemetry centers grouped by type. "
            "Highlight the source summary for each (bucket, query, view, etc). "
            "For each center, show which virtual tags use it (used_by_virtual_tags). "
            "Flag unused centers as potential cleanup candidates."
        ),
    }
