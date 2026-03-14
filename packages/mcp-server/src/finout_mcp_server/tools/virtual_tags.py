"""Virtual tag analysis — graph building, chain discovery, subgraph analysis."""

import asyncio
from typing import Any

from ..finout_client import FinoutClient

_MAX_GRAPH_NODES = 50

_TAG_TYPE_CLASS: dict[str, str] = {
    "reallocation": "tagReallocation",
    "relational": "tagRelational",
    "custom": "tagCustom",
    "base": "tagBase",
    "unknown": "tagUnknown",
}


def _extract_virtual_tag_references(tag: dict, tag_map: dict[str, str]) -> list[str]:
    """Extract IDs of virtual tags referenced by this tag's rules."""
    refs: list[str] = []
    for rule in tag.get("rules") or []:
        # A. rule.to is {key: <tag_id>}
        to = rule.get("to")
        if isinstance(to, dict) and "key" in to:
            ref_id = to["key"]
            if ref_id in tag_map:
                refs.append(ref_id)

        filters = rule.get("filters") or {}
        if not isinstance(filters, dict):
            continue

        # B. direct filter with costCenter == 'virtualTag'
        if filters.get("costCenter") == "virtualTag" and filters.get("key"):
            ref_id = filters["key"]
            if ref_id in tag_map:
                refs.append(ref_id)

        # C. OR conditions
        for cond in filters.get("OR") or []:
            if (
                isinstance(cond, dict)
                and cond.get("costCenter") == "virtualTag"
                and cond.get("key")
            ):
                ref_id = cond["key"]
                if ref_id in tag_map:
                    refs.append(ref_id)

        # D. AND conditions
        for cond in filters.get("AND") or []:
            if (
                isinstance(cond, dict)
                and cond.get("costCenter") == "virtualTag"
                and cond.get("key")
            ):
                ref_id = cond["key"]
                if ref_id in tag_map:
                    refs.append(ref_id)

    return refs


def _infer_tag_type(tag: dict, tag_map: dict[str, str]) -> str:
    """
    Derive tag type. The API type field is almost always 'default' and not useful,
    with the exception of 'multiKeyReallocation' which means relational.

    For 'default' tags, type is inferred structurally:
    - reallocation: has allocations (metric/telemetry-based cost splits)
    - relational:   rules reference other virtual tags via costCenter == 'virtualTag'
    - custom:       has rules but no cross-tag references
    - base:         no rules, no allocations
    """
    if (tag.get("type") or "") == "multiKeyReallocation":
        return "relational"
    if tag.get("allocations"):
        return "reallocation"
    for rule in tag.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        filters = rule.get("filters") or {}
        if not isinstance(filters, dict):
            continue
        if filters.get("costCenter") == "virtualTag":
            return "relational"
        for cond in (filters.get("OR") or []) + (filters.get("AND") or []):
            if isinstance(cond, dict) and cond.get("costCenter") == "virtualTag":
                return "relational"
    if tag.get("rules"):
        return "custom"
    return "base"


def _get_reallocation_info(tag: dict) -> dict:
    """
    Extract reallocation strategy from a tag's allocations.
    Allocation entries have shape: {name, type, active, data: {metricName, kpiCenterId,
    tagName, joinField, filters, keys}}.
    """
    allocations = tag.get("allocations") or []
    if not allocations:
        return {"strategy": "unknown", "metric_sources": [], "allocation_count": 0}

    metric_sources: list[dict] = []
    strategy = "unknown"

    for alloc in allocations:
        if not isinstance(alloc, dict):
            continue
        alloc_type = (alloc.get("type") or "").lower()
        data = alloc.get("data") or {}
        if alloc_type == "metric" or data.get("metricName") or data.get("kpiCenterId"):
            strategy = "metric"
            source: dict[str, Any] = {"name": alloc.get("name") or ""}
            if data.get("metricName"):
                source["metric"] = data["metricName"]
            if data.get("tagName"):
                source["dimension"] = data["tagName"]
            if data.get("joinField"):
                source["join_on"] = data["joinField"]
            if data.get("kpiCenterId"):
                source["kpi_center_id"] = data["kpiCenterId"]
            metric_sources.append(source)
        elif (
            alloc_type in ("percentage", "fixed")
            or alloc.get("targets")
            or alloc.get("participants")
        ):
            if strategy == "unknown":
                strategy = "percentage"

    return {
        "strategy": strategy,
        "metric_sources": metric_sources,
        "allocation_count": len(allocations),
    }


