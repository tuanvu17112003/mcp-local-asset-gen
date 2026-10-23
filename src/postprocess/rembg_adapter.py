"""Background-removal adapter (contract C3-processed-asset v0.1.1).

Pillow-only canned path + version-guarded lazy live path. The adapter never
downloads a model itself, but the live path asks ``rembg`` for a session: if
the model is absent, ``rembg.new_session`` downloads it once (network
required) — pre-download it before an offline run (see ``setup_notes.md``).
"""

from __future__ import annotations

import io
import sys

from PIL import Image

from .errors import DecodeFailedError, LicenseRequiredError, SegmentationFailedError

SUPPORTED_MODELS = ("u2net", "isnet-general-use", "bria-rmbg")
DEFAULT_MODEL = "u2net"
QUALITY_MODEL = "isnet-general-use"
BRIA_MODEL = "bria-rmbg"
MIN_PYTHON = (3, 11)

# Strict PNG-first (C3 invalid example): the 8-byte PNG signature.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _require_png_signature(data: bytes) -> None:
    """Reject non-PNG input bytes before any decode attempt or version guard."""
    if (
        not isinstance(data, (bytes, bytearray))
        or bytes(data[:8]) != _PNG_SIGNATURE
    ):
        raise DecodeFailedError(
            "[DECODE_FAILED] input bytes are not a PNG image "
            "(bad or missing PNG signature)."
        )


def remove_background(
    png_bytes: bytes,
    model: str = DEFAULT_MODEL,
    *,
    bria_license_accepted: bool = False,
    mask_provider=None,
):
    """Remove background, returning an RGBA ``PIL.Image``.

    Order: (0) non-PNG bytes -> DecodeFailedError (strict PNG-first);
    (a) unknown model -> ValueError; (b) bria-rmbg without
    acceptance -> LicenseRequiredError; (c) canned ``mask_provider``
    path (no ``rembg`` import attempted); (d) live ``rembg`` path with
    Python-floor guard and lazy import. The adapter itself never downloads:
    a cached model is used; a missing model makes ``rembg`` fetch it once
    (network required) — pre-download before offline runs.
    """
    # (0) strict PNG-first: before any decode attempt or version guard.
    _require_png_signature(png_bytes)

    # (a) unknown model.
    if model not in SUPPORTED_MODELS:
        raise ValueError(
            f"unknown model {model!r}; supported: {', '.join(SUPPORTED_MODELS)}"
        )

    # (b) bria-rmbg license gate (RMBG-1.4 is NON-commercial).
    if model == BRIA_MODEL and not bria_license_accepted:
        raise LicenseRequiredError(
            "[LICENSE_REQUIRED] model 'bria-rmbg' (RMBG-1.4) is NON-commercial "
            "and requires a paid BRIA agreement for commercial use; pass "
            "bria_license_accepted=True only after accepting those terms."
        )

    # (c) canned-mask path: decode, apply provider mask as alpha.
    # No `rembg` import is attempted on this path.
    if mask_provider is not None:
        try:
            base = Image.open(io.BytesIO(png_bytes))
            base.load()
        except Exception as exc:
            raise DecodeFailedError(
                f"[DECODE_FAILED] input bytes are not a decodable PNG: {exc}"
            ) from exc
        base = base.convert("RGBA")
        try:
            mask = mask_provider(png_bytes)
        except Exception as exc:
            raise SegmentationFailedError(
                f"[SEGMENTATION_FAILED] mask_provider failed: {exc}"
            ) from exc
        if mask.mode != "L":
            mask = mask.convert("L")
        if mask.size != base.size:
            mask = mask.resize(base.size, Image.NEAREST)
        base.putalpha(mask)
        return base

    # (d) live path.
    try:
        probe = Image.open(io.BytesIO(png_bytes))
        probe.load()
    except Exception as exc:
        raise DecodeFailedError(
            f"[DECODE_FAILED] input bytes are not a decodable PNG: {exc}"
        ) from exc

    if sys.version_info < MIN_PYTHON:
        raise SegmentationFailedError(
            "[SEGMENTATION_FAILED] live background-removal models require "
            "Python >=3.11 (this interpreter is "
            f"{sys.version_info[0]}.{sys.version_info[1]}); re-run under "
            "`uv run --python 3.11` or a Python 3.11+ venv with rembg "
            "installed and models pre-downloaded."
        )

    try:
        import rembg  # lazy: only on the live path
    except ImportError as exc:
        raise SegmentationFailedError(
            "[SEGMENTATION_FAILED] 'rembg' is not installed (Python 3.11+ "
            "required). Install it first (`pip install -r requirements.txt`), "
            "then pre-download the model once (network required) with "
            f"`python -c \"from rembg import new_session; new_session('{model}')\"` "
            "(honouring the model cache) before using the live path."
        ) from exc

    try:
        session = rembg.new_session(model)
        out_bytes = rembg.remove(png_bytes, session=session)
        out = Image.open(io.BytesIO(out_bytes))
        out.load()
        return out.convert("RGBA")
    except SegmentationFailedError:
        raise
    except Exception as exc:
        raise SegmentationFailedError(
            f"[SEGMENTATION_FAILED] rembg model {model!r} failed: {exc}"
        ) from exc

