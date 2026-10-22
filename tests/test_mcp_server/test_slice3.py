"""Slice 3 tests: server entrypoint, SVG guard, idempotency copy, fixtures.

Fakes only: no ``fastmcp`` import (asserts the entrypoint degrades with a
clear error), stub backend/postprocess, ``tmp_path`` as project root.
No network, no model downloads, no installs.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "c1"

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes-no-decode-needed"


def _load(name: str):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class FakeBackend:
    """Stub backend: canned job_id + canned PNG bytes."""

    def __init__(self, png_bytes: bytes = FAKE_PNG, seed: int = 7) -> None:
        self.png_bytes = png_bytes
        self.seed = seed
        self.calls = []

    def submit_txt2img(self, **kwargs):
        self.calls.append(("txt2img", kwargs))
        return "backend-job-1"

    def submit_img2img(self, **kwargs):
        self.calls.append(("img2img", kwargs))
        return "backend-job-2"

    def fetch_result(self, job_id):
        assert job_id.startswith("backend-job-")
        return {"png_bytes": self.png_bytes, "seed": self.seed}


def fake_postprocess(png_bytes, **kwargs):
    stem = kwargs.get("stem", "icon")
    return {
        "files": [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}],
        "alpha": True,
        "model_used": "none",
    }


def dict_writer(store: dict):
    def _write(path, data: bytes) -> None:
        store[str(path)] = bytes(data)

    return _write


def test_server_imports_without_fastmcp():
    assert "fastmcp" not in sys.modules
    import src.mcp_server.server as server

    assert "fastmcp" not in sys.modules
    assert callable(server.create_server)
    assert callable(server.main)


@pytest.mark.skipif(
    importlib.util.find_spec("fastmcp") is not None,
    reason="transport present; covered live by IC-3",
)
def test_create_server_without_fastmcp_raises_clear_error():
    import src.mcp_server.server as server

    assert "fastmcp" not in sys.modules  # precondition: env has no fastmcp
    with pytest.raises(RuntimeError, match="FastMCP is not installed"):
        server.create_server()


def test_svg_format_refused_loudly(tmp_path):
    from src.mcp_server.errors import PostprocessFailedError
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, writer=dict_writer({})
    )
    args = validate_tool_args(
        prompt="bear", category="avatar", save_path="a/bear.png", format="svg"
    )
    with pytest.raises(PostprocessFailedError, match=r"SVG-DEFERRED"):
        orch.generate(args, tmp_path)


def test_png_format_still_echoed(tmp_path):
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, writer=dict_writer({})
    )
    args = validate_tool_args(
        prompt="bear", category="avatar", save_path="a/bear.png", format="png"
    )
    result = orch.generate(args, tmp_path, job_id="png-echo")
    assert result["format"] == "png"
    assert result["asset_path"] == "a/bear.png"


def test_idempotency_store_returns_copy():
    from src.mcp_server.registry import JobRegistry

    reg = JobRegistry()
    reg.register("j1")
    reg.complete("j1", {"asset_path": "a/b.png", "job_id": "j1"})
    first = reg.get("j1")
    first["asset_path"] = "MUTATED"
    second = reg.get("j1")
    assert second == {"asset_path": "a/b.png", "job_id": "j1"}


def test_golden_bear_call_validates():
    from src.mcp_server.schemas import BEAR_AVATAR_EXAMPLE
    from src.mcp_server.validation import validate_tool_args

    call = _load("bear_avatar_call.json")
    assert call == BEAR_AVATAR_EXAMPLE
    validated = validate_tool_args(**call)
    assert validated["save_path"] == "assets/images/bear_avatar.png"
    assert validated["width"] == 512
    assert validated["format"] == "png"


def test_golden_result_shape_matches_output_schema():
    from src.mcp_server.schemas import GENERATE_APP_ASSET_SCHEMA

    result = _load("bear_avatar_result.json")
    required = GENERATE_APP_ASSET_SCHEMA["output_schema"]["required"]
    assert sorted(result) == sorted(required)
    assert result["asset_path"] == "assets/images/bear_avatar.png"


def test_path_escape_call_raises_policy_denied():
    from src.mcp_server.errors import PolicyDeniedError
    from src.mcp_server.validation import validate_tool_args

    call = _load("path_escape_call.json")
    assert call["save_path"] == "../../etc/pass.png"
    assert call.pop("expected_code") == "POLICY_DENIED"
    with pytest.raises(PolicyDeniedError, match="POLICY_DENIED"):
        validate_tool_args(**call)


def test_server_info_fixture_shape(monkeypatch, tmp_path):
    from src.mcp_server.orchestrator import SERVER_MODELS
    from src.mcp_server.schemas import SERVER_INFO_SCHEMA
    from src.mcp_server.config import (
        DEFAULT_COMFYUI_URL,
        SERVER_VERSION,
        ServerConfig,
    )
    from src.mcp_server.orchestrator import AssetOrchestrator
    import src.mcp_server.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_probe_comfyui_queue", lambda url: (True, 0))
    expected = _load("server_info.json")
    assert sorted(expected) == sorted(SERVER_INFO_SCHEMA["output_schema"]["required"])
    assert expected["backend"] == "comfyui"
    assert expected["comfyui_url"] == DEFAULT_COMFYUI_URL
    assert expected["models"] == list(SERVER_MODELS)
    assert expected["version"] == SERVER_VERSION
    # Example documents the live-probe success shape (reachable + depth 0).
    assert expected["reachable"] is True
    assert expected["queue_depth"] == 0
    # Example root is an absolute path string (platform flavors differ, so
    # accept either absolute form); live values are asserted dynamically.
    assert isinstance(expected["project_root"], str) and expected["project_root"]
    from pathlib import PurePosixPath, PureWindowsPath

    assert PurePosixPath(expected["project_root"]).is_absolute() or PureWindowsPath(
        expected["project_root"]
    ).is_absolute()

    cfg = ServerConfig(project_root=str(tmp_path))
    orch = AssetOrchestrator(
        FakeBackend(),
        postprocess=fake_postprocess,
        writer=dict_writer({}),
        config=cfg,
    )
    assert orch.server_info() == {
        **expected,
        "project_root": os.path.abspath(os.fspath(tmp_path)),
        "workspaces": {"default": os.path.abspath(os.fspath(tmp_path))},
    }
