"""Shared canned-mask helper for postprocess tests."""

from __future__ import annotations

import io

from PIL import Image


def canned_center_square(png_bytes: bytes) -> Image.Image:
    """Canned mask: 512x512 'L', centered 256x256 opaque square."""
    base = Image.open(io.BytesIO(png_bytes))
    w, h = base.size
    assert (w, h) == (512, 512)
    mask = Image.new("L", (w, h), 0)
    mask.paste(255, (128, 128, 384, 384))
    return mask