def _compute_summary(
    tags: list[dict],
    all_edges: dict[tuple[str, str], int],
    tag_id_to_type: dict[str, str],
) -> dict:
    """Compute account-wide summary stats."""
    connected = {n for e in all_edges for n in e}
    by_type: dict[str, int] = {}
    for tag in tags:
        t = tag_id_to_type.get(tag.get("id", ""), "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "total": len(tags),
        "with_dependencies": len(connected),
        "isolated": len(tags) - len(connected),
        "by_type": by_type,
    }


def _notable_tags(
    tags: list[dict],
    all_edges: dict[tuple[str, str], int],
    tag_map: dict[str, str],
    tag_id_to_type: dict[str, str],
) -> list[dict]:
    """Return top-5 tags by connectivity+rule score."""
    used_by_count: dict[str, int] = {}
    depends_on_count: dict[str, int] = {}
    for src, tgt in all_edges:
        depends_on_count[src] = depends_on_count.get(src, 0) + 1
        used_by_count[tgt] = used_by_count.get(tgt, 0) + 1

    scored: list[tuple[int, dict[str, Any]]] = []
    for tag in tags:
        tid = tag.get("id")
        if not tid or tid not in tag_map:
            continue
        used_by = used_by_count.get(tid, 0)
        depends_on = depends_on_count.get(tid, 0)
        rule_count = len(tag.get("rules") or [])
        score = (used_by + depends_on) * 2 + rule_count
        if score == 0:
            continue
        scored.append(
            (
                score,
                {
                    "name": tag_map[tid],
                    "type": tag_id_to_type.get(tid, "unknown"),
                    "rules": rule_count,
                    "used_by": used_by,
                    "depends_on": depends_on,
                },
            )
        )

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:5]]


def _tag_cost_dimensions(tag: dict) -> list[str]:
    """Extract unique non-virtual cost centers that this tag's rules filter on."""
    centers: set[str] = set()
    for rule in tag.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        filters = rule.get("filters") or {}
        if not isinstance(filters, dict):
            continue
        for obj in [filters] + (filters.get("OR") or []) + (filters.get("AND") or []):
            if isinstance(obj, dict):
                cc = obj.get("costCenter")
                if cc and cc != "virtualTag":
                    centers.add(cc)
    return sorted(centers)


def _dag_longest_path(edge_counts: dict[tuple[str, str], int]) -> int:
    """Longest path (number of edges) in the DAG via topological DP."""
    if not edge_counts:
        return 0
    forward: dict[str, list[str]] = {}
    in_deg: dict[str, int] = {}
    nodes: set[str] = set()
    for src, tgt in edge_counts:
        forward.setdefault(src, []).append(tgt)
        in_deg[tgt] = in_deg.get(tgt, 0) + 1
        nodes.update((src, tgt))
    for n in nodes:
        in_deg.setdefault(n, 0)
    dist: dict[str, int] = {n: 0 for n in nodes}
    queue = [n for n in nodes if in_deg[n] == 0]
    while queue:
        node = queue.pop()
        for nb in forward.get(node, []):
            dist[nb] = max(dist[nb], dist[node] + 1)
            in_deg[nb] -= 1
            if in_deg[nb] == 0:
                queue.append(nb)
    return max(dist.values()) if dist else 0


