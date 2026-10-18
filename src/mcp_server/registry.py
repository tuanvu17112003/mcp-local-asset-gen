"""In-memory job registry: concurrency guard + idempotency store (C1 v0.1.0).

Two duties, one lock:

* VRAM guard — at most ``max_concurrent`` jobs hold a slot (default 2,
  matching ``ServerConfig``). :meth:`register` raises
  :class:`QueuedError` (``QUEUED``) past the limit instead of blocking.
* Idempotency — :meth:`complete` stores the finished result per
  ``job_id``; :meth:`get` returns it so a retried ``job_id`` returns the
  same ``asset_path`` without re-running the backend.

``job_id`` is auto-generated (``uuid4`` hex) when the caller omits it.
Pure stdlib (``threading.Lock``); no I/O, no backend coupling.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, Optional

from .errors import QueuedError

DEFAULT_MAX_CONCURRENT = 2


class JobRegistry:
    """Thread-safe in-memory registry of active slots and finished results."""

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        if (
            isinstance(max_concurrent, bool)
            or not isinstance(max_concurrent, int)
            or max_concurrent < 1
        ):
            raise ValueError(
                "INVALID_MAX_CONCURRENT: must be an int >= 1, got %r"
                % (max_concurrent,)
            )
        self._max_concurrent = max_concurrent
        self._lock = threading.Lock()
        self._active = set()
        self._results: Dict[str, Dict[str, Any]] = {}

    @property
    def max_concurrent(self) -> int:
        """Slot limit this registry enforces."""
        return self._max_concurrent

    @property
    def active_count(self) -> int:
        """Number of currently held slots (lock-guarded snapshot)."""
        with self._lock:
            return len(self._active)

    @staticmethod
    def new_job_id() -> str:
        """Generate a fresh idempotency key (``uuid4`` hex)."""
        return uuid.uuid4().hex

    def register(self, job_id: Optional[str] = None) -> str:
        """Take a slot for ``job_id`` (generating one when omitted).

        Returns the effective ``job_id``. Raises :class:`QueuedError`
        (``QUEUED``) when ``max_concurrent`` slots are already held. A
        ``job_id`` that is already active or already finished returns
        as-is without consuming an extra slot (the orchestrator checks
        :meth:`get` first; this is a safety net, not the idempotency
        path).
        """
        jid = job_id if isinstance(job_id, str) and job_id else self.new_job_id()
        with self._lock:
            if jid in self._results or jid in self._active:
                return jid
            if len(self._active) >= self._max_concurrent:
                raise QueuedError(
                    "QUEUED: backend saturated, %d active (max %d); "
                    "retry later with the same job_id" % (len(self._active), self._max_concurrent)
                )
            self._active.add(jid)
            return jid

    def complete(self, job_id: str, result: Dict[str, Any]) -> None:
        """Release ``job_id``'s slot and store its finished result.

        Stores (and :meth:`get` returns) a copy so callers cannot mutate
        the cached result through a retrieved reference.
        """
        with self._lock:
            self._active.discard(job_id)
            self._results[job_id] = dict(result)

    def fail(self, job_id: str) -> None:
        """Release ``job_id``'s slot without storing a result."""
        with self._lock:
            self._active.discard(job_id)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return a copy of the stored finished result for ``job_id``, or ``None``."""
        with self._lock:
            stored = self._results.get(job_id)
            return dict(stored) if stored is not None else None

    def find_job_by_asset(self, asset_path: str) -> Optional[str]:
        """Reverse lookup: ``job_id`` whose stored result has ``asset_path``.

        Used to attribute ``parent_job_id`` for path-addressed refines.
        Returns ``None`` when no finished job produced that path.
        """
        with self._lock:
            for jid, res in self._results.items():
                if isinstance(res, dict) and res.get("asset_path") == asset_path:
                    return jid
            return None


__all__ = [
    "JobRegistry",
    "DEFAULT_MAX_CONCURRENT",
]
