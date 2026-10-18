"""Multi-resolution PNG export (contract C3-processed-asset v0.1.1).

The base image passed in is the ``@1x``; higher scales are exact integer
multiples. All encoding is in-memory (no disk I/O).

Icon rendering (C3 v0.1.1, ``icon_sizes``/``ico``): each icon size is a
center square-crop of the final base image (side ``min(w, h)``; a no-op
copy when already square) followed by a Lanczos resize to ``(s, s)``.
The ``.ico`` entry is a multi-size Pillow ICO container holding the
16/32/48/64 px directory entries generated from the deterministic 64 px
render (pixel-identical to the ``icon64`` entry when ``64`` is among
``icon_sizes``, else derived via the same square-crop+Lanczos path).
"""

from __future__ import annotations

import io
import re

from PIL import Image

_STEM_RE = re.compile(r"[A-Za-z0-9._-]+")

_RESAMPLE = getattr(Image, "LANCZOS", Image.BICUBIC)


def scale_filename(stem: str, scale: int) -> str:
    """Return the PNG leaf filename for ``stem`` at ``scale``.

    ``1`` -> ``"<stem>.png"``; ``N`` -> ``"<stem>@<N>x.png"``.

    The stem is basename-sanitized (rejected, not silently fixed):
    empty/whitespace-only, any path separator (``/`` or ``\\``),
    any ``..`` substring, or any character outside ``[A-Za-z0-9._-]``
    raises ``ValueError``. ``scale`` must be an ``int`` (``bool`` is
    rejected) greater than 0, else ``ValueError``.
    """
    if not isinstance(stem, str) or not stem.strip():
        raise ValueError(f"stem must be a non-empty string, got {stem!r}")
    if "/" in stem or "\\" in stem:
        raise ValueError(f"stem must not contain path separators: {stem!r}")
    if ".." in stem:
        raise ValueError(f"stem must not contain '..': {stem!r}")
    if _STEM_RE.fullmatch(stem) is None:
        raise ValueError(f"stem has non-PNG-safe chars: {stem!r}")
    if isinstance(scale, bool) or not isinstance(scale, int):
        raise ValueError(f"scale must be an int > 0, got {scale!r}")
    if scale <= 0:
        raise ValueError(f"scale must be an int > 0, got {scale!r}")
    if scale == 1:
        return f"{stem}.png"
    return f"{stem}@{scale}x.png"


def export_scales(rgba: Image.Image, stem: str, sizes=(1, 2, 3)):
    """Export ``rgba`` at each integer scale in ``sizes``.

    The input image is the ``@1x``; scale ``N`` is exactly
    ``(width*N, height*N)`` via high-quality resampling
    (LANCZOS, BICUBIC fallback). Each entry is encoded to PNG bytes
    in-memory; no disk I/O is performed.

    Returns a list of dicts
    ``{filename, width, height, scale, png_bytes}`` in ``sizes`` order.

    Empty ``sizes`` raises ``ValueError``; any non-int (``bool``
    included) or ``<= 0`` scale raises ``ValueError``; bad stems raise
    ``ValueError`` via :func:`scale_filename`.
    """
    if sizes is None:
        raise ValueError("sizes must be a non-empty sequence of int scales")
    try:
        scales = list(sizes)
    except TypeError as exc:
        raise ValueError(f"sizes must be a sequence of int scales: {exc}") from exc
    if not scales:
        raise ValueError("sizes must be a non-empty sequence of int scales")
    for s in scales:
        if isinstance(s, bool) or not isinstance(s, int):
            raise ValueError(f"scale must be an int > 0, got {s!r}")
        if s <= 0:
            raise ValueError(f"scale must be an int > 0, got {s!r}")

    base = rgba.convert("RGBA") if rgba.mode != "RGBA" else rgba
    bw, bh = base.size
    out: list[dict] = []
    for scale in scales:
        if scale == 1:
            img = base
        else:
            img = base.resize((bw * scale, bh * scale), _RESAMPLE)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(
            {
                "filename": scale_filename(stem, scale),
                "width": bw * scale,
                "height": bh * scale,
                "scale": scale,
                "png_bytes": buf.getvalue(),
            }
        )
    return out


# ICO directory sizes embedded in the ``.ico`` container (C3 v0.1.1).
_ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64)]
_ICO_LARGEST = 64


def icon_filename(stem: str, size: int) -> str:
    """Return the icon PNG leaf filename for ``stem`` at pixel ``size``.

    ``size`` -> ``"<stem>-<size>px.png"`` (e.g. ``"icon-16px.png"``).

    Stem rules are identical to :func:`scale_filename` (delegated, so
    path separators and unsafe chars raise ``ValueError``). ``size``
    is used as-given: icon sizes are core-validated pre-call per
    contract C3 v0.1.1, so no size validation happens here.
    """
    scale_filename(stem, 1)  # validate stem only; discard the @1x name
    return f"{stem}-{size}px.png"


def _square_crop(rgba: Image.Image) -> Image.Image:
    """Center square-crop ``rgba`` (side ``min(w, h)``).

    Square input yields an equal-size copy; non-square input is
    centered on both axes. Icons are square by construction.
    """
    w, h = rgba.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return rgba.crop((left, top, left + side, top + side))


def _icon_render(rgba: Image.Image, size: int) -> Image.Image:
    """Render one square icon: center square-crop, then Lanczos to ``(size, size)``."""
    base = rgba.convert("RGBA") if rgba.mode != "RGBA" else rgba
    return _square_crop(base).resize((size, size), _RESAMPLE)


def export_icons(rgba: Image.Image, stem: str, icon_sizes) -> list[dict]:
    """Export one square icon PNG per size in ``icon_sizes`` (order preserved).

    Each entry is ``{filename:"<stem>-<s>px.png", width:s, height:s,
    scale:"icon<s>", png_bytes}`` with in-memory PNG encoding (no disk
    I/O). Sizes are used as-given (core-validated per C3 v0.1.1).
    """
    out: list[dict] = []
    for size in icon_sizes:
        img = _icon_render(rgba, size)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(
            {
                "filename": icon_filename(stem, size),
                "width": size,
                "height": size,
                "scale": f"icon{size}",
                "png_bytes": buf.getvalue(),
            }
        )
    return out


def export_ico(rgba: Image.Image, stem: str) -> dict:
    """Export the multi-size ``<stem>.ico`` container entry (C3 v0.1.1).

    The 16/32/48/64 px directory entries are generated by Pillow from
    the deterministic 64 px render (the same square-crop+Lanczos path
    as :func:`export_icons`, so pixel-identical to the ``icon64``
    entry when ``64`` was requested, else derived from the final
    base). Bytes start with ICO magic ``00 00 01 00``.

    Entry shape reuses the ``png_bytes`` key (holding the ICO
    container bytes) so consumers iterate one bytes field;
    ``width``/``height`` are the largest embedded size (64, 64) and
    ``scale`` is ``"ico"``.
    """
    scale_filename(stem, 1)  # validate stem only; the .ico name needs no scale
    src = _icon_render(rgba, _ICO_LARGEST)
    buf = io.BytesIO()
    src.save(buf, format="ICO", sizes=list(_ICO_SIZES))
    return {
        "filename": f"{stem}.ico",
        "width": _ICO_LARGEST,
        "height": _ICO_LARGEST,
        "scale": "ico",
        "png_bytes": buf.getvalue(),
    }