def _subgraph_analysis(
    subgraph_tags: list[dict],
    edge_counts: dict[tuple[str, str], int],
    tag_map: dict[str, str],
    tag_id_to_type: dict[str, str],
) -> dict[str, Any]:
    """Structural analysis of a subgraph: sources, sinks, depth, cost dimensions, type mix."""
    ids = {t["id"] for t in subgraph_tags if "id" in t}
    has_incoming = {tgt for _, tgt in edge_counts if tgt in ids}
    has_outgoing = {src for src, _ in edge_counts if src in ids}

    sources = sorted(tag_map[tid] for tid in ids if tid not in has_incoming and tid in tag_map)
    sinks = sorted(tag_map[tid] for tid in ids if tid not in has_outgoing and tid in tag_map)

    dimensions: set[str] = set()
    for tag in subgraph_tags:
        dimensions.update(_tag_cost_dimensions(tag))

    by_type: dict[str, int] = {}
    for tag in subgraph_tags:
        t = tag_id_to_type.get(tag.get("id", ""), "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "source_tags": sources,
        "output_tags": sinks,
        "chain_depth": _dag_longest_path(edge_counts),
        "by_type": by_type,
        "cost_dimensions": sorted(dimensions),
    }


_MAX_TAG_VALUES = 20


def _extract_tag_values(tag: dict) -> list[str]:
    """
    Extract the distinct string values this tag assigns costs to (from rule.to).
    Only meaningful for custom tags — relational tags reference other tag IDs there.
    Capped at _MAX_TAG_VALUES; returns [] when all rule.to entries are objects (relational).
    """
    values: set[str] = set()
    for rule in tag.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        to = rule.get("to")
        if isinstance(to, str) and to.strip():
            values.add(to.strip())
    return sorted(values)[:_MAX_TAG_VALUES]


def _focused_tag_detail(
    seed_ids: set[str],
    edge_counts: dict[tuple[str, str], int],
    tag_map: dict[str, str],
    tag_index: dict[str, dict],
    tag_id_to_type: dict[str, str],
) -> list[dict[str, Any]]:
    """Per-seed-tag breakdown: type, position, direct deps/consumers, cost dimensions."""
    direct_deps: dict[str, list[str]] = {}
    direct_consumers: dict[str, list[str]] = {}
    for src, tgt in edge_counts:
        direct_deps.setdefault(tgt, []).append(src)
        direct_consumers.setdefault(src, []).append(tgt)

    result = []
    for tid in seed_ids:
        if tid not in tag_map:
            continue
        tag = tag_index.get(tid, {})
        deps = sorted(tag_map[d] for d in direct_deps.get(tid, []) if d in tag_map)
        consumers = sorted(tag_map[c] for c in direct_consumers.get(tid, []) if c in tag_map)
        if deps and consumers:
            position = "bridge"
        elif consumers and not deps:
            position = "source"
        elif deps and not consumers:
            position = "output"
        else:
            position = "isolated"
        values = _extract_tag_values(tag)
        entry: dict[str, Any] = {
            "name": tag_map[tid],
            "type": tag_id_to_type.get(tid, "unknown"),
            "rules": len(tag.get("rules") or []),
            "position": position,
            "direct_dependencies": deps,
            "direct_consumers": consumers,
            "cost_dimensions": _tag_cost_dimensions(tag),
        }
        if values:
            entry["values"] = values
        result.append(entry)
    return result


def _tag_details_list(
    subgraph_tags: list[dict],
    edge_counts: dict[tuple[str, str], int],
    tag_map: dict[str, str],
    tag_id_to_type: dict[str, str],
) -> list[dict[str, Any]]:
    """Compact per-tag summary for every tag in a subgraph."""
    used_by: dict[str, int] = {}
    depends_on: dict[str, int] = {}
    for src, tgt in edge_counts:
        depends_on[src] = depends_on.get(src, 0) + 1
        used_by[tgt] = used_by.get(tgt, 0) + 1

    rows = []
    for tag in subgraph_tags:
        tid = tag.get("id")
        if not tid or tid not in tag_map:
            continue
        values = _extract_tag_values(tag)
        row: dict[str, Any] = {
            "name": tag_map[tid],
            "type": tag_id_to_type.get(tid, "unknown"),
            "rules": len(tag.get("rules") or []),
            "used_by": used_by.get(tid, 0),
            "depends_on": depends_on.get(tid, 0),
            "cost_dimensions": _tag_cost_dimensions(tag),
        }
        if values:
            row["values"] = values
        rows.append(row)
    rows.sort(key=lambda r: (-(r["used_by"] + r["depends_on"]), r["name"]))  # type: ignore[operator]
    return rows


