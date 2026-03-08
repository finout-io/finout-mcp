"""Object usage tracing — finds where Finout entities are referenced."""

import asyncio
from typing import Any


def _find_id_paths(obj: Any, target_id: str, path: str = "") -> list[str]:
    """Recursively find all paths where target_id appears as an exact value."""
    paths: list[str] = []
    if isinstance(obj, str) and obj.lower() == target_id.lower():
        paths.append(path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            paths.extend(_find_id_paths(v, target_id, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            paths.extend(_find_id_paths(v, target_id, f"{path}[{i}]"))
    return paths


def _derive_context(path: str) -> str:
    path_lower = path.lower()
    if "filter" in path_lower:
        return "filter"
    if "groupby" in path_lower or "group_by" in path_lower:
        return "groupBy"
    if "allocation" in path_lower:
        return "allocation"
    return "column"


def _entity_name(entity: dict) -> str:  # type: ignore[type-arg]
    return (
        entity.get("name")
        or entity.get("title")
        or entity.get("_id")
        or entity.get("id")
        or "Unknown"
    )


def _entity_id(entity: dict) -> str | None:  # type: ignore[type-arg]
    val = entity.get("id") or entity.get("_id")
    return str(val) if val else None


async def _fetch_all_entities(client: Any) -> dict[str, list[dict]]:  # type: ignore[type-arg]
    """Fetch all entity types in parallel."""

    async def _safe(coro: Any, key: str) -> tuple[str, list[dict]]:  # type: ignore[type-arg]
        try:
            result = await coro
            return key, result if isinstance(result, list) else []
        except Exception:
            return key, []

    results = await asyncio.gather(
        _safe(client.get_virtual_tags(), "virtual_tag"),
        _safe(client.get_views(), "view"),
        _safe(client.get_dashboards(), "dashboard"),
        _safe(client.get_widgets(), "widget"),
        _safe(client.get_data_explorers(), "explorer"),
        _safe(client.get_financial_plans(), "financial_plan"),
        _safe(client.get_alerts(), "alert"),
    )
    return dict(results)


def _find_usages(
    target_id: str,
    all_entities: dict[str, list[dict]],  # type: ignore[type-arg]
) -> list[dict]:  # type: ignore[type-arg]
    """Find all entities that reference target_id."""
    usages: list[dict] = []  # type: ignore[type-arg]
    for entity_type, entities in all_entities.items():
        for entity in entities:
            eid = _entity_id(entity)
            if eid and eid.lower() == target_id.lower():
                continue  # skip self-references
            paths = _find_id_paths(entity, target_id)
            if not paths:
                continue
            contexts = list({_derive_context(p) for p in paths})
            usages.append(
                {
                    "entity_id": eid,
                    "entity_type": entity_type,
                    "entity_name": _entity_name(entity),
                    "contexts": contexts,
                    "match_paths": paths,
                    "reference_count": len(paths),
                }
            )
    return usages


def _safe_id(raw: str) -> str:
    """Return a Mermaid-safe node ID."""
    return "".join(c if c.isalnum() else "_" for c in raw)


def _safe_label(text: str) -> str:
    """Escape quotes inside Mermaid labels."""
    return text.replace('"', "'")


def _build_summary_diagram(
    target_name: str,
    target_type: str,
    usages: list[dict],  # type: ignore[type-arg]
) -> str:
    """Build a compact Mermaid diagram with one node per entity type and count."""
    lines = ["graph LR"]
    tid = "TARGET"
    lines.append(f'    {tid}["{_safe_label(target_name)}<br/><i>{target_type}</i>"]')

    # Group usages by entity_type
    groups: dict[str, list[dict]] = {}  # type: ignore[type-arg]
    for u in usages:
        etype = u.get("entity_type", "unknown")
        groups.setdefault(etype, []).append(u)

    for i, (etype, group) in enumerate(sorted(groups.items())):
        nid = f"G{i}"
        count = len(group)
        label = f"{etype}s ({count})" if count > 1 else f"{etype} (1)"
        lines.append(f'    {nid}["{_safe_label(label)}"]')
        all_contexts: set[str] = set()
        for u in group:
            all_contexts.update(u.get("contexts", ["ref"]))
        ctx = ", ".join(sorted(all_contexts))
        lines.append(f'    {tid} -->|"{ctx}"| {nid}')

    lines.append(f"    style {tid} fill:#e0f2fe,stroke:#38B28E,stroke-width:3px")
    return "\n".join(lines)


def _build_detail_diagram(
    target_name: str,
    target_type: str,
    usages: list[dict],  # type: ignore[type-arg]
) -> str:
    """Build a detailed Mermaid diagram with subgraphs per entity type."""
    lines = ["graph LR"]
    tid = "TARGET"
    lines.append(f'    {tid}["{_safe_label(target_name)}<br/><i>{target_type}</i>"]')

    # Group usages by entity_type
    groups: dict[str, list[dict]] = {}  # type: ignore[type-arg]
    for u in usages:
        etype = u.get("entity_type", "unknown")
        groups.setdefault(etype, []).append(u)

    node_idx = 0
    for etype, group in sorted(groups.items()):
        sg_id = _safe_id(etype)
        lines.append(f"    subgraph {sg_id} [{etype}s]")
        for u in group:
            nid = f"U{node_idx}"
            name = _safe_label(u.get("entity_name", "Unknown"))
            lines.append(f'        {nid}["{name}"]')
            node_idx += 1
        lines.append("    end")

    # Add edges outside subgraphs
    node_idx = 0
    for _etype, group in sorted(groups.items()):
        for u in group:
            nid = f"U{node_idx}"
            ctx = ", ".join(sorted(u.get("contexts", ["ref"])))
            lines.append(f'    {tid} -->|"{ctx}"| {nid}')
            node_idx += 1

    lines.append(f"    style {tid} fill:#e0f2fe,stroke:#38B28E,stroke-width:3px")
    return "\n".join(lines)


def _build_usage_diagrams(
    target_name: str,
    target_type: str,
    usages: list[dict],  # type: ignore[type-arg]
) -> dict[str, str]:
    """Build both summary and detail Mermaid diagrams."""
    return {
        "summary": _build_summary_diagram(target_name, target_type, usages),
        "detail": _build_detail_diagram(target_name, target_type, usages),
    }


def _find_by_name(
    name: str,
    entity_type: str | None,
    all_entities: dict[str, list[dict]],  # type: ignore[type-arg]
) -> tuple[str, str] | None:
    """Find entity ID + type by name. Case-insensitive exact match first, then partial."""
    search_types = [entity_type] if entity_type else list(all_entities.keys())
    name_lower = name.lower()

    # Exact match first
    for etype in search_types:
        for entity in all_entities.get(etype, []):
            if _entity_name(entity).lower() == name_lower:
                eid = _entity_id(entity)
                if eid:
                    return eid, etype

    # Partial match
    for etype in search_types:
        for entity in all_entities.get(etype, []):
            if name_lower in _entity_name(entity).lower():
                eid = _entity_id(entity)
                if eid:
                    return eid, etype

    return None


async def get_object_usages_impl(args: dict) -> dict:  # type: ignore[type-arg]
    from ..server import finout_client

    assert finout_client is not None

    name = args["name"]
    entity_type = args.get("entity_type")

    all_entities = await _fetch_all_entities(finout_client)
    match = _find_by_name(name, entity_type, all_entities)

    if not match:
        return {
            "found": False,
            "message": f"No entity named '{name}' found.",
        }

    target_id, target_type = match
    usages = _find_usages(target_id, all_entities)

    result: dict[str, Any] = {
        "found": True,
        "entity_id": target_id,
        "entity_type": target_type,
        "entity_name": name,
        "usage_count": len(usages),
        "usages": usages,
    }
    if usages:
        diagrams = _build_usage_diagrams(name, target_type, usages)
        result["mermaid_diagram"] = diagrams["summary"]
        result["mermaid_diagram_detail"] = diagrams["detail"]
    return result


async def check_delete_safety_impl(args: dict) -> dict:  # type: ignore[type-arg]
    from ..server import finout_client

    assert finout_client is not None

    name = args["name"]
    entity_type = args.get("entity_type")

    all_entities = await _fetch_all_entities(finout_client)
    match = _find_by_name(name, entity_type, all_entities)

    if not match:
        return {
            "found": False,
            "message": f"No entity named '{name}' found.",
        }

    target_id, target_type = match
    usages = _find_usages(target_id, all_entities)
    safe_to_delete = len(usages) == 0

    result: dict[str, Any] = {
        "found": True,
        "entity_id": target_id,
        "entity_type": target_type,
        "entity_name": name,
        "safe_to_delete": safe_to_delete,
        "blocking_usages": usages if not safe_to_delete else [],
        "message": (
            f"'{name}' is not referenced by any other entity. Safe to delete."
            if safe_to_delete
            else (
                f"'{name}' is referenced by {len(usages)} entity(ies). "
                "Review blocking_usages before deleting."
            )
        ),
    }
    if usages:
        diagrams = _build_usage_diagrams(name, target_type, usages)
        result["mermaid_diagram"] = diagrams["summary"]
        result["mermaid_diagram_detail"] = diagrams["detail"]
    return result
