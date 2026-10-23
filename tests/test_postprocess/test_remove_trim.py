"""Canned-mask tests for the postprocess core (slice-pp1)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from postprocess.errors import (
    DecodeFailedError,
    LicenseRequiredError,
    SegmentationFailedError,
)
from postprocess.rembg_adapter import remove_background
from postprocess.trim import trim_and_pad

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "c3" / "input-512.png"
MANIFEST = ROOT / "fixtures" / "c3" / "expected-manifest.json"


def _png_bytes() -> bytes:
    return FIXTURE.read_bytes()


def canned_center_square(png_bytes: bytes) -> Image.Image:
    """Canned mask: 512x512 'L', centered 256x256 opaque square."""
    from PIL import Image as _Image
    import io as _io

    base = _Image.open(_io.BytesIO(png_bytes))
    w, h = base.size
    assert (w, h) == (512, 512)
    mask = _Image.new("L", (w, h), 0)
    mask.paste(255, (128, 128, 384, 384))
    return mask


def test_manifest_matches_canned_math():
    data = json.loads(MANIFEST.read_text())
    assert data["input"] == {
        "path": "fixtures/c3/input-512.png",
        "width": 512,
        "height": 512,
        "mode": "RGB",
    }
    assert data["canned_mask"]["box"] == [128, 128, 384, 384]
    assert data["trimmed"] == {"width": 256, "height": 256}
    assert data["padded"] == {"width": 272, "height": 272}
    assert data["alpha"] is True


def test_canned_center_square_trims_and_pads():
    out = remove_background(_png_bytes(), model="u2net", mask_provider=canned_center_square)
    assert out.mode == "RGBA"
    trimmed = trim_and_pad(out, pad_px=8)
    assert trimmed.size == (272, 272)
    assert trimmed.mode == "RGBA"
    # Corners transparent, center opaque.
    assert trimmed.getpixel((0, 0))[3] == 0
    cx, cy = trimmed.size[0] // 2, trimmed.size[1] // 2
    assert trimmed.getpixel((cx, cy))[3] == 255
    # Alpha channel is genuinely present (not all opaque).
    extrema = trimmed.getchannel("A").getextrema()
    assert extrema == (0, 255)


def test_license_gate_bria():
    with pytest.raises(LicenseRequiredError, match="LICENSE_REQUIRED"):
        remove_background(_png_bytes(), model="bria-rmbg")
    # With acceptance + canned mask the license path still works.
    out = remove_background(
        _png_bytes(),
        model="bria-rmbg",
        bria_license_accepted=True,
        mask_provider=canned_center_square,
    )
    assert out.mode == "RGBA"
    assert trim_and_pad(out, pad_px=8).size == (272, 272)


def test_non_png_bytes_decode_failed():
    with pytest.raises(DecodeFailedError, match="DECODE_FAILED"):
        remove_background(b"not-a-png", mask_provider=canned_center_square)


def test_unknown_model_value_error():
    with pytest.raises(ValueError, match="unknown model"):
        remove_background(_png_bytes(), model="nope", mask_provider=canned_center_square)


def test_fully_transparent_trim_no_crash():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    out = trim_and_pad(img, pad_px=8)
    assert out.size == (64, 64)
    assert out.mode == "RGBA"


def test_negative_pad_value_error():
    img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    with pytest.raises(ValueError, match="pad_px"):
        trim_and_pad(img, pad_px=-1)


@pytest.mark.skipif(
    importlib.util.find_spec("rembg") is not None,
    reason="live path present; covered live by IC-2",
)
def test_live_path_version_guard_no_download():
    with pytest.raises(SegmentationFailedError) as excinfo:
        remove_background(_png_bytes())
    assert "SEGMENTATION_FAILED" in str(excinfo.value)
    msg = str(excinfo.value)
    assert ("3.11" in msg) or ("new_session" in msg)


def test_canned_path_never_imports_rembg(monkeypatch):
    if "rembg" in sys.modules:
        pytest.skip("rembg already imported in this session")
    monkeypatch.setitem(sys.modules, "rembg", None)
    out = remove_background(_png_bytes(), model="u2net", mask_provider=canned_center_square)
    assert out.mode == "RGBA"
    assert sys.modules.get("rembg") is None
