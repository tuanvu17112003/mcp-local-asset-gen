"""GPU-less fake ComfyUI server for the REST surface asset-gen talks to.

Contract: C2-gen-backend-job v0.1.0 (see ``fixtures/c2/fake_comfyui.md``) and
the adapter in ``src/gen_backend/client.py``. Stdlib only (``http.server``,
``json``, ``threading``, ``urllib.parse``); the one PNG it serves is a real
512x512 RGBA image produced once with Pillow and cached in memory, so
``fetch_result`` sees decodable bytes without a GPU, weights or network
access beyond loopback.

Implemented routes (all in-memory, deterministic):

* ``POST /prompt``          -> ``{"prompt_id": ..., "number": 1, "node_errors": {}}``
* ``GET  /queue``           -> ``{"queue_running": [], "queue_pending": []}``
* ``GET  /history/<id>``    -> one success entry per submitted prompt id
* ``GET  /view``            -> the cached 512x512 RGBA PNG bytes
* ``POST /upload/image``    -> multipart parsed by hand; echoes ``{name, subfolder, type}``
* ``POST /interrupt``       -> marks the prompt cancelled, ``{}`` response
* ``GET  /object_info``     -> small but real-shaped loader payload
* ``GET  /prompt``          -> ``{"exec_info": {"queue_remaining": 0}}`` (reachability probe)
* ``GET  /system_stats``    -> minimal system summary

Usage::

    from fixtures.fake_comfyui import start_fake_comfyui

    with start_fake_comfyui() as fake:
        client = ComfyClient(base_url=fake.url)
        prompt_id = client.submit({...})

``start_fake_comfyui()`` returns a :class:`FakeComfyUI` handle with ``.url``,
``.stop()`` and context-manager support; it binds ``127.0.0.1:0`` (ephemeral
port) unless one is passed, and never touches the network beyond loopback.
"""

from __future__ import annotations

import io
import json
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

#: Rendered PNG side length (contract: 512px default asset size).
PNG_SIZE = 512

#: Node classes the adapter may ask ``/object_info`` about. Payload is the
#: real ComfyUI shape: ``{node: {input: {required: {input_name: [spec, {}]}}}}``
OBJECT_INFO: Dict[str, Any] = {
    "UnetLoaderGGUF": {
        "input": {"required": {"unet_name": [["flux1-schnell-Q4_K_S.gguf"], {}]}},
        "output": ["MODEL"],
        "output_name": ["MODEL"],
    },
    "DualCLIPLoader": {
        "input": {
            "required": {
                "clip_name1": [["t5xxl_fp8_e4m3fn.safetensors"], {}],
                "clip_name2": [["clip_l.safetensors"], {}],
                "type": [["flux"], {}],
            }
        },
        "output": ["CLIP"],
        "output_name": ["CLIP"],
    },
    "VAELoader": {
        "input": {"required": {"vae_name": [["ae.safetensors"], {}]}},
        "output": ["VAE"],
        "output_name": ["VAE"],
    },
    "UpscaleModelLoader": {
        "input": {"required": {"model_name": [["RealESRGAN_x4.pth"], {}]}},
        "output": ["UPSCALE_MODEL"],
        "output_name": ["UPSCALE_MODEL"],
    },
    "CheckpointLoaderSimple": {
        "input": {
            "required": {"ckpt_name": [["flux1-schnell-fp8.safetensors"], {}]}
        },
        "output": ["MODEL", "CLIP", "VAE"],
        "output_name": ["MODEL", "CLIP", "VAE"],
    },
    "LoraLoaderModelOnly": {
        "input": {"required": {"lora_name": [["style-lora.safetensors"], {}]}},
        "output": ["MODEL"],
        "output_name": ["MODEL"],
    },
    "LoadImage": {
        "input": {"required": {"image": [["uploaded.png"], {"image_upload": True}]}},
        "output": ["IMAGE", "MASK"],
        "output_name": ["IMAGE", "MASK"],
    },
    "LoaderImage": {
        "input": {"required": {"image": [["uploaded.png"], {"image_upload": True}]}},
        "output": ["IMAGE", "MASK"],
        "output_name": ["IMAGE", "MASK"],
    },
    "LoaderOutput": {
        "input": {"required": {"filename": [["output.png"], {}]}},
        "output": ["IMAGE"],
        "output_name": ["IMAGE"],
    },
}


