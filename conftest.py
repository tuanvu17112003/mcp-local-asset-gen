"""Repo-root pytest bootstrap: both sanctioned import styles must resolve.

``pytest tests/ -q`` (bare console script) does not put the checkout on
``sys.path`` the way ``python -m pytest`` does, so collection failed with
``ModuleNotFoundError: No module named 'src'``. Insert the checkout root
(package-style ``from src.mcp_server...``) and ``src/`` (top-level shim
``import postprocess`` / ``import mcp_server``) once here instead of editing
the tests. Idempotent: an entry already on ``sys.path`` is never re-added.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def ensure_repo_paths() -> None:
    """Put ``src/`` then the checkout root on ``sys.path`` (idempotent)."""
    for path in (_HERE / "src", _HERE):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


ensure_repo_paths()
