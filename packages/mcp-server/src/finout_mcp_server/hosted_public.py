"""
Hosted public MCP service (Streamable HTTP transport).

This service runs the same MCP tool core in fixed PUBLIC mode and is intentionally
separate from VECTIQOR.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import finout_mcp_server.server as server_module

from .finout_client import FinoutClient, InternalAuthMode
from .server import MCPMode, server


@asynccontextmanager
async def lifespan(app: Starlette):
    """Initialize MCP core in fixed public mode and expose it over HTTP transport."""
    server_module.runtime_mode = MCPMode.PUBLIC.value
    # Hosted public mode receives Finout credentials per HTTP call.
    server_module.finout_client = None

    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    app.state.transport = transport
    app.state.client_lock = anyio.Lock()
    app.state.client_fingerprint = None

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


def _extract_public_auth_from_scope(scope: Any) -> tuple[str, str, str]:
    """Extract required auth headers from ASGI scope."""
    headers = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
    }
    client_id = headers.get("x-finout-client-id", "").strip()
    secret_key = headers.get("x-finout-secret-key", "").strip()
    api_url = headers.get("x-finout-api-url", "").strip() or "https://app.finout.io"

    if not client_id or not secret_key:
        raise ValueError(
            "Missing credentials. Provide x-finout-client-id and x-finout-secret-key headers."
        )
    return client_id, secret_key, api_url


async def mcp_asgi(scope, receive, send) -> None:
    """ASGI mount for Streamable HTTP MCP transport."""
    if scope.get("method") == "POST":
        try:
            client_id, secret_key, api_url = _extract_public_auth_from_scope(scope)
        except ValueError as exc:
            response = JSONResponse({"error": str(exc)}, status_code=401)
            await response(scope, receive, send)
            return

        fingerprint = (client_id, secret_key, api_url)
        async with scope["app"].state.client_lock:
            if scope["app"].state.client_fingerprint != fingerprint:
                if server_module.finout_client:
                    await server_module.finout_client.close()
                server_module.runtime_mode = MCPMode.PUBLIC.value
                server_module.finout_client = FinoutClient(
                    client_id=client_id,
                    secret_key=secret_key,
                    internal_api_url=api_url,
                    internal_auth_mode=InternalAuthMode.KEY_SECRET,
                    allow_missing_credentials=False,
                )
                scope["app"].state.client_fingerprint = fingerprint
            await scope["app"].state.transport.handle_request(scope, receive, send)
        return

    await scope["app"].state.transport.handle_request(scope, receive, send)


async def _invoke_asgi_as_response(request: Request) -> Response:
    """Invoke ASGI MCP transport and adapt output to a Starlette Response."""
    events: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        events.append(message)

    await mcp_asgi(request.scope, request.receive, send)

    start = next((event for event in events if event.get("type") == "http.response.start"), None)
    body_events = [event for event in events if event.get("type") == "http.response.body"]
    status_code = int(start.get("status", 500)) if start else 500
    raw_headers = start.get("headers", []) if start else []
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in raw_headers}
    body = b"".join(event.get("body", b"") for event in body_events)

    return Response(content=body, status_code=status_code, headers=headers)


async def mcp_route(request: Request) -> Response:
    """Request-style route wrapper for the MCP ASGI transport."""
    return await _invoke_asgi_as_response(request)


app = Starlette(
    routes=[
        Route("/health", endpoint=health, methods=["GET"]),
        # Register both variants explicitly to avoid framework-level slash redirects.
        Route("/mcp", endpoint=mcp_route, methods=["GET", "POST", "DELETE"]),
        Route("/mcp/", endpoint=mcp_route, methods=["GET", "POST", "DELETE"]),
    ],
    lifespan=lifespan,
)
app.router.redirect_slashes = False


def main() -> None:
    """Run hosted public MCP service."""
    import uvicorn

    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8080"))
    uvicorn.run("finout_mcp_server.hosted_public:app", host=host, port=port, lifespan="on")
