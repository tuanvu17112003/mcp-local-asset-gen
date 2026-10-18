"""Alpha trim + uniform transparent padding (seam for slice-pp2)."""

from __future__ import annotations

from PIL import Image


def trim_and_pad(rgba, pad_px: int = 8):
    """Crop to the alpha>0 bbox, then add uniform transparent padding.

    Fully-transparent input (empty bbox) returns a copy unchanged.
    Negative ``pad_px`` raises ValueError. ``pad_px=0`` returns the
    tight crop (or a copy when fully transparent).
    """
    if pad_px < 0:
        raise ValueError(f"pad_px must be >= 0, got {pad_px!r}")
    img = rgba.convert("RGBA") if rgba.mode != "RGBA" else rgba.copy()
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        # Fully transparent: nothing to trim; return copy unchanged.
        return img.copy()
    cropped = img.crop(bbox)
    if pad_px == 0:
        return cropped
    w, h = cropped.size
    out = Image.new("RGBA", (w + 2 * pad_px, h + 2 * pad_px), (0, 0, 0, 0))
    out.paste(cropped, (pad_px, pad_px))
    return out
