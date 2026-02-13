"""
Finout MCP Server - Model Context Protocol server for Finout cloud cost platform.

This package provides an MCP server that exposes Finout's cloud cost data,
anomaly detection, and optimization capabilities to AI assistants.
"""

__version__ = "0.1.0"
__author__ = "Finout"

from .finout_client import CostType, FinoutClient, Granularity
from .server import server

__all__ = [
    "FinoutClient",
    "CostType",
    "Granularity",
    "server",
]
