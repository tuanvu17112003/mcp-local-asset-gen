"""C1 error taxonomy (contract ``C1-mcp-asset-tool`` v0.1.0).

Each exception carries a ``.code`` equal to the contract error string, and
the string form always embeds that code so callers never parse messages.

Sibling-code mapping (C2 ``src/gen_backend/errors.py``,
C3 ``src/postprocess/errors.py``)::

    COMFY_UNREACHABLE -> BACKEND_UNAVAILABLE
    MODEL_NOT_FOUND   -> MODEL_MISSING
    QUEUE_FULL        -> QUEUED (also raised past ``max_concurrent`` = 2 jobs)
    JOB_FAILED        -> GENERATION_FAILED
    JOB_TIMEOUT       -> GENERATION_FAILED
    UNKNOWN_WORKFLOW  -> GENERATION_FAILED (server-side workflow-registry
                         misconfiguration surfaces as a generation failure)
    DECODE_FAILED / SEGMENTATION_FAILED / VECTORIZE_FAILED -> POSTPROCESS_FAILED
    LICENSE_REQUIRED -> POSTPROCESS_FAILED

LICENSE_REQUIRED choice: surfaces as POSTPROCESS_FAILED, not POLICY_DENIED.
POLICY_DENIED is reserved for the project-root path jail, overwrite refusal
without ``overwrite:true``, and non-loopback backend URLs without explicit
``allow_remote``. A license-gated postprocess failure is a failure of the
postprocess stage, so POSTPROCESS_FAILED keeps the stage attribution exact
and the POLICY_DENIED meaning narrow (caller did something forbidden).
"""

from __future__ import annotations

from typing import Dict, Optional, Type

BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
MODEL_MISSING = "MODEL_MISSING"
POLICY_DENIED = "POLICY_DENIED"
GENERATION_FAILED = "GENERATION_FAILED"
POSTPROCESS_FAILED = "POSTPROCESS_FAILED"
QUEUED = "QUEUED"

ERROR_CODES = (
    BACKEND_UNAVAILABLE,
    MODEL_MISSING,
    POLICY_DENIED,
    GENERATION_FAILED,
    POSTPROCESS_FAILED,
    QUEUED,
)


class McpServerError(Exception):
    """Base error for all MCP-server (C1) failures."""

    code = "MCP_SERVER_ERROR"

    def __init__(self, message: str = "", *, job_id: Optional[str] = None) -> None:
        if self.code not in (message or ""):
            message = "[%s] %s" % (self.code, message) if message else "[%s]" % self.code
        super().__init__(message)
        self.message = message
        self.job_id = job_id

    def __str__(self) -> str:
        suffix = " [job_id=%s]" % self.job_id if self.job_id else ""
        return "%s%s" % (self.message, suffix)


class BackendUnavailableError(McpServerError):
    """ComfyUI backend not reachable (C2 ``COMFY_UNREACHABLE``)."""

    code = BACKEND_UNAVAILABLE


class ModelMissingError(McpServerError):
    """Required checkpoint/model file missing (C2 ``MODEL_NOT_FOUND``)."""

    code = MODEL_MISSING


class PolicyDeniedError(McpServerError):
    """Path escape, unapproved overwrite, or other policy refusal."""

    code = POLICY_DENIED


class GenerationFailedError(McpServerError):
    """Diffusion job errored or timed out (C2 ``JOB_FAILED``/``JOB_TIMEOUT``)."""

    code = GENERATION_FAILED


class PostprocessFailedError(McpServerError):
    """Postprocess stage failed (C3 ``DECODE_FAILED``/``SEGMENTATION_FAILED``/
    ``LICENSE_REQUIRED``/``VECTORIZE_FAILED``)."""

    code = POSTPROCESS_FAILED


class QueuedError(McpServerError):
    """Job queued: backend saturated or past ``max_concurrent`` (C2 ``QUEUE_FULL``)."""

    code = QUEUED


_BACKEND_MAP: Dict[str, Type[McpServerError]] = {
    "COMFY_UNREACHABLE": BackendUnavailableError,
    "MODEL_NOT_FOUND": ModelMissingError,
    "QUEUE_FULL": QueuedError,
    "JOB_FAILED": GenerationFailedError,
    "JOB_TIMEOUT": GenerationFailedError,
    "UNKNOWN_WORKFLOW": GenerationFailedError,
}

_POSTPROCESS_MAP: Dict[str, Type[McpServerError]] = {
    "DECODE_FAILED": PostprocessFailedError,
    "SEGMENTATION_FAILED": PostprocessFailedError,
    "LICENSE_REQUIRED": PostprocessFailedError,
    "VECTORIZE_FAILED": PostprocessFailedError,
}

#: Combined sibling-code -> C1 error-class table (read-only view rebuilt per call).
SIBLING_MAP: Dict[str, Type[McpServerError]] = dict(_BACKEND_MAP)
SIBLING_MAP.update(_POSTPROCESS_MAP)


def error_class_for_sibling_code(code: str) -> Type[McpServerError]:
    """Return the C1 error class for a sibling (C2/C3) error code string.

    Raises ``KeyError`` for unknown codes so new sibling codes fail loudly
    instead of being silently reinterpreted.
    """
    try:
        return SIBLING_MAP[code]
    except KeyError:
        raise KeyError("unknown sibling error code: %r" % (code,)) from None


def translate_sibling_error(exc: Exception) -> McpServerError:
    """Translate a caught sibling error (carrying ``.code``) to a C1 error.

    Preserves the original message and ``job_id`` when present. Unknown
    codes raise ``KeyError`` (see :func:`error_class_for_sibling_code`).
    Non-sibling exceptions (no ``.code``) raise ``TypeError``.
    """
    code = getattr(exc, "code", None)
    if not isinstance(code, str):
        raise TypeError(
            "cannot translate exception without a string .code: %r" % (exc,)
        )
    cls = error_class_for_sibling_code(code)
    job_id = getattr(exc, "job_id", None)
    try:
        message = str(exc)
    except Exception:
        message = ""
    return cls(message, job_id=job_id)


__all__ = [
    "McpServerError",
    "BackendUnavailableError",
    "ModelMissingError",
    "PolicyDeniedError",
    "GenerationFailedError",
    "PostprocessFailedError",
    "QueuedError",
    "BACKEND_UNAVAILABLE",
    "MODEL_MISSING",
    "POLICY_DENIED",
    "GENERATION_FAILED",
    "POSTPROCESS_FAILED",
    "QUEUED",
    "ERROR_CODES",
    "SIBLING_MAP",
    "error_class_for_sibling_code",
    "translate_sibling_error",
]
