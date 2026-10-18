"""Rework review-1 regression tests (H-1/H-3/M-1/H-2/M-3). Package-style imports."""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from gen_backend import (
    ComfyClient,
    UnknownWorkflowError,
    build_img2img_params,
    build_txt2img_params,
    inject_img2img,
    inject_params,
    submit_img2img,
    submit_txt2img,
)
from gen_backend.presets import DEFAULT_MODEL_ID, DEFAULT_WORKFLOW_ID, MODEL_PRESETS

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "c2")
WORKFLOWS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src", "gen_backend", "workflows")
TINY_PNG = os.path.normpath(os.path.join(FIXTURES_DIR, "tiny.png"))


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def load_workflow(name):
    with open(os.path.join(WORKFLOWS_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


class _StubTransport:
    """Minimal stub: queue empty, history_success.json, tiny.png bytes."""

    PROMPT_ID = "prompt-abc123"

    def __init__(self, history=None):
        self.submitted = {}
        self.interrupt_calls = []
        self._history = history

    def post_json(self, url, body, timeout):
        if url.endswith("/prompt"):
            self.submitted[self.PROMPT_ID] = dict(body or {}).get("prompt", {})
            return 200, {"prompt_id": self.PROMPT_ID, "number": 1, "node_errors": {}}
        if url.endswith("/interrupt"):
            self.interrupt_calls.append(dict(body or {}))
            return 200, {}
        raise AssertionError("unexpected POST " + url)

    def get_json(self, url, timeout):
        if url.endswith("/queue"):
            return 200, {"queue_running": [], "queue_pending": []}
        if "/history/" in url:
            if self._history is not None:
                return 200, self._history
            return 200, load_fixture("history_success.json")
        raise AssertionError("unexpected GET " + url)

    def get_bytes(self, url, timeout):
        if "/view" in url:
            with open(TINY_PNG, "rb") as fh:
                return 200, fh.read()
        raise AssertionError("unexpected GET bytes " + url)


class TypedUnknownWorkflowTest(unittest.TestCase):
    def test_unknown_workflow_typed(self):
        with self.assertRaises(UnknownWorkflowError) as ctx:
            build_txt2img_params("x", workflow_id="nope")
        self.assertEqual(ctx.exception.code, "UNKNOWN_WORKFLOW")
        self.assertTrue(str(ctx.exception).startswith("UNKNOWN_WORKFLOW:"))
        self.assertEqual(ctx.exception.payload["workflow_id"], "nope")
        self.assertIn("txt2img-flux-schnell-gguf-q4", ctx.exception.payload["known"])


class DefaultPairingTest(unittest.TestCase):
    def test_default_model_follows_default_workflow(self):
        self.assertEqual(DEFAULT_WORKFLOW_ID, "txt2img-flux-schnell-gguf-q4")
        self.assertEqual(DEFAULT_MODEL_ID, "flux-schnell-gguf-q4")
        self.assertIn(DEFAULT_MODEL_ID, MODEL_PRESETS)
        self.assertEqual(
            MODEL_PRESETS[DEFAULT_MODEL_ID]["workflow_id"], DEFAULT_WORKFLOW_ID
        )
        params = build_txt2img_params("a scooter icon", seed=7)
        self.assertEqual(params["workflow_id"], DEFAULT_WORKFLOW_ID)
        self.assertEqual(params["model_id"], "flux-schnell-gguf-q4")

    def test_workflow_derives_model(self):
        params = build_txt2img_params(
            "x", workflow_id="txt2img-flux-schnell-fp8", seed=7
        )
        self.assertEqual(params["model_id"], "flux-schnell-fp8")

    def test_explicit_override_allowed(self):
        params = build_txt2img_params(
            "x",
            workflow_id="txt2img-flux-schnell-gguf-q4",
            model_id="flux-schnell-fp8",
            seed=7,
        )
        self.assertEqual(params["model_id"], "flux-schnell-fp8")


class MetaPrecedenceTest(unittest.TestCase):
    def test_meta_fallback_without_request_echo(self):
        transport = _StubTransport()
        client = ComfyClient(transport=transport, sleep=lambda s: None,
                             clock=lambda: 1000.0)
        result = client.fetch_result("prompt-abc123", request_echo=None)
        self.assertEqual(result["seed"], 12345)
        self.assertEqual(result["model_id"], "flux1-schnell-fp8")
        self.assertEqual(result["elapsed_s"], 12.4)
        self.assertTrue(result["png_bytes"].startswith(b"\x89PNG"))
        # No W/H anywhere in this fixture -> None (no regression to fake values).
        self.assertIsNone(result["width"])
        self.assertIsNone(result["height"])

    def test_prompt_echo_outranks_meta(self):
        base = load_fixture("history_success.json")["prompt-abc123"]
        history = {
            "pid1": {
                "meta": {"seed": 1, "model_id": "meta-model",
                         "elapsed_s": 3.0, "width": 512, "height": 512},
                "prompt": {"6": {"inputs": {"width": 768, "height": 512,
                                            "seed": 99}}},
                "outputs": copy.deepcopy(base["outputs"]),
                "status": {"status_str": "success", "completed": True},
            }
        }
        transport = _StubTransport(history=history)
        client = ComfyClient(transport=transport, sleep=lambda s: None,
                             clock=lambda: 1000.0)
        result = client.fetch_result("pid1", request_echo=None)
        # Prompt echo wins over meta for W/H; meta fills seed/model/ellapsed.
        self.assertEqual(result["width"], 768)
        self.assertEqual(result["height"], 512)
        self.assertEqual(result["seed"], 99)
        self.assertEqual(result["model_id"], "meta-model")
        self.assertEqual(result["elapsed_s"], 3.0)


class Img2ImgInjectTest(unittest.TestCase):
    def test_inject_wiring_gguf(self):
        wf = load_workflow("txt2img-flux-schnell-gguf-q4.json")
        snapshot = copy.deepcopy(wf)
        txt = build_txt2img_params("a scooter", seed=42)
        injected = inject_params(wf, txt)
        params = build_img2img_params(os.path.abspath(TINY_PNG), "make it red",
                                      strength=0.6, seed=42)
        before = os.path.getmtime(os.path.abspath(TINY_PNG))
        out = inject_img2img(injected, params)
        # Inputs untouched (deep copy).
        self.assertEqual(wf, snapshot)
        self.assertEqual(injected.get("11"), None)
        # Nodes 11/12 present with documented schema.
        self.assertEqual(out["11"]["class_type"], "LoadImage")
        self.assertEqual(out["11"]["inputs"]["image"], "tiny.png")
        self.assertEqual(out["12"]["class_type"], "VAEEncode")
        self.assertEqual(out["12"]["inputs"]["pixels"], ["11", 0])
        self.assertEqual(out["12"]["inputs"]["vae"], ["3", 0])  # GGUF VAE source
        self.assertEqual(out["7"]["inputs"]["latent_image"], ["12", 0])
        self.assertEqual(out["7"]["inputs"]["denoise"], 0.6)
        self.assertEqual(before, os.path.getmtime(os.path.abspath(TINY_PNG)))

    def test_inject_vae_source_fp8(self):
        wf = load_workflow("txt2img-flux-schnell-fp8.json")
        txt = build_txt2img_params("x", workflow_id="txt2img-flux-schnell-fp8",
                                   seed=1)
        injected = inject_params(wf, txt)
        params = build_img2img_params(os.path.abspath(TINY_PNG), "redo",
                                      strength=0.8, seed=1)
        out = inject_img2img(injected, params)
        self.assertEqual(out["12"]["inputs"]["vae"], ["1", 2])  # FP8 VAE source
        self.assertEqual(out["7"]["inputs"]["denoise"], 0.8)


class SubmitHelpersTest(unittest.TestCase):
    def test_submit_txt2img_helper(self):
        transport = _StubTransport()
        client = ComfyClient(transport=transport, sleep=lambda s: None,
                             clock=lambda: 1000.0)
        prompt_id = submit_txt2img(client, "a scooter icon", seed=12345)
        self.assertEqual(prompt_id, "prompt-abc123")
        submitted = transport.submitted[prompt_id]
        self.assertFalse(any(k.startswith("_") for k in submitted))
        self.assertEqual(submitted["6"]["inputs"]["width"], 512)
        self.assertEqual(submitted["7"]["inputs"]["seed"], 12345)

    def test_submit_img2img_helper(self):
        transport = _StubTransport()
        client = ComfyClient(transport=transport, sleep=lambda s: None,
                             clock=lambda: 1000.0)
        prompt_id = submit_img2img(client, os.path.abspath(TINY_PNG),
                                   "make it red", strength=0.6, seed=42)
        self.assertEqual(prompt_id, "prompt-abc123")
        submitted = transport.submitted[prompt_id]
        self.assertEqual(submitted["11"]["class_type"], "LoadImage")
        self.assertEqual(submitted["12"]["class_type"], "VAEEncode")
        self.assertEqual(submitted["7"]["inputs"]["latent_image"], ["12", 0])
        self.assertEqual(submitted["7"]["inputs"]["denoise"], 0.6)


if __name__ == "__main__":
    unittest.main()
