"""img2img param tests. Source file read-only, never mutated (stdlib only)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "gen_backend"))

import img2img

TINY_PNG = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "c2", "tiny.png")


class Img2ImgTest(unittest.TestCase):
    def test_build_defaults(self):
        params = img2img.build_img2img_params(os.path.abspath(TINY_PNG), "make it red")
        self.assertEqual(params["strength"], 0.6)
        self.assertEqual(params["input_png_name"], "tiny.png")
        self.assertEqual(params["instruction"], "make it red")
        self.assertEqual(params["steps"], 4)

    def test_rejects_bad_strength(self):
        for bad in (0, 1.5, "0.6"):
            with self.assertRaisesRegex(ValueError, "INVALID_STRENGTH"):
                img2img.build_img2img_params(os.path.abspath(TINY_PNG), "x", strength=bad)

    def test_rejects_missing_input(self):
        with self.assertRaisesRegex(ValueError, "INPUT_NOT_FOUND"):
            img2img.build_img2img_params("does-not-exist.png", "x")

    def test_load_is_readonly(self):
        before = os.path.getmtime(os.path.abspath(TINY_PNG))
        blob = img2img.load_input_bytes(os.path.abspath(TINY_PNG))
        self.assertTrue(blob.startswith(b"\x89PNG"))
        self.assertEqual(before, os.path.getmtime(os.path.abspath(TINY_PNG)))

    def test_node_map_documents_hook(self):
        self.assertEqual(img2img.IMG2IMG_NODE_MAP["load_image_node"], "11")
        self.assertEqual(img2img.IMG2IMG_NODE_MAP["strength_field"], "denoise")


if __name__ == "__main__":
    unittest.main()
