"""
Hosted public MCP service (Streamable HTTP transport).

This service runs the same MCP tool core in fixed PUBLIC mode and is intentionally
separate from VECTIQOR.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import anyio
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

import finout_mcp_server.server as server_module

from .server import MCPMode, _init_client_for_mode, server


@asynccontextmanager
async def lifespan(app: Starlette):
    """Initialize MCP core in fixed public mode and expose it over HTTP transport."""
    server_module.runtime_mode = MCPMode.PUBLIC.value
    server_module.finout_client = _init_client_for_mode(MCPMode.PUBLIC)

    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    app.state.transport = transport

    try:
        async with transport.connect() as (read_stream, write_stream):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(
                    server.run,
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
                yield
                task_group.cancel_scope.cancel()
    finally:
        if server_module.finout_client:
            await server_module.finout_client.close()


async def health(_: Request) -> JSONResponse:
    """Health check endpoint for hosted deployment."""
    return JSONResponse(
        {
            "status": "healthy",
            "mode": "public",
            "transport": "streamable-http",
        }
    )


async def mcp_transport(scope, receive, send) -> None:
    """ASGI mount for Streamable HTTP MCP transport."""
    await scope["app"].state.transport.handle_request(scope, receive, send)


app = Starlette(
    routes=[
        Route("/health", endpoint=health, methods=["GET"]),
        Mount("/mcp", app=mcp_transport),
    ],
    lifespan=lifespan,
)


def main() -> None:
    """Run hosted public MCP service."""
    import uvicorn

    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8080"))
    uvicorn.run("finout_mcp_server.hosted_public:app", host=host, port=port, lifespan="on")
