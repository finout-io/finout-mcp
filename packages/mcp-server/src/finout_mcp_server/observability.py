"""Optional Langfuse observability for MCP tool calls.

Provides a lightweight async context manager that wraps each tool invocation
in a Langfuse trace+span. Fully optional: no-op when langfuse is unavailable.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

_langfuse_instance: Any = None
_langfuse_checked = False


def _get_langfuse() -> Any:
    """Return a cached Langfuse client, or ``None`` if unavailable."""
    global _langfuse_instance, _langfuse_checked

    if _langfuse_checked:
        return _langfuse_instance

    _langfuse_checked = True

    if not os.getenv("LANGFUSE_SECRET_KEY"):
        return None

    try:
        from langfuse import Langfuse

        candidate = Langfuse()
        if hasattr(candidate, "start_as_current_span") and hasattr(
            candidate, "update_current_trace"
        ):
            _langfuse_instance = candidate
            logger.info("Langfuse observability enabled (host=%s)", os.getenv("LANGFUSE_HOST"))
        else:
            logger.warning(
                "Langfuse client missing v3 tracing API; disabling MCP observability. "
                "Install a newer langfuse package to re-enable observability."
            )
            _langfuse_instance = None
    except Exception:
        logger.debug("Langfuse not available", exc_info=True)
        _langfuse_instance = None

    return _langfuse_instance


@asynccontextmanager
async def trace_tool(name: str, args: dict[str, Any], *, user_id: str | None = None):
    """Wrap a tool call in a Langfuse trace and span."""
    lf = _get_langfuse()
    if lf is None:
        yield {}
        return

    ctx: dict[str, Any] = {}
    start = time.monotonic()

    with lf.start_as_current_span(name=f"tool:{name}", input=args) as span:
        if user_id:
            lf.update_current_trace(user_id=user_id)
        try:
            yield ctx
            duration_ms = (time.monotonic() - start) * 1000
            span.update(
                output=ctx.get("output", {"status": "success"}),
                metadata={"duration_ms": round(duration_ms, 2)},
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            span.update(
                output={"status": "error", "error": str(exc), "error_type": type(exc).__name__},
                level="ERROR",
                metadata={"duration_ms": round(duration_ms, 2)},
            )
            raise


def shutdown() -> None:
    """Flush pending Langfuse events. Safe to call when Langfuse is ``None``."""
    global _langfuse_instance, _langfuse_checked

    if _langfuse_instance is not None:
        try:
            _langfuse_instance.flush()
        except Exception:
            logger.debug("Langfuse flush failed", exc_info=True)

    _langfuse_instance = None
    _langfuse_checked = False
