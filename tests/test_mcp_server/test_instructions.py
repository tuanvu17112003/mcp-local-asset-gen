"""Server initialization instructions (MCP `InitializeResult.instructions`).

Asserts the guidance text covers every required topic and that
``create_server`` wires it onto the FastMCP app (live-serving needs
``fastmcp``; the text assertions need nothing).
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

from src.mcp_server.server import SERVER_INSTRUCTIONS

REQUIRED_SNIPPETS = (
    "generate_app_asset",
    "refine_asset",
    "check_model",
    "server_info",
    "save_path",
    "overwrite",
    "reachable",
    "queue_depth",
    "icon_sizes",
    "strength",
    "job_id",
    "svg",
    "localhost",
    "BACKEND_UNAVAILABLE",
    "POLICY_DENIED",
    "INVALID_",
    "LICENSE_REQUIRED",
)


def test_instructions_cover_required_topics():
    missing = [s for s in REQUIRED_SNIPPETS if s not in SERVER_INSTRUCTIONS]
    assert not missing, "instructions missing topics: %r" % (missing,)


def test_instructions_token_budget():
    assert len(SERVER_INSTRUCTIONS) < 4000, len(SERVER_INSTRUCTIONS)


@pytest.fixture(autouse=True)
def _no_fastmcp_leak():
    """Slice3 asserts ``fastmcp not in sys.modules``; don't pollute it."""
    before = {k for k in sys.modules if k == "fastmcp" or k.startswith("fastmcp.")}
    yield
    for k in [k for k in sys.modules
              if (k == "fastmcp" or k.startswith("fastmcp.")) and k not in before]:
        del sys.modules[k]


@pytest.mark.skipif(
    importlib.util.find_spec("fastmcp") is None,
    reason="live serving needs fastmcp; text covered above",
)
def test_create_server_exposes_instructions():
    from src.mcp_server.config import ServerConfig
    from src.mcp_server.server import create_server

    class FakeBackend:
        def fetch_result(self, job_id):
            raise AssertionError("no live calls in this test")

    mcp = create_server(
        config=ServerConfig(project_root="."),
        backend_factory=FakeBackend(),
        postprocess_fn=lambda **kwargs: {"files": [], "alpha": True,
                                         "model_used": "none"},
    )
    assert mcp.instructions == SERVER_INSTRUCTIONS
