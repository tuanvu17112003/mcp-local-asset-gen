"""Export/naming/pipeline/vectorize tests (slice-pp2, canned path)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from postprocess.errors import LicenseRequiredError, VectorizeFailedError
from postprocess.export import export_scales, scale_filename
from postprocess.pipeline import process

from .canned import canned_center_square

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "c3" / "input-512.png"


def _png_bytes() -> bytes:
    return FIXTURE.read_bytes()


def test_scale_filename_scales():
    assert scale_filename("icon", 1) == "icon.png"
    assert scale_filename("icon", 2) == "icon@2x.png"
    assert scale_filename("icon", 3) == "icon@3x.png"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "a/b", "a\\b", "..", "a..b", "a b", "icon!", "icon@", "é"],
)
def test_scale_filename_rejects_bad_stems(bad):
    with pytest.raises(ValueError):
        scale_filename(bad, 1)


@pytest.mark.parametrize("bad_scale", [0, -1, 1.5, "2", None, True])
def test_scale_filename_rejects_bad_scales(bad_scale):
    with pytest.raises(ValueError):
        scale_filename("icon", bad_scale)


def test_canned_end_to_end_exact_multiples():
    res = process(_png_bytes(), mask_provider=canned_center_square, sizes=(1, 2, 3))
    assert res["alpha"] is True
    assert res["model_used"] == "u2net"
    files = res["files"]
    assert [(f["filename"], f["width"], f["height"], f["scale"]) for f in files] == [
        ("icon.png", 272, 272, 1),
        ("icon@2x.png", 544, 544, 2),
        ("icon@3x.png", 816, 816, 3),
    ]


def test_exported_bytes_redecodable_rgba():
    res = process(_png_bytes(), mask_provider=canned_center_square, sizes=(1, 2, 3))
    for entry in res["files"]:
        img = Image.open(io.BytesIO(entry["png_bytes"]))
        img.load()
        assert (img.width, img.height) == (entry["width"], entry["height"])
        assert img.convert("RGBA").size == (entry["width"], entry["height"])
    # Pure transform: fixture untouched (size + mtime stable enough via bytes).
    assert FIXTURE.read_bytes() == _png_bytes()


def test_license_gate_through_process():
    with pytest.raises(LicenseRequiredError, match="LICENSE_REQUIRED"):
        process(
            _png_bytes(),
            model="bria-rmbg",
            mask_provider=canned_center_square,
        )


def test_vectorize_true_raises_no_files():
    with pytest.raises(VectorizeFailedError, match="VECTORIZE_FAILED"):
        process(_png_bytes(), mask_provider=canned_center_square, vectorize=True)


def test_vectorize_default_no_svg():
    res = process(_png_bytes(), mask_provider=canned_center_square, sizes=(1, 2, 3))
    assert all(not f["filename"].endswith(".svg") for f in res["files"])
    assert len(res["files"]) == 3


def test_remove_bg_false_opaque_decodes():
    res = process(_png_bytes(), remove_bg=False, trim=False)
    assert res["model_used"] == "none"
    assert res["alpha"] is False
    assert len(res["files"]) == 3
    assert (res["files"][0]["width"], res["files"][0]["height"]) == (512, 512)


def test_custom_sizes_two_files():
    res = process(_png_bytes(), mask_provider=canned_center_square, sizes=(1, 2))
    assert [f["scale"] for f in res["files"]] == [1, 2]
    assert [f["filename"] for f in res["files"]] == ["icon.png", "icon@2x.png"]


@pytest.mark.parametrize("bad_sizes", [(), [], (1, 0), (1, -2), (1, 1.5), (1, "2")])
def test_bad_sizes_value_error(bad_sizes):
    with pytest.raises(ValueError):
        process(_png_bytes(), mask_provider=canned_center_square, sizes=bad_sizes)


def test_export_scales_empty_sizes_value_error():
    img = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    with pytest.raises(ValueError):
        export_scales(img, "icon", sizes=())
