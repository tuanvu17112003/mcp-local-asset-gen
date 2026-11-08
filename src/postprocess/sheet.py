"""Contact sheet composition: contract C3-processed-asset v0.8 (contact sheet addition).

Pure Pillow, stdlib only: no disk I/O and no new dependency. Raw PNG
bytes go in, one composed PNG (returned as bytes) comes out. The
orchestrator wires this for `generate_app_asset(..., variants=N,
contact_sheet=True)` and writes the returned `png_bytes` itself;
:func:`build_manifest` produces the deterministic JSON sidecar that
lists the variant files next to the sheet.

Layout: each cell is a `cell_px` square on a
`columns*cell_px + (columns+1)*gap_px` (same formula vertically) RGBA
canvas. Every image is Lanczos-fitted inside its cell with the aspect
ratio preserved, then centered. Transparency is preserved end-to-end
(the default background is fully transparent).
"""

from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw

__all__ = ["layout_grid", "compose_contact_sheet", "build_manifest"]

_MAX_CELL_PX = 4096
_MAX_GAP_PX = 256

_RESAMPLE = getattr(Image, "LANCZOS", Image.BICUBIC)

_MANIFEST_SCHEMA = "asset-gen/contact-sheet/1"
_SHEET_SUMMARY_KEYS = ("width", "height", "columns", "rows", "cell_px")
_REQUIRED_ENTRY_KEYS = ("index", "filename")


def _is_int(value) -> bool:
    """True for real ints only (`bool` is rejected as a value)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _rgba_tuple(value, *, code: str) -> tuple[int, int, int, int]:
    """Validate a 3-/4-tuple of int channels 0..255, returning RGBA."""
    if not isinstance(value, (tuple, list)) or len(value) not in (3, 4):
        raise ValueError(
            f"{code}: colour must be a 3- or 4-tuple of ints 0..255, got {value!r}"
        )
    channels = list(value)
    if any(not _is_int(c) or not 0 <= c <= 255 for c in channels):
        raise ValueError(
            f"{code}: colour components must be ints 0..255, got {value!r}"
        )
    if len(channels) == 3:
        channels.append(255)
    return channels[0], channels[1], channels[2], channels[3]


def _is_json_scalar(value) -> bool:
    """True for the scalar types the manifest copies verbatim."""
    if value is None or isinstance(value, (str, bool, int)):
        return True
    # Non-finite floats are not strict JSON; drop them rather than emit NaN.
    return isinstance(value, float) and math.isfinite(value)


def _decode_rgba(payload, index: int) -> Image.Image:
    """Decode raw PNG `payload` (1-based `index`) to an RGBA image.

    Empty/invalid/undecodable payloads raise
    `ValueError("DECODE_FAILED: ...")` naming the offending index.
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ValueError(
            f"DECODE_FAILED: image {index} is not a bytes-like PNG payload, "
            f"got {type(payload).__name__}"
        )
    data = bytes(payload)
    if not data:
        raise ValueError(f"DECODE_FAILED: image {index} is empty")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            return img.convert("RGBA")
    except (OSError, ValueError, TypeError, SyntaxError) as exc:
        raise ValueError(
            f"DECODE_FAILED: image {index} is not a decodable PNG: {exc}"
        ) from exc


