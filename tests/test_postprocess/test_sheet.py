"""Contact-sheet composition tests (contract C3-processed-asset v0.8, P2).

Covers the pure in-memory sheet module: grid layout, aspect-preserving
cell fit + centering, canvas geometry, transparency, the optional cell
border, machine-readable error codes and the deterministic JSON
manifest. PNG fixtures are built in-memory with Pillow (no binary
fixtures on disk).
"""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from postprocess.sheet import build_manifest, compose_contact_sheet, layout_grid


def _png(width: int, height: int, color=(255, 0, 0, 255)) -> bytes:
    """Return in-memory PNG bytes of a solid RGBA image."""
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _sheet_image(result: dict) -> Image.Image:
    """Decode the composed sheet PNG back to a loaded RGBA image."""
    img = Image.open(io.BytesIO(result["png_bytes"]))
    img.load()
    return img.convert("RGBA")


def _cell_origin(result: dict, offset: int, gap_px: int) -> tuple[int, int]:
    """Return the (left, top) canvas origin of the cell at `offset`."""
    stride = result["cell_px"] + gap_px
    return (
        gap_px + (offset % result["columns"]) * stride,
        gap_px + (offset // result["columns"]) * stride,
    )


# --- layout_grid -----------------------------------------------------------


@pytest.mark.parametrize(
    "count, expected",
    [
        (1, (1, 1)),
        (2, (2, 1)),
        (3, (2, 2)),
        (4, (2, 2)),
        (5, (3, 2)),
        (6, (3, 2)),
        (9, (3, 3)),
        (10, (4, 3)),
    ],
)
def test_layout_grid_auto_columns(count, expected):
    assert layout_grid(count) == expected


@pytest.mark.parametrize(
    "count, columns, expected",
    [
        (1, 1, (1, 1)),
        (4, 2, (2, 2)),
        (5, 5, (5, 1)),
        (5, 1, (1, 5)),
        (6, 4, (4, 2)),
        (9, 4, (4, 3)),
        (9, 1, (1, 9)),
    ],
)
def test_layout_grid_explicit_columns(count, columns, expected):
    assert layout_grid(count, columns=columns) == expected


@pytest.mark.parametrize("bad_count", [0, -1, -5, True, 1.5, "3", None])
def test_layout_grid_rejects_bad_count(bad_count):
    with pytest.raises(ValueError, match=r"^INVALID_SHEET_COUNT: "):
        layout_grid(bad_count)


@pytest.mark.parametrize(
    "count, bad_columns", [(4, 0), (4, -1), (4, 5), (4, True), (4, 2.0), (4, "2")]
)
def test_layout_grid_rejects_bad_columns(count, bad_columns):
    with pytest.raises(ValueError, match=r"^INVALID_SHEET_COLUMNS: "):
        layout_grid(count, columns=bad_columns)


def test_layout_grid_columns_is_keyword_only():
    with pytest.raises(TypeError):
        layout_grid(4, 2)


# --- compose_contact_sheet -------------------------------------------------


def test_compose_single_image():
    res = compose_contact_sheet([_png(50, 50)], cell_px=64, gap_px=4)
    assert res["columns"] == 1
    assert res["rows"] == 1
    assert res["count"] == 1
    assert res["cell_px"] == 64
    assert (res["width"], res["height"]) == (64 + 2 * 4, 64 + 2 * 4)
    img = _sheet_image(res)
    assert img.size == (res["width"], res["height"])


def test_compose_four_images_grid():
    images = [_png(64, 64, (10 * i, 20 * i, 30 * i, 255)) for i in range(4)]
    res = compose_contact_sheet(images, cell_px=32, gap_px=2)
    assert res["columns"] == 2
    assert res["rows"] == 2
    assert res["count"] == 4
    assert (res["width"], res["height"]) == (2 * 32 + 3 * 2, 2 * 32 + 3 * 2)


def test_compose_six_images_grid():
    res = compose_contact_sheet([_png(40, 40) for _ in range(6)], cell_px=16, gap_px=1)
    assert res["columns"] == 3
    assert res["rows"] == 2
    assert res["count"] == 6
    assert (res["width"], res["height"]) == (3 * 16 + 4 * 1, 2 * 16 + 3 * 1)


@pytest.mark.parametrize(
    "size, expected_bbox",
    [
        ((400, 200), (0, 25, 100, 75)),
        ((200, 400), (25, 0, 75, 100)),
        ((300, 300), (0, 0, 100, 100)),
    ],
)
def test_compose_preserves_aspect_ratio_and_centers(size, expected_bbox):
    res = compose_contact_sheet([_png(*size)], cell_px=100, gap_px=0)
    img = _sheet_image(res)
    cell = img.crop((0, 0, 100, 100))
    assert cell.getchannel("A").getbbox() == expected_bbox


@pytest.mark.parametrize(
    "count, columns, cell_px, gap_px",
    [
        (1, None, 64, 4),
        (4, None, 32, 2),
        (6, None, 16, 1),
        (5, 2, 20, 3),
        (3, 3, 10, 0),
    ],
)
def test_canvas_size_formula(count, columns, cell_px, gap_px):
    images = [_png(8, 8) for _ in range(count)]
    res = compose_contact_sheet(
        images, columns=columns, cell_px=cell_px, gap_px=gap_px
    )
    cols, rows = layout_grid(count, columns=columns)
    assert (res["columns"], res["rows"]) == (cols, rows)
    assert res["width"] == cols * cell_px + (cols + 1) * gap_px
    assert res["height"] == rows * cell_px + (rows + 1) * gap_px
    assert _sheet_image(res).size == (res["width"], res["height"])


def test_transparent_background_stays_transparent():
    res = compose_contact_sheet([_png(10, 10)], cell_px=20, gap_px=4)
    img = _sheet_image(res)
    assert img.getpixel((0, 0))[3] == 0  # gap margin
    left, top = _cell_origin(res, 0, 4)
    cell = img.crop((left, top, left + 20, top + 20))
    assert cell.getchannel("A").getbbox() == (5, 5, 15, 15)


def test_background_fills_gaps_and_empty_cells():
    res = compose_contact_sheet(
        [_png(10, 10)], cell_px=20, gap_px=4, background=(255, 255, 255, 255)
    )
    img = _sheet_image(res)
    assert img.getpixel((0, 0)) == (255, 255, 255, 255)
    assert img.getpixel((2, 2)) == (255, 255, 255, 255)


def test_alpha_composite_onto_opaque_background():
    transparent = _png(20, 20, (0, 0, 255, 0))
    res = compose_contact_sheet(
        [transparent], cell_px=20, gap_px=0, background=(0, 128, 0, 255)
    )
    img = _sheet_image(res)
    assert img.getpixel((10, 10)) == (0, 128, 0, 255)


def test_cells_placed_row_major():
    colours = [
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 255, 0, 255),
    ]
    res = compose_contact_sheet(
        [_png(8, 8, c) for c in colours], cell_px=8, gap_px=4
    )
    img = _sheet_image(res)
    for offset, colour in enumerate(colours):
        left, top = _cell_origin(res, offset, 4)
        assert img.getpixel((left + 4, top + 4)) == colour
        if offset:
            assert img.getpixel((left - 1, top + 4))[3] == 0


