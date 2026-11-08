"""Upscale node-chain injection tests (P1 / v0.8.0). No live ComfyUI needed.

The graphs under test are the real API-format workflow JSONs on disk
(`txt2img-flux-schnell-gguf-q4.json` / `-fp8.json`), read from
`src/gen_backend/workflows/`; nothing here talks to ComfyUI or downloads a
model. Contract under test: `C2-gen-backend-job` v0.2 upscale slice
(`src/gen_backend/upscale.py`).
"""

from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "gen_backend"))

import gen_backend  # noqa: E402  (path shim must run first)
import presets  # noqa: E402
import upscale  # noqa: E402

WORKFLOWS_DIR = os.path.join(ROOT, "src", "gen_backend", "workflows")
MODEL = "RealESRGAN_x4.pth"


def load_workflow(filename):
    with open(os.path.join(WORKFLOWS_DIR, filename), encoding="utf-8") as fh:
        return json.load(fh)


def injected_prompt(filename="txt2img-flux-schnell-gguf-q4.json", seed=7):
    """The exact input `inject_upscale` sees in production: params already injected."""
    workflow_id = filename[: -len(".json")]
    wf = load_workflow(filename)
    params = presets.build_txt2img_params(
        "an orange scooter icon", workflow_id=workflow_id, seed=seed
    )
    return presets.inject_params(wf, params)


# -- factor contract ---------------------------------------------------------


@pytest.mark.parametrize("value, expected", [(None, 1), (1, 1), (2, 2), (4, 4)])
def test_validate_upscale_factor_accepts(value, expected):
    assert upscale.validate_upscale_factor(value) == expected


@pytest.mark.parametrize(
    "bad", [0, 3, 8, -1, 1.0, 2.5, "2", "", True, False, [2], (2,), {"2": 2}]
)
def test_validate_upscale_factor_rejects(bad):
    with pytest.raises(ValueError, match="INVALID_UPSCALE:"):
        upscale.validate_upscale_factor(bad)


def test_upscale_constants_contract():
    assert upscale.UPSCALE_FACTORS == (1, 2, 4)
    assert upscale.UPSCALE_NODE_MAP == {
        "loader_node": "14",
        "loader_class": "UpscaleModelLoader",
        "upscale_node": "15",
        "upscale_class": "ImageUpscaleWithModel",
        "save_node": "9",
    }


# -- model-name contract -----------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("RealESRGAN_x4.pth", "RealESRGAN_x4.pth"),
        ("  RealESRGAN_x2.pth  ", "RealESRGAN_x2.pth"),
        ("4x-UltraSharp.pth", "4x-UltraSharp.pth"),
    ],
)
def test_validate_upscale_model_accepts(value, expected):
    assert upscale.validate_upscale_model(value) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "../evil.pth",
        "sub/dir.pth",
        "sub\\dir.pth",
        "..\\evil.pth",
        "..",
        "models/upscale_models/RealESRGAN_x4.pth",
        123,
        ["RealESRGAN_x4.pth"],
    ],
)
def test_validate_upscale_model_rejects_traversal(bad):
    with pytest.raises(ValueError, match="INVALID_UPSCALE_MODEL:"):
        upscale.validate_upscale_model(bad)


# -- injection ---------------------------------------------------------------


@pytest.mark.parametrize("factor", [2, 4])
def test_inject_adds_exactly_nodes_14_and_15(factor):
    source = injected_prompt()
    before = set(source)
    prompt = upscale.inject_upscale(source, factor=factor, model_name=MODEL)

    assert set(prompt) - before == {"14", "15"}
    assert prompt["14"] == {
        "class_type": "UpscaleModelLoader",
        "inputs": {"model_name": MODEL},
    }
    assert prompt["15"] == {
        "class_type": "ImageUpscaleWithModel",
        "inputs": {"upscale_model": ["14", 0], "image": ["8", 0]},
    }
    # SaveImage is repointed at the upscale pass; nothing else changes.
    assert prompt["9"]["inputs"]["images"] == ["15", 0]
    assert prompt["9"]["class_type"] == "SaveImage"
    assert prompt["8"] == source["8"]


