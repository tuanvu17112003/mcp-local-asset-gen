"""C1 v0.8: real model upscale (P1) + variants/contact sheet (P2).

Generate-level tests that drive the real orchestrator with fakes (no
network, no model downloads): the upscale chain is asserted on the
submitted prompt dict, the variants write <stem>-v2..N siblings, and
``contact_sheet:true`` emits ``<stem>-sheet.png`` plus its JSON manifest.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from src.mcp_server.config import ServerConfig
from src.mcp_server.errors import PolicyDeniedError
from src.mcp_server.orchestrator import AssetOrchestrator
from src.mcp_server.validation import validate_tool_args


def _png(w: int = 64, h: int = 64, color=(200, 40, 40, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class FakeBackend:
    """Records submits; serves one canned PNG per job."""

    def __init__(self):
        self.submissions = []
        self.loader_calls = []

    def submit_txt2img(self, **kwargs):
        self.submissions.append(kwargs)
        return "job-%d" % len(self.submissions)

    def submit_img2img(self, **kwargs):  # pragma: no cover - unused here
        raise AssertionError("refine not used in these tests")

    def fetch_result(self, job_id, **kwargs):
        return {"png_bytes": _png(), "seed": 1000 + len(self.submissions)}

    def loader_files(self, loader):
        self.loader_calls.append(loader)
        if loader == "UpscaleModelLoader":
            return {"model_name": ["RealESRGAN_x4.pth"]}
        raise AssertionError("unexpected loader %r" % (loader,))


def _postprocess(png_bytes, **kwargs):
    """Tiny postprocess stub: one base PNG + @2x/@3x, honours resize_to."""
    stem = kwargs["stem"]
    resize = kwargs.get("resize_to")
    files = []
    for scale in (1, 2, 3):
        size = 64 * scale
        if resize is not None and scale == 1:
            size = resize[0]
        files.append(
            {
                "filename": "%s.png" % stem if scale == 1 else "%s@%dx.png" % (stem, scale),
                "width": size,
                "height": size,
                "scale": scale,
                "png_bytes": _png(size, size) if size < 512 else _png(8, 8),
            }
        )
    return {"files": files, "alpha": True, "model_used": "u2net"}


def _orch(tmp_path, backend=None):
    config = ServerConfig(project_root=str(tmp_path))
    return AssetOrchestrator(
        backend or FakeBackend(), postprocess=_postprocess, config=config
    )


def _args(**overrides):
    base = dict(prompt="robot icon", category="icon", save_path="a/robot.png")
    base.update(overrides)
    return validate_tool_args(**base)


# -- P1 upscale ------------------------------------------------------------


def test_default_call_reports_identity_upscale(tmp_path):
    backend = FakeBackend()
    result = _orch(tmp_path, backend).generate(_args(), tmp_path)
    assert result["upscale"] == 1
    # width/height stay the REQUESTED size (C1 contract); the real written
    # size is output_width/output_height (this stub writes 64 px bases).
    assert (result["width"], result["height"]) == (512, 512)
    assert (result["output_width"], result["output_height"]) == (64, 64)
    assert result["variants"] == 1
    assert [a["index"] for a in result["assets"]] == [0]
    assert backend.submissions[0]["upscale"] == 1
    assert backend.loader_calls == []


def test_upscale_passes_model_and_reports_output_size(tmp_path):
    backend = FakeBackend()
    result = _orch(tmp_path, backend).generate(
        _args(upscale=4), tmp_path
    )
    assert result["upscale"] == 4
    assert result["output_width"] == 512 * 4
    assert result["output_height"] == 512 * 4
    assert backend.submissions[0]["upscale"] == 4
    assert backend.submissions[0]["upscale_model"] == "RealESRGAN_x4.pth"


def test_upscale_degrades_to_one_without_installed_model(tmp_path):
    class NoModelBackend(FakeBackend):
        def loader_files(self, loader):
            self.loader_calls.append(loader)
            return {"model_name": []}

    backend = NoModelBackend()
    result = _orch(tmp_path, backend).generate(_args(upscale=2), tmp_path)
    assert result["upscale"] == 1
    assert (result["width"], result["height"]) == (512, 512)
    assert backend.submissions[0]["upscale"] == 1


def test_explicit_upscale_model_skips_discovery(tmp_path):
    backend = FakeBackend()
    result = _orch(tmp_path, backend).generate(
        _args(upscale=2, upscale_model="MyUpscaler.pth"), tmp_path
    )
    assert result["upscale"] == 2
    assert backend.submissions[0]["upscale_model"] == "MyUpscaler.pth"
    assert backend.loader_calls == []


def test_upscale_model_without_factor_is_rejected():
    with pytest.raises(ValueError, match="INVALID_UPSCALE_MODEL"):
        _args(upscale_model="RealESRGAN_x4.pth")


def test_invalid_upscale_factor_rejected():
    with pytest.raises(ValueError, match="INVALID_UPSCALE"):
        _args(upscale=3)


# -- P2 variants -----------------------------------------------------------


def test_variants_write_numbered_siblings(tmp_path):
    result = _orch(tmp_path).generate(_args(variants=3), tmp_path)
    assert result["variants"] == 3
    assert len(result["assets"]) == 3
    paths = [a["asset_path"] for a in result["assets"]]
    assert paths == ["a/robot.png", "a/robot-v2.png", "a/robot-v3.png"]
    for path in paths:
        assert (tmp_path / path).is_file()
    # variant 1 keeps the requested leaf; the extra ones are new files
    assert (tmp_path / "a/robot@2x.png").is_file()
    assert (tmp_path / "a/robot-v2@2x.png").is_file()


def test_variant_seeds_differ(tmp_path):
    backend = FakeBackend()
    result = _orch(tmp_path, backend).generate(_args(variants=2), tmp_path)
    seeds = [a["seed"] for a in result["assets"]]
    assert len(set(seeds)) == 2


def test_variants_refuse_existing_sibling_without_overwrite(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/robot-v2.png").write_bytes(_png())
    with pytest.raises(PolicyDeniedError, match="POLICY_DENIED"):
        _orch(tmp_path).generate(_args(variants=2), tmp_path)


def test_variants_overwrite_allows_existing_sibling(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/robot-v2.png").write_bytes(_png())
    result = _orch(tmp_path).generate(_args(variants=2, overwrite=True), tmp_path)
    assert result["variants"] == 2


def test_contact_sheet_requires_variants():
    with pytest.raises(ValueError, match="INVALID_CONTACT_SHEET"):
        _args(contact_sheet=True)


def test_contact_sheet_writes_grid_and_manifest(tmp_path):
    result = _orch(tmp_path).generate(
        _args(variants=4, contact_sheet=True), tmp_path
    )
    sheet = tmp_path / "a/robot-sheet.png"
    manifest_path = tmp_path / "a/robot-sheet.json"
    assert result["contact_sheet_path"] == "a/robot-sheet.png"
    assert result["contact_sheet_manifest_path"] == "a/robot-sheet.json"
    assert sheet.is_file() and manifest_path.is_file()

    with Image.open(sheet) as img:
        assert img.format == "PNG"
        assert img.size == (sheet_span := (2 * 512 + 3 * 8, 2 * 512 + 3 * 8)), img.size
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "asset-gen/contact-sheet/1"
    assert manifest["count"] == 4
    assert [entry["index"] for entry in manifest["entries"]] == [1, 2, 3, 4]
    assert manifest["sheet"]["columns"] == 2
    assert manifest["sheet"]["rows"] == 2


def test_contact_sheet_absent_for_single_variant(tmp_path):
    result = _orch(tmp_path).generate(_args(), tmp_path)
    assert "contact_sheet_path" not in result
    assert not (tmp_path / "a/robot-sheet.png").exists()
