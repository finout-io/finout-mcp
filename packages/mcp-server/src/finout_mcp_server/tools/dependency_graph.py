"""Object usage tracing — finds where Finout entities are referenced."""

import asyncio
import json
import re
from typing import Any

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s))


def _find_id_paths(obj: Any, target_id: str, path: str = "") -> list[str]:
    """Recursively find all paths where target_id appears as an exact value."""
    paths: list[str] = []
    if not obj and obj != 0:
        return paths
    if isinstance(obj, str):
        if obj == target_id:
            paths.append(path or "root")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            paths.extend(_find_id_paths(v, target_id, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            paths.extend(_find_id_paths(v, target_id, f"{path}[{i}]"))
    return paths


def _derive_context(path: str) -> str:
    if "filter" in path.lower():
        return "filter"
    if "groupby" in path.lower() or "group_by" in path.lower():
        return "groupBy"
    if "allocation" in path.lower():
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


# ---------------------------------------------------------------------------
# Structured virtual-tag dependency detection
# ---------------------------------------------------------------------------


def _add_vt_ref(refs: dict[str, tuple[str, str]], vt_id: str, path: str) -> None:
    key = f"{vt_id}:{path}"
    if key not in refs:
        refs[key] = (vt_id, path)


def _collect_vt_dependencies(
    value: Any,
    current_path: str,
    known_vt_ids: set[str],
    refs: dict[str, tuple[str, str]],
) -> None:
    """Collect virtual tag → virtual tag dependencies via known structural patterns."""
    if value is None:
        return

    if isinstance(value, list):
        for i, entry in enumerate(value):
            _collect_vt_dependencies(entry, f"{current_path}[{i}]", known_vt_ids, refs)
        return

    if not isinstance(value, dict):
        return

    # Pattern: {costCenter: 'virtualTag', key: <vtId>}
    if (
        value.get("costCenter") == "virtualTag"
        and isinstance(value.get("key"), str)
        and value["key"] in known_vt_ids
    ):
        _add_vt_ref(refs, value["key"], f"{current_path}.key")

    # Pattern: {to: {key: <vtId>}}
    to_val = value.get("to")
    if (
        isinstance(to_val, dict)
        and isinstance(to_val.get("key"), str)
        and to_val["key"] in known_vt_ids
    ):
        _add_vt_ref(refs, to_val["key"], f"{current_path}.to.key")

    for k, child in value.items():
        child_path = f"{current_path}.{k}" if current_path else k

        # Pattern: *.default.value.key = <vtId>
        if (
            k == "key"
            and isinstance(child, str)
            and child_path.endswith("default.value.key")
            and child in known_vt_ids
        ):
            _add_vt_ref(refs, child, child_path)

        _collect_vt_dependencies(child, child_path, known_vt_ids, refs)


def _create_vt_resolver(virtual_tags: list[dict]) -> dict[str, Any]:  # type: ignore[type-arg]
    """Build a resolver for direct and transitive VT→VT dependencies with cycle detection."""
    known_vt_ids = {_entity_id(vt) for vt in virtual_tags if _entity_id(vt)}
    known_vt_ids_clean: set[str] = {s for s in known_vt_ids if s}

    direct_deps: dict[str, list[tuple[str, str]]] = {}
    for vt in virtual_tags:
        vt_id = _entity_id(vt)
        if not vt_id:
            continue
        refs: dict[str, tuple[str, str]] = {}
        _collect_vt_dependencies(vt, "", known_vt_ids_clean, refs)
        direct_deps[vt_id] = list(refs.values())

    transitive_cache: dict[str, list[tuple[str, str]]] = {}

    def _resolve_transitive(vt_id: str, visited: set[str]) -> list[tuple[str, str]]:
        if vt_id in transitive_cache:
            return transitive_cache[vt_id]
        if vt_id in visited:
            return []
        visited.add(vt_id)
        refs2: dict[str, tuple[str, str]] = {}
        for target_id, path in direct_deps.get(vt_id, []):
            _add_vt_ref(refs2, target_id, path)
            for nested_id, _ in _resolve_transitive(target_id, visited):
                _add_vt_ref(refs2, nested_id, f"{path} -> {nested_id}")
        result = [(tid, p) for tid, p in refs2.values() if tid != vt_id]
        transitive_cache[vt_id] = result
        return result

    return {
        "get_direct": lambda vt_id: direct_deps.get(vt_id, []),
        "get_transitive": lambda vt_id: _resolve_transitive(vt_id, set()),
    }


# ---------------------------------------------------------------------------
# Structured financial-plan virtual-tag reference extraction
# ---------------------------------------------------------------------------


def _add_fp_vt_ref(
    refs: dict[str, dict],  # type: ignore[type-arg]
    vt_id: str,
    path: str,
    context: str,
) -> None:
    key = f"{vt_id}:{path}:{context}"
    if key not in refs:
        refs[key] = {"virtualTagId": vt_id, "path": path, "context": context}


def _collect_fp_vt_refs_from_filters(
    value: Any,
    current_path: str,
    known_vt_ids: set[str],
    refs: dict[str, dict],  # type: ignore[type-arg]
) -> None:
    if not value or not isinstance(value, dict | list):
        return

    if isinstance(value, list):
        for i, entry in enumerate(value):
            _collect_fp_vt_refs_from_filters(entry, f"{current_path}[{i}]", known_vt_ids, refs)
        return

    if (
        isinstance(value, dict)
        and value.get("costCenter") == "virtualTag"
        and isinstance(value.get("key"), str)
        and value["key"] in known_vt_ids
    ):
        _add_fp_vt_ref(refs, value["key"], f"{current_path}.key", "filter")

    if isinstance(value, dict):
        for k, child in value.items():
            child_path = f"{current_path}.{k}" if current_path else k
            _collect_fp_vt_refs_from_filters(child, child_path, known_vt_ids, refs)


def _collect_fp_vt_refs(
    value: Any,
    current_path: str,
    known_vt_ids: set[str],
    refs: dict[str, dict],  # type: ignore[type-arg]
) -> None:
    if value is None:
        return

    if isinstance(value, list):
        for i, entry in enumerate(value):
            _collect_fp_vt_refs(entry, f"{current_path}[{i}]", known_vt_ids, refs)
        return

    if not isinstance(value, dict):
        return

    # Pattern: {costCenter: 'virtualTag', key: <vtId>} → filter
    if (
        value.get("costCenter") == "virtualTag"
        and isinstance(value.get("key"), str)
        and value["key"] in known_vt_ids
    ):
        _add_fp_vt_ref(refs, value["key"], f"{current_path}.key", "filter")

    # Pattern: {to: {key: <vtId>}} → column
    to_val = value.get("to")
    if (
        isinstance(to_val, dict)
        and isinstance(to_val.get("key"), str)
        and to_val["key"] in known_vt_ids
    ):
        _add_fp_vt_ref(refs, to_val["key"], f"{current_path}.to.key", "column")

    for k, child in value.items():
        child_path = f"{current_path}.{k}" if current_path else k

        # Pattern: components[*].id = <vtId>
        if (
            k == "id"
            and isinstance(child, str)
            and current_path.startswith("components[")
            and child in known_vt_ids
        ):
            _add_fp_vt_ref(refs, child, child_path, "column")

        # Pattern: *.default.value.key = <vtId>
        if (
            k == "key"
            and isinstance(child, str)
            and child_path.endswith(".default.value.key")
            and child in known_vt_ids
        ):
            _add_fp_vt_ref(refs, child, child_path, "column")

        if k == "filters":
            _collect_fp_vt_refs_from_filters(child, child_path, known_vt_ids, refs)
            continue

        _collect_fp_vt_refs(child, child_path, known_vt_ids, refs)


def _normalize_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", path)


def _build_dep_signature(plan: dict, vt_refs: list[dict]) -> str:  # type: ignore[type-arg]
    components = plan.get("components", [])
    sig = {
        "componentCount": len(components) if isinstance(components, list) else 0,
        "rootFilters": plan.get("filters"),
        "virtualTagReferences": sorted(
            [
                {
                    "virtualTagId": r["virtualTagId"],
                    "context": r["context"],
                    "path": _normalize_path(r["path"]),
                }
                for r in vt_refs
            ],
            key=lambda x: f"{x['virtualTagId']}:{x['context']}:{x['path']}",
        ),
    }
    return json.dumps(sig, sort_keys=True)


def _extract_fp_facts(
    plan: dict,  # type: ignore[type-arg]
    known_vt_ids: set[str],
    plans_by_id: dict[str, dict],  # type: ignore[type-arg]
    vt_resolver: dict[str, Any],  # type: ignore[type-arg]
) -> dict[str, Any]:  # type: ignore[type-arg]
    """Extract structured dependency facts from a financial plan."""
    refs: dict[str, dict] = {}  # type: ignore[type-arg]
    _collect_fp_vt_refs(plan, "", known_vt_ids, refs)
    direct_vt_refs = list(refs.values())

    # Expand transitive dependencies
    all_vt_refs: dict[str, dict] = {}  # type: ignore[type-arg]
    for r in direct_vt_refs:
        key = f"{r['virtualTagId']}:{r['path']}:{r['context']}"
        all_vt_refs[key] = r

    for direct_ref in direct_vt_refs:
        for transitive_id, _ in vt_resolver["get_transitive"](direct_ref["virtualTagId"]):
            key = f"{transitive_id}:{direct_ref['path']}:{direct_ref['context']}:{direct_ref['virtualTagId']}"
            if key not in all_vt_refs:
                all_vt_refs[key] = {
                    "virtualTagId": transitive_id,
                    "path": f"{direct_ref['path']} -> {direct_ref['virtualTagId']}",
                    "context": direct_ref["context"],
                    "isTransitive": transitive_id != direct_ref["virtualTagId"],
                    "viaVirtualTagId": direct_ref["virtualTagId"],
                }

    # Origin tracking
    origin_id_raw = plan.get("originId")
    origin_id: str | None = (
        origin_id_raw if isinstance(origin_id_raw, str) and origin_id_raw else None
    )

    plan_refs: list[dict] = []  # type: ignore[type-arg]
    sync_status = "standalone"

    if origin_id:
        plan_refs.append(
            {
                "targetId": origin_id,
                "targetType": "financial_plan",
                "contexts": ["origin"],
                "match_method": "structured",
                "dependency_kind": "origin",
                "match_path": "originId",
                "reference_count": 1,
            }
        )
        origin_plan = plans_by_id.get(origin_id)
        if not origin_plan:
            sync_status = "originMissing"
        else:
            origin_refs: dict[str, dict] = {}  # type: ignore[type-arg]
            _collect_fp_vt_refs(origin_plan, "", known_vt_ids, origin_refs)
            if _build_dep_signature(plan, direct_vt_refs) == _build_dep_signature(
                origin_plan, list(origin_refs.values())
            ):
                sync_status = "synced"
            else:
                sync_status = "outOfSync"

    return {
        "origin_id": origin_id,
        "sync_status": sync_status,
        "direct_vt_refs": direct_vt_refs,
        "all_vt_refs": list(all_vt_refs.values()),
        "plan_refs": plan_refs,
    }


# ---------------------------------------------------------------------------
# Reference merging
# ---------------------------------------------------------------------------


def _merge_refs(
    primary: list[dict],  # type: ignore[type-arg]
    fallback: list[dict],  # type: ignore[type-arg]
) -> list[dict]:  # type: ignore[type-arg]
    """Merge structured and text-search references, preferring structured."""
    merged: dict[str, dict] = {}  # type: ignore[type-arg]

    def upsert(ref: dict) -> None:  # type: ignore[type-arg]
        key = f"{ref['entity_id']}:{ref['entity_type']}"
        existing = merged.get(key)
        if not existing:
            merged[key] = dict(ref)
            return

        em = existing.get("match_method", "textSearch")
        rm = ref.get("match_method", "textSearch")
        prefer_structured = em == "structured" or rm == "structured"
        ec, rc = existing.get("reference_count", 1), ref.get("reference_count", 1)

        merged[key] = {
            **existing,
            "contexts": list(set(existing.get("contexts", []) + ref.get("contexts", []))),
            "match_method": "structured" if prefer_structured else em,
            "match_path": (
                existing.get("match_path")
                if em == "structured"
                else ref.get("match_path")
                if rm == "structured"
                else existing.get("match_path") or ref.get("match_path")
            ),
            "dependency_kind": existing.get("dependency_kind") or ref.get("dependency_kind"),
            "via_target_id": existing.get("via_target_id") or ref.get("via_target_id"),
            "reference_count": max(ec, rc) if (em != rm and prefer_structured) else ec + rc,
        }

    for r in primary:
        upsert(r)
    for r in fallback:
        upsert(r)

    return list(merged.values())


# ---------------------------------------------------------------------------
# Entity fetching
# ---------------------------------------------------------------------------


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
        _safe(client.get_financial_plans_raw(), "financial_plan"),
        _safe(client.get_alerts(), "alert"),
    )
    return dict(results)


# ---------------------------------------------------------------------------
# Core usage finding
# ---------------------------------------------------------------------------


def _find_usages(
    target_id: str,
    all_entities: dict[str, list[dict]],  # type: ignore[type-arg]
) -> list[dict]:  # type: ignore[type-arg]
    """Find all entities that reference target_id."""
    # Build helpers once
    raw_vts = all_entities.get("virtual_tag", [])
    known_vt_ids = {_entity_id(vt) for vt in raw_vts if _entity_id(vt)}
    known_vt_ids_clean: set[str] = {s for s in known_vt_ids if s}
    vt_resolver = _create_vt_resolver(raw_vts)
    plans_by_id: dict[str, dict] = {  # type: ignore[type-arg]
        pid: p for p in all_entities.get("financial_plan", []) if (pid := _entity_id(p))
    }

    usages: list[dict] = []  # type: ignore[type-arg]
    for entity_type, entities in all_entities.items():
        for entity in entities:
            eid = _entity_id(entity)
            if eid and eid == target_id:
                continue  # skip self

            structured: list[dict] = []  # type: ignore[type-arg]

            if entity_type == "financial_plan":
                facts = _extract_fp_facts(entity, known_vt_ids_clean, plans_by_id, vt_resolver)
                # Check if target is referenced as a VT
                for vt_ref in facts["all_vt_refs"]:
                    if vt_ref["virtualTagId"] == target_id:
                        structured.append(
                            {
                                "entity_id": eid,
                                "entity_type": entity_type,
                                "entity_name": _entity_name(entity),
                                "contexts": [vt_ref["context"]],
                                "match_paths": [vt_ref["path"]],
                                "match_method": "structured",
                                "dependency_kind": (
                                    "transitive" if vt_ref.get("isTransitive") else "direct"
                                ),
                                "via_target_id": vt_ref.get("viaVirtualTagId"),
                                "reference_count": 1,
                            }
                        )
                # Check if target is the origin plan
                for plan_ref in facts["plan_refs"]:
                    if plan_ref["targetId"] == target_id:
                        structured.append(
                            {
                                "entity_id": eid,
                                "entity_type": entity_type,
                                "entity_name": _entity_name(entity),
                                "contexts": plan_ref["contexts"],
                                "match_paths": [plan_ref["match_path"]],
                                "match_method": "structured",
                                "dependency_kind": plan_ref["dependency_kind"],
                                "reference_count": 1,
                            }
                        )

            # Text-search fallback
            paths = _find_id_paths(entity, target_id)
            if not paths and not structured:
                continue

            if paths:
                contexts = list({_derive_context(p) for p in paths})
                text_ref = [
                    {
                        "entity_id": eid,
                        "entity_type": entity_type,
                        "entity_name": _entity_name(entity),
                        "contexts": contexts,
                        "match_paths": paths,
                        "match_method": "textSearch",
                        "reference_count": len(paths),
                    }
                ]
                usages.extend(_merge_refs(structured, text_ref))
            else:
                usages.extend(structured)

    return usages


# ---------------------------------------------------------------------------
# Mermaid diagram generation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Name lookup
# ---------------------------------------------------------------------------


def _find_by_name(
    name: str,
    entity_type: str | None,
    all_entities: dict[str, list[dict]],  # type: ignore[type-arg]
) -> tuple[str, str] | None:
    """Find entity ID + type by name. Case-insensitive exact match first, then partial."""
    search_types = [entity_type] if entity_type else list(all_entities.keys())
    name_lower = name.lower()

    for etype in search_types:
        for entity in all_entities.get(etype, []):
            if _entity_name(entity).lower() == name_lower:
                eid = _entity_id(entity)
                if eid:
                    return eid, etype

    for etype in search_types:
        for entity in all_entities.get(etype, []):
            if name_lower in _entity_name(entity).lower():
                eid = _entity_id(entity)
                if eid:
                    return eid, etype

    return None


# ---------------------------------------------------------------------------
# Public tool implementations
# ---------------------------------------------------------------------------


async def get_object_usages_impl(args: dict) -> dict:  # type: ignore[type-arg]
    from ..server import get_client

    finout_client = get_client()

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
    from ..server import get_client

    finout_client = get_client()

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