def test_border_draws_one_pixel_frame_per_cell():
    res = compose_contact_sheet(
        [_png(20, 20) for _ in range(4)],
        cell_px=20,
        gap_px=3,
        border_rgba=(0, 0, 255, 255),
    )
    img = _sheet_image(res)
    for offset in range(4):
        left, top = _cell_origin(res, offset, 3)
        for x, y in (
            (left, top),
            (left + 19, top),
            (left, top + 19),
            (left + 19, top + 19),
        ):
            assert img.getpixel((x, y)) == (0, 0, 255, 255)


def test_no_border_by_default():
    res = compose_contact_sheet([_png(20, 20)], cell_px=40, gap_px=5)
    img = _sheet_image(res)
    left, top = _cell_origin(res, 0, 5)
    assert img.getpixel((left, top))[3] == 0


@pytest.mark.parametrize(
    "bad_border",
    [(1, 2), (1, 2, 3, 4, 5), (0, 0, 0, 256), (0, 0, 256), ("a", 0, 0, 0), 5],
)
def test_bad_border_rgba_rejected(bad_border):
    with pytest.raises(ValueError, match=r"^INVALID_BORDER_RGBA: "):
        compose_contact_sheet([_png(4, 4)], cell_px=8, border_rgba=bad_border)


def test_decode_failure_reports_empty_payload_index():
    images = [_png(8, 8), b"", _png(8, 8)]
    with pytest.raises(ValueError, match=r"^DECODE_FAILED: image 2 is empty$"):
        compose_contact_sheet(images, cell_px=8, gap_px=0)


