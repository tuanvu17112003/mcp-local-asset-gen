"""Canned-history parser + fixture-conformance tests. No live ComfyUI (stdlib only).

Reference extractor mirrors the contract history shape
({prompt_id: {outputs: {node_id: {images: [{filename, subfolder, type}]}}}}
+ status/meta), i.e. what sibling slice client.py parses. If client.py later
exposes its own extractor, these fixtures must satisfy it identically.
"""

import json
import os
import unittest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "c2")


def load_fixture(name, binary=False):
    with open(os.path.join(FIXTURES_DIR, name), "rb" if binary else "r",
              encoding=None if binary else "utf-8") as fh:
        return fh.read()


def extract_images(history, prompt_id):
    """Reference outputs extractor: (images, status_str). Raises on error payload."""
    try:
        entry = history[prompt_id]
    except KeyError:
        raise ValueError("NOT_FOUND: prompt_id=%r" % (prompt_id,))
    status = entry.get("status", {})
    if status.get("status_str") == "error":
        raise ValueError("JOB_FAILED: %s" % (status.get("messages"),))
    images = []
    for node_id, output in (entry.get("outputs") or {}).items():
        for image in output.get("images", []):
            images.append((node_id, image))
    return images, status.get("status_str")


class HistoryFixturesTest(unittest.TestCase):
    def test_success_extraction(self):
        history = json.loads(load_fixture("history_success.json"))
        images, status = extract_images(history, "prompt-abc123")
        self.assertEqual(status, "success")
        self.assertTrue(images, "no images extracted")
        node_id, image = images[0]
        self.assertEqual(image["filename"], "gen_backend/txt2img_00001_.png")
        self.assertIn("subfolder", image)
        self.assertIn("type", image)

    def test_error_payload(self):
        history = json.loads(load_fixture("history_error.json"))
        with self.assertRaisesRegex(ValueError, "JOB_FAILED"):
            extract_images(history, "prompt-bad456")
        entry = history["prompt-bad456"]
        self.assertEqual(entry["status"]["status_str"], "error")
        self.assertTrue(entry["status"]["messages"])
        self.assertEqual(entry["outputs"], {})

    def test_unknown_id(self):
        history = json.loads(load_fixture("history_success.json"))
        with self.assertRaisesRegex(ValueError, "NOT_FOUND"):
            extract_images(history, "prompt-missing")

    def test_tiny_png_valid(self):
        raw = load_fixture("tiny.png", binary=True)
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"), "not a PNG")
        self.assertGreater(len(raw), 0)

    def test_fake_comfyui_spec_covers_routes(self):
        spec = load_fixture("fake_comfyui.md")
        for route in ("POST /prompt", "GET /history/", "GET /view", "GET /queue", "POST /interrupt"):
            self.assertIn(route, spec)


if __name__ == "__main__":
    unittest.main()
