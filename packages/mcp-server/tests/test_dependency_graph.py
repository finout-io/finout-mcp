"""Tests for dependency_graph usage diagram generation."""

import importlib

import pytest

dep_mod = importlib.import_module("src.finout_mcp_server.tools.dependency_graph")
server_module = importlib.import_module("src.finout_mcp_server.server")


class _FakeClient:
    """Stub returning canned entities for dependency_graph tests."""

    def __init__(
        self,
        virtual_tags: list | None = None,
        views: list | None = None,
        dashboards: list | None = None,
        financial_plans: list | None = None,
    ):
        self._virtual_tags = virtual_tags or []
        self._views = views or []
        self._dashboards = dashboards or []
        self._financial_plans = financial_plans or []

    async def get_virtual_tags(self) -> list:
        return self._virtual_tags

    async def get_views(self) -> list:
        return self._views

    async def get_dashboards(self) -> list:
        return self._dashboards

    async def get_widgets(self) -> list:
        return []

    async def get_data_explorers(self) -> list:
        return []

    async def get_financial_plans(self) -> list:
        return self._financial_plans

    async def get_financial_plans_raw(self) -> list:
        return self._financial_plans

    async def get_alerts(self) -> list:
        return []


# --- Unit tests for _build_summary_diagram ---


def test_build_summary_diagram_groups_by_type():
    usages = [
        {"entity_name": "View A", "entity_type": "view", "contexts": ["filter"]},
        {"entity_name": "View B", "entity_type": "view", "contexts": ["groupBy"]},
        {"entity_name": "Dashboard X", "entity_type": "dashboard", "contexts": ["filter"]},
    ]
    diagram = dep_mod._build_summary_diagram("Production", "virtual_tag", usages)
    assert "graph LR" in diagram
    assert 'TARGET["Production<br/><i>virtual_tag</i>"]' in diagram
    # Should contain counts, not individual names
    assert "views (2)" in diagram
    assert "dashboard (1)" in diagram
    assert "View A" not in diagram
    assert "View B" not in diagram
    assert "Dashboard X" not in diagram
    assert "style TARGET" in diagram


def test_build_summary_diagram_aggregates_contexts():
    usages = [
        {"entity_name": "View A", "entity_type": "view", "contexts": ["filter"]},
        {"entity_name": "View B", "entity_type": "view", "contexts": ["groupBy"]},
    ]
    diagram = dep_mod._build_summary_diagram("Tag", "virtual_tag", usages)
    # Both contexts should appear on the single edge
    assert "filter" in diagram
    assert "groupBy" in diagram


# --- Unit tests for _build_detail_diagram ---


def test_build_detail_diagram_has_subgraphs():
    usages = [
        {"entity_name": "View A", "entity_type": "view", "contexts": ["filter"]},
        {"entity_name": "View B", "entity_type": "view", "contexts": ["groupBy"]},
        {"entity_name": "Dashboard X", "entity_type": "dashboard", "contexts": ["filter"]},
    ]
    diagram = dep_mod._build_detail_diagram("Production", "virtual_tag", usages)
    assert "graph LR" in diagram
    assert 'TARGET["Production<br/><i>virtual_tag</i>"]' in diagram
    assert "subgraph" in diagram
    assert "View A" in diagram
    assert "View B" in diagram
    assert "Dashboard X" in diagram
    assert "style TARGET" in diagram


def test_build_detail_diagram_escapes_quotes():
    usages = [
        {"entity_name": 'A "quoted" name', "entity_type": "view", "contexts": ["filter"]},
    ]
    diagram = dep_mod._build_detail_diagram("Target", "virtual_tag", usages)
    assert "A 'quoted' name" in diagram
    assert '"quoted"' not in diagram


# --- Unit tests for _build_usage_diagrams ---