def test_decode_failure_reports_garbage_payload_index():
    images = [_png(8, 8), _png(8, 8), b"\x89PNG\r\n\x1a\nbroken"]
    with pytest.raises(ValueError, match=r"^DECODE_FAILED: image 3 "):
        compose_contact_sheet(images, cell_px=8, gap_px=0)


def test_decode_failure_reports_non_bytes_index():
    with pytest.raises(ValueError, match=r"^DECODE_FAILED: image 1 "):
        compose_contact_sheet([None], cell_px=8, gap_px=0)


def test_empty_image_list_rejected():
    with pytest.raises(
        ValueError, match=r"^INVALID_SHEET_IMAGES: at least one image is required$"
    ):
        compose_contact_sheet([])


def test_bare_bytes_payload_rejected():
    with pytest.raises(ValueError, match=r"^INVALID_SHEET_IMAGES: "):
        compose_contact_sheet(_png(8, 8))


@pytest.mark.parametrize("bad_cell_px", [0, -1, 4097, 1.5, "64", True, None])
def test_invalid_cell_px_rejected(bad_cell_px):
    with pytest.raises(ValueError, match=r"^INVALID_CELL_PX: "):
        compose_contact_sheet([_png(4, 4)], cell_px=bad_cell_px)


@pytest.mark.parametrize("bad_gap_px", [-1, 257, 1.5, "8", True])
def test_invalid_gap_px_rejected(bad_gap_px):
    with pytest.raises(ValueError, match=r"^INVALID_GAP_PX: "):
        compose_contact_sheet([_png(4, 4)], cell_px=8, gap_px=bad_gap_px)


def test_compose_rejects_bad_columns():
    with pytest.raises(ValueError, match=r"^INVALID_SHEET_COLUMNS: "):
        compose_contact_sheet([_png(4, 4), _png(4, 4)], columns=3)


def test_boundary_cell_and_gap_accepted():
    res = compose_contact_sheet([_png(4, 4)], cell_px=1, gap_px=0)
    assert (res["width"], res["height"]) == (1, 1)
    res = compose_contact_sheet([_png(4, 4)], cell_px=1, gap_px=256)
    assert (res["width"], res["height"]) == (513, 513)


def test_result_shape_and_decodable_rgba_png():
    res = compose_contact_sheet((_png(9, 9), _png(9, 9)))
    assert set(res) == {
        "png_bytes",
        "width",
        "height",
        "columns",
        "rows",
        "cell_px",
        "count",
    }
    assert isinstance(res["png_bytes"], bytes)
    assert res["png_bytes"].startswith(b"\x89PNG")
    img = _sheet_image(res)
    assert img.mode == "RGBA"
    assert (img.width, img.height) == (res["width"], res["height"])


def test_compose_is_deterministic():
    images = [_png(16, 16, (30 * i % 256, 0, 0, 255)) for i in range(4)]
    first = compose_contact_sheet(images, cell_px=24, gap_px=3)
    second = compose_contact_sheet(images, cell_px=24, gap_px=3)
    assert first == second


# --- build_manifest --------------------------------------------------------


def test_manifest_shape_sorted_and_json_round_trip():
    entries = [
        {"index": 2, "filename": "asset-2.png", "seed": 22, "score": 1.5},
        {"index": 0, "filename": "asset-0.png", "seed": 11},
        {"index": 1, "filename": "asset-1.png"},
    ]
    manifest = build_manifest(entries)
    assert manifest["schema"] == "asset-gen/contact-sheet/1"
    assert manifest["count"] == 3
    assert [e["index"] for e in manifest["entries"]] == [0, 1, 2]
    assert [e["filename"] for e in manifest["entries"]] == [
        "asset-0.png",
        "asset-1.png",
        "asset-2.png",
    ]
    assert manifest["entries"][0]["seed"] == 11
    assert manifest["entries"][2]["seed"] == 22
    assert manifest["entries"][2]["score"] == 1.5
    assert json.loads(json.dumps(manifest)) == manifest


