"""v0.7 features: WS per-node progress, LoRA injection, PNG metadata, CI file.

Client-level tests use fake transports / fake websocket objects (no live
server, no real sockets). Orchestrator-level tests reuse the fake-backend
conventions from test_progress_cancel.py.
"""

from __future__ import annotations

import io
import json
import os
import sys

import pytest

SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


@pytest.fixture(autouse=True)
def _no_fastmcp_leak():
    before = {k for k in sys.modules if k == "fastmcp" or k.startswith("fastmcp.")}
    yield
    for k in [k for k in sys.modules
              if (k == "fastmcp" or k.startswith("fastmcp.")) and k not in before]:
        del sys.modules[k]


# -- WS progress drain (unit) ----------------------------------------------


class FakeWS:
    def __init__(self, frames):
        self._frames = list(frames)
        self.closed = False

    def recv(self):
        if not self._frames:
            import websocket

            raise websocket.WebSocketTimeoutException()
        frame = self._frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame


def _progress_frame(value, maximum, prompt_id="p1", node="7"):
    return json.dumps(
        {"type": "progress", "data": {"value": value, "max": maximum,
                                      "prompt_id": prompt_id, "node": node}}
    )


def test_drain_progress_ws_forwards_matching_frames():
    sys.path.insert(0, SRC)
    from gen_backend.client import _drain_progress_ws

    seen = []
    ws = FakeWS([
        _progress_frame(0, 4, prompt_id="other"),   # different prompt: ignored
        b"\x00\x01binary-preview",                   # binary: ignored
        "not json",                                  # malformed: ignored
        json.dumps({"type": "status", "data": {}}),  # other type: ignored
        _progress_frame(1, 4),
        _progress_frame(4, 4, node=None),
    ])
    assert _drain_progress_ws(ws, "p1", lambda f, n: seen.append((f, n))) is True
    assert seen == [(0.25, "7"), (1.0, None)]


def test_drain_progress_ws_reports_dead_on_transport_error():
    sys.path.insert(0, SRC)
    from gen_backend.client import _drain_progress_ws

    ws = FakeWS([ConnectionError("reset")])
    assert _drain_progress_ws(ws, "p1", lambda f, n: None) is False


def test_drain_progress_ws_reports_dead_on_raising_callback():
    sys.path.insert(0, SRC)
    from gen_backend.client import _drain_progress_ws

    def bad(fraction, node):
        raise RuntimeError("sink down")

    ws = FakeWS([_progress_frame(1, 4)])
    assert _drain_progress_ws(ws, "p1", bad) is False


def test_poll_without_websocket_module_skips_ws(monkeypatch):
    """No websocket-client installed -> poll still completes, no WS attempted."""
    sys.path.insert(0, SRC)
    monkeypatch.setitem(sys.modules, "websocket", None)  # import fails

    from gen_backend.client import ComfyClient

    class Transport:
        def get_json(self, url, timeout):
            if "/queue" in url:
                return 200, {"queue_running": [], "queue_pending": []}
            return 200, {"p1": {"outputs": {"8": {"images": []}},
                                "status": {"completed": True, "status_str": "success"}}}

    calls = {"drained": 0}
    client = ComfyClient(base_url="http://127.0.0.1:1", max_wait_s=1.0,
                         transport=Transport())
    assert client.poll("p1", on_progress=lambda f, n: None)


# -- LoRA: params + injection ----------------------------------------------


def test_build_params_lora_defaults_and_validation():
    sys.path.insert(0, SRC)
    from gen_backend.presets import build_txt2img_params

    params = build_txt2img_params("bear", lora="flat_v2.safetensors", lora_strength=1.4)
    assert params["lora"] == "flat_v2.safetensors"
    assert params["lora_strength"] == 1.4
    assert build_txt2img_params("bear")["lora"] is None
    with pytest.raises(ValueError, match="INVALID_LORA"):
        build_txt2img_params("bear", lora="../evil.safetensors")
    with pytest.raises(ValueError, match="INVALID_LORA_STRENGTH"):
        build_txt2img_params("bear", lora="x.safetensors", lora_strength=0)
    with pytest.raises(ValueError, match="INVALID_LORA_STRENGTH"):
        build_txt2img_params("bear", lora="x.safetensors", lora_strength=5)


def test_inject_params_lora_rewires_model_chain():
    sys.path.insert(0, SRC)
    from gen_backend.presets import build_txt2img_params, inject_params

    workflow = json.load(open(os.path.join(
        SRC, "gen_backend", "workflows", "txt2img-flux-schnell-gguf-q4.json"),
        encoding="utf-8"))
    params = build_txt2img_params("bear", lora="flat.safetensors")
    prompt = inject_params(workflow, params)
    assert prompt["13"]["class_type"] == "LoraLoaderModelOnly"
    assert prompt["13"]["inputs"]["lora_name"] == "flat.safetensors"
    assert prompt["13"]["inputs"]["model"] == ["1", 0]
    assert prompt["10"]["inputs"]["model"] == ["13", 0]
    # No lora -> untouched chain, no node 13.
    plain = inject_params(workflow, build_txt2img_params("bear"))
    assert "13" not in plain
    assert plain["10"]["inputs"]["model"] == ["1", 0]
    assert not any(k.startswith("_") for k in prompt)


