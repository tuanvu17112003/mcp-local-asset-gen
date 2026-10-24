"""Seamless-tiling postprocess tests (P2, pure Pillow, canned path)."""

from __future__ import annotations

import io

from PIL import Image, ImageChops

from postprocess.export import export_scales
from postprocess.pipeline import process
from postprocess.seamless import DEFAULT_FEATHER, export_tile_preview, make_seamless

from .canned import canned_center_square


def _gradient_png(w=128, h=64):
    """Horizontal 0->255 gradient: opposite edges differ maximally."""
    img = Image.new("RGB", (w, h))
    for x in range(w):
        for y in range(h):
            img.putpixel((x, y), (x * 255 // (w - 1), 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _edge_gap(img):
    """Max channel delta between the last and first column."""
    w, h = img.size
    diff = ImageChops.difference(
        img.crop((w - 1, 0, w, h)), img.crop((0, 0, 1, h))
    )
    return diff.getextrema()[0][1] if isinstance(diff.getextrema()[0], tuple) else diff.getextrema()[0]


def test_make_seamless_preserves_size_and_reduces_edge_gap():
    src = Image.open(io.BytesIO(_gradient_png())).convert("RGBA")
    out = make_seamless(src)
    assert out.size == src.size
    assert out.mode == "RGBA"
    assert _edge_gap(out) < _edge_gap(src) // 2


def test_make_seamless_zero_feather_is_copy():
    src = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    out = make_seamless(src, feather=0)
    assert out.size == src.size
    assert out.tobytes() == src.tobytes()


def test_make_seamless_tiny_image_clamps_feather():
    src = Image.new("RGBA", (3, 3), (0, 255, 0, 255))
    out = make_seamless(src, feather=DEFAULT_FEATHER)
    assert out.size == (3, 3)


def test_tile_preview_is_2x2_repeat():
    src = Image.new("RGBA", (8, 5), (10, 20, 30, 255))
    src.putpixel((0, 0), (255, 0, 0, 255))
    entry = export_tile_preview(src, "tile")
    assert entry["filename"] == "tile-tile.png"
    assert (entry["width"], entry["height"]) == (16, 10)
    img = Image.open(io.BytesIO(entry["png_bytes"]))
    assert img.size == (16, 10)
    # Every quadrant repeats the tile exactly.
    assert img.getpixel((0, 0)) == img.getpixel((8, 5)) == (255, 0, 0, 255)


def _bordered_png(size=512, border=64):
    """RGBA with a transparent border, so trim would shrink it."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste((139, 90, 43, 255), (border, border, size - border, size - border))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_pipeline_seamless_skips_trim_and_emits_preview():
    """seamless=True forces trim off: the tile keeps its full frame."""
    png = _bordered_png()
    res = process(png, mask_provider=canned_center_square, seamless=True, sizes=(1,))
    base = res["files"][0]
    assert (base["width"], base["height"]) == (512, 512)
    tiles = [f for f in res["files"] if f["filename"].endswith("-tile.png")]
    assert len(tiles) == 1
    assert (tiles[0]["width"], tiles[0]["height"]) == (1024, 1024)
    # Contrast: the same input without seamless IS trimmed down to the
    # canned mask's opaque 256px center (+ 2*8 pad).
    res_plain = process(png, mask_provider=canned_center_square, sizes=(1,))
    assert res_plain["files"][0]["width"] == 256 + 2 * 8


def test_seamless_module_exports_scales_unchanged():
    img = Image.new("RGBA", (4, 4), (1, 2, 3, 255))
    out = export_scales(make_seamless(img), "t", sizes=(1, 2))
    assert [e["filename"] for e in out] == ["t.png", "t@2x.png"]