def layout_grid(count: int, *, columns: int | None = None) -> tuple[int, int]:
    """Return `(columns, rows)` for `count` sheet cells.

    `columns=None` picks `ceil(sqrt(count))` (a near-square grid); an
    explicit `columns` must be in `1..count`. Rows are always
    `ceil(count / columns)`, so the last row may be partially empty.

    `count` must be a positive int (`bool` rejected), else
    `ValueError("INVALID_SHEET_COUNT: ...")`; an out-of-range or
    non-int `columns` raises `ValueError("INVALID_SHEET_COLUMNS: ...")`.
    """
    if not _is_int(count) or count <= 0:
        raise ValueError(
            f"INVALID_SHEET_COUNT: count must be a positive int, got {count!r}"
        )
    if columns is None:
        cols = math.isqrt(count - 1) + 1
    else:
        if not _is_int(columns):
            raise ValueError(
                f"INVALID_SHEET_COLUMNS: columns must be an int or None, "
                f"got {columns!r}"
            )
        if not 1 <= columns <= count:
            raise ValueError(
                f"INVALID_SHEET_COLUMNS: columns must be in 1..{count}, "
                f"got {columns!r}"
            )
        cols = columns
    return cols, -(-count // cols)


def compose_contact_sheet(
    images,
    *,
    columns: int | None = None,
    cell_px: int = 512,
    gap_px: int = 8,
    background=(0, 0, 0, 0),
    border_rgba=None,
) -> dict:
    """Compose `images` (raw PNG bytes, >= 1) into one in-memory PNG.

    Returns `{png_bytes, width, height, columns, rows, cell_px, count}`.
    The canvas is filled with `background` (default fully transparent);
    each image is decoded, converted to RGBA, Lanczos-fitted inside
    `cell_px` with its aspect ratio preserved, then centered in its cell
    and alpha-composited onto the canvas. `border_rgba` (4 ints 0..255)
    additionally draws a 1 px rectangle on every cell box.

    `images` must not be empty (`ValueError("INVALID_SHEET_IMAGES: at
    least one image is required")`); empty/invalid/undecodable entries
    raise `ValueError("DECODE_FAILED: ...")` with the 1-based image
    index. `cell_px` must be an int in `1..4096` (`INVALID_CELL_PX`)
    and `gap_px` an int in `0..256` (`INVALID_GAP_PX`).
    """
    if isinstance(images, (bytes, bytearray, memoryview)):
        raise ValueError(
            "INVALID_SHEET_IMAGES: expected a sequence of PNG byte strings, "
            "got bytes; wrap the single PNG in a list"
        )
    try:
        payloads = list(images)
    except TypeError as exc:
        raise ValueError(
            f"INVALID_SHEET_IMAGES: images must be a sequence of PNG byte "
            f"strings: {exc}"
        ) from exc
    if not payloads:
        raise ValueError("INVALID_SHEET_IMAGES: at least one image is required")
    cols, rows = layout_grid(len(payloads), columns=columns)
    if not _is_int(cell_px) or not 1 <= cell_px <= _MAX_CELL_PX:
        raise ValueError(
            f"INVALID_CELL_PX: cell_px must be an int in 1..{_MAX_CELL_PX}, "
            f"got {cell_px!r}"
        )
    if not _is_int(gap_px) or not 0 <= gap_px <= _MAX_GAP_PX:
        raise ValueError(
            f"INVALID_GAP_PX: gap_px must be an int in 0..{_MAX_GAP_PX}, "
            f"got {gap_px!r}"
        )
    bg = _rgba_tuple(background, code="INVALID_BACKGROUND")
    border = (
        None
        if border_rgba is None
        else _rgba_tuple(border_rgba, code="INVALID_BORDER_RGBA")
    )

    width = cols * cell_px + (cols + 1) * gap_px
    height = rows * cell_px + (rows + 1) * gap_px
    canvas = Image.new("RGBA", (width, height), bg)
    stride = cell_px + gap_px
    for offset, payload in enumerate(payloads):
        rgba = _decode_rgba(payload, offset + 1)
        rgba.thumbnail((cell_px, cell_px), _RESAMPLE)
        cell = Image.new("RGBA", (cell_px, cell_px), (0, 0, 0, 0))
        cell.paste(rgba, ((cell_px - rgba.width) // 2, (cell_px - rgba.height) // 2))
        canvas.alpha_composite(
            cell,
            (gap_px + (offset % cols) * stride, gap_px + (offset // cols) * stride),
        )

    if border is not None:
        draw = ImageDraw.Draw(canvas)
        for offset in range(len(payloads)):
            left = gap_px + (offset % cols) * stride
            top = gap_px + (offset // cols) * stride
            draw.rectangle(
                (left, top, left + cell_px - 1, top + cell_px - 1), outline=border
            )

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return {
        "png_bytes": buf.getvalue(),
        "width": width,
        "height": height,
        "columns": cols,
        "rows": rows,
        "cell_px": cell_px,
        "count": len(payloads),
    }


def _sheet_summary(sheet) -> dict:
    """Normalise `sheet` to the manifest's embedded sheet summary."""
    if not isinstance(sheet, dict):
        raise ValueError(
            "INVALID_SHEET_SUMMARY: sheet must be the dict returned by "
            f"compose_contact_sheet, got {type(sheet).__name__}"
        )
    filename = sheet.get("filename")
    if filename is not None and (not isinstance(filename, str) or not filename.strip()):
        raise ValueError(
            "INVALID_SHEET_SUMMARY: sheet 'filename' must be a non-empty "
            f"string when present, got {filename!r}"
        )
    summary: dict = {"filename": filename}
    for key in _SHEET_SUMMARY_KEYS:
        if key not in sheet:
            raise ValueError(f"INVALID_SHEET_SUMMARY: sheet is missing {key!r}")
        value = sheet[key]
        if not _is_int(value):
            raise ValueError(
                f"INVALID_SHEET_SUMMARY: sheet {key!r} must be an int, got {value!r}"
            )
        summary[key] = value
    return summary


def build_manifest(entries, *, sheet=None) -> dict:
    """Return the JSON-serialisable contact-sheet manifest.

    Shape: `{'schema': 'asset-gen/contact-sheet/1', 'count': n,
    'entries': [...]}`; `entries` are sorted by `index` ascending, so
    the same input always yields the same dict. Each manifest entry
    keeps `index`/`filename` plus any extra scalar key copied verbatim
    (str/int/float/bool/None only; nested containers, bytes and
    non-finite floats are dropped). A non-dict entry or a missing or
    invalid `index`/`filename` raises
    `ValueError("INVALID_MANIFEST_ENTRY: ...")`.

    When `sheet` is the dict from :func:`compose_contact_sheet` (its
    `png_bytes` is ignored; pass a `filename` key for the sheet leaf
    name), a `sheet` summary with `filename`, `width`, `height`,
    `columns`, `rows` and `cell_px` is embedded under the `'sheet'` key.
    """
    if isinstance(entries, (bytes, bytearray, memoryview)):
        raise ValueError(
            "INVALID_MANIFEST_ENTRY: entries must be a sequence of dicts, got bytes"
        )
    try:
        items = list(entries)
    except TypeError as exc:
        raise ValueError(
            f"INVALID_MANIFEST_ENTRY: entries must be a sequence of dicts: {exc}"
        ) from exc

    parsed: list[dict] = []
    for position, entry in enumerate(items, start=1):
        if not isinstance(entry, dict):
            raise ValueError(
                f"INVALID_MANIFEST_ENTRY: entry {position} must be a dict, "
                f"got {type(entry).__name__}"
            )
        for key in _REQUIRED_ENTRY_KEYS:
            if key not in entry:
                raise ValueError(
                    f"INVALID_MANIFEST_ENTRY: entry {position} is missing {key!r}"
                )
        index = entry["index"]
        if not _is_int(index):
            raise ValueError(
                f"INVALID_MANIFEST_ENTRY: entry {position} 'index' must be an "
                f"int, got {index!r}"
            )
        filename = entry["filename"]
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError(
                f"INVALID_MANIFEST_ENTRY: entry {position} 'filename' must be "
                f"a non-empty string, got {filename!r}"
            )
        item = {"index": index, "filename": filename}
        for key, value in entry.items():
            if not isinstance(key, str) or key in _REQUIRED_ENTRY_KEYS:
                continue
            if _is_json_scalar(value):
                item[key] = value
        parsed.append(item)

    parsed.sort(key=lambda entry: entry["index"])
    manifest: dict = {
        "schema": _MANIFEST_SCHEMA,
        "count": len(parsed),
        "entries": parsed,
    }
    if sheet is not None:
        manifest["sheet"] = _sheet_summary(sheet)
    return manifest
