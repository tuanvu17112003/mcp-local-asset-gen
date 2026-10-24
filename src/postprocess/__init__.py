"""Postprocess pipeline (slices pp1+pp2).

Producer of contract C3-processed-asset v0.1.1 (canned-path side).

Live-model note: the ``rembg`` live path requires Python >=3.11 plus an
offline pre-downloaded model cache (``python -c "from rembg import
new_session; new_session('<model>')"``, ``U2NET_HOME``); on older
interpreters :func:`remove_background` raises ``SegmentationFailedError``
without attempting any download. The ``rembg`` CLI extra is not installed
(see ``requirements.txt``).
"""

from __future__ import annotations

from .errors import (
    DecodeFailedError,
    LicenseRequiredError,
    PostprocessError,
    SegmentationFailedError,
    VectorizeFailedError,
)
from .export import export_icons, export_ico, export_scales, icon_filename, scale_filename
from .pipeline import process
from .rembg_adapter import (
    BRIA_MODEL,
    DEFAULT_MODEL,
    MIN_PYTHON,
    QUALITY_MODEL,
    SUPPORTED_MODELS,
    remove_background,
)
from .seamless import export_tile_preview, make_seamless
from .symmetry import symmetrize
from .palette import recolor_to_palette
from .trim import trim_and_pad
from .vectorize import vectorize_rgba

__version__ = "0.6.0"

__all__ = [
    "__version__",
    "PostprocessError",
    "DecodeFailedError",
    "SegmentationFailedError",
    "LicenseRequiredError",
    "VectorizeFailedError",
    "remove_background",
    "trim_and_pad",
    "export_scales",
    "scale_filename",
    "export_icons",
    "export_ico",
    "icon_filename",
    "vectorize_rgba",
    "make_seamless",
    "export_tile_preview",
    "symmetrize",
    "recolor_to_palette",
    "process",
    "SUPPORTED_MODELS",
    "DEFAULT_MODEL",
    "QUALITY_MODEL",
    "BRIA_MODEL",
    "MIN_PYTHON",
]
