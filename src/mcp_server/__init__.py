"""MCP server core (contract ``C1-mcp-asset-tool`` v0.1.0).

Slice 1 foundation: JSON schemas, server config, argument validation and
the C1 error taxonomy. Pure Python, stdlib-only.

No ``fastmcp`` import at package level (or anywhere in this slice):
``fastmcp`` is an optional runtime dependency for the slice-3 server
entrypoint only, and it is not installed in this environment.
"""

from __future__ import annotations

__version__ = "0.6.0"
