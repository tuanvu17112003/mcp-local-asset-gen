"""Presets + workflow injection tests. No live ComfyUI, no downloads (stdlib only)."""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "gen_backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import presets

try:
    from gen_backend.errors import UnknownWorkflowError
except ImportError:  # direct-file fallback
    from errors import UnknownWorkflowError  # type: ignore

WORKFLOWS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src", "gen_backend", "workflows")


def load_workflow(name):
    with open(os.path.join(WORKFLOWS_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


class ApiFormatTest(unittest.TestCase):
    def test_both_workflows_are_api_format(self):
        for name in ("txt2img-flux-schnell-gguf-q4.json", "txt2img-flux-schnell-fp8.json"):
            with self.subTest(workflow=name):
                wf = load_workflow(name)
                node_ids = [k for k in wf if not k.startswith("_")]
                self.assertTrue(node_ids, "no nodes")
                for nid in node_ids:
                    self.assertTrue(nid.isdigit(), "non-numeric node id %r" % nid)
                    self.assertIn("class_type", wf[nid])
                    self.assertIn("inputs", wf[nid])
                    # UI-layout keys must not appear in API format
                    for banned in ("pos", "size", "widgets_values", "flags", "order", "mode"):
                        self.assertNotIn(banned, wf[nid])

    def test_gguf_defaults(self):
        wf = load_workflow("txt2img-flux-schnell-gguf-q4.json")
        self.assertEqual(wf["1"]["class_type"], "UnetLoaderGGUF")
        self.assertEqual(wf["1"]["inputs"]["unet_name"], "flux1-schnell-Q4_K_S.gguf")
        self.assertEqual(wf["2"]["inputs"]["device"], "cpu")  # T5-XXL/CLIP on CPU
        self.assertEqual(wf["6"]["inputs"]["width"], 512)
        self.assertEqual(wf["6"]["inputs"]["height"], 512)
        self.assertEqual(wf["7"]["inputs"]["steps"], 4)
        self.assertEqual(wf["10"]["inputs"]["guidance"], 0.0)
        self.assertIn("_meta", wf)
        self.assertIn("models/unet/", json.dumps(wf["_meta"]))

    def test_fp8_defaults(self):
        wf = load_workflow("txt2img-flux-schnell-fp8.json")
        self.assertEqual(wf["1"]["class_type"], "CheckpointLoaderSimple")
        self.assertEqual(wf["1"]["inputs"]["ckpt_name"], "flux1-schnell-fp8.safetensors")
        self.assertEqual(wf["6"]["inputs"]["width"], 512)
        self.assertEqual(wf["7"]["inputs"]["steps"], 4)
        self.assertEqual(wf["10"]["inputs"]["guidance"], 0.0)


class PresetsTest(unittest.TestCase):
    def test_lists(self):
        self.assertIn("flux-schnell-gguf-q4", presets.list_models())
        self.assertIn("flux-schnell-fp8", presets.list_models())
        self.assertEqual(presets.list_models()[0], "flux-schnell-gguf-q4")  # default first
        for style in ("flat", "3d-clay", "minimal-line", "pixel-art"):
            self.assertIn(style, presets.list_styles())

    def test_lora_stub_empty(self):
        self.assertEqual(presets.LORA_HOOK["loras"], [])
        self.assertFalse(presets.LORA_HOOK["enabled"])
        self.assertIn("hook", presets.LORA_HOOK)

    def test_build_defaults(self):
        params = presets.build_txt2img_params("a scooter icon")
        self.assertEqual(params["width"], 512)
        self.assertEqual(params["height"], 512)
        self.assertEqual(params["steps"], 4)
        self.assertEqual(params["guidance"], 0.0)
        self.assertIsInstance(params["seed"], int)

    def test_build_unknown_workflow(self):
        with self.assertRaises(UnknownWorkflowError) as ctx:
            presets.build_txt2img_params("x", workflow_id="nope")
        self.assertEqual(ctx.exception.code, "UNKNOWN_WORKFLOW")
        self.assertIn("UNKNOWN_WORKFLOW", str(ctx.exception))
        self.assertEqual(ctx.exception.payload["workflow_id"], "nope")

    def test_build_rejects_guidance(self):
        with self.assertRaisesRegex(ValueError, "GUIDANCE_NOT_SUPPORTED"):
            presets.build_txt2img_params("x", guidance=7.5)

    def test_build_rejects_bad_steps(self):
        for bad in (0, 5, "4"):
            with self.assertRaisesRegex(ValueError, "INVALID_STEPS"):
                presets.build_txt2img_params("x", steps=bad)

    def test_style_applied(self):
        params = presets.build_txt2img_params("a scooter", style="flat")
        self.assertIn("a scooter", params["prompt"])
        self.assertIn("flat", params["prompt"].lower())
        with self.assertRaisesRegex(ValueError, "UNKNOWN_STYLE"):
            presets.build_txt2img_params("x", style="nope")


class InjectTest(unittest.TestCase):
    def test_wxh_seed_propagation_both_workflows(self):
        for name, wid in (("txt2img-flux-schnell-gguf-q4.json", "txt2img-flux-schnell-gguf-q4"),
                          ("txt2img-flux-schnell-fp8.json", "txt2img-flux-schnell-fp8")):
            with self.subTest(workflow=wid):
                wf = load_workflow(name)
                snapshot = copy.deepcopy(wf)
                params = presets.build_txt2img_params(
                    "a scooter icon", negative="blurry", workflow_id=wid,
                    width=768, height=512, steps=2, seed=42)
                prompt = presets.inject_params(wf, params)
                self.assertNotIn("_meta", prompt)  # stripped before submit
                self.assertEqual(prompt["4"]["inputs"]["text"], "a scooter icon")
                self.assertEqual(prompt["5"]["inputs"]["text"], "blurry")
                self.assertEqual(prompt["6"]["inputs"]["width"], 768)
                self.assertEqual(prompt["6"]["inputs"]["height"], 512)
                self.assertEqual(prompt["7"]["inputs"]["seed"], 42)
                self.assertEqual(prompt["7"]["inputs"]["steps"], 2)
                self.assertEqual(prompt["10"]["inputs"]["guidance"], 0.0)
                self.assertEqual(prompt["10"]["inputs"]["width"], 768)
                self.assertEqual(wf, snapshot, "input workflow must not be mutated")

    def test_node_mismatch(self):
        with self.assertRaisesRegex(ValueError, "WORKFLOW_NODE_MISMATCH"):
            presets.inject_params({"4": {}}, {"prompt": "x", "width": 1,
                                              "height": 1, "seed": 1, "steps": 1})


class EncoderClipTest(unittest.TestCase):
    """Gen-5 (IC-3 live finding): fp8 encoder default + overrides."""

    def test_pinned_workflow_default_is_fp8(self):
        wf = load_workflow("txt2img-flux-schnell-gguf-q4.json")
        self.assertEqual(wf["2"]["inputs"]["clip_name1"],
                         "t5xxl_fp8_e4m3fn.safetensors")
        self.assertEqual(wf["2"]["inputs"]["clip_name2"], "clip_l.safetensors")
        self.assertIn("t5xxl_fp8_e4m3fn.safetensors",
                      json.dumps(wf["_meta"]["required_files"]))
        self.assertNotIn("t5xxl_fp16", json.dumps(wf))

    def test_inject_defaults_resolve_to_pinned(self):
        wf = load_workflow("txt2img-flux-schnell-gguf-q4.json")
        params = presets.build_txt2img_params("a scooter icon", seed=7)
        prompt = presets.inject_params(wf, params)
        self.assertEqual(prompt["2"]["inputs"]["clip_name1"],
                         presets.DEFAULT_CLIP_NAME1)
        self.assertEqual(prompt["2"]["inputs"]["clip_name2"],
                         presets.DEFAULT_CLIP_NAME2)
        self.assertEqual(prompt["2"]["inputs"]["clip_name1"],
                         "t5xxl_fp8_e4m3fn.safetensors")

    def test_inject_overrides_honored(self):
        wf = load_workflow("txt2img-flux-schnell-gguf-q4.json")
        params = presets.build_txt2img_params("a scooter icon", seed=7)
        prompt = presets.inject_params(
            wf, params,
            clip_name1="custom-t5.safetensors", clip_name2="custom-clip.safetensors")
        self.assertEqual(prompt["2"]["inputs"]["clip_name1"], "custom-t5.safetensors")
        self.assertEqual(prompt["2"]["inputs"]["clip_name2"], "custom-clip.safetensors")
        # params-dict form is also honored when kwargs are omitted
        params2 = dict(params, clip_name1="via-params.safetensors")
        prompt2 = presets.inject_params(wf, params2)
        self.assertEqual(prompt2["2"]["inputs"]["clip_name1"], "via-params.safetensors")
        self.assertEqual(prompt2["2"]["inputs"]["clip_name2"], "clip_l.safetensors")

    def test_inject_rejects_bad_clip_names(self):
        wf = load_workflow("txt2img-flux-schnell-gguf-q4.json")
        params = presets.build_txt2img_params("a scooter icon", seed=7)
        for bad in ("", "   ", "../evil.safetensors", "sub/dir.safetensors",
                    "c:\\evil.safetensors", "..", 123):
            with self.subTest(clip=bad):
                with self.assertRaisesRegex(ValueError, "INVALID_CLIP_NAME"):
                    presets.inject_params(wf, params, clip_name1=bad)

    def test_inject_leaves_fp8_checkpoint_workflow_untouched(self):
        wf = load_workflow("txt2img-flux-schnell-fp8.json")
        self.assertNotIn("2", wf)
        params = presets.build_txt2img_params(
            "a scooter icon", workflow_id="txt2img-flux-schnell-fp8", seed=7)
        prompt = presets.inject_params(wf, params)
        self.assertNotIn("2", prompt)  # no encoder node invented


if __name__ == "__main__":
    unittest.main()
