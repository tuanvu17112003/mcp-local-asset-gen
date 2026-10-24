"""C3 canned-path consumer + SVG-deferral + JPEG strict-probe checks.

All PNG/JPEG bytes are generated at runtime via Pillow (no fixture
writes, no network, no model downloads — the canned ``mask_provider``
seam avoids the live ``rembg`` path entirely).
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from postprocess.errors import DecodeFailedError
from postprocess.pipeline import process

SRC_SIZE = 128
BORDER = 16
PAD_PX = 8


def _bear_png() -> bytes:
    """128x128 RGBA: transparent border so the trim/pad path is exercised."""
    img = Image.new("RGBA", (SRC_SIZE, SRC_SIZE), (0, 0, 0, 0))
    img.paste((139, 90, 43, 255), (BORDER, BORDER, SRC_SIZE - BORDER, SRC_SIZE - BORDER))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _opaque_rgba_mask(png_bytes: bytes) -> Image.Image:
    """Canned mask seam returning an RGBA image (adapter converts to L)."""
    base = Image.open(io.BytesIO(png_bytes))
    return Image.new("RGBA", base.size, (255, 255, 255, 255))


def _jpeg_bytes() -> bytes:
    img = Image.new("RGB", (64, 64), (200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_canned_consumer_exact_multiples_with_alpha():
    res = process(
        _bear_png(),
        mask_provider=_opaque_rgba_mask,
        stem="bear_avatar",
        sizes=(1, 2, 3),
    )
    assert res["alpha"] is True
    assert res["model_used"] == "u2net"
    files = res["files"]
    assert [f["filename"] for f in files] == [
        "bear_avatar.png",
        "bear_avatar@2x.png",
        "bear_avatar@3x.png",
    ]
    # Fully-opaque canned mask -> trim keeps 128x128, pad 8 -> 144x144 base.
    base_w, base_h = SRC_SIZE + 2 * PAD_PX, SRC_SIZE + 2 * PAD_PX
    assert (files[0]["width"], files[0]["height"]) == (base_w, base_h)
    for entry, scale in zip(files, (1, 2, 3)):
        assert entry["scale"] == scale
        assert (entry["width"], entry["height"]) == (base_w * scale, base_h * scale)
        img = Image.open(io.BytesIO(entry["png_bytes"]))
        img.load()
        assert (img.width, img.height) == (entry["width"], entry["height"])
        rgba = img.convert("RGBA")
        lo, _hi = rgba.getchannel("A").getextrema()
        assert lo < 255  # base carries real transparency (pad border)
    base = Image.open(io.BytesIO(files[0]["png_bytes"])).convert("RGBA")
    assert base.mode == "RGBA"


def test_vectorize_true_inline_svg_wellformed():
    """C3 v0.2: vectorize=True traces the base to a well-formed SVG entry."""
    res = process(_bear_png(), mask_provider=_opaque_rgba_mask, vectorize=True)
    svg_entries = [f for f in res["files"] if f["filename"].endswith(".svg")]
    assert len(svg_entries) == 1
    root = ET.fromstring(svg_entries[0]["png_bytes"].decode("utf-8"))
    assert root.tag.endswith("svg")
    res_plain = process(_bear_png(), mask_provider=_opaque_rgba_mask, sizes=(1,))
    assert all(not f["filename"].endswith(".svg") for f in res_plain["files"])


def test_strict_probe_jpeg_must_yield_decode_failed():
    """PQM0-DIRECTED STRICT PROBE: valid JPEG bytes MUST yield DECODE_FAILED.

    Reported truthfully either way — no catch-and-relabel. On the current
    pipeline Pillow decodes JPEG bytes, so this probe is EXPECTED TO FAIL
    loudly (wrong error or no error); PQM0 scopes postprocess rework
    (format-strictness) on failure.
    """
    jpeg = _jpeg_bytes()
    with pytest.raises(DecodeFailedError, match="DECODE_FAILED"):
        process(jpeg)
