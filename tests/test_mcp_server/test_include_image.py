"""include_image opt-in (C1 v0.2): result["image"] carries MCP ImageContent.

Orchestrator-level tests with fake backend/postprocess. The fastmcp import
happens lazily inside ``_image_content``; the autouse fixture cleans
``sys.modules`` so the no-fastmcp slice assertions stay valid.
"""

from __future__ import annotations

import base64
import sys

import pytest

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


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

    def submit_img2img(self, **kwargs):
        return "backend-job-2"

    def fetch_result(self, job_id):
        return {"png_bytes": FAKE_PNG, "seed": 7}


def fake_postprocess(png_bytes, **kwargs):
    stem = kwargs.get("stem", "icon")
    return {
        "files": [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}],
        "alpha": True,
        "model_used": "none",
    }


def _writer(store: dict):
    def _write(path, data: bytes) -> None:
        store[str(path)] = bytes(data)

    return _write


def test_generate_include_image(tmp_path):
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, writer=_writer({})
    )
    args = validate_tool_args(
        prompt="bear",
        category="avatar",
        save_path="a/bear.png",
        include_image=True,
    )
    result = orch.generate(args, tmp_path)
    image = result["image"]
    assert image.type == "image"
    assert image.mime_type == "image/png"
    assert base64.b64decode(image.data) == FAKE_PNG


def test_generate_default_has_no_image_key(tmp_path):
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, writer=_writer({})
    )
    args = validate_tool_args(prompt="bear", category="avatar", save_path="a/bear.png")
    result = orch.generate(args, tmp_path)
    assert "image" not in result


def test_refine_include_image(tmp_path):
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_refine_args

    (tmp_path / "p.png").write_bytes(FAKE_PNG)
    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, writer=_writer({})
    )
    args = validate_refine_args(
        asset_path="p.png", instruction="make it red", include_image=True
    )
    result = orch.refine(args, tmp_path)
    image = result["image"]
    assert image.type == "image"
    assert base64.b64decode(image.data) == FAKE_PNG


def test_refine_default_has_no_image_key(tmp_path):
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_refine_args

    (tmp_path / "p.png").write_bytes(FAKE_PNG)
    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, writer=_writer({})
    )
    args = validate_refine_args(asset_path="p.png", instruction="make it red")
    result = orch.refine(args, tmp_path)
    assert "image" not in result


def test_include_image_must_be_bool():
    from src.mcp_server.validation import validate_tool_args

    with pytest.raises(ValueError, match="INVALID_INCLUDE_IMAGE"):
        validate_tool_args(
            prompt="bear",
            category="avatar",
            save_path="a/bear.png",
            include_image="yes",
        )


def test_server_returns_image_block_not_base64_json(tmp_path):
    """Fix 1 (v0.5): include_image becomes a real MCP image content block.

    The heavy base64 must NOT ride inside the structured JSON (token
    bloat); it travels as a separate image content block instead.
    """
    import asyncio
    import base64

    from fastmcp import Client

    from src.mcp_server.config import ServerConfig
    from src.mcp_server.server import create_server

    class FakeBackend:
        def submit_txt2img(self, **kwargs):
            return "backend-job-1"

        def fetch_result(self, job_id):
            return {"png_bytes": FAKE_PNG, "seed": 7}

    def fake_postprocess(png_bytes, **kwargs):
        stem = kwargs.get("stem", "icon")
        return {
            "files": [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}],
            "alpha": True,
            "model_used": "none",
        }

    async def main():
        mcp = create_server(
            config=ServerConfig(project_root=str(tmp_path)),
            backend_factory=FakeBackend(),
            postprocess_fn=fake_postprocess,
        )
        async with Client(mcp) as client:
            return await client.call_tool(
                "generate_app_asset",
                {
                    "prompt": "bear",
                    "category": "avatar",
                    "save_path": "a/bear.png",
                    "include_image": True,
                },
            )

    res = asyncio.run(main())
    image_blocks = [c for c in res.content if getattr(c, "type", "") == "image"]
    assert len(image_blocks) == 1
    assert base64.b64decode(image_blocks[0].data) == FAKE_PNG
    structured = res.structured_content or {}
    assert "image" not in structured
