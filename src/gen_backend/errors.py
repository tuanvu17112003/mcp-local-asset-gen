"""Error taxonomy for the ComfyUI generation backend.

Contract: ``C2-gen-backend-job`` v0.1.0. Every failure the adapter raises
carries a stable machine-readable :attr:`GenBackendError.code` so consumers
(``mod-mcp-core``, ``mod-postprocess``) can map it without parsing messages.

Codes: ``COMFY_UNREACHABLE``, ``UNKNOWN_WORKFLOW``, ``UNKNOWN_LOADER``,
``MODEL_NOT_FOUND``, ``QUEUE_FULL``, ``JOB_FAILED`` (carries the ComfyUI error payload),
``JOB_TIMEOUT``.
"""

from __future__ import annotations

from typing import Any, Optional

COMFY_UNREACHABLE = "COMFY_UNREACHABLE"
UNKNOWN_WORKFLOW = "UNKNOWN_WORKFLOW"
UNKNOWN_LOADER = "UNKNOWN_LOADER"
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
QUEUE_FULL = "QUEUE_FULL"
JOB_FAILED = "JOB_FAILED"
JOB_TIMEOUT = "JOB_TIMEOUT"

ERROR_CODES = (
    COMFY_UNREACHABLE,
    UNKNOWN_WORKFLOW,
    UNKNOWN_LOADER,
    MODEL_NOT_FOUND,
    QUEUE_FULL,
    JOB_FAILED,
    JOB_TIMEOUT,
)


class GenBackendError(Exception):
    """Base error for all generation-backend failures."""

    code = "GEN_BACKEND_ERROR"

    def __init__(
        self,
        message: str,
        job_id: Optional[str] = None,
        payload: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.job_id = job_id
        self.payload = payload

    def __str__(self) -> str:
        suffix = f" [job_id={self.job_id}]" if self.job_id else ""
        return f"{self.code}: {self.message}{suffix}"


class ComfyUnreachableError(GenBackendError):
    """ComfyUI host not reachable (connection refused/timeout/DNS)."""

    code = COMFY_UNREACHABLE


class UnknownWorkflowError(GenBackendError):
    """Requested ``workflow_id`` is not registered (raised by slice B registry)."""

    code = UNKNOWN_WORKFLOW


class UnknownLoaderError(GenBackendError):
    """Requested loader node is not allowlisted or not known to ComfyUI.

    Raised when ``loader`` is outside the C2 v0.1.2 allowlist
    (``UnetLoaderGGUF|DualCLIPLoader|VAELoader|CheckpointLoaderSimple``),
    or when ``GET /object_info/{loader}`` answers 404 / carries no entry
    for an allowlisted loader (e.g. node not installed server-side).
    Code: ``UNKNOWN_LOADER``.
    """

    code = UNKNOWN_LOADER


class ModelNotFoundError(GenBackendError):
    """Required checkpoint/loader file missing on the ComfyUI host."""

    code = MODEL_NOT_FOUND


class QueueFullError(GenBackendError):
    """ComfyUI queue saturated; retry later."""

    code = QUEUE_FULL


class JobFailedError(GenBackendError):
    """Job errored inside ComfyUI; :attr:`payload` holds the ComfyUI error body
    (``node_errors`` / history ``status.messages``) verbatim — never reinterpreted."""

    code = JOB_FAILED


class JobTimeoutError(GenBackendError):
    """Job did not finish within ``max_wait_s``; adapter attempted ``POST /interrupt``."""

    code = JOB_TIMEOUT
