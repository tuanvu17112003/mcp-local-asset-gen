"""Symmetry postprocess (P4): mirror / radial ornaments, deterministic.

* ``mirror-x``: the right half becomes a mirrored copy of the left.
* ``mirror-quad``: mirror-x + mirror-y (both axes).
* ``radial:<n>``: true n-fold rotational symmetry — the wedge from the
  center at 3 o'clock spanning 360/n degrees is extracted and rotated
  n times around the center (kaleidoscope). Off-wedge content is
  discarded; resampling can leave faint seams at wedge boundaries.

shortcut: radial fills the full circle from one wedge, so detail outside
the first wedge is lost by design; if callers want mirror + radial
combinations, upgrade to a per-axis wedge-mirror kaleidoscope.
"""

from __future__ import annotations

from PIL import Image, ImageDraw


def _mirror_x(img):
    w, h = img.size
    flipped = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    out = img.copy()
    out.paste(flipped.crop((w - (w - w // 2), 0, w, h)), (w // 2, 0))
    return out


def _mirror_y(img):
    w, h = img.size
    flipped = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    out = img.copy()
    out.paste(flipped.crop((0, h - (h - h // 2), w, h)), (0, h // 2))
    return out


def _radial(img, n):
    w, h = img.size
    cx, cy = w / 2, h / 2
    step = 360.0 / n
    # Wedge mask: sector from 3 o'clock spanning `step` degrees.
    radius = (w**2 + h**2) ** 0.5  # covers the farthest corner
    import math

    pts = [(cx, cy)]
    for i in range(0, 91):  # dense arc sampling
        ang = math.radians(i * step / 90.0)
        pts.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang)))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    wedge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    wedge.paste(img, (0, 0), mask)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for i in range(n):
        out = Image.alpha_composite(
            out, wedge.rotate(i * step, resample=Image.Resampling.BICUBIC, center=(cx, cy))
        )
    return out


def symmetrize(rgba, symmetry):
    """Apply the validated ``symmetry`` instruction; return a new image.

    ``symmetry`` is ``"mirror-x"``, ``"mirror-quad"`` or
    ``"radial:<n>"`` (n = 2..12, validated upstream). Size and RGBA mode
    are preserved; the result is deterministic.
    """
    img = rgba.convert("RGBA") if rgba.mode != "RGBA" else rgba.copy()
    if symmetry == "mirror-x":
        return _mirror_x(img)
    if symmetry == "mirror-quad":
        return _mirror_y(_mirror_x(img))
    if symmetry and symmetry.startswith("radial:"):
        return _radial(img, int(symmetry.split(":", 1)[1]))
    raise ValueError(f"UNKNOWN_SYMMETRY: {symmetry!r}")
