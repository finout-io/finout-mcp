"""Tests for the observability module (Langfuse integration)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from finout_mcp_server import observability


@pytest.fixture(autouse=True)
def _reset_langfuse_state():
    """Reset module-level caching between tests."""
    observability._langfuse_instance = None
    observability._langfuse_checked = False
    yield
    observability._langfuse_instance = None
    observability._langfuse_checked = False


def _make_mock_langfuse():
    """Create a mock Langfuse client with the tracing API expected by Langfuse 4."""
    mock_span = MagicMock()
    mock_lf = MagicMock()

    @contextmanager
    def fake_start_as_current_span(**kwargs):
        yield mock_span

    mock_lf.start_as_current_span = MagicMock(side_effect=fake_start_as_current_span)
    return mock_lf, mock_span


def test_get_langfuse_returns_none_without_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert observability._get_langfuse() is None


def test_get_langfuse_caches_result(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    observability._get_langfuse()
    assert observability._langfuse_checked is True
    observability._get_langfuse()
    assert observability._langfuse_checked is True


def test_get_langfuse_creates_instance_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    mock_lf = MagicMock()

    with patch("finout_mcp_server.observability.Langfuse", mock_lf, create=True):
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf)}):
            observability._langfuse_checked = False
            observability._langfuse_instance = None
            result = observability._get_langfuse()

    assert result is not None


def test_get_langfuse_returns_none_on_import_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    with patch.dict("sys.modules", {"langfuse": None}):
        result = observability._get_langfuse()

    assert result is None
    assert observability._langfuse_checked is True


@pytest.mark.asyncio
async def test_trace_tool_noop_without_langfuse(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    async with observability.trace_tool("query_costs", {"period": "last_7_days"}) as ctx:
        ctx["output"] = {"status": "success"}

    assert ctx.get("output") == {"status": "success"}


@pytest.mark.asyncio
async def test_trace_tool_creates_span_when_langfuse_available():
    mock_lf, mock_span = _make_mock_langfuse()
    observability._langfuse_instance = mock_lf
    observability._langfuse_checked = True

    async with observability.trace_tool("search_filters", {"query": "ec2"}) as ctx:
        ctx["output"] = {"status": "success", "count": 5}

    mock_lf.start_as_current_span.assert_called_once_with(
        name="tool:search_filters", input={"query": "ec2"}
    )
    mock_lf.update_current_trace.assert_called_once()
    update_trace_kwargs = mock_lf.update_current_trace.call_args.kwargs
    assert update_trace_kwargs["tags"] == ["origin:direct_mcp", "mode:unknown", "channel:mcp"]
    assert update_trace_kwargs["metadata"] == {}
    mock_span.update.assert_called_once()
    update_kwargs = mock_span.update.call_args[1]
    assert update_kwargs["output"] == {"status": "success", "count": 5}
    assert "duration_ms" in update_kwargs["metadata"]


@pytest.mark.asyncio
async def test_trace_tool_sets_user_id_when_provided():
    mock_lf, _ = _make_mock_langfuse()
    observability._langfuse_instance = mock_lf
    observability._langfuse_checked = True

    async with observability.trace_tool(
        "query_costs", {"period": "last_7_days"}, user_id="acct-123"
    ) as ctx:
        ctx["output"] = {"status": "success"}

    mock_lf.update_current_trace.assert_called_once()
    update_trace_kwargs = mock_lf.update_current_trace.call_args.kwargs
    assert update_trace_kwargs["user_id"] == "acct-123"
    assert update_trace_kwargs["tags"] == ["origin:direct_mcp", "mode:unknown", "channel:mcp"]


@pytest.mark.asyncio
async def test_trace_tool_noop_for_billy_internal():
    mock_lf, _ = _make_mock_langfuse()
    observability._langfuse_instance = mock_lf
    observability._langfuse_checked = True

    with patch("finout_mcp_server.server.get_runtime_mode", return_value="billy-internal"):
        async with observability.trace_tool("query_costs", {"period": "last_7_days"}) as ctx:
            ctx["output"] = {"status": "success"}

    mock_lf.start_as_current_span.assert_not_called()
    mock_lf.update_current_trace.assert_not_called()


@pytest.mark.asyncio
async def test_trace_tool_records_error_on_exception():
    mock_lf, mock_span = _make_mock_langfuse()
    observability._langfuse_instance = mock_lf
    observability._langfuse_checked = True

    with pytest.raises(ValueError, match="bad input"):
        async with observability.trace_tool("query_costs", {"bad": True}):
            raise ValueError("bad input")

    update_kwargs = mock_span.update.call_args[1]
    assert update_kwargs["output"]["status"] == "error"
    assert update_kwargs["output"]["error"] == "bad input"
    assert update_kwargs["output"]["error_type"] == "ValueError"
    assert update_kwargs["level"] == "ERROR"


def test_shutdown_flushes_langfuse():
    mock_lf = MagicMock()
    observability._langfuse_instance = mock_lf
    observability._langfuse_checked = True

    observability.shutdown()

    mock_lf.flush.assert_called_once()
    assert observability._langfuse_instance is None
    assert observability._langfuse_checked is False