def test_manifest_is_deterministic_regardless_of_input_order():
    entries = [{"index": i, "filename": f"a{i}.png"} for i in (3, 1, 2)]
    assert build_manifest(entries) == build_manifest(list(reversed(entries)))


def test_manifest_drops_non_json_values():
    class Opaque:
        pass

    entries = [
        {
            "index": 0,
            "filename": "a.png",
            "nested": {"a": 1},
            "listed": [1, 2],
            "payload": b"bytes",
            "missing": None,
            "flag": False,
            "ratio": 0.25,
            "number": 7,
            "text": "x",
            "object": Opaque(),
            "nan": float("nan"),
            "inf": float("inf"),
        }
    ]
    entry = build_manifest(entries)["entries"][0]
    assert set(entry) == {
        "index",
        "filename",
        "missing",
        "flag",
        "ratio",
        "number",
        "text",
    }
    assert entry["missing"] is None
    assert entry["flag"] is False
    json.dumps(build_manifest(entries), allow_nan=False)


def test_manifest_empty_entries_allowed():
    manifest = build_manifest([])
    assert manifest == {
        "schema": "asset-gen/contact-sheet/1",
        "count": 0,
        "entries": [],
    }


@pytest.mark.parametrize("bad_entry", [None, ["index", 0], "entry", 5])
def test_manifest_rejects_non_dict_entry(bad_entry):
    with pytest.raises(
        ValueError, match=r"^INVALID_MANIFEST_ENTRY: entry 1 must be a dict"
    ):
        build_manifest([bad_entry])


@pytest.mark.parametrize(
    "bad_entry",
    [
        {"filename": "a.png"},
        {"index": 0},
        {"index": True, "filename": "a.png"},
        {"index": 0, "filename": ""},
        {"index": 0, "filename": "   "},
        {"index": 0, "filename": 3},
        {"index": "0", "filename": "a.png"},
        {"index": 1.0, "filename": "a.png"},
    ],
)
def test_manifest_rejects_bad_entries(bad_entry):
    with pytest.raises(ValueError, match=r"^INVALID_MANIFEST_ENTRY: "):
        build_manifest([bad_entry])


@pytest.mark.parametrize("bad_entries", [None, b"bytes", "abc", 5])
def test_manifest_rejects_non_sequence_entries(bad_entries):
    with pytest.raises(ValueError, match=r"^INVALID_MANIFEST_ENTRY: "):
        build_manifest(bad_entries)


def test_manifest_embeds_sheet_summary_without_png_bytes():
    res = compose_contact_sheet([_png(8, 8) for _ in range(4)], cell_px=16, gap_px=2)
    sheet = dict(res, filename="contact-sheet.png")
    manifest = build_manifest([{"index": 0, "filename": "a.png"}], sheet=sheet)
    summary = manifest["sheet"]
    assert summary == {
        "filename": "contact-sheet.png",
        "width": res["width"],
        "height": res["height"],
        "columns": res["columns"],
        "rows": res["rows"],
        "cell_px": res["cell_px"],
    }
    assert "png_bytes" not in summary
    assert json.loads(json.dumps(manifest)) == manifest


def test_manifest_sheet_without_filename_key():
    res = compose_contact_sheet([_png(8, 8)])
    manifest = build_manifest([], sheet=res)
    assert manifest["sheet"]["filename"] is None
    assert manifest["sheet"]["cell_px"] == res["cell_px"]


@pytest.mark.parametrize(
    "bad_sheet",
    [
        "sheet.png",
        5,
        {},
        {"width": 1},
        {
            "filename": "s.png",
            "width": "1",
            "height": 1,
            "columns": 1,
            "rows": 1,
            "cell_px": 1,
        },
    ],
)
def test_manifest_rejects_bad_sheet(bad_sheet):
    with pytest.raises(ValueError, match=r"^INVALID_SHEET_SUMMARY: "):
        build_manifest([], sheet=bad_sheet)
