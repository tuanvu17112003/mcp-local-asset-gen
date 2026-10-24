"""Assembled postprocess pipeline (contract C3-processed-asset v0.1.1).

``process()`` is a pure transform: PNG bytes in, file-entry dicts out.
It performs no disk writes.

Contract-field mapping note: the pinned C3 contract names the file
leaf field ``path``. This package returns the leaf under the key
``filename``; the MCP core caller joins it with the output directory
to form the full ``path`` (``path = output_dir / filename``). The
``filename`` values follow the ``<stem>[@Nx].{png,svg}`` naming rule,
plus C3 v0.1.1 ``<stem>-<s>px.png`` icon files and ``<stem>.ico``.
"""

from __future__ import annotations

import io

from PIL import Image

from .errors import DecodeFailedError
from .export import export_ico, export_icons, export_scales
from .rembg_adapter import DEFAULT_MODEL, _require_png_signature, remove_background
from .trim import trim_and_pad
from .vectorize import vectorize_rgba


def process(
    png_bytes: bytes,
    *,
    remove_bg: bool = True,
    model: str = DEFAULT_MODEL,
    trim: bool = True,
    pad_px: int = 8,
    sizes=(1, 2, 3),
    vectorize: bool = False,
    icon_sizes=None,
    ico: bool = False,
    stem: str = "icon",
    bria_license_accepted: bool = False,
    mask_provider=None,
):
    """Run the full postprocess pipeline (pure, no disk writes).

    Steps: (1) background removal via :func:`remove_background` when
    ``remove_bg`` is true (license gate enforced there), else decode
    ``png_bytes`` directly to RGBA (failure -> ``DecodeFailedError``);
    (2) trim via :func:`trim_and_pad` when ``trim`` is true (``trim=False``
    skips both trim and pad); (3) vectorization via
    :func:`vectorize_rgba` — ``vectorize=True`` appends the
    ``<stem>.svg`` entry last (a missing vtracer install or a tracing
    failure raises ``VectorizeFailedError``);
    (4) multi-resolution export via :func:`export_scales`;
    (5) when ``icon_sizes`` is given (C3 v0.1.1), one square icon PNG
    per size via :func:`export_icons`, appended AFTER the ``@Nx``
    entries in ``icon_sizes`` order — each is a center square-crop of
    the FINAL base image (post trim/pad) Lanczos-resized to
    ``(s, s)``; sizes are core-validated pre-call, so no validation
    happens here; (6) when ``ico`` is true, one multi-size
    ``<stem>.ico`` container via :func:`export_ico`, appended LAST
    (derived internally even when ``icon_sizes`` is ``None``).

    ``alpha`` is defined EXACTLY as: True when the final base image
    has an alpha channel with any transparent pixel (alpha min < 255),
    OR ``remove_bg`` was requested. The canned path therefore yields
    True. ``model_used`` is the requested ``model`` string when
    ``remove_bg`` is true, else ``"none"``.

    Returns ``dict{files, alpha, model_used}`` where each file entry is
    ``{filename, width, height, scale, png_bytes}``; see the module
    docstring for the ``filename``-vs-contract-``path`` mapping.
    Ordering: ``@Nx`` entries, then icon PNGs (``scale:"icon<s>"``),
    then the ``.ico`` entry (``scale:"ico"``) when requested. The
    ``.ico`` entry reuses the ``png_bytes`` key for its ICO container
    bytes (``width``/``height`` 64/64); ``icon_sizes=None``/``[]`` with
    ``ico=False`` is byte-identical to the pre-icon behavior.
    """
    # Strict PNG-first (C3 invalid example): reject non-PNG bytes before
    # any decode attempt (covers both remove_bg paths).
    _require_png_signature(png_bytes)

    if remove_bg:
        base = remove_background(
            png_bytes,
            model,
            bria_license_accepted=bria_license_accepted,
            mask_provider=mask_provider,
        )
    else:
        try:
            img = Image.open(io.BytesIO(png_bytes))
            img.load()
        except Exception as exc:
            raise DecodeFailedError(
                f"[DECODE_FAILED] input bytes are not a decodable PNG: {exc}"
            ) from exc
        base = img.convert("RGBA")

    if trim:
        base = trim_and_pad(base, pad_px=pad_px)

    # Vectorization (C3 v0.2): vectorize=True appends the ``<stem>.svg``
    # entry LAST (after the @Nx/icon/.ico entries); failure raises
    # VectorizeFailedError, so the caller never receives files as a
    # success in that case.
    svg_entry = vectorize_rgba(base, stem, vectorize=vectorize)

    files = export_scales(base, stem, sizes=sizes)

    # C3 v0.1.1 icons: @Nx entries first, then icon PNGs in
    # icon_sizes order, then the .ico container last. Falsy
    # icon_sizes (None/[]) adds nothing; ico=True without
    # icon_sizes still produces the .ico (sizes derived inside).
    if icon_sizes:
        files.extend(export_icons(base, stem, icon_sizes))
    if ico:
        files.append(export_ico(base, stem))
    if svg_entry is not None:
        files.append(svg_entry)

    if remove_bg:
        alpha = True
    else:
        try:
            alpha_min, _alpha_max = base.getchannel("A").getextrema()
            alpha = alpha_min < 255
        except Exception:
            alpha = False

    return {
        "files": files,
        "alpha": alpha,
        "model_used": model if remove_bg else "none",
    }
