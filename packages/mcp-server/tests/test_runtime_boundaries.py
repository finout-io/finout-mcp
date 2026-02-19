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
