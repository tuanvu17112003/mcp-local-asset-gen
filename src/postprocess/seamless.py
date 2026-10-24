"""Seamless-tiling postprocess (P2, pattern slice 2026-10-24).

``make_seamless`` applies the classic edge cross-fade: the last
``feather`` columns are faded into the first ones (and the same for
rows), so the tile wraps continuously at the period boundary. Pure
Pillow, deterministic, size-preserving — FLUX.1-schnell has no native
tiling, so this is the dependency-free route (see
``docs/research/pattern-features-research-2026-10-24.md``).

shortcut: cross-fade ghosting can show on hard-structured motifs; if
quality disappoints, upgrade to circular padding via a ComfyUI
seamless-tiling custom node (research F1.4 / proposal P5).
"""

from __future__ import annotations

import io

from PIL import Image

#: Blend band width in px (clamped to a quarter of each side).
DEFAULT_FEATHER = 32


def make_seamless(rgba, feather: int = DEFAULT_FEATHER):
    """Return a wrap-continuous copy of ``rgba`` (same size, RGBA).

    The right ``feather`` columns are cross-faded with the left ones
    (and the bottom rows with the top ones), so opposite edges join
    smoothly when the image repeats. ``feather`` is clamped to
    ``min(side)//4`` (min 1), so tiny inputs degrade gracefully. A
    feather of 0 (or negative) returns a copy unchanged.
    """
    img = rgba.convert("RGBA") if rgba.mode != "RGBA" else rgba.copy()
    w, h = img.size
    f = min(feather, w // 4, h // 4)
    if f < 1:
        return img

    # Horizontal: the last f columns fade into the first f columns
    # (t ramps 0 -> 1 across the band), so column W-1 continues into
    # column 0 when the tile repeats.
    band = img.crop((w - f, 0, w, h))
    first = img.crop((0, 0, f, h))
    # linear_gradient("L") is 256x256, 0 at top -> 255 at bottom; rotate
    # +90 so the ramp runs left -> right (0 at band-left, 255 at
    # band-right), then resize to the band.
    mask = Image.linear_gradient("L").rotate(90, expand=True).resize((f, h))
    img.paste(Image.composite(first, band, mask), (w - f, 0))

    # Vertical: same fade for the bottom rows into the top ones.
    band = img.crop((0, h - f, w, h))
    first = img.crop((0, 0, w, f))
    mask = Image.linear_gradient("L").resize((w, f))
    img.paste(Image.composite(first, band, mask), (0, h - f))
    return img


def export_tile_preview(rgba, stem: str):
    """Render a 2x2 tiled preview ``{filename, width, height, png_bytes}``.

    The preview is the tile repeated once per axis (canvas ``2w x 2h``)
    so a viewer can judge the seams. No ``scale`` key (size is carried
    by ``width``/``height``); bytes land under the shared ``png_bytes``
    carrier like every other file entry.
    """
    img = rgba.convert("RGBA") if rgba.mode != "RGBA" else rgba
    w, h = img.size
    canvas = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    for x in (0, w):
        for y in (0, h):
            canvas.paste(img, (x, y))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return {
        "filename": f"{stem}-tile.png",
        "width": w * 2,
        "height": h * 2,
        "png_bytes": buf.getvalue(),
    }
