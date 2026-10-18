"""Postprocess error hierarchy (contract C3-processed-asset v0.1.0).

Each exception carries a ``.code`` matching the contract error string, and
the string form of the exception always embeds that code.
"""

from __future__ import annotations


class PostprocessError(Exception):
    """Base postprocess error."""

    code = "POSTPROCESS_ERROR"

    def __init__(self, message: str = "") -> None:
        if self.code not in (message or ""):
            message = f"[{self.code}] {message}" if message else f"[{self.code}]"
        super().__init__(message)


class DecodeFailedError(PostprocessError):
    """Input bytes are not a decodable PNG."""

    code = "DECODE_FAILED"


class SegmentationFailedError(PostprocessError):
    """Background segmentation / live-model path failed."""

    code = "SEGMENTATION_FAILED"


class LicenseRequiredError(PostprocessError):
    """Commercially restricted model used without explicit acceptance."""

    code = "LICENSE_REQUIRED"


class VectorizeFailedError(PostprocessError):
    """Vectorization failed (slice-pp2 seam; defined here for stability)."""

    code = "VECTORIZE_FAILED"