def _discover_chains(
    tags: list[dict],
    all_edges: dict[tuple[str, str], int],
    tag_map: dict[str, str],
    tag_index: dict[str, dict],
    tag_id_to_type: dict[str, str],
) -> dict[str, Any]:
    """
    Organize the full account graph into independent allocation chains.

    Each chain is anchored by an "output" tag — a tag that nothing else depends on
    (the final cost allocation result). BFS backward collects its full dependency tree.

    Returns chains sorted largest-first, plus isolated tags (no edges at all).
    """
    if not all_edges:
        return {"chains": [], "isolated_tags": sorted(tag_map.values()), "total_chains": 0}

    all_src = {e[0] for e in all_edges}
    all_tgt = {e[1] for e in all_edges}

    # Output tags: consumed by something (appear as tgt) but depended on by nothing (never src)
    output_ids = all_tgt - all_src

    # Backward adjacency: consumer → its dependencies
    backward: dict[str, set[str]] = {}
    for src, tgt in all_edges:
        backward.setdefault(tgt, set()).add(src)

    chains: list[dict[str, Any]] = []
    for output_id in sorted(output_ids, key=lambda tid: tag_map.get(tid, "")):
        if output_id not in tag_map:
            continue
        # BFS backward to collect the full chain
        chain_ids: set[str] = set()
        queue = [output_id]
        while queue:
            node = queue.pop()
            if node in chain_ids:
                continue
            chain_ids.add(node)
            queue.extend(backward.get(node, set()) - chain_ids)

        chain_tags = [tag_index[tid] for tid in chain_ids if tid in tag_index]
        chain_edges = {
            e: c for e, c in all_edges.items() if e[0] in chain_ids and e[1] in chain_ids
        }

        by_type: dict[str, int] = {}
        for tag in chain_tags:
            t = tag_id_to_type.get(tag.get("id", ""), "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        dimensions: set[str] = set()
        for tag in chain_tags:
            dimensions.update(_tag_cost_dimensions(tag))

        # Values the output tag assigns (for custom outputs)
        output_values = _extract_tag_values(tag_index.get(output_id, {}))

        chains.append(
            {
                "output_tag": tag_map[output_id],
                "output_type": tag_id_to_type.get(output_id, "unknown"),
                "output_values": output_values,
                "chain_size": len(chain_ids),
                "chain_depth": _dag_longest_path(chain_edges),
                "by_type": by_type,
                "cost_dimensions": sorted(dimensions),
            }
        )

    chains.sort(key=lambda c: -c["chain_size"])

    all_connected = all_src | all_tgt
    isolated = sorted(tag_map[tid] for tid in tag_map if tid not in all_connected)

    return {
        "chains": chains,
        "isolated_tags": isolated,
        "total_chains": len(chains),
        "total_isolated": len(isolated),
    }


def _safe_mermaid_id(tag_id: str) -> str:
    """Return a Mermaid-safe node ID (alphanumeric + underscore only)."""
    return "".join(c if c.isalnum() else "_" for c in tag_id)


def _safe_mermaid_label(name: str) -> str:
    """Escape double-quotes inside Mermaid node labels."""
    return name.replace('"', "'")


def _build_virtual_tag_graph(
    tag_map: dict[str, str],
    edge_counts: dict[tuple[str, str], int],
    tag_id_to_type: dict[str, str] | None = None,
) -> tuple[str, bool]:
    """
    Build a styled Mermaid graph LR diagram from virtual tag relationships.
    Returns (mermaid_diagram, was_truncated).
    Caps at _MAX_GRAPH_NODES by keeping the highest-degree nodes.
    """
    if not edge_counts:
        return "", False

    degree: dict[str, int] = {}
    for src, tgt in edge_counts:
        degree[src] = degree.get(src, 0) + 1
        degree[tgt] = degree.get(tgt, 0) + 1

    truncated = False
    if len(degree) > _MAX_GRAPH_NODES:
        truncated = True
        top_nodes = {n for n, _ in sorted(degree.items(), key=lambda x: -x[1])[:_MAX_GRAPH_NODES]}
        edge_counts = {
            e: c for e, c in edge_counts.items() if e[0] in top_nodes and e[1] in top_nodes
        }

    if not edge_counts:
        return "", truncated

    all_src = {e[0] for e in edge_counts}
    all_tgt = {e[1] for e in edge_counts}
    node_ids = sorted(all_src | all_tgt)

    lines: list[str] = [
        "%%{init: {'theme': 'dark', 'flowchart': {'curve': 'basis', 'nodeSpacing': 45, 'rankSpacing': 90, 'diagramPadding': 20}}}%%",
        "graph LR",
        "  classDef tagReallocation fill:#f59f00,stroke:#d08700,stroke-width:2px,color:#000,font-weight:bold",
        "  classDef root fill:#0ca678,stroke:#087f5b,stroke-width:2px,color:#fff,font-weight:bold",
        "  classDef leaf fill:#1c7ed6,stroke:#1864ab,stroke-width:2px,color:#fff",
        "  classDef mid  fill:#25262b,stroke:#373a40,stroke-width:1px,color:#c1c2c5",
    ]

    # Reallocation tags get semantic color; all others use graph position (root/leaf/mid).
    for tid in node_ids:
        safe_id = _safe_mermaid_id(tid)
        label = _safe_mermaid_label(tag_map.get(tid, tid))
        tag_type = (tag_id_to_type or {}).get(tid, "unknown")
        if tag_type == "reallocation":
            css_class = "tagReallocation"
        elif tid in all_src and tid not in all_tgt:
            css_class = "root"
        elif tid in all_tgt and tid not in all_src:
            css_class = "leaf"
        else:
            css_class = "mid"
        lines.append(f'  {safe_id}("{label}"):::{css_class}')

    # Edges
    for src, tgt in edge_counts:
        lines.append(f"  {_safe_mermaid_id(src)} --> {_safe_mermaid_id(tgt)}")

    return "\n".join(lines), truncated


def _subgraph_ids(seed_ids: set[str], edge_counts: dict[tuple[str, str], int]) -> set[str]:
    """
    Return seed nodes plus all transitive ancestors and descendants in the directed graph.

    Edges are (dependency, consumer). We follow:
    - Forward (dependency → consumer): finds all tags that transitively depend on seeds
    - Backward (consumer → dependency): finds all tags seeds transitively depend on

    This keeps unrelated sibling chains out even when they share a common ancestor.
    """
    forward: dict[str, set[str]] = {}  # dependency → consumers
    backward: dict[str, set[str]] = {}  # consumer → dependencies
    for src, tgt in edge_counts:
        forward.setdefault(src, set()).add(tgt)
        backward.setdefault(tgt, set()).add(src)

    def bfs(starts: set[str], adj: dict[str, set[str]]) -> set[str]:
        visited: set[str] = set()
        queue = list(starts)
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(adj.get(node, set()) - visited)
        return visited

    return bfs(seed_ids, forward) | bfs(seed_ids, backward) | seed_ids


_MAX_LIVE_VALUES = 50


async def _fetch_virtual_tag_live_values(
    client: FinoutClient,
    seed_ids: set[str],
    tag_map: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Fetch actual values from the filters API for virtual tags.

    Returns dict mapping tag name to {values, truncated}.
    """
    results: dict[str, dict[str, Any]] = {}

    async def _fetch_one(tag_name: str) -> tuple[str, list[str]]:
        try:
            values = await client.get_filter_values(
                filter_key=tag_name,
                cost_center="virtualTag",
                limit=_MAX_LIVE_VALUES,
            )
            return tag_name, [str(v) for v in values]
        except Exception:
            return tag_name, []

    tag_names = [tag_map[tid] for tid in seed_ids if tid in tag_map]
    fetched = await asyncio.gather(*[_fetch_one(name) for name in tag_names])
    for name, values in fetched:
        if values:
            entry: dict[str, Any] = {"values": values}
            if len(values) >= _MAX_LIVE_VALUES:
                entry["truncated"] = True
            results[name] = entry

    return results


async def analyze_virtual_tags_impl(args: dict) -> dict:
    from ..server import get_client

    finout_client = get_client()

    tags = await finout_client.get_virtual_tags()
    if not tags:
        return {"message": "No virtual tags found for this account."}

    tag_map: dict[str, str] = {t["id"]: t["name"] for t in tags if "id" in t and "name" in t}
    tag_index: dict[str, dict] = {t["id"]: t for t in tags if "id" in t}
    tag_id_to_type: dict[str, str] = {
        t["id"]: _infer_tag_type(t, tag_map) for t in tags if "id" in t
    }

    # Build full edge graph
    all_edges: dict[tuple[str, str], int] = {}
    for tag in tags:
        tag_id = tag.get("id")
        if not tag_id or tag_id not in tag_map:
            continue
        for ref_id in _extract_virtual_tag_references(tag, tag_map):
            edge = (ref_id, tag_id)
            all_edges[edge] = all_edges.get(edge, 0) + 1

    # Filter to subgraph if tag_name provided
    tag_name = (args.get("tag_name") or "").strip().lower()
    focused = bool(tag_name)
    seed_ids: set[str] = set()

    if focused:
        seed_ids = {tid for tid, name in tag_map.items() if name.lower() == tag_name}
        if not seed_ids:
            seed_ids = {tid for tid, name in tag_map.items() if tag_name in name.lower()}
        if not seed_ids:
            return {"message": f"No virtual tag matching '{args['tag_name']}' found."}
        subgraph = _subgraph_ids(seed_ids, all_edges)
        edge_counts = {e: c for e, c in all_edges.items() if e[0] in subgraph and e[1] in subgraph}
        subgraph_tags = [tag_index[tid] for tid in subgraph if tid in tag_index]
        scope = f"Subgraph for '{args['tag_name']}': {len(subgraph)} tags, {len(edge_counts)} relationships."
    else:
        subgraph = set(tag_map.keys())
        edge_counts = all_edges
        subgraph_tags = tags
        scope = f"{len(tag_map)} total tags."

    result: dict[str, Any] = {
        "scope": scope,
        "account_summary": _compute_summary(tags, all_edges, tag_id_to_type),
    }

    if focused:
        focused_detail = _focused_tag_detail(
            seed_ids, edge_counts, tag_map, tag_index, tag_id_to_type
        )

        # Fetch live values from the filters API for seed tags
        live_values = await _fetch_virtual_tag_live_values(finout_client, seed_ids, tag_map)
        for entry in focused_detail:
            tag_name_key = entry["name"]
            if tag_name_key in live_values:
                entry["live_values"] = live_values[tag_name_key]

        result["focused_tag"] = focused_detail
        result["subgraph_analysis"] = _subgraph_analysis(
            subgraph_tags, edge_counts, tag_map, tag_id_to_type
        )
        result["tag_details"] = _tag_details_list(
            subgraph_tags, edge_counts, tag_map, tag_id_to_type
        )
    else:
        result["ecosystem"] = _discover_chains(tags, all_edges, tag_map, tag_index, tag_id_to_type)
        result["notable_tags"] = _notable_tags(tags, all_edges, tag_map, tag_id_to_type)

    diagram, truncated = _build_virtual_tag_graph(tag_map, edge_counts, tag_id_to_type)
    if diagram:
        result["mermaid_diagram"] = diagram
        if truncated:
            result["truncation_note"] = (
                f"Diagram capped at {_MAX_GRAPH_NODES} highest-connected nodes. "
                "Use tag_name to zoom into a specific subgraph."
            )
        if focused:
            result["_presentation_hint"] = (
                "The UI renders mermaid_diagram automatically — do NOT output it as text. "
                "Use focused_tag, subgraph_analysis, and tag_details to narrate: "
                "what the tag does, its position in the chain (source/bridge/output), "
                "what feeds into it, what it feeds into, the chain depth, "
                "and which underlying cost dimensions power the whole chain. "
                "If live_values is present, mention the actual values the tag produces "
                "in cost data (these come from the filters API, not rule config). "
                "Compare live_values with config values to highlight gaps or unexpected mappings."
            )
        else:
            result["_presentation_hint"] = (
                "The UI renders mermaid_diagram automatically — do NOT output it as text. "
                "Use ecosystem.chains to describe each allocation chain by name, size, depth, "
                "and what cost services it draws from. Mention isolated_tags count. "
                "Use notable_tags for the most connected/complex tags."
            )
    else:
        result["message"] = "No relationships found in this scope — tags are all independent."

    return result
