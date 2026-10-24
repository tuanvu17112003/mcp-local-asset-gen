"""Pattern slice tests (P1+P2+P7): categories, style, seamless param, dim cap."""

from __future__ import annotations

import base64
import sys

import pytest

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"
FAKE_TILE = b"\x89PNG\r\n\x1a\nfake-tile-bytes"


@pytest.fixture(autouse=True)
def _no_fastmcp_leak():
    """Slice3 asserts ``fastmcp not in sys.modules``; don't pollute it."""
    before = {k for k in sys.modules if k == "fastmcp" or k.startswith("fastmcp.")}
    yield
    for k in [k for k in sys.modules
              if (k == "fastmcp" or k.startswith("fastmcp.")) and k not in before]:
        del sys.modules[k]


class FakeBackend:
    def submit_txt2img(self, **kwargs):
        return "backend-job-1"

    def fetch_result(self, job_id):
        return {"png_bytes": FAKE_PNG, "seed": 7}


def fake_postprocess(png_bytes, **kwargs):
    stem = kwargs.get("stem", "icon")
    files = [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}]
    if kwargs.get("seamless"):
        files.append(
            {"filename": "%s-tile.png" % stem, "png_bytes": FAKE_TILE,
             "width": 256, "height": 256}
        )
    return {"files": files, "alpha": True, "model_used": "none"}


def _writer(store: dict):
    def _write(path, data: bytes) -> None:
        store[str(path)] = bytes(data)

    return _write


def test_pattern_and_texture_categories_validate():
    from src.mcp_server.validation import validate_tool_args

    for category in ("pattern", "texture"):
        args = validate_tool_args(
            prompt="blue floral tile", category=category, save_path="a/p.png"
        )
        assert args["remove_bg"] is False  # full frame kept by default
    # Explicit remove_bg still wins.
    args = validate_tool_args(
        prompt="x", category="pattern", save_path="a/p.png", remove_bg=True
    )
    assert args["remove_bg"] is True


def test_pattern_style_preset_validates():
    from src.mcp_server.validation import validate_tool_args

    args = validate_tool_args(
        prompt="x", category="icon", save_path="a/p.png", style_preset="pattern"
    )
    assert args["style_preset"] == "pattern"


def test_width_height_capped_at_1024():
    from src.mcp_server.validation import validate_tool_args

    with pytest.raises(ValueError, match="INVALID_WIDTH"):
        validate_tool_args(
            prompt="x", category="icon", save_path="a/p.png", width=1025
        )
    with pytest.raises(ValueError, match="INVALID_HEIGHT"):
        validate_tool_args(
            prompt="x", category="icon", save_path="a/p.png", height=2048
        )
    args = validate_tool_args(
        prompt="x", category="pattern", save_path="a/p.png", width=1024, height=1024
    )
    assert (args["width"], args["height"]) == (1024, 1024)


def test_seamless_must_be_bool():
    from src.mcp_server.validation import validate_tool_args

    with pytest.raises(ValueError, match="INVALID_SEAMLESS"):
        validate_tool_args(
            prompt="x", category="pattern", save_path="a/p.png", seamless="yes"
        )


def test_backend_pattern_style_template():
    sys.path.insert(
        0, __import__("os").path.normpath(
            __import__("os").path.join(
                __import__("os").path.dirname(__file__), "..", "..", "src"
            )
        )
    )
    from gen_backend.presets import build_txt2img_params

    params = build_txt2img_params(prompt="floral", style="pattern")
    assert "seamless repeating pattern" in params["prompt"]
    assert "tileable" in params["prompt"]


def test_orchestrator_passes_seamless_and_prefers_tile_image(tmp_path):
    """seamless flows into postprocess; include_image attaches the 2x2 tile."""
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    calls = {}
    def recording_postprocess(png_bytes, **kwargs):
        calls.update(kwargs)
        return fake_postprocess(png_bytes, **kwargs)

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=recording_postprocess, writer=_writer({})
    )
    args = validate_tool_args(
        prompt="floral",
        category="pattern",
        save_path="a/tile.png",
        seamless=True,
        include_image=True,
    )
    result = orch.generate(args, tmp_path)
    assert calls["seamless"] is True
    image = result["image"]
    assert image.type == "image"
    assert base64.b64decode(image.data) == FAKE_TILE  # tile preview, not base


def test_orchestrator_no_seamless_keeps_base_image(tmp_path):
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, writer=_writer({})
    )
    args = validate_tool_args(
        prompt="bear", category="avatar", save_path="a/bear.png", include_image=True
    )
    result = orch.generate(args, tmp_path)
    assert base64.b64decode(result["image"].data) == FAKE_PNG
