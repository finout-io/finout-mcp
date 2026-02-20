"""
Boundary tests for public vs internal MCP behavior.
"""

import importlib
import json
import sys
import tomllib
from pathlib import Path

import pytest

server_module = importlib.import_module("src.finout_mcp_server.server")


class _DummyClient:
    """Minimal client stub for call_tool tests."""

    def __init__(self):
        self.internal_api_url = "https://app.finout.io"
        self.client_id = "test-client"
        self.secret_key = "test-secret"
        self._collect_calls = 0

    def collect_curls(self) -> list[str]:
        # call_tool clears first, then collects after execution
        self._collect_calls += 1
        if self._collect_calls == 1:
            return []
        return ["curl -X GET 'https://app.finout.io/cost-service/filters'"]


@pytest.mark.asyncio
async def test_public_mode_does_not_include_debug_curl(monkeypatch):
    client = _DummyClient()
    monkeypatch.setattr(server_module, "finout_client", client)
    monkeypatch.setattr(server_module, "runtime_mode", server_module.MCPMode.PUBLIC.value)

    async def _fake_query_costs(_: dict) -> dict:
        return {"ok": True}

    monkeypatch.setattr(server_module, "query_costs_impl", _fake_query_costs)

    response = await server_module.call_tool("query_costs", {"time_period": "last_7_days"})
    payload = json.loads(response[0].text)
    assert "_debug_curl" not in payload


@pytest.mark.asyncio
async def test_internal_mode_includes_debug_curl(monkeypatch):
    client = _DummyClient()
    monkeypatch.setattr(server_module, "finout_client", client)
    monkeypatch.setattr(
        server_module, "runtime_mode", server_module.MCPMode.VECTIQOR_INTERNAL.value
    )

    async def _fake_query_costs(_: dict) -> dict:
        return {"ok": True}

    monkeypatch.setattr(server_module, "query_costs_impl", _fake_query_costs)

    response = await server_module.call_tool("query_costs", {"time_period": "last_7_days"})
    payload = json.loads(response[0].text)
    assert "_debug_curl" in payload


@pytest.mark.asyncio
async def test_list_tools_public_hides_internal_only_tools(monkeypatch):
    monkeypatch.setattr(server_module, "runtime_mode", server_module.MCPMode.PUBLIC.value)
    tools = await server_module.list_tools()
    names = {tool.name for tool in tools}

    assert "discover_context" not in names
    assert "get_account_context" not in names
    assert "debug_filters" not in names
    assert "query_costs" in names
    assert "get_waste_recommendations" in names


@pytest.mark.asyncio
async def test_list_tools_internal_hides_public_key_secret_tools(monkeypatch):
    monkeypatch.setattr(
        server_module, "runtime_mode", server_module.MCPMode.VECTIQOR_INTERNAL.value
    )
    tools = await server_module.list_tools()
    names = {tool.name for tool in tools}

    assert "get_waste_recommendations" not in names
    assert "get_anomalies" not in names
    assert "discover_context" in names
    assert "get_account_context" in names


@pytest.mark.asyncio
async def test_call_tool_blocks_internal_only_tool_in_public_mode(monkeypatch):
    client = _DummyClient()
    monkeypatch.setattr(server_module, "finout_client", client)
    monkeypatch.setattr(server_module, "runtime_mode", server_module.MCPMode.PUBLIC.value)

    response = await server_module.call_tool("discover_context", {"query": "foo"})
    assert "Tool not available in this deployment mode" in response[0].text


@pytest.mark.asyncio
async def test_call_tool_blocks_key_secret_tool_in_internal_mode(monkeypatch):
    client = _DummyClient()
    monkeypatch.setattr(server_module, "finout_client", client)
    monkeypatch.setattr(
        server_module, "runtime_mode", server_module.MCPMode.VECTIQOR_INTERNAL.value
    )

    response = await server_module.call_tool("get_waste_recommendations", {})
    assert "Tool not available in this deployment mode" in response[0].text


def test_public_entrypoint_is_fixed_public_mode(monkeypatch):
    called: list[server_module.MCPMode] = []
    monkeypatch.setattr(server_module, "_main_with_mode", lambda mode: called.append(mode))
    monkeypatch.setattr(sys, "argv", ["finout-mcp"])

    server_module.main()
    assert called == [server_module.MCPMode.PUBLIC]


def test_public_help_does_not_initialize_runtime(monkeypatch, capsys):
    called: list[server_module.MCPMode] = []
    monkeypatch.setattr(server_module, "_main_with_mode", lambda mode: called.append(mode))
    monkeypatch.setattr(sys, "argv", ["finout-mcp", "--help"])

    server_module.main()
    out = capsys.readouterr().out
    assert "finout-mcp - Finout public MCP server" in out
    assert called == []


def test_public_package_exposes_only_public_script():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    scripts = data["project"]["scripts"]

    assert "finout-mcp" in scripts
    assert "vectiqor-mcp-internal" not in scripts


def test_internal_mode_reads_finout_account_id_env(monkeypatch):
    monkeypatch.setenv("FINOUT_ACCOUNT_ID", "11111111-1111-1111-1111-111111111111")

    client = server_module._init_client_for_mode(server_module.MCPMode.VECTIQOR_INTERNAL)
    try:
        assert client.account_id == "11111111-1111-1111-1111-111111111111"
    finally:
        import asyncio

        asyncio.run(client.close())