def test_inject_factor_one_adds_nothing():
    source = injected_prompt()
    prompt = upscale.inject_upscale(source, factor=1, model_name=None)
    assert prompt == source
    assert "14" not in prompt and "15" not in prompt
    assert prompt["9"]["inputs"]["images"] == ["8", 0]
    assert prompt is not source


def test_inject_keeps_meta_stripping():
    raw_wf = load_workflow("txt2img-flux-schnell-gguf-q4.json")
    assert "_meta" in raw_wf
    prompt = upscale.inject_upscale(raw_wf, factor=2, model_name=MODEL)
    assert "_meta" not in prompt
    # factor 1 on a raw workflow returns the deep copy untouched.
    assert "_meta" in upscale.inject_upscale(raw_wf, factor=1, model_name=None)


def test_inject_does_not_mutate_input():
    source = injected_prompt()
    snapshot = copy.deepcopy(source)
    upscale.inject_upscale(source, factor=4, model_name=MODEL)
    assert source == snapshot, "inject_upscale must not mutate prompt_dict"


def test_double_injection_is_idempotent():
    once = upscale.inject_upscale(injected_prompt(), factor=4, model_name=MODEL)
    twice = upscale.inject_upscale(once, factor=4, model_name="other-4x.pth")

    assert "16" not in twice  # never grows a second upscale node
    assert twice["14"]["inputs"]["model_name"] == "other-4x.pth"
    assert twice["15"] == once["15"]  # image wiring preserved, no 15 -> 15 loop
    assert twice["15"]["inputs"]["image"] == ["8", 0]
    assert twice["9"]["inputs"]["images"] == ["15", 0]
    # Chains follow the single upscale node in both runs.
    assert twice["15"]["inputs"]["upscale_model"] == ["14", 0]


def test_inject_requires_model_name_for_upscaling():
    for bad in (None, "", "  "):
        with pytest.raises(ValueError, match="INVALID_UPSCALE_MODEL:"):
            upscale.inject_upscale(injected_prompt(), factor=2, model_name=bad)


def test_inject_rejects_bad_factor_before_touching_nodes():
    with pytest.raises(ValueError, match="INVALID_UPSCALE:"):
        upscale.inject_upscale(injected_prompt(), factor=3, model_name=MODEL)


