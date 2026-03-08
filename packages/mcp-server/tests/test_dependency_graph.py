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
    ):
        self._virtual_tags = virtual_tags or []
        self._views = views or []
        self._dashboards = dashboards or []

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
        return []

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
