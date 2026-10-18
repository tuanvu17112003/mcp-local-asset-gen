"""Vectorization stub (contract C3-processed-asset v0.1.0).

PNG-first decision per Q4: vtracer-based SVG output is deferred
post-MVP. This module exposes only the interface seam so the pipeline
can fail loudly when vectorization is requested. No vtracer import,
no implementation, no vtracer dependency.
"""

from __future__ import annotations

from .errors import VectorizeFailedError


def vectorize_rgba(rgba, stem, *, vectorize=False, **_):
    """Stub seam for future SVG vectorization.

    ``vectorize=False`` (default) returns ``None`` (no SVG entry).
    ``vectorize=True`` raises ``VectorizeFailedError`` stating the
    deferral; the future pin (vtracer 1.0.0a4 API differs from 0.6.x —
    re-pin at re-activation) must be revisited when re-activated.
    Extra keywords are accepted and ignored so callers can pass
    future options without breaking.
    """
    if not vectorize:
        return None
    raise VectorizeFailedError(
        "[VECTORIZE_FAILED] SVG vectorization is deferred post-MVP per the "
        "Q4 PNG-first decision (vtracer deferred); re-activation must re-pin "
        "vtracer (1.0.0a4 API differs from 0.6.x) before implementing."
    )
