"""Entrypoint for BILLY internal MCP runtime."""

from finout_mcp_server.server import main_billy_internal


def main() -> None:
    main_billy_internal()


if __name__ == "__main__":
    main()
