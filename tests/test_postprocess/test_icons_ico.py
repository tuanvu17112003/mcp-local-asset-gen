"""Icon sizes + .ico export tests (contract C3-processed-asset v0.1.1, gen-5)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from postprocess.pipeline import process

from .canned import canned_center_square

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "c3" / "input-512.png"

ICO_MAGIC = b"\x00\x00\x01\x00"


def _png_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _wide_png_bytes(w: int = 200, h: int = 100) -> bytes:
    img = Image.new("RGBA", (w, h), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_icon_sizes_exact_entries_and_bytes():
    # Canned pipeline: final base is 272x272; icon_sizes appends after @Nx.
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        icon_sizes=[16, 32],
    )
    files = res["files"]
    assert [(f["filename"], f["width"], f["height"], f["scale"]) for f in files] == [
        ("icon.png", 272, 272, 1),
        ("icon@2x.png", 544, 544, 2),
        ("icon@3x.png", 816, 816, 3),
        ("icon-16px.png", 16, 16, "icon16"),
        ("icon-32px.png", 32, 32, "icon32"),
    ]
    for entry, size in (files[3], 16), (files[4], 32):
        img = Image.open(io.BytesIO(entry["png_bytes"]))
        img.load()
        assert (img.width, img.height) == (size, size)


def test_icon_naming_accepts_dash_dot_underscore():
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        stem="my-icon_v2",
        icon_sizes=[16],
    )
    names = [f["filename"] for f in res["files"]]
    assert names[-1] == "my-icon_v2-16px.png"
    res2 = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        stem="my.icon_v2-3",
        icon_sizes=[32],
    )
    assert [f["filename"] for f in res2["files"]][-1] == "my.icon_v2-3-32px.png"


def test_ico_magic_multisize_and_openable():
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        icon_sizes=[16, 32, 48, 64],
        ico=True,
    )
    files = res["files"]
    last = files[-1]
    assert last["filename"] == "icon.ico"
    assert last["width"] == 64 and last["height"] == 64
    assert last["scale"] == "ico"
    raw = last["png_bytes"]
    assert raw[:4] == ICO_MAGIC
    assert int.from_bytes(raw[4:6], "little") == 4
    img = Image.open(io.BytesIO(raw))
    img.load()
    assert img.format == "ICO"


def test_square_crop_path_non_square_base():
    res = process(
        _wide_png_bytes(200, 100),
        remove_bg=False,
        trim=False,
        icon_sizes=[32],
    )
    files = res["files"]
    assert (files[0]["width"], files[0]["height"]) == (200, 100)
    icon = files[-1]
    assert icon["filename"] == "icon-32px.png"
    assert (icon["width"], icon["height"]) == (32, 32)
    img = Image.open(io.BytesIO(icon["png_bytes"]))
    img.load()
    assert (img.width, img.height) == (32, 32)


def test_ico_without_sizes_single_entry():
    res = process(
        _png_bytes(),
        mask_provider=canned_center_square,
        ico=True,
    )
    files = res["files"]
    assert len(files) == 4
    assert [f["filename"] for f in files] == [
        "icon.png",
        "icon@2x.png",
        "icon@3x.png",
        "icon.ico",
    ]
    assert not any(f["filename"].endswith("px.png") for f in files)
    raw = files[-1]["png_bytes"]
    assert raw[:4] == ICO_MAGIC
    assert int.from_bytes(raw[4:6], "little") == 4


def test_defaults_unchanged_three_entries():
    res = process(_png_bytes(), mask_provider=canned_center_square)
    assert [f["filename"] for f in res["files"]] == [
        "icon.png",
        "icon@2x.png",
        "icon@3x.png",
    ]
    res2 = process(
        _png_bytes(), mask_provider=canned_center_square, icon_sizes=[], ico=False
    )
    assert [f["filename"] for f in res2["files"]] == [
        "icon.png",
        "icon@2x.png",
        "icon@3x.png",
    ]