@pytest.mark.parametrize(
    "broken",
    [
        {},  # empty dict
        {"4": {"class_type": "CLIPTextEncode", "inputs": {}}},  # no SaveImage
        {"9": {"class_type": "SaveImage", "inputs": {}}},  # no images input
        {"9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}}},  # dangling
        {"9": {"class_type": "SaveImage", "inputs": {"images": "8"}}},  # bad ref
        {"9": "SaveImage"},  # non-dict node
    ],
)
def test_inject_missing_nodes_raise_workflow_mismatch(broken):
    with pytest.raises(ValueError, match="WORKFLOW_NODE_MISMATCH:"):
        upscale.inject_upscale(broken, factor=2, model_name=MODEL)


def test_inject_rejects_foreign_node_15():
    source = injected_prompt()
    source["15"] = {"class_type": "KSampler", "inputs": {}}
    with pytest.raises(ValueError, match="WORKFLOW_NODE_MISMATCH:"):
        upscale.inject_upscale(source, factor=2, model_name=MODEL)


@pytest.mark.parametrize(
    "filename",
    ["txt2img-flux-schnell-gguf-q4.json", "txt2img-flux-schnell-fp8.json"],
)
def test_inject_real_workflows_cleanly(filename):
    raw_wf = load_workflow(filename)
    prompt = upscale.inject_upscale(raw_wf, factor=4, model_name=MODEL)

    assert prompt["14"]["class_type"] == "UpscaleModelLoader"
    assert prompt["15"]["class_type"] == "ImageUpscaleWithModel"
    assert prompt["9"]["inputs"]["images"] == ["15", 0]
    # Every [node, slot] edge in the injected graph resolves.
    node_ids = set(prompt)
    for node_id, node in prompt.items():
        for name, value in node["inputs"].items():
            if isinstance(value, list) and value and isinstance(value[0], str):
                assert value[0] in node_ids, "%s.%s -> %s dangling" % (
                    node_id, name, value[0]
                )
    # The un-upscaled VAEDecode still feeds the upscale node.
    assert prompt["15"]["inputs"]["image"] == ["8", 0]


def test_inject_coexists_with_lora_node_13():
    """LoRA (node 13) and upscale (14/15) chains coexist without id clashes."""
    wf = load_workflow("txt2img-flux-schnell-gguf-q4.json")
    params = presets.build_txt2img_params(
        "an orange scooter icon", seed=3, lora="style-lora.safetensors"
    )
    injected = presets.inject_params(wf, params)
    assert injected["13"]["class_type"] == "LoraLoaderModelOnly"
    prompt = upscale.inject_upscale(injected, factor=2, model_name=MODEL)
    assert prompt["13"]["class_type"] == "LoraLoaderModelOnly"
    assert prompt["13"]["inputs"]["model"] == ["1", 0]
    assert prompt["10"]["inputs"]["model"] == ["13", 0]
    assert prompt["14"]["class_type"] == "UpscaleModelLoader"
    assert prompt["9"]["inputs"]["images"] == ["15", 0]


def test_inject_real_workflow_model_name_flows_to_loader():
    prompt = upscale.inject_upscale(
        load_workflow("txt2img-flux-schnell-fp8.json"), factor=2,
        model_name="4x-UltraSharp.pth",
    )
    assert prompt["14"]["inputs"]["model_name"] == "4x-UltraSharp.pth"


# -- model resolution --------------------------------------------------------


def test_resolve_upscale_model_auto_picks_first():
    assert upscale.resolve_upscale_model(None, [MODEL, "other.pth"]) == MODEL
    assert upscale.resolve_upscale_model(None, ["", MODEL]) == MODEL


def test_resolve_upscale_model_explicit_wins():
    assert upscale.resolve_upscale_model("custom.pth", [MODEL]) == "custom.pth"
    # Existence is ComfyUI's job: an explicit name is passed through.
    assert upscale.resolve_upscale_model("missing.pth", []) == "missing.pth"


def test_resolve_upscale_model_none_when_nothing_available():
    assert upscale.resolve_upscale_model(None, []) is None
    assert upscale.resolve_upscale_model(None, None) is None


def test_resolve_upscale_model_accepts_loader_files_shape():
    """`ComfyClient.loader_files` returns `{input_name: [names]}`; flatten it."""
    loader_files = {"model_name": [MODEL, "other.pth"]}
    assert upscale.resolve_upscale_model(None, loader_files) == MODEL
    assert upscale.resolve_upscale_model(None, {"model_name": []}) is None
    assert upscale.resolve_upscale_model(None, {"model_name": [""]}) is None
    assert upscale.resolve_upscale_model("custom.pth", loader_files) == "custom.pth"


def test_resolve_upscale_model_accepts_single_name():
    assert upscale.resolve_upscale_model(None, MODEL) == MODEL
    assert upscale.resolve_upscale_model(None, "") is None


# -- package surface ---------------------------------------------------------


def test_package_exports_upscale_helpers():
    """The package re-exports the slice (same contract, same behaviour).

    `gen_backend.upscale` and the top-level `upscale` shim are two module
    objects (package-relative vs `sys.path` import), so the functions are
    compared by behaviour, not identity.
    """
    assert gen_backend.UPSCALE_FACTORS == (1, 2, 4) == upscale.UPSCALE_FACTORS
    assert gen_backend.UPSCALE_NODE_MAP == upscale.UPSCALE_NODE_MAP
    assert gen_backend.UPSCALE_NODE_MAP["upscale_node"] == "15"
    assert gen_backend.validate_upscale_factor(4) == 4
    assert gen_backend.validate_upscale_model(" RealESRGAN_x4.pth ") == MODEL
    assert gen_backend.resolve_upscale_model(None, [MODEL]) == MODEL
    prompt = gen_backend.inject_upscale(injected_prompt(), factor=2, model_name=MODEL)
    assert prompt["9"]["inputs"]["images"] == ["15", 0]
    for name in (
        "UPSCALE_FACTORS",
        "UPSCALE_NODE_MAP",
        "inject_upscale",
        "resolve_upscale_model",
        "validate_upscale_factor",
        "validate_upscale_model",
    ):
        assert name in gen_backend.__all__