def test_build_usage_diagrams_returns_both():
    usages = [
        {"entity_name": "EC2 Dashboard", "entity_type": "dashboard", "contexts": ["filter"]},
        {"entity_name": "Cost View", "entity_type": "view", "contexts": ["groupBy"]},
    ]
    result = dep_mod._build_usage_diagrams("Production", "virtual_tag", usages)
    assert "summary" in result
    assert "detail" in result
    assert "graph LR" in result["summary"]
    assert "graph LR" in result["detail"]
    # Summary should not have individual names
    assert "EC2 Dashboard" not in result["summary"]
    # Detail should have individual names
    assert "EC2 Dashboard" in result["detail"]
    assert "Cost View" in result["detail"]
    assert "subgraph" in result["detail"]


# --- Integration tests via get_object_usages_impl / check_delete_safety_impl ---


@pytest.mark.asyncio
async def test_get_object_usages_includes_mermaid(monkeypatch):
    client = _FakeClient(
        virtual_tags=[{"_id": "vt1", "name": "Production"}],
        views=[{"_id": "v1", "name": "Cost View", "filters": [{"value": "vt1"}]}],
    )
    monkeypatch.setattr(server_module, "finout_client", client)

    result = await dep_mod.get_object_usages_impl({"name": "Production"})
    assert result["found"] is True
    assert result["usage_count"] == 1
    assert "mermaid_diagram" in result
    assert "mermaid_diagram_detail" in result
    assert "graph LR" in result["mermaid_diagram"]
    assert "TARGET" in result["mermaid_diagram"]
    assert "subgraph" in result["mermaid_diagram_detail"]


@pytest.mark.asyncio
async def test_get_object_usages_no_mermaid_when_no_usages(monkeypatch):
    client = _FakeClient(
        virtual_tags=[{"_id": "vt1", "name": "Production"}],
    )
    monkeypatch.setattr(server_module, "finout_client", client)

    result = await dep_mod.get_object_usages_impl({"name": "Production"})
    assert result["found"] is True
    assert result["usage_count"] == 0
    assert "mermaid_diagram" not in result
    assert "mermaid_diagram_detail" not in result


