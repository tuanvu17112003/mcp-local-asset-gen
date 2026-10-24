"""Vectorization (contract C3 v0.2): vtracer-based SVG output.

The Q4 PNG-first deferral is lifted (2026-10-24): ``vectorize_rgba``
traces the final RGBA via the stable PyPI pin ``vtracer==0.6.15``
(legacy ``convert_image_to_svg_py`` file-to-file API; the 1.0.0a*
``convert_bytes`` API is still pre-release). Probed 2026-10-24: fully
transparent pixels are NOT traced, so a transparent-background icon
yields an SVG with no background fill — no matte flattening needed.
"""

from __future__ import annotations

import os
import tempfile

from .errors import VectorizeFailedError


def vectorize_rgba(rgba, stem, *, vectorize=False, **_):
    """Trace ``rgba`` to an SVG entry when ``vectorize`` is true.

    ``vectorize=False`` (default) returns ``None`` (no SVG entry).
    ``vectorize=True`` runs vtracer in ``color``/``stacked``/``spline``
    mode and returns ``{filename: "<stem>.svg", scale: "svg",
    png_bytes: <svg bytes>}`` — the ``png_bytes`` key is reused for the
    SVG payload (same convention as the ``.ico`` entry). A missing
    ``vtracer`` install, a tracing failure, or empty output raises
    ``VectorizeFailedError``. Extra keywords are accepted and ignored.
    """
    if not vectorize:
        return None
    try:
        import vtracer
    except ImportError as exc:
        raise VectorizeFailedError(
            "[VECTORIZE_FAILED] the 'vtracer' package is not installed "
            "(pip install vtracer==0.6.15); SVG output is unavailable"
        ) from exc
    base = rgba.convert("RGBA") if rgba.mode != "RGBA" else rgba
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, f"{stem}.png")
        dst = os.path.join(tmp, f"{stem}.svg")
        base.save(src, format="PNG")
        try:
            vtracer.convert_image_to_svg_py(
                src,
                dst,
                colormode="color",
                hierarchical="stacked",
                mode="spline",
                filter_speckle=4,
            )
        except Exception as exc:
            raise VectorizeFailedError(
                f"[VECTORIZE_FAILED] vtracer tracing failed: {exc}"
            ) from exc
        try:
            with open(dst, "rb") as fh:
                svg_bytes = fh.read()
        except OSError as exc:
            raise VectorizeFailedError(
                f"[VECTORIZE_FAILED] reading traced SVG failed: {exc}"
            ) from exc
    if not svg_bytes:
        raise VectorizeFailedError(
            "[VECTORIZE_FAILED] vtracer produced an empty SVG"
        )
    return {"filename": f"{stem}.svg", "scale": "svg", "png_bytes": svg_bytes}
