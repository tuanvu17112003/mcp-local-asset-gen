"""Minimal ComfyUI REST client (contract ``C2-gen-backend-job`` v0.1.0, slice A).

C2 operation -> HTTP mapping (ComfyUI at ``base_url``, default localhost:8188):

* ``submit``      -> ``POST /prompt`` ``{"prompt": {...}, "client_id"?}`` -> ``prompt_id``
* ``upload_image``-> ``POST /upload/image`` multipart/form-data
  (fields ``image`` file + ``overwrite``/``subfolder``/``type``) ->
  ``{"name","subfolder","type"}`` — the file lands in the ComfyUI
  ``input/`` dir; LoadImage takes the ``subfolder/name`` value.
* ``queue_status``-> ``GET /queue`` first, then ``GET /history/{id}`` presence
* ``poll``        -> ``GET /queue`` once, then ``GET /history/{id}`` each ``poll_interval``
* ``fetch_outputs``/``fetch_png`` -> parse history ``outputs``; ``GET /view?...`` -> bytes
* ``fetch_result``-> ``poll`` + first-image download -> result dict
* ``cancel``      -> ``POST /interrupt`` ``{"prompt_id"?|,"client_id"?}``

Security: localhost-only by default. A non-loopback ``base_url`` raises
``ValueError`` unless ``allow_remote=True``. WARNING: remote use needs explicit
authority plus a TLS/reverse-proxy decision (plain HTTP leaks prompts/images);
never put credentials in query params — this client sends none.

No live ComfyUI is needed for tests: pass any ``transport`` object exposing
``post_json(url, body, timeout) -> (status, data)``,
``post_multipart(url, fields, file_field, file_name, file_bytes, timeout)
-> (status, data)``,
``get_json(url, timeout) -> (status, data)`` and
``get_bytes(url, timeout) -> (status, bytes)`` (a fake/stub). Default is a
stdlib-``urllib`` transport (no third-party dependency). ``sleep`` is also
injectable so polling tests need no real waiting.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from .errors import (
    ComfyUnreachableError,
    JobFailedError,
    JobTimeoutError,
    ModelNotFoundError,
    QueueFullError,
    UnknownLoaderError,
)

_QUEUE_ENDPOINT = "/queue"
_PROMPT_ENDPOINT = "/prompt"
_HISTORY_ENDPOINT = "/history"
_VIEW_ENDPOINT = "/view"
_INTERRUPT_ENDPOINT = "/interrupt"
_OBJECT_INFO_ENDPOINT = "/object_info"
_UPLOAD_ENDPOINT = "/upload/image"
_WS_ENDPOINT = "/ws"

# C2 v0.1.2 read-only introspection allowlist (verified live 2026-10-18).
# v0.7 adds "lora" (LoraLoaderModelOnly -> models/loras/).
ALLOWED_LOADERS = frozenset(
    {"UnetLoaderGGUF", "DualCLIPLoader", "VAELoader", "CheckpointLoaderSimple",
     "LoraLoaderModelOnly"}
)

SUBMIT_TIMEOUT_S = 5.0  # contract: submit timeout 5 s
REQUEST_TIMEOUT_S = 10.0  # non-submit single-request timeout
_WS_HANDSHAKE_TIMEOUT_S = 3.0
_WS_FRAME_TIMEOUT_S = 0.2  # drain window per poll iteration

JobStatus = str  # one of queued|running|completed|error|not_found


def _drain_progress_ws(ws: Any, prompt_id: str, on_progress: Callable[[float, Optional[str]], None]) -> bool:
    """Drain pending WebSocket text frames; return False when the WS is dead.

    Only ``progress`` frames matching ``prompt_id`` reach ``on_progress``
    as ``(value/max, node)``. Binary (preview) frames, other message
    types, other prompts and malformed JSON are ignored. Any transport
    error or a raising callback reports the WS as dead (caller drops it —
    progress is best-effort, never breaks polling).
    """
    import websocket  # lazy: only when a caller asked for WS progress

    while True:
        try:
            frame = ws.recv()
        except websocket.WebSocketTimeoutException:
            return True  # drain window empty; WS healthy
        except Exception:
            return False  # transport error: drop the socket
        if not isinstance(frame, str):
            continue  # binary preview frame
        try:
            msg = json.loads(frame)
        except ValueError:
            continue
        data = msg.get("data") if isinstance(msg, dict) else None
        if not isinstance(data, dict) or msg.get("type") != "progress":
            continue
        if data.get("prompt_id") != prompt_id:
            continue
        value, maximum = data.get("value"), data.get("max")
        if (
            isinstance(value, (int, float))
            and isinstance(maximum, (int, float))
            and maximum > 0
        ):
            node = data.get("node")
            try:
                on_progress(
                    min(float(value) / float(maximum), 1.0),
                    node if isinstance(node, str) else None,
                )
            except Exception:
                return False
    return True


class _HttpStatusError(Exception):
    """Internal carrier for non-2xx responses: status + parsed body."""

    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"HTTP {status}: {body!r}")
        self.status = status
        self.body = body


class _UrllibTransport:
    """Default stdlib transport; raises ComfyUnreachableError on I/O failure."""

    @staticmethod
    def _read_json(resp: Any) -> Any:
        raw = resp.read()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {"_raw": raw.decode("utf-8", "replace")}

    def post_json(self, url: str, body: Dict[str, Any], timeout: float) -> Tuple[int, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        return self._send(req, timeout)

    def post_multipart(
        self,
        url: str,
        fields: Dict[str, str],
        file_field: str,
        file_name: str,
        file_bytes: bytes,
        timeout: float,
    ) -> Tuple[int, Any]:
        """``multipart/form-data`` POST (the shape ComfyUI ``/upload/image`` takes)."""
        boundary = uuid.uuid4().hex
        lines: List[str] = []
        for name, value in fields.items():
            lines += [
                f"--{boundary}",
                f'Content-Disposition: form-data; name="{name}"',
                "",
                value,
            ]
        lines += [
            f"--{boundary}",
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_name}"',
            "Content-Type: image/png",
            "",
        ]
        head = ("\r\n".join(lines) + "\r\n").encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            url,
            data=head + bytes(file_bytes) + tail,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return self._send(req, timeout)

    def _send(self, req: Any, timeout: float) -> Tuple[int, Any]:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, self._read_json(resp)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8") or "{}")
            except ValueError:
                payload = {}
            raise _HttpStatusError(exc.code, payload) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, socket.error) as exc:
            raise ComfyUnreachableError(f"ComfyUI unreachable at {req.full_url}: {exc}") from exc

    def get_json(self, url: str, timeout: float) -> Tuple[int, Any]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.status, self._read_json(resp)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8") or "{}")
            except ValueError:
                payload = {}
            raise _HttpStatusError(exc.code, payload) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, socket.error) as exc:
            raise ComfyUnreachableError(f"ComfyUI unreachable at {url}: {exc}") from exc

    def get_bytes(self, url: str, timeout: float) -> Tuple[int, bytes]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            raise _HttpStatusError(exc.code, {}) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, socket.error) as exc:
            raise ComfyUnreachableError(f"ComfyUI unreachable at {url}: {exc}") from exc


def _is_loopback_host(host: Optional[str]) -> bool:
    if not host:
        return False
    h = host.strip().lower().strip("[]")
    return h == "localhost" or h == "::1" or h.startswith("127.") or h == "::ffff:127.0.0.1"


def _contains_id(entries: Any, prompt_id: str) -> bool:
    """Match ComfyUI queue entries shaped as [num, id, ...] lists or {prompt_id} dicts."""
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if isinstance(entry, (list, tuple)) and len(entry) > 1 and entry[1] == prompt_id:
            return True
        if isinstance(entry, dict):
            if entry.get("prompt_id") == prompt_id:
                return True
            inner = entry.get("prompt")
            if isinstance(inner, dict) and inner.get("prompt_id") == prompt_id:
                return True
    return False


def _select_history_entry(payload: Any, prompt_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Accept a full ``GET /history`` response or one entry; return the entry dict or None."""
    if not isinstance(payload, dict) or not payload:
        return None
    if prompt_id is not None and isinstance(payload.get(prompt_id), dict):
        return payload[prompt_id]
    if isinstance(payload.get("outputs"), dict):
        return payload  # already a single entry
    if prompt_id is None and len(payload) == 1:
        only = next(iter(payload.values()))
        if isinstance(only, dict):
            return only
    return None


