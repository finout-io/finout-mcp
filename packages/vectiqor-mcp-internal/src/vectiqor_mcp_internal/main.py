"""Entrypoint for VECTIQOR internal MCP runtime."""

from finout_mcp_server.server import main_vectiqor_internal


def main() -> None:
    main_vectiqor_internal()


if __name__ == "__main__":
    main()
