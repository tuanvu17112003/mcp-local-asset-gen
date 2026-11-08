"""Assembled postprocess pipeline (contract C3-processed-asset v0.1.1).

``process()`` is a pure transform: PNG bytes in, file-entry dicts out.
It performs no disk writes.

P1 (v0.8.0) adds ``resize_to``: an optional ``(width, height)`` target
applied to the base image right after it is established (post background
removal / decode) and BEFORE trim/pad, palette, vectorization and the
export stages, so trim/pad, the ``@Nx`` exports, the icon renders and the
``.ico`` container all operate on the final resized base. ``None`` (the
default) is a strict no-op: the pre-P1 behaviour is byte-identical.

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
from .palette import recolor_to_palette
from .rembg_adapter import DEFAULT_MODEL, _require_png_signature, remove_background
from .seamless import export_tile_preview, make_seamless
from .symmetry import symmetrize
from .trim import trim_and_pad
from .vectorize import vectorize_rgba

_RESAMPLE = getattr(Image, "LANCZOS", Image.BICUBIC)


def _validate_resize_to(resize_to):
    """Return ``(width, height)`` for a valid ``resize_to``; raise on anything else.

    A valid target is a 2-tuple/list of positive ``int`` pixels (``bool`` is
    rejected even though it subclasses ``int``). ``None`` passes through
    (resize disabled). Any other value -- a non-pair, a float, a string,
    0/negative sides -- raises ``ValueError`` ``INVALID_RESIZE_TO``.
    """
    if resize_to is None:
        return None
    if not isinstance(resize_to, (tuple, list)) or len(resize_to) != 2:
        raise ValueError(
            f"INVALID_RESIZE_TO: resize_to must be a (width, height) pair of "
            f"positive ints, got {resize_to!r}"
        )
    for side in resize_to:
        if isinstance(side, bool) or not isinstance(side, int) or side <= 0:
            raise ValueError(
                f"INVALID_RESIZE_TO: resize_to must be a (width, height) pair of "
                f"positive ints, got {resize_to!r}"
            )
    return (resize_to[0], resize_to[1])


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
    seamless: bool = False,
    palette=None,
    symmetry=None,
    resize_to=None,
):
    """Run the full postprocess pipeline (pure, no disk writes).

    Steps: (1) background removal via :func:`remove_background` when
    ``remove_bg`` is true (license gate enforced there), else decode
    ``png_bytes`` directly to RGBA (failure -> ``DecodeFailedError``);
    (2) P1 ``resize_to`` when given: Lanczos resize to ``(width, height)``
    right after the base is established and BEFORE trim/pad, so the
    trimmed/padded base, the ``@Nx`` exports, the icon renders and the
    ``.ico`` container all derive from the resized base
    (``resize_to=None`` leaves the image untouched); (3) trim via
    :func:`trim_and_pad` when ``trim`` is true (``trim=False`` skips both
    trim and pad); (4) vectorization via
    :func:`vectorize_rgba` — ``vectorize=True`` appends the
    ``<stem>.svg`` entry last (a missing vtracer install or a tracing
    failure raises ``VectorizeFailedError``);
    (5) multi-resolution export via :func:`export_scales`;
    (6) when ``icon_sizes`` is given (C3 v0.1.1), one square icon PNG
    per size via :func:`export_icons`, appended AFTER the ``@Nx``
    entries in ``icon_sizes`` order — each is a center square-crop of
    the FINAL base image (post trim/pad) Lanczos-resized to
    ``(s, s)``; sizes are core-validated pre-call, so no validation
    happens here; (7) when ``ico`` is true, one multi-size
    ``<stem>.ico`` container via :func:`export_ico`, appended LAST
    (derived internally even when ``icon_sizes`` is ``None``);
    (8) when ``seamless`` is true (P2): the base is made wrap-continuous
    via :func:`make_seamless` BEFORE trim (trim is forced off — cropping
    would destroy periodicity) and a ``<stem>-tile.png`` 2x2 preview is
    appended after the ``.ico`` entry.

    ``alpha`` is defined EXACTLY as: True when the final base image
    has an alpha channel with any transparent pixel (alpha min < 255),
    OR ``remove_bg`` was requested. The canned path therefore yields
    True. ``model_used`` is the requested ``model`` string when
    ``remove_bg`` is true, else ``"none"``.

    ``resize_to`` is validated up-front: not a 2-tuple/list of positive
    ints -> ``ValueError`` ``INVALID_RESIZE_TO`` (before any decoding,
    so a bad target never costs a segmentation run).

    Returns ``dict{files, alpha, model_used}`` where each file entry is
    ``{filename, width, height, scale, png_bytes}``; see the module
    docstring for the ``filename``-vs-contract-``path`` mapping.
    Ordering: ``@Nx`` entries, then icon PNGs (``scale:"icon<s>"``),
    then the ``.ico`` entry (``scale:"ico"``) when requested. The
    ``.ico`` entry reuses the ``png_bytes`` key for its ICO container
    bytes (``width``/``height`` 64/64); ``icon_sizes=None``/``[]`` with
    ``ico=False`` is byte-identical to the pre-icon behavior.
    """
    # P1 pre-flight first: a bad resize target must fail before the
    # (potentially expensive) segmentation stage runs.
    resize = _validate_resize_to(resize_to)

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

    # P1: the resized image becomes the base for every later stage, so
    # trim/pad, the @Nx exports, the icon renders, the .ico container and
    # the tile preview are all sized off it.
    if resize is not None:
        base = base.convert("RGBA") if base.mode != "RGBA" else base
        base = base.resize(resize, _RESAMPLE)

    # Then geometry (P4), tiling (P2, forces trim off), trim,
    # then exact colors (P3) so every exported entry carries the palette.
    # The P1 resize already ran above, so everything below sees the final
    # base size.
    if symmetry:
        base = symmetrize(base, symmetry)

    tile_preview = None
    if seamless:
        base = make_seamless(base)
        trim = False

    if trim:
        base = trim_and_pad(base, pad_px=pad_px)

    if palette:
        base = recolor_to_palette(base, palette)

    if seamless:
        tile_preview = export_tile_preview(base, stem)

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
    if tile_preview is not None:
        files.append(tile_preview)
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
