"""Gen-9 tests: foreign-cwd launch entrypoint (root ``asset-gen.py``).

Fakes/mocks only: no network, no live server run, no fastmcp-absence
assumption (``--help`` exits before ``create_server``; the tool-set check
uses canned backend/postprocess fakes with fastmcp present).
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from src.mcp_server.config import ServerConfig

ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCHER = ROOT / "asset-gen.py"

EXPECTED_TOOLS = frozenset(
    {"generate_app_asset", "refine_asset", "server_info", "check_model"}
)

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes-no-decode-needed"


class FakeBackend:
    """Stub backend: canned job_id + canned PNG bytes, call recording."""

    def __init__(self, png_bytes: bytes = FAKE_PNG, seed: int = 7) -> None:
        self.png_bytes = png_bytes
        self.seed = seed
        self.txt2img_calls: list = []
        self.img2img_calls: list = []
        self.fetch_calls: list = []

    def submit_txt2img(self, **kwargs):
        self.txt2img_calls.append(kwargs)
        return "fake-txt2img-1"

    def submit_img2img(self, **kwargs):
        self.img2img_calls.append(kwargs)
        return "fake-img2img-1"

    def fetch_result(self, job_id):
        self.fetch_calls.append(job_id)
        return {"png_bytes": self.png_bytes, "seed": self.seed}


def fake_postprocess(png_bytes, **kwargs):
    stem = kwargs.get("stem", "icon")
    return {
        "files": [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}],
        "alpha": True,
        "model_used": "none",
    }


@pytest.fixture(autouse=True)
def _no_fastmcp_leak():
    """Slice3 asserts ``fastmcp not in sys.modules``; don't pollute it."""
    before = {k for k in sys.modules if k == "fastmcp" or k.startswith("fastmcp.")}
    yield
    for k in [k for k in sys.modules
              if (k == "fastmcp" or k.startswith("fastmcp.")) and k not in before]:
        del sys.modules[k]


# -- (a) foreign-cwd --help subprocess ----------------------------------------


def test_launcher_help_from_foreign_cwd(tmp_path):
    assert tmp_path.resolve() != ROOT.resolve()
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER), "--help"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "asset-gen" in proc.stdout
    assert "--project-root" in proc.stdout


# -- (b) entrypoint parity -----------------------------------------------------


def test_launcher_imports_main_from_server_module():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    imports_main = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "src.mcp_server.server"
        and any(a.name == "main" for a in node.names)
        for node in ast.walk(tree)
    )
    assert imports_main, "asset-gen.py must do `from src.mcp_server.server import main`"


def test_launcher_main_is_server_main():
    import src.mcp_server.server as server

    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    assert isinstance(tree.body[-1], ast.Raise), "launcher must end with raise SystemExit(main())"
    probe = ast.Module(body=list(tree.body[:-1]), type_ignores=[])
    namespace = {"__file__": str(LAUNCHER), "__name__": "asset_gen_launcher_probe"}
    exec(compile(probe, str(LAUNCHER), "exec"), namespace)  # noqa: S102 - test probe, no server run
    assert namespace["main"] is server.main


def test_create_server_exposes_four_tools(tmp_path):
    from src.mcp_server.server import create_server

    mcp = create_server(
        config=ServerConfig(project_root=str(tmp_path)),
        backend_factory=FakeBackend(),
        postprocess_fn=fake_postprocess,
    )
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == set(EXPECTED_TOOLS)