def _render_png(size: int = PNG_SIZE) -> bytes:
    """Render one deterministic RGBA PNG with Pillow (cached by callers).

    A solid mid-grey square with an opaque alpha channel: small, valid and
    fully decodable, so postprocess/trim paths behave like a real render
    without any model execution. Raises ``ImportError`` when Pillow is
    absent (callers skip such tests).
    """
    from PIL import Image

    image = Image.new("RGBA", (size, size), (128, 128, 128, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _parse_multipart(content_type: str, body: bytes) -> Dict[str, Any]:
    """Parse a ``multipart/form-data`` body by hand (no third-party parser).

    Returns ``{"fields": {name: str}, "files": {name: (filename, bytes)}}``.
    Raises ``ValueError`` when the boundary is missing or the body is
    truncated; a malformed upload is the only thing that makes this raise,
    so callers can map it to a 400.
    """
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("INVALID_MULTIPART: boundary missing from Content-Type")
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    if not boundary:
        raise ValueError("INVALID_MULTIPART: empty boundary")
    delimiter = b"--" + boundary.encode("ascii")
    fields: Dict[str, str] = {}
    files: Dict[str, Tuple[str, bytes]] = {}
    for chunk in body.split(delimiter):
        if not chunk or chunk in (b"--\r\n", b"--", b"\r\n"):
            continue
        part = chunk[2:] if chunk.startswith(b"\r\n") else chunk
        head, separator, payload = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        disposition = ""
        for line in head.decode("utf-8", "replace").split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                disposition = line
                break
        name = _disposition_param(disposition, "name")
        if name is None:
            continue
        payload = payload[:-2] if payload.endswith(b"\r\n") else payload
        filename = _disposition_param(disposition, "filename")
        if filename is None:
            fields[name] = payload.decode("utf-8", "replace")
        else:
            files[name] = (filename, payload)
    return {"fields": fields, "files": files}


def _disposition_param(disposition: str, key: str) -> Optional[str]:
    """Extract ``key="value"`` (or unquoted) from a Content-Disposition header."""
    marker = key + '="'
    if marker in disposition:
        return disposition.split(marker, 1)[1].split('"', 1)[0]
    marker = key + "="
    if marker in disposition:
        return disposition.split(marker, 1)[1].split(";", 1)[0].strip()
    return None


class _FakeState:
    """In-memory ComfyUI state: submitted prompts, cancellation, PNG cache."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.prompts: Dict[str, Dict[str, Any]] = {}
        self.prompt_order: List[str] = []
        self.cancelled: set = set()
        self.uploads: List[Dict[str, Any]] = []
        self._png: Optional[bytes] = None

    def png(self) -> bytes:
        """Return the cached 512x512 RGBA PNG, rendering it on first use."""
        if self._png is None:
            self._png = _render_png()
        return self._png

    def submit(self, payload: Dict[str, Any]) -> str:
        """Record a submitted prompt dict; return its fake ``prompt_id``."""
        prompt_id = "prompt-" + uuid.uuid4().hex[:12]
        with self.lock:
            self.prompts[prompt_id] = payload
            self.prompt_order.append(prompt_id)
        return prompt_id

    def history_entry(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """The success history entry for ``prompt_id`` (``None`` when cancelled)."""
        with self.lock:
            if prompt_id in self.cancelled:
                return None
            payload = self.prompts.get(prompt_id)
            if payload is None:
                return None
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        seed = 0
        if isinstance(prompt, dict):
            for node in prompt.values():
                inputs = node.get("inputs") if isinstance(node, dict) else None
                if isinstance(inputs, dict) and isinstance(inputs.get("seed"), int):
                    seed = inputs["seed"]
                    break
        return {
            "prompt": prompt if isinstance(prompt, dict) else {},
            "outputs": {
                "9": {
                    "images": [
                        {
                            "filename": "gen_backend/txt2img_00001_.png",
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                }
            },
            "status": {"completed": True, "messages": [], "status_str": "success"},
            "meta": {"seed": seed, "elapsed_s": 0.1, "model_id": "fake-comfyui"},
        }


class _FakeHandler(BaseHTTPRequestHandler):
    """Route handler for the fake ComfyUI surface (no state of its own)."""

    server_version = "FakeComfyUI/0.1"
    state: _FakeState  # injected by :func:`start_fake_comfyui`

    # -- response helpers --------------------------------------------------

    def _send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code: int, blob: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence per-request logging (test output stays readable)."""

    # -- routing -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/queue":
            self._send_json(200, {"queue_running": [], "queue_pending": []})
        elif path.startswith("/history/"):
            prompt_id = urllib.parse.unquote(path.split("/history/", 1)[1])
            entry = self.state.history_entry(prompt_id)
            self._send_json(200, {prompt_id: entry} if entry is not None else {})
        elif path == "/view":
            try:
                self._send_bytes(200, self.state.png(), "image/png")
            except ImportError:
                self._send_json(500, {"error": "Pillow is not installed"})
        elif path == "/object_info":
            self._send_json(200, OBJECT_INFO)
        elif path.startswith("/object_info/"):
            loader = urllib.parse.unquote(path.split("/object_info/", 1)[1])
            node = OBJECT_INFO.get(loader)
            if node is None:
                self._send_json(404, {"error": f"unknown node {loader!r}"})
            else:
                self._send_json(200, {loader: node})
        elif path == "/prompt":
            self._send_json(200, {"exec_info": {"queue_remaining": 0}})
        elif path == "/system_stats":
            self._send_json(
                200,
                {
                    "system": {"os": "nt", "python_version": "3.13", "embedded_python": False},
                    "devices": [{"name": "fake-cpu", "type": "cpu", "vram_total": 0, "vram_free": 0}],
                },
            )
        else:
            self._send_json(404, {"error": f"unknown route {path!r}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        body = self._read_body()
        if path == "/prompt":
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                self._send_json(400, {"error": "invalid JSON body"})
                return
            if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), dict):
                self._send_json(400, {"error": "missing prompt dict"})
                return
            prompt_id = self.state.submit(payload)
            self._send_json(
                200, {"prompt_id": prompt_id, "number": 1, "node_errors": {}}
            )
        elif path == "/upload/image":
            try:
                parsed_form = _parse_multipart(
                    self.headers.get("Content-Type") or "", body
                )
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            files = parsed_form["files"]
            if "image" not in files:
                self._send_json(400, {"error": "missing image file field"})
                return
            filename, blob = files["image"]
            fields = parsed_form["fields"]
            record = {
                "name": filename,
                "subfolder": fields.get("subfolder", ""),
                "type": fields.get("type", "input"),
                "size": len(blob),
            }
            with self.state.lock:
                self.state.uploads.append(record)
            self._send_json(
                200,
                {
                    "name": record["name"],
                    "subfolder": record["subfolder"],
                    "type": record["type"],
                },
            )
        elif path == "/interrupt":
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                payload = {}
            prompt_id = payload.get("prompt_id") if isinstance(payload, dict) else None
            if isinstance(prompt_id, str):
                with self.state.lock:
                    self.state.cancelled.add(prompt_id)
            self._send_json(200, {})
        else:
            self._send_json(404, {"error": f"unknown route {path!r}"})


class FakeComfyUI:
    """Running fake ComfyUI instance; use as a context manager or ``.stop()``."""

    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread) -> None:
        self._server = server
        self._thread = thread
        host, port = server.server_address[:2]
        self.host = host
        self.port = int(port)
        self.url = f"http://{host}:{port}"

    def stop(self) -> None:
        """Shut the HTTP server down and join its thread (idempotent)."""
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()
            self._thread.join(timeout=10)

    def __enter__(self) -> "FakeComfyUI":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "FakeComfyUI(url=%r)" % (self.url,)


def start_fake_comfyui(port: int = 0) -> FakeComfyUI:
    """Start the fake server on loopback (ephemeral port by default).

    ``port=0`` binds a free port, which keeps parallel test runs from
    colliding. The returned handle exposes ``.url`` with the real bound
    port, ``.stop()`` and context-manager support; the server thread is a
    daemon so a leaked handle never blocks interpreter exit.
    """
    state = _FakeState()
    handler = type("_BoundFakeHandler", (_FakeHandler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    thread = threading.Thread(
        target=server.serve_forever,
        name="fake-comfyui",
        daemon=True,
    )
    thread.start()
    return FakeComfyUI(server, thread)


__all__ = [
    "FakeComfyUI",
    "OBJECT_INFO",
    "PNG_SIZE",
    "start_fake_comfyui",
]
