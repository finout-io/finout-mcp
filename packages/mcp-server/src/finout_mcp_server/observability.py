"""Optional Langfuse observability for MCP tool calls.

Provides a lightweight async context manager that wraps each tool invocation
in a Langfuse trace+span. Fully optional: no-op when langfuse is unavailable.
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

_langfuse_instance: Any = None
_langfuse_checked = False
_trace_context_var: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "langfuse_trace_ctx", default=None
)


def _env(name: str) -> str | None:
    return os.getenv(f"LANGFUSE_MCP_{name}") or os.getenv(f"LANGFUSE_{name}")


def set_trace_context(context: dict[str, Any]) -> contextvars.Token[dict[str, Any] | None]:
    """Attach per-request Langfuse correlation context for direct MCP requests."""
    return _trace_context_var.set(context)


def reset_trace_context(token: contextvars.Token[dict[str, Any] | None]) -> None:
    _trace_context_var.reset(token)


def _get_langfuse() -> Any:
    """Return a cached Langfuse client, or ``None`` if unavailable."""
    global _langfuse_instance, _langfuse_checked

    if _langfuse_checked:
        return _langfuse_instance

    _langfuse_checked = True

    public_key = _env("PUBLIC_KEY")
    secret_key = _env("SECRET_KEY")
    if not public_key or not secret_key:
        logger.debug(
            "Langfuse observability disabled: missing credentials",
            extra={
                "has_public_key": bool(public_key),
                "has_secret_key": bool(secret_key),
            },
        )
        return None

    try:
        from langfuse import Langfuse

        candidate = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=_env("HOST"),
        )
        if hasattr(candidate, "start_as_current_span") and hasattr(
            candidate, "update_current_trace"
        ):
            _langfuse_instance = candidate
            logger.info("Langfuse MCP observability enabled (host=%s)", _env("HOST"))
        else:
            logger.warning(
                "Langfuse client missing required tracing API; disabling MCP observability."
            )
            _langfuse_instance = None
    except Exception:
        logger.debug("Langfuse not available", exc_info=True)
        _langfuse_instance = None

    return _langfuse_instance


@asynccontextmanager
async def trace_tool(name: str, args: dict[str, Any], *, user_id: str | None = None):
    """Wrap a tool call in a Langfuse trace and span."""
    from .server import MCPMode, get_runtime_mode

    active_mode = get_runtime_mode()
    trace_context = dict(_trace_context_var.get() or {})
    origin = str(trace_context.get("origin") or "direct_mcp")

    # Billy-owned conversations should be traced from the Billy process, not
    # as separate top-level MCP traces.
    if active_mode == MCPMode.BILLY_INTERNAL.value or origin == "billy":
        yield {}
        return

    lf = _get_langfuse()
    if lf is None:
        yield {}
        return

    ctx: dict[str, Any] = {}
    start = time.monotonic()

    with lf.start_as_current_span(name=f"tool:{name}", input=args) as span:
        tags = [f"origin:{origin}", f"mode:{active_mode or 'unknown'}", "channel:mcp"]
        extra_tags = trace_context.get("tags")
        if isinstance(extra_tags, list):
            tags.extend(str(tag) for tag in extra_tags if tag)

        trace_metadata = {
            key: value
            for key, value in trace_context.items()
            if key not in {"user_id", "session_id", "tags"}
        }
        lf.update_current_trace(
            user_id=trace_context.get("user_id") or user_id,
            session_id=trace_context.get("session_id"),
            tags=tags,
            metadata=trace_metadata,
        )
        try:
            yield ctx
            duration_ms = (time.monotonic() - start) * 1000
            span.update(
                output=ctx.get("output", {"status": "success"}),
                metadata={
                    "duration_ms": round(duration_ms, 2),
                    "origin": origin,
                    "runtime_mode": active_mode,
                    "request_id": trace_context.get("request_id"),
                    "account_id": trace_context.get("account_id"),
                    "client_id": trace_context.get("client_id"),
                },
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            span.update(
                output={"status": "error", "error": str(exc), "error_type": type(exc).__name__},
                level="ERROR",
                metadata={
                    "duration_ms": round(duration_ms, 2),
                    "origin": origin,
                    "runtime_mode": active_mode,
                    "request_id": trace_context.get("request_id"),
                    "account_id": trace_context.get("account_id"),
                    "client_id": trace_context.get("client_id"),
                },
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
