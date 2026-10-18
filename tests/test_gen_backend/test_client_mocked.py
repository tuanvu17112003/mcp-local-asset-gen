"""Mocked-HTTP adapter tests (stub transport, no live server, stdlib only).

ClientMockedHttpTest drives ComfyClient end-to-end against an injected stub
transport serving fixtures/c2 payloads. FakeTransportTest covers the
contract-shape transport checks directly.
"""

import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from gen_backend import ComfyClient
from gen_backend.presets import build_txt2img_params, inject_params

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "c2")


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


class FakeTransport:
    """In-memory fake ComfyUI: POST /prompt, GET /history/{id}, GET /view, GET /queue."""

    def __init__(self):
        self.prompts = {}
        self.cancelled = set()

    def post_prompt(self, payload):
        prompt = payload.get("prompt", {})
        node_ids = [k for k in prompt if not k.startswith("_")]
        if not node_ids or not all(n.isdigit() for n in node_ids):
            raise ValueError("UNKNOWN_WORKFLOW: non-API-format prompt")
        prompt_id = "prompt-abc123"
        self.prompts[prompt_id] = prompt
        return {"prompt_id": prompt_id, "number": 1, "node_errors": {}}

    def get_history(self, prompt_id):
        if prompt_id in self.cancelled or prompt_id not in self.prompts:
            return {}
        return load_fixture("history_success.json")

    def get_view(self, filename, subfolder="", type="output"):
        with open(os.path.join(FIXTURES_DIR, "tiny.png"), "rb") as fh:
            return fh.read()

    def get_queue(self):
        return {"queue_running": [], "queue_pending": []}

    def post_interrupt(self):
        self.cancelled.update(self.prompts)
        return {}


class FakeTransportTest(unittest.TestCase):
    """Contract-shape transport checks that run with or without client.py."""

    def test_submit_then_history_then_view(self):
        transport = FakeTransport()
        with open(os.path.join(os.path.dirname(__file__), "..", "..", "src",
                               "gen_backend", "workflows",
                               "txt2img-flux-schnell-fp8.json"), encoding="utf-8") as fh:
            workflow = json.load(fh)
        resp = transport.post_prompt({"prompt": workflow})
        prompt_id = resp["prompt_id"]
        self.assertEqual(transport.get_queue(), {"queue_running": [], "queue_pending": []})
        history = transport.get_history(prompt_id)
        entry = history[prompt_id]
        image = entry["outputs"]["8"]["images"][0]
        blob = transport.get_view(image["filename"], image["subfolder"], image["type"])
        self.assertTrue(blob.startswith(b"\x89PNG"))

    def test_cancel_never_resolves(self):
        transport = FakeTransport()
        transport.post_prompt({"prompt": {"1": {"class_type": "X", "inputs": {}}}})
        transport.post_interrupt()
        self.assertEqual(transport.get_history("prompt-abc123"), {})

    def test_rejects_non_api_format(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(ValueError, "UNKNOWN_WORKFLOW"):
            transport.post_prompt({"prompt": {"weird-key": {}}})


class _StubComfyTransport:
    """Injectable fake for ComfyClient(post_json/get_json/get_bytes), no network.

    Serves fixtures/c2 payloads: POST /prompt -> prompt_id, GET /queue empty,
    GET /history/{id} -> history_success.json, GET /view -> tiny.png bytes,
    POST /interrupt records cancel.
    """

    PROMPT_ID = "prompt-abc123"

    def __init__(self):
        self.submitted = {}
        self.interrupt_calls = []

    def post_json(self, url, body, timeout):
        if url.endswith("/prompt"):
            prompt = (body or {}).get("prompt", {})
            if any(k.startswith("_") for k in prompt):
                raise AssertionError("prompt_dict still carries _meta keys")
            node_ids = [k for k in prompt]
            if not node_ids or not all(n.isdigit() for n in node_ids):
                raise AssertionError("prompt_dict is not API-format (digit node ids)")
            self.submitted[self.PROMPT_ID] = prompt
            return 200, {"prompt_id": self.PROMPT_ID, "number": 1, "node_errors": {}}
        if url.endswith("/interrupt"):
            self.interrupt_calls.append(dict(body or {}))
            return 200, {}
        raise AssertionError("unexpected POST " + url)

    def get_json(self, url, timeout):
        if url.endswith("/queue"):
            return 200, {"queue_running": [], "queue_pending": []}
        if "/history/" in url:
            prompt_id = url.rsplit("/", 1)[-1]
            if any(c.get("prompt_id") == prompt_id for c in self.interrupt_calls):
                return 200, {}
            return 200, load_fixture("history_success.json")
        raise AssertionError("unexpected GET " + url)

    def get_bytes(self, url, timeout):
        if "/view" in url:
            with open(os.path.join(FIXTURES_DIR, "tiny.png"), "rb") as fh:
                return 200, fh.read()
        raise AssertionError("unexpected GET bytes " + url)


class ClientMockedHttpTest(unittest.TestCase):
    """End-to-end build->inject->submit->poll->fetch->cancel on a stub transport."""

    def test_submit_poll_fetch_cancel(self):
        workflow_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "src",
            "gen_backend", "workflows",
            "txt2img-flux-schnell-gguf-q4.json")
        with open(os.path.normpath(workflow_path), encoding="utf-8") as fh:
            workflow = json.load(fh)
        params = build_txt2img_params(
            prompt="a scooter icon",
            workflow_id="txt2img-flux-schnell-gguf-q4",
            width=512, height=512, seed=12345)
        prompt_dict = inject_params(workflow, params)
        # _meta stripped + W/H/seed propagation at injection time.
        self.assertFalse(any(k.startswith("_") for k in prompt_dict))
        self.assertEqual(prompt_dict["6"]["inputs"]["width"], 512)
        self.assertEqual(prompt_dict["6"]["inputs"]["height"], 512)
        self.assertEqual(prompt_dict["7"]["inputs"]["seed"], 12345)

        transport = _StubComfyTransport()
        client = ComfyClient(
            transport=transport,
            sleep=lambda s: None,
            clock=lambda: 1000.0)
        prompt_id = client.submit(prompt_dict)
        self.assertEqual(prompt_id, "prompt-abc123")
        # Submitted payload is the injected prompt (512x512 + seed echo).
        submitted = transport.submitted[prompt_id]
        self.assertEqual(submitted["6"]["inputs"]["width"], 512)
        self.assertEqual(submitted["6"]["inputs"]["height"], 512)
        self.assertEqual(submitted["7"]["inputs"]["seed"], 12345)

        self.assertEqual(client.queue_status(prompt_id), "completed")
        history = client.poll(prompt_id)
        self.assertIn(prompt_id, history)

        result = client.fetch_result(
            prompt_id,
            request_echo={"width": params["width"], "height": params["height"],
                          "seed": params["seed"], "model_id": params["model_id"]})
        self.assertEqual(result["width"], 512)
        self.assertEqual(result["height"], 512)
        self.assertEqual(result["seed"], 12345)
        self.assertTrue(result["png_bytes"].startswith(b"\x89PNG"))
        self.assertTrue(len(result["png_bytes"]) > 0)

        self.assertTrue(client.cancel(prompt_id))
        self.assertTrue(any(c.get("prompt_id") == prompt_id
                            for c in transport.interrupt_calls))


if __name__ == "__main__":
    unittest.main()