def test_inject_params_lora_missing_flux_node_raises():
    sys.path.insert(0, SRC)
    from gen_backend.presets import build_txt2img_params, inject_params

    workflow = {"1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "x"}}}
    with pytest.raises(ValueError, match="WORKFLOW_NODE_MISMATCH"):
        inject_params(workflow, build_txt2img_params("bear", lora="x.safetensors"))


def test_check_model_lora_kind_validates():
    sys.path.insert(0, SRC)
    from src.mcp_server.validation import validate_check_model_args

    assert validate_check_model_args("x.safetensors", "lora") == {
        "name": "x.safetensors", "kind": "lora"}
    with pytest.raises(ValueError, match="UNKNOWN_LOADER"):
        validate_check_model_args("x.safetensors", "embeddings")


# -- MCP validation: lora params -------------------------------------------


def test_mcp_lora_validation():
    sys.path.insert(0, SRC)
    from src.mcp_server.validation import validate_tool_args

    args = validate_tool_args(
        prompt="bear", category="icon", save_path="a/b.png",
        lora="flat.safetensors", lora_strength=0.8,
    )
    assert args["lora"] == "flat.safetensors"
    assert args["lora_strength"] == 0.8
    args = validate_tool_args(prompt="bear", category="icon", save_path="a/b.png")
    assert args["lora"] is None and args["lora_strength"] == 1.0
    with pytest.raises(ValueError, match="INVALID_LORA_STRENGTH"):
        validate_tool_args(
            prompt="bear", category="icon", save_path="a/b.png",
            lora="flat.safetensors", lora_strength=3,
        )
    with pytest.raises(ValueError, match="INVALID_LORA"):
        validate_tool_args(
            prompt="bear", category="icon", save_path="a/b.png", lora_strength=1.0,
        )
    with pytest.raises(ValueError, match="INVALID_LORA"):
        validate_tool_args(
            prompt="bear", category="icon", save_path="a/b.png", lora="a/b.sft",
        )


# -- PNG metadata -----------------------------------------------------------


def _png_bytes(w=8, h=8):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(buf, "PNG")
    return buf.getvalue()


def _read_text_chunks(png):
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    return dict(img.text or {})


def test_generate_embeds_png_metadata(tmp_path):
    sys.path.insert(0, SRC)
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    class FakeBackend:
        def submit_txt2img(self, **kwargs):
            return "backend-job-1"

        def fetch_result(self, job_id, on_progress=None):
            return {"png_bytes": _png_bytes(), "seed": 7}

    def fake_postprocess(png_bytes, **kwargs):
        stem = kwargs.get("stem", "icon")
        return {"files": [{"filename": "%s.png" % stem,
                           "png_bytes": bytes(png_bytes)}],
                "alpha": True, "model_used": "u2net"}

    written = {}

    def writer(path, data):
        written[str(path)] = bytes(data)

    orch = AssetOrchestrator(FakeBackend(), postprocess=fake_postprocess, writer=writer)
    result = orch.generate(
        validate_tool_args(prompt="bear", category="icon", save_path="a/bear.png"),
        tmp_path,
    )
    meta = _read_text_chunks(next(iter(written.values())))
    assert meta["prompt"] == "bear"
    assert meta["category"] == "icon"
    assert meta["job_id"] == result["job_id"] and meta["seed"] == "7"
    assert meta["software"].startswith("mcp-local-asset-gen/")
    assert meta["remove_bg_model"] == "u2net"


def test_metadata_embed_is_best_effort_on_fake_png(tmp_path):
    """Undecodable canned bytes must flow through unchanged (no crash)."""
    sys.path.insert(0, SRC)
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    class FakeBackend:
        def submit_txt2img(self, **kwargs):
            return "backend-job-1"

        def fetch_result(self, job_id, on_progress=None):
            return {"png_bytes": FAKE_PNG, "seed": 7}

    def fake_postprocess(png_bytes, **kwargs):
        stem = kwargs.get("stem", "icon")
        return {"files": [{"filename": "%s.png" % stem,
                           "png_bytes": bytes(png_bytes)}],
                "alpha": True, "model_used": "none"}

    written = {}

    def writer(path, data):
        written[str(path)] = bytes(data)

    orch = AssetOrchestrator(FakeBackend(), postprocess=fake_postprocess, writer=writer)
    orch.generate(
        validate_tool_args(prompt="bear", category="icon", save_path="a/bear.png"),
        tmp_path,
    )
    assert next(iter(written.values())) == FAKE_PNG


# -- orchestrator: fraction bridge (fake backend with on_progress) ----------


def test_orchestrator_maps_fractions_to_sub_phase_ticks(tmp_path):
    sys.path.insert(0, SRC)
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    class FakeBackend:
        def submit_txt2img(self, **kwargs):
            return "backend-job-1"

        def fetch_result(self, job_id, on_progress=None):
            on_progress(0.25, "7")
            on_progress(1.0, None)
            return {"png_bytes": FAKE_PNG, "seed": 7}

    def fake_postprocess(png_bytes, **kwargs):
        stem = kwargs.get("stem", "icon")
        return {"files": [{"filename": "%s.png" % stem,
                           "png_bytes": bytes(png_bytes)}],
                "alpha": True, "model_used": "none"}

    ticks = []
    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess,
        writer=lambda p, d: None,
    )
    orch.generate(
        validate_tool_args(prompt="bear", category="icon", save_path="a/bear.png"),
        tmp_path,
        progress=lambda v, t, m: ticks.append((v, t)),
    )
    assert (0, 4) in ticks and (2, 4) in ticks
    fracs = [v for v, _ in ticks if isinstance(v, float)]
    assert 1.25 in fracs and 2.0 in fracs


# -- CI workflow file --------------------------------------------------------


def test_ci_workflow_defines_expected_matrix():
    root = os.path.normpath(os.path.join(SRC, ".."))
    path = os.path.join(root, ".github", "workflows", "ci.yml")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert "ubuntu-latest" in text and "windows-latest" in text
    assert "requirements-dev.txt" in text and "pytest" in text
