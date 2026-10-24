"""Palette recolor (P3): map the image onto brand colors (deterministic).

``recolor_to_palette`` quantizes the image to ``len(colors)`` clusters
(Pillow FASTOCTREE, the only quantize method that supports RGBA) and
replaces every cluster's RGB with the NEAREST user color (Euclidean,
alpha kept per entry). Output colors are therefore always exactly the
user's palette — prompt color words stay the soft first pass, this is
the exact pass.
"""

from __future__ import annotations

from PIL import Image


def _hex_to_rgb(value: str):
    digits = value[1:]
    if len(digits) == 3:  # "#abc" -> "#aabbcc"
        digits = "".join(ch * 2 for ch in digits)
    return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))


def recolor_to_palette(rgba, colors):
    """Return ``rgba`` recolored so every pixel RGB is one of ``colors``.

    ``colors`` is a list of validated ``#rrggbb`` strings (2..8, checked
    upstream). Alpha is preserved per quantized cluster; the image size
    and mode are unchanged. Deterministic: quantize + nearest-neighbor
    mapping involve no randomness.
    """
    img = rgba.convert("RGBA") if rgba.mode != "RGBA" else rgba.copy()
    targets = [_hex_to_rgb(c) for c in colors]
    q = img.quantize(colors=len(targets), method=Image.Quantize.FASTOCTREE)
    pal = q.getpalette("RGBA")
    stride = 4
    new_pal = []
    for idx in range(len(pal) // stride):
        r, g, b, a = pal[idx * stride : idx * stride + 4]
        nr, ng, nb = min(
            targets,
            key=lambda t: (t[0] - r) ** 2 + (t[1] - g) ** 2 + (t[2] - b) ** 2,
        )
        new_pal += [nr, ng, nb, a]
    q.putpalette(new_pal, rawmode="RGBA")
    return q.convert("RGBA")