def _scan_inputs(obj: Any, keys: Tuple[str, ...], depth: int = 0) -> Dict[str, Any]:
    """Shallow recursive scan (workflow/prompt echo) for first occurrence of each key."""
    found: Dict[str, Any] = {}
    if depth > 4 or not isinstance(obj, dict):
        return found
    inputs = obj.get("inputs") if "inputs" in obj else obj
    if isinstance(inputs, dict):
        for key in keys:
            if key in inputs and key not in found:
                found[key] = inputs[key]
    for value in obj.values():
        if len(found) == len(keys):
            break
        if isinstance(value, dict):
            for key, val in _scan_inputs(value, keys, depth + 1).items():
                found.setdefault(key, val)
    return found


class ComfyClient:
    """Blocking ComfyUI adapter client; see module docstring for the HTTP map.

    Concurrency: at most 2 concurrent jobs is a deployment/PQM0-schedule
    responsibility (VRAM guard per assignment gen-2); no semaphore lives in
    this class by design.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        submit_timeout: float = SUBMIT_TIMEOUT_S,
        request_timeout: float = REQUEST_TIMEOUT_S,
        poll_interval: float = 1.0,
        max_wait_s: float = 300.0,
        allow_remote: bool = False,
        transport: Optional[Any] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        host = urllib.parse.urlparse(base_url).hostname
        if not _is_loopback_host(host) and not allow_remote:
            raise ValueError(
                f"Refusing non-loopback ComfyUI base_url {base_url!r}: "
                "localhost-only by default (C2 trust boundary). Pass allow_remote=True "
                "with explicit authority + a TLS decision; plain HTTP leaks prompts/images."
            )
        self.base_url = base_url.rstrip("/")
        self.submit_timeout = submit_timeout
        self.request_timeout = request_timeout
        self.poll_interval = poll_interval
        self.max_wait_s = max_wait_s
        self.allow_remote = allow_remote
        self._transport = transport or _UrllibTransport()
        self._sleep = sleep
        self._clock = clock
        self._last_client_id: Optional[str] = None

    # -- low-level helpers -------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def submit(self, prompt_dict: Dict[str, Any], client_id: Optional[str] = None) -> str:
        """``POST /prompt`` an API-format workflow; return ``prompt_id`` (== C2 ``job_id``).

        Maps connection failures to ``COMFY_UNREACHABLE``; ComfyUI-reported
        ``error``/``node_errors`` to ``JOB_FAILED`` (payload preserved), with
        missing-model hints -> ``MODEL_NOT_FOUND`` and saturated-queue hints ->
        ``QUEUE_FULL``. No credentials are sent; ``client_id`` goes in the JSON body.
        """
        if not isinstance(prompt_dict, dict) or not prompt_dict:
            raise ValueError("prompt_dict must be a non-empty API-format workflow dict")
        body: Dict[str, Any] = {"prompt": prompt_dict}
        if not client_id:
            # Auto id binds this submit to the poll-time progress WS (C1 v0.7).
            client_id = uuid.uuid4().hex
        body["client_id"] = client_id
        self._last_client_id = client_id
        try:
            _status, data = self._transport.post_json(
                self._url(_PROMPT_ENDPOINT), body, self.submit_timeout
            )
        except _HttpStatusError as exc:
            raise self._classify_submit_error(exc.body) from exc
        if not isinstance(data, dict):
            raise JobFailedError(f"Unexpected /prompt response: {data!r}", payload=data)
        if data.get("error") or data.get("node_errors"):
            raise self._classify_submit_error(data)
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise JobFailedError(f"/prompt gave no prompt_id: {data!r}", payload=data)
        return str(prompt_id)

    @staticmethod
    def _classify_submit_error(data: Any) -> JobFailedError | ModelNotFoundError | QueueFullError:
        text = json.dumps(data).lower() if not isinstance(data, str) else data.lower()
        if any(hint in text for hint in ("model_not_found", "missing model", "checkpoint", "no model", "not found")) and any(
            hint in text for hint in ("model", "checkpoint", "ckpt", "safetensors", "gguf")
        ):
            return ModelNotFoundError(
                "Required model file missing on ComfyUI host "
                "(place under models/checkpoints/); see ComfyUI error payload.",
                payload=data,
            )
        if "queue" in text and any(hint in text for hint in ("full", "saturated", "max", "limit")):
            return QueueFullError(f"ComfyUI queue saturated: {data!r}", payload=data)
        return JobFailedError(f"ComfyUI rejected prompt: {data!r}", payload=data)

    def queue_status(self, prompt_id: str) -> JobStatus:
        """``GET /queue`` first, then ``GET /history/{id}`` presence.

        Returns ``queued`` | ``running`` | ``completed`` | ``error`` | ``not_found``.
        """
        try:
            _status, queue = self._transport.get_json(self._url(_QUEUE_ENDPOINT), self.request_timeout)
        except _HttpStatusError as exc:
            raise JobFailedError(f"/queue failed: {exc.body!r}", job_id=prompt_id, payload=exc.body) from exc
        queue = queue if isinstance(queue, dict) else {}
        if _contains_id(queue.get("queue_running"), prompt_id):
            return "running"
        if _contains_id(queue.get("queue_pending"), prompt_id):
            return "queued"
        try:
            _status, history = self._transport.get_json(
                self._url(f"{_HISTORY_ENDPOINT}/{urllib.parse.quote(prompt_id)}"), self.request_timeout
            )
        except _HttpStatusError as exc:
            if exc.status == 404:
                return "not_found"
            raise JobFailedError(
                f"/history failed: {exc.body!r}", job_id=prompt_id, payload=exc.body
            ) from exc
        entry = _select_history_entry(history, prompt_id)
        if not entry:
            return "not_found"
        status = entry.get("status") or {}
        status_str = str(status.get("status_str", "")).lower()
        if status_str == "error" or status.get("error"):
            return "error"
        if entry.get("outputs"):
            return "completed"
        if status.get("completed") or status_str == "success":
            return "completed"
        return "running"  # entry exists but no outputs yet

    def poll(
        self,
        prompt_id: str,
        on_progress: Optional[Callable[[float, Optional[str]], None]] = None,
    ) -> Dict[str, Any]:
        """``GET /queue`` once (fail fast on unknown id), then ``GET /history/{id}``
        every ``poll_interval`` up to ``max_wait_s``; return the history payload.

        ``on_progress`` (optional, C1 v0.7): when given and a WebSocket can
        be opened for the submit's ``client_id``, ``progress`` frames for
        this ``prompt_id`` reach it as ``(value/max, node)`` each poll
        iteration. Best-effort: import/transport failures silently skip WS
        progress; ``/history`` polling stays the source of truth.

        Raises ``JOB_FAILED`` with the ComfyUI error payload, or ``JOB_TIMEOUT``
        (after best-effort ``POST /interrupt``) on expiry.
        """
        if self.queue_status(prompt_id) == "not_found":
            raise JobFailedError(f"Unknown prompt_id {prompt_id!r}: absent from queue and history",
                                 job_id=prompt_id)
        deadline = self._clock() + self.max_wait_s
        history_url = self._url(f"{_HISTORY_ENDPOINT}/{urllib.parse.quote(prompt_id)}")
        ws = None
        if on_progress is not None and self._last_client_id:
            try:
                import websocket  # lazy: only when a caller asked for progress

                netloc = urllib.parse.urlsplit(self.base_url).netloc
                ws = websocket.create_connection(
                    f"ws://{netloc}{_WS_ENDPOINT}?clientId="
                    f"{urllib.parse.quote(self._last_client_id)}",
                    timeout=_WS_HANDSHAKE_TIMEOUT_S,
                )
                ws.settimeout(_WS_FRAME_TIMEOUT_S)
            except Exception:
                ws = None  # no WS -> poll-only, phase ticks still flow
        try:
            last: Any = None
            while True:
                try:
                    _status, last = self._transport.get_json(history_url, self.request_timeout)
                except _HttpStatusError as exc:
                    if exc.status != 404:
                        raise JobFailedError(
                            f"/history failed: {exc.body!r}", job_id=prompt_id, payload=exc.body
                        ) from exc
                if ws is not None and not _drain_progress_ws(ws, prompt_id, on_progress):
                    try:
                        ws.close()
                    except Exception:
                        pass
                    ws = None
                entry = _select_history_entry(last, prompt_id)
                if entry:
                    status = entry.get("status") or {}
                    if str(status.get("status_str", "")).lower() == "error" or status.get("error"):
                        raise JobFailedError(
                            f"ComfyUI job failed: {status!r}", job_id=prompt_id, payload=status
                        )
                    if entry.get("outputs") or status.get("completed"):
                        return last if isinstance(last, dict) else {prompt_id: entry}
                if self._clock() >= deadline:
                    try:
                        self.cancel(prompt_id=prompt_id)
                    except Exception:
                        pass  # best-effort interrupt; timeout is raised regardless
                    raise JobTimeoutError(
                        f"Job {prompt_id!r} not complete after {self.max_wait_s:g}s; "
                        "interrupt attempted, record job_id for resume.",
                        job_id=prompt_id,
                    )
                self._sleep(self.poll_interval)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    @staticmethod
    def fetch_outputs(history_payload: Dict[str, Any], prompt_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Parse history ``outputs`` nodes into ``{filename, subfolder, type}`` refs.

        Accepts a full ``GET /history`` response or a single entry. Reads ``images``
        and ``gifs`` lists; other output kinds are ignored (not downloadable via /view).
        """
        entry = _select_history_entry(history_payload, prompt_id)
        if not entry:
            return []
        outputs = entry.get("outputs") or {}
        refs: List[Dict[str, str]] = []
        for node_out in outputs.values():
            if not isinstance(node_out, dict):
                continue
            for key in ("images", "gifs"):
                items = node_out.get(key) or []
                for item in items:
                    if not isinstance(item, dict) or "filename" not in item:
                        continue
                    refs.append(
                        {
                            "filename": str(item["filename"]),
                            "subfolder": str(item.get("subfolder", "")),
                            "type": str(item.get("type", "output")),
                        }
                    )
        return refs

    def fetch_png(self, ref: Dict[str, str]) -> bytes:
        """``GET /view?filename=&subfolder=&type=`` -> PNG bytes (no creds in params)."""
        query = urllib.parse.urlencode(
            {
                "filename": ref["filename"],
                "subfolder": ref.get("subfolder", ""),
                "type": ref.get("type", "output"),
            }
        )
        try:
            _status, data = self._transport.get_bytes(
                self._url(f"{_VIEW_ENDPOINT}?{query}"), self.request_timeout
            )
        except _HttpStatusError as exc:
            raise JobFailedError(
                f"/view failed for {ref['filename']!r}: {exc.body!r}", payload=exc.body
            ) from exc
        return bytes(data)

    def fetch_result(
        self,
        prompt_id: str,
        request_echo: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[float, Optional[str]], None]] = None,
    ) -> Dict[str, Any]:
        """``poll`` + download first image -> ``{png_bytes, width, height, seed,
        model_id, elapsed_s}``.

        ``on_progress`` (optional, C1 v0.7) forwards WS per-node progress
        from :meth:`poll` as ``(value/max, node)``; best-effort.

        Meta source precedence (documented per contract): (1) history
        ``outputs`` node metadata, (2) history entry ``prompt`` echo
        (submitted workflow), (3) history entry ``meta`` dict (seed/model_id/
        elapsed_s recorded by the fake/history writer), (4)
        caller-supplied ``request_echo`` (submit args), else ``None``.
        Later sources only fill keys still missing — they never override an
        earlier hit, preserving existing W/H-from-outputs/prompt behavior.
        ``elapsed_s`` is the history ``meta`` value when numeric, else the
        client-measured wall time around ``poll`` + download.
        """
        start = self._clock()
        history = self.poll(prompt_id, on_progress=on_progress)
        entry = _select_history_entry(history, prompt_id) or {}
        refs = self.fetch_outputs(history, prompt_id)
        if not refs:
            raise JobFailedError(f"Job {prompt_id!r} completed with no downloadable images",
                                 job_id=prompt_id, payload=history)
        png = self.fetch_png(refs[0])
        elapsed = self._clock() - start
        meta = _scan_inputs(entry.get("outputs") or {}, ("width", "height", "seed", "model_id", "model"))
        meta.update(
            {k: v for k, v in _scan_inputs(entry.get("prompt") or {}, ("width", "height", "seed", "model_id", "model")).items()
             if k not in meta}
        )
        history_meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
        for key in ("width", "height", "seed", "model_id", "model"):
            if meta.get(key) is None and history_meta.get(key) is not None:
                meta[key] = history_meta[key]
        if request_echo:
            for key in ("width", "height", "seed", "model_id"):
                if meta.get(key) is None and request_echo.get(key) is not None:
                    meta[key] = request_echo[key]
        model_id = meta.get("model_id", meta.get("model"))
        meta_elapsed = history_meta.get("elapsed_s")
        if isinstance(meta_elapsed, (int, float)):
            elapsed = float(meta_elapsed)
        return {
            "png_bytes": png,
            "width": meta.get("width"),
            "height": meta.get("height"),
            "seed": meta.get("seed"),
            "model_id": model_id,
            "elapsed_s": elapsed,
        }

    def cancel(
        self, prompt_id: Optional[str] = None, client_id: Optional[str] = None
    ) -> bool:
        """``POST /interrupt`` with ``{"prompt_id"?}`` and/or ``{"client_id"?}``;
        at least one id is required. Returns True on acknowledgement."""
        if not prompt_id and not client_id:
            raise ValueError("cancel requires prompt_id and/or client_id")
        body: Dict[str, Any] = {}
        if prompt_id:
            body["prompt_id"] = prompt_id
        if client_id:
            body["client_id"] = client_id
        try:
            self._transport.post_json(self._url(_INTERRUPT_ENDPOINT), body, self.request_timeout)
        except _HttpStatusError as exc:
            raise JobFailedError(f"/interrupt failed: {exc.body!r}",
                                 job_id=prompt_id, payload=exc.body) from exc
        return True

    def upload_image(
        self,
        png_bytes: bytes,
        *,
        subfolder: str = "asset-gen",
        filename: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """``POST /upload/image`` the PNG into the ComfyUI ``input/`` dir.

        Returns the server response ``{"name","subfolder","type"}``; the
        LoadImage node value is ``f"{subfolder}/{name}"`` (or ``name``
        when ``subfolder`` is empty). ``filename`` defaults to a fresh
        unique name, so collisions (and the ``overwrite`` decision) never
        happen on the server side. I/O failures map to
        ``COMFY_UNREACHABLE``; HTTP errors to ``JOB_FAILED``.
        """
        if not isinstance(png_bytes, (bytes, bytearray, memoryview)) or not png_bytes:
            raise ValueError("png_bytes must be non-empty bytes")
        name = filename if filename else f"asset-{uuid.uuid4().hex}.png"
        _status, data = self._transport.post_multipart(
            self._url(_UPLOAD_ENDPOINT),
            fields={
                "overwrite": "true" if overwrite else "false",
                "subfolder": subfolder,
                "type": "input",
            },
            file_field="image",
            file_name=name,
            file_bytes=bytes(png_bytes),
            timeout=self.request_timeout,
        )
        if not isinstance(data, dict) or not isinstance(data.get("name"), str):
            raise JobFailedError(
                f"/upload/image gave no file name: {data!r}", payload=data
            )
        return {
            "name": data["name"],
            "subfolder": str(data.get("subfolder") or ""),
            "type": str(data.get("type") or "input"),
        }

    def loader_files(self, loader: str) -> Dict[str, List[str]]:
        """``GET /object_info/{loader}`` -> ``{input_name: [filenames]}``.

        Read-only introspection (contract ``C2-gen-backend-job`` v0.1.2): no
        queue/submit side effects. Only the allowlisted loaders are accepted
        (``UnetLoaderGGUF|DualCLIPLoader|VAELoader|CheckpointLoaderSimple``);
        anything else raises ``UNKNOWN_LOADER`` without touching the network.
        Returns the required file-list inputs (``*_name`` keys whose option
        spec is a list of strings; non-file inputs such as DualCLIPLoader
        ``type`` are excluded). An allowlisted loader with no entry in the
        server response (node not installed) also raises ``UNKNOWN_LOADER``.
        Transport-level I/O failures propagate as ``COMFY_UNREACHABLE``.
        """
        if not isinstance(loader, str) or loader not in ALLOWED_LOADERS:
            raise UnknownLoaderError(
                "UNKNOWN_LOADER: loader=%r allowed=%s"
                % (loader, sorted(ALLOWED_LOADERS)),
                payload={"loader": loader, "allowed": sorted(ALLOWED_LOADERS)},
            )
        url = self._url(
            f"{_OBJECT_INFO_ENDPOINT}/{urllib.parse.quote(loader, safe='')}"
        )
        try:
            _status, data = self._transport.get_json(url, self.request_timeout)
        except _HttpStatusError as exc:
            if exc.status == 404:
                raise UnknownLoaderError(
                    f"UNKNOWN_LOADER: ComfyUI has no object_info for {loader!r}",
                    payload={"loader": loader, "status": exc.status},
                ) from exc
            raise JobFailedError(
                f"/object_info/{loader} failed: {exc.body!r}", payload=exc.body
            ) from exc
        if not isinstance(data, dict) or loader not in data:
            raise UnknownLoaderError(
                f"UNKNOWN_LOADER: ComfyUI has no object_info for {loader!r}",
                payload={"loader": loader},
            )
        node = data[loader]
        required = (
            node.get("input", {}).get("required", {})
            if isinstance(node, dict)
            else {}
        )
        if not isinstance(required, dict):
            return {}
        files: Dict[str, List[str]] = {}
        for input_name, spec in required.items():
            # File-list convention across all four allowlisted loaders
            # (verified live 2026-10-18): every file input carries "_name"
            # (unet_name, clip_name1/2, vae_name, ckpt_name); non-file
            # option lists such as DualCLIPLoader "type" do not.
            if "_name" not in input_name:
                continue
            if (
                isinstance(spec, list)
                and spec
                and isinstance(spec[0], list)
                and all(isinstance(item, str) for item in spec[0])
            ):
                files[input_name] = list(spec[0])
        return files