@pytest.mark.asyncio
async def test_get_object_usages_no_mermaid_when_not_found(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(server_module, "finout_client", client)

    result = await dep_mod.get_object_usages_impl({"name": "NonExistent"})
    assert result["found"] is False
    assert "mermaid_diagram" not in result
    assert "mermaid_diagram_detail" not in result


@pytest.mark.asyncio
async def test_check_delete_safety_includes_mermaid(monkeypatch):
    client = _FakeClient(
        virtual_tags=[{"_id": "vt1", "name": "Production"}],
        dashboards=[{"_id": "d1", "name": "Main Dashboard", "groupBy": "vt1"}],
    )
    monkeypatch.setattr(server_module, "finout_client", client)

    result = await dep_mod.check_delete_safety_impl({"name": "Production"})
    assert result["found"] is True
    assert result["safe_to_delete"] is False
    assert "mermaid_diagram" in result
    assert "mermaid_diagram_detail" in result
    assert "Main Dashboard" in result["mermaid_diagram_detail"]


@pytest.mark.asyncio
async def test_check_delete_safety_no_mermaid_when_safe(monkeypatch):
    client = _FakeClient(
        virtual_tags=[{"_id": "vt1", "name": "Production"}],
    )
    monkeypatch.setattr(server_module, "finout_client", client)

    result = await dep_mod.check_delete_safety_impl({"name": "Production"})
    assert result["found"] is True
    assert result["safe_to_delete"] is True
    assert "mermaid_diagram" not in result
    assert "mermaid_diagram_detail" not in result


# --- Unit tests for structured VT dependency detection ---


def test_create_vt_resolver_direct():
    vts = [
        {"_id": "vt-a", "name": "A", "filters": [{"costCenter": "virtualTag", "key": "vt-b"}]},
        {"_id": "vt-b", "name": "B"},
    ]
    resolver = dep_mod._create_vt_resolver(vts)
    direct = resolver["get_direct"]("vt-a")
    assert any(tid == "vt-b" for tid, _ in direct)


def test_create_vt_resolver_transitive():
    vts = [
        {"_id": "vt-a", "name": "A", "filters": [{"costCenter": "virtualTag", "key": "vt-b"}]},
        {"_id": "vt-b", "name": "B", "filters": [{"costCenter": "virtualTag", "key": "vt-c"}]},
        {"_id": "vt-c", "name": "C"},
    ]
    resolver = dep_mod._create_vt_resolver(vts)
    transitive = resolver["get_transitive"]("vt-a")
    transitive_ids = [tid for tid, _ in transitive]
    assert "vt-b" in transitive_ids
    assert "vt-c" in transitive_ids


def test_create_vt_resolver_cycle_safe():
    # Circular dependency must not infinite-loop
    vts = [
        {"_id": "vt-a", "name": "A", "filters": [{"costCenter": "virtualTag", "key": "vt-b"}]},
        {"_id": "vt-b", "name": "B", "filters": [{"costCenter": "virtualTag", "key": "vt-a"}]},
    ]
    resolver = dep_mod._create_vt_resolver(vts)
    result = resolver["get_transitive"]("vt-a")
    # Should return vt-b (or empty) but not loop
    ids = [tid for tid, _ in result]
    assert "vt-a" not in ids  # no self-reference in result


def test_collect_fp_vt_refs_filter_pattern():
    refs: dict = {}
    known = {"vt-1"}
    plan_obj = {"filters": [{"costCenter": "virtualTag", "key": "vt-1"}]}
    dep_mod._collect_fp_vt_refs(plan_obj, "", known, refs)
    assert any(r["virtualTagId"] == "vt-1" and r["context"] == "filter" for r in refs.values())


def test_collect_fp_vt_refs_to_key_pattern():
    refs: dict = {}
    known = {"vt-2"}
    plan_obj = {"column": {"to": {"key": "vt-2"}}}
    dep_mod._collect_fp_vt_refs(plan_obj, "", known, refs)
    assert any(r["virtualTagId"] == "vt-2" and r["context"] == "column" for r in refs.values())


def test_collect_fp_vt_refs_default_value_key():
    refs: dict = {}
    known = {"vt-3"}
    plan_obj = {"field": {"default": {"value": {"key": "vt-3"}}}}
    dep_mod._collect_fp_vt_refs(plan_obj, "", known, refs)
    assert any(r["virtualTagId"] == "vt-3" for r in refs.values())


# --- Unit tests for _extract_fp_facts ---


def _empty_resolver() -> dict:
    return {"get_direct": lambda _: [], "get_transitive": lambda _: []}


def test_extract_fp_facts_direct_vt():
    plan = {"id": "fp-1", "name": "Plan", "filters": [{"costCenter": "virtualTag", "key": "vt-1"}]}
    facts = dep_mod._extract_fp_facts(plan, {"vt-1"}, {}, _empty_resolver())
    assert any(r["virtualTagId"] == "vt-1" for r in facts["direct_vt_refs"])
    assert any(r["virtualTagId"] == "vt-1" for r in facts["all_vt_refs"])
    assert facts["sync_status"] == "standalone"
    assert facts["origin_id"] is None


def test_extract_fp_facts_origin_synced():
    common_filters = [{"costCenter": "virtualTag", "key": "vt-1"}]
    plan = {"id": "fp-child", "name": "Child", "originId": "fp-origin", "filters": common_filters}
    origin = {"id": "fp-origin", "name": "Origin", "filters": common_filters}
    facts = dep_mod._extract_fp_facts(plan, {"vt-1"}, {"fp-origin": origin}, _empty_resolver())
    assert facts["origin_id"] == "fp-origin"
    assert facts["sync_status"] == "synced"
    assert any(r["targetId"] == "fp-origin" for r in facts["plan_refs"])


def test_extract_fp_facts_origin_out_of_sync():
    plan = {
        "id": "fp-child",
        "name": "Child",
        "originId": "fp-origin",
        "filters": [{"costCenter": "virtualTag", "key": "vt-1"}],
    }
    origin = {
        "id": "fp-origin",
        "name": "Origin",
        "filters": [{"costCenter": "virtualTag", "key": "vt-2"}],
    }
    facts = dep_mod._extract_fp_facts(
        plan, {"vt-1", "vt-2"}, {"fp-origin": origin}, _empty_resolver()
    )
    assert facts["sync_status"] == "outOfSync"


def test_extract_fp_facts_origin_missing():
    plan = {"id": "fp-1", "name": "Plan", "originId": "fp-gone"}
    facts = dep_mod._extract_fp_facts(plan, set(), {}, _empty_resolver())
    assert facts["sync_status"] == "originMissing"


# --- Integration: financial plan structured detection via _find_usages ---


def test_find_usages_fp_structured_filter():
    vts = [{"_id": "vt-1", "name": "Env Tag"}]
    fps = [
        {
            "_id": "fp-1",
            "name": "Q1 Budget",
            "filters": [{"costCenter": "virtualTag", "key": "vt-1"}],
        }
    ]
    all_entities = {"virtual_tag": vts, "financial_plan": fps}
    usages = dep_mod._find_usages("vt-1", all_entities)
    assert len(usages) == 1
    u = usages[0]
    assert u["entity_type"] == "financial_plan"
    assert u["match_method"] == "structured"
    assert u["dependency_kind"] == "direct"
    assert "filter" in u["contexts"]


def test_find_usages_fp_transitive():
    vts = [
        {"_id": "vt-a", "name": "Tag A", "filters": [{"costCenter": "virtualTag", "key": "vt-b"}]},
        {"_id": "vt-b", "name": "Tag B"},
    ]
    fps = [
        {
            "_id": "fp-1",
            "name": "Plan",
            "filters": [{"costCenter": "virtualTag", "key": "vt-a"}],
        }
    ]
    all_entities = {"virtual_tag": vts, "financial_plan": fps}
    # vt-b should appear as a transitive dependency of the plan
    usages = dep_mod._find_usages("vt-b", all_entities)
    assert any(
        u["entity_type"] == "financial_plan" and u["dependency_kind"] == "transitive"
        for u in usages
    )


def test_find_usages_fp_origin_reference():
    fps = [
        {"_id": "fp-origin", "name": "Origin Plan"},
        {"_id": "fp-child", "name": "Child Plan", "originId": "fp-origin"},
    ]
    all_entities = {"virtual_tag": [], "financial_plan": fps}
    usages = dep_mod._find_usages("fp-origin", all_entities)
    assert any(
        u["entity_type"] == "financial_plan" and u["dependency_kind"] == "origin" for u in usages
    )


# --- Unit tests for _merge_refs ---


def test_merge_refs_structured_wins_over_text():
    structured = [
        {
            "entity_id": "e1",
            "entity_type": "financial_plan",
            "entity_name": "Plan",
            "contexts": ["filter"],
            "match_paths": ["filters[0].key"],
            "match_method": "structured",
            "dependency_kind": "direct",
            "reference_count": 1,
        }
    ]
    text = [
        {
            "entity_id": "e1",
            "entity_type": "financial_plan",
            "entity_name": "Plan",
            "contexts": ["column"],
            "match_paths": ["somewhere"],
            "match_method": "textSearch",
            "reference_count": 2,
        }
    ]
    merged = dep_mod._merge_refs(structured, text)
    assert len(merged) == 1
    assert merged[0]["match_method"] == "structured"
    assert set(merged[0]["contexts"]) == {"filter", "column"}


@pytest.mark.asyncio
async def test_get_object_usages_fp_structured(monkeypatch):
    client = _FakeClient(
        virtual_tags=[{"_id": "vt-1", "name": "Env"}],
        financial_plans=[
            {
                "_id": "fp-1",
                "name": "Annual Budget",
                "filters": [{"costCenter": "virtualTag", "key": "vt-1"}],
            }
        ],
    )
    monkeypatch.setattr(server_module, "finout_client", client)
    result = await dep_mod.get_object_usages_impl({"name": "Env"})
    assert result["found"] is True
    assert result["usage_count"] >= 1
    u = next(u for u in result["usages"] if u["entity_type"] == "financial_plan")
    assert u["match_method"] == "structured"
