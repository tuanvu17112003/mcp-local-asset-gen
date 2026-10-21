"""Foreign-cwd launcher for the asset-gen MCP server.

Run as ``<python> <root>/asset-gen.py --project-root <root>`` from any
working directory; no PYTHONPATH setup needed. All CLI behavior lives in
``src.mcp_server.server:main``.
"""

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.mcp_server.server import main

raise SystemExit(main())
