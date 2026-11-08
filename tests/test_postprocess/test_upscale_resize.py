"""P1 upscale resize tests: `resize_to` on the assembled postprocess pipeline.

Contract: C3-processed-asset v0.1.1 + P1 (v0.8.0) `resize_to`. The
resize happens right after the base is established and BEFORE trim/pad,
so the @1x base, the @Nx exports, the icon renders and the .ico container
all derive from the resized image. No live model, no disk writes.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from postprocess.pipeline import process

from .canned import canned_center_square

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "c3" / "input-512.png"


def _png_bytes() -> bytes:
    return FIXTURE.read_bytes()


def test_resize_to_1024_resizes_base_and_scales():
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        trim=False,
        sizes=(1, 2, 3),
        resize_to=(1024, 1024),
    )
    files = res["files"]
    assert [(f["filename"], f["width"], f["height"], f["scale"]) for f in files] == [
        ("icon.png", 1024, 1024, 1),
        ("icon@2x.png", 2048, 2048, 2),
        ("icon@3x.png", 3072, 3072, 3),
    ]
    base = Image.open(io.BytesIO(files[0]["png_bytes"]))
    base.load()
    assert base.size == (1024, 1024)
    assert base.mode == "RGBA"


def test_resize_to_then_trim_keeps_resized_scale():
    """Trim/pad run AFTER the resize, so the base is not shrunk back to 512."""
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        trim=True,
        pad_px=8,
        sizes=(1, 2),
        resize_to=(1024, 1024),
    )
    files = res["files"]
    # The canned mask keeps a 256x256 square inside the 512 px source; at
    # the 1024 px resize that content is ~512 px, plus 2*8 px padding (the
    # Lanczos edge bleeds a few px, so compare against the exact multiples
    # and the resized band rather than a hardcoded pixel count).
    base_w, base_h = files[0]["width"], files[0]["height"]
    assert (base_w, base_h) == (base_h, base_w)
    assert 512 + 16 <= base_w <= 540
    assert (files[1]["width"], files[1]["height"]) == (base_w * 2, base_h * 2)


def test_resize_to_drives_icons_and_ico():
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        trim=False,
        sizes=(1,),
        icon_sizes=(64,),
        ico=True,
        resize_to=(1024, 1024),
    )
    by_name = {f["filename"]: f for f in res["files"]}
    assert by_name["icon.png"]["width"] == 1024
    # Icons are rendered FROM the resized base but keep their pixel sizes.
    assert by_name["icon-64px.png"]["width"] == 64
    assert by_name["icon-64px.png"]["scale"] == "icon64"
    assert by_name["icon.ico"]["width"] == 64
    assert by_name["icon.ico"]["png_bytes"].startswith(b"\x00\x00\x01\x00")


def test_resize_to_none_is_unchanged():
    default = process(_png_bytes(), mask_provider=canned_center_square, sizes=(1, 2, 3))
    explicit = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        sizes=(1, 2, 3),
        resize_to=None,
    )
    assert explicit == default
    assert [(f["filename"], f["width"], f["height"]) for f in explicit["files"]] == [
        ("icon.png", 272, 272),
        ("icon@2x.png", 544, 544),
        ("icon@3x.png", 816, 816),
    ]


def test_resize_to_smaller_than_source():
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        trim=False,
        sizes=(1, 2),
        resize_to=(256, 128),
    )
    assert [(f["width"], f["height"]) for f in res["files"]] == [(256, 128), (512, 256)]


def test_resize_to_is_lanczos_smoke():
    """Non-uniform target keeps the RGBA payload decodable and correctly sized."""
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        trim=False,
        sizes=(1,),
        resize_to=(640, 320),
    )
    entry = res["files"][0]
    img = Image.open(io.BytesIO(entry["png_bytes"]))
    img.load()
    assert (img.width, img.height) == (640, 320)


@pytest.mark.parametrize(
    "bad",
    [
        512,
        "1024x1024",
        (1024,),
        (1024, 1024, 1024),
        (0, 1024),
        (1024, 0),
        (-8, 1024),
        (1024, -8),
        (1024.0, 1024),
        ("1024", 1024),
        (True, 1024),
        (1024, False),
        {"width": 1024, "height": 1024},
    ],
)
def test_bad_resize_to_raises_invalid_resize_to(bad):
    with pytest.raises(ValueError, match="INVALID_RESIZE_TO:"):
        process(_png_bytes(), remove_bg=False, trim=False, resize_to=bad)


def test_bad_resize_to_fails_before_decoding():
    """Validation is pre-flight: it must not depend on the PNG payload."""
    with pytest.raises(ValueError, match="INVALID_RESIZE_TO:"):
        process(b"not-a-png", remove_bg=False, resize_to=(0, 0))
