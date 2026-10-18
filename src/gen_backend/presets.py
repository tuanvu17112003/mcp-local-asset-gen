"""Model/style presets + txt2img param building and workflow injection.

Contract: C2-gen-backend-job v0.1.0. Guidance is fixed at 0.0 for
FLUX-schnell; any non-zero guidance is rejected with a clear error.
LoRA wiring is a documented stub (empty list + hook); nothing is downloaded.
"""

import copy
import random

try:  # package import (tests/test_client_mocked style: sys.path src/)
    from gen_backend.errors import UnknownWorkflowError
except ImportError:  # pragma: no cover - direct-file layout (sys.path src/gen_backend)
    try:
        from .errors import UnknownWorkflowError
    except ImportError:
        from errors import UnknownWorkflowError

DEFAULT_WORKFLOW_ID = "txt2img-flux-schnell-gguf-q4"
# GGUF-Q4 is the default model: assignment gen-2 (10 GB profile, 2026-10-17)
# supersedes the contract C2 v0.1.0 text default "flux1-schnell-fp8" (a
# checkpoint file id). Keys below are MODEL_PRESETS ids, not file names.
DEFAULT_MODEL_ID = "flux-schnell-gguf-q4"
DEFAULT_STEPS = 4
DEFAULT_SIZE = 512
FIXED_GUIDANCE = 0.0

WORKFLOW_FILES = {
    "txt2img-flux-schnell-gguf-q4": "txt2img-flux-schnell-gguf-q4.json",
    "txt2img-flux-schnell-fp8": "txt2img-flux-schnell-fp8.json",
}

MODEL_PRESETS = {
    "flux-schnell-gguf-q4": {
        "name": "FLUX.1-schnell GGUF Q4_K_S (default, 10 GB target)",
        "workflow_id": "txt2img-flux-schnell-gguf-q4",
        "file": "flux1-schnell-Q4_K_S.gguf",
        "placement": "models/unet/",
        "default": True,
    },
    "flux-schnell-fp8": {
        "name": "FLUX.1-schnell FP8 (scale-up, >=12 GB VRAM)",
        "workflow_id": "txt2img-flux-schnell-fp8",
        "file": "flux1-schnell-fp8.safetensors",
        "placement": "models/checkpoints/",
        "default": False,
    },
    "sdxl-turbo": {
        "name": "SDXL-Turbo (non-default stub, not wired to a workflow yet)",
        "workflow_id": None,
        "file": None,
        "placement": "models/checkpoints/",
        "default": False,
        "stub": True,
    },
}

# Style presets are prompt-template modifiers applied to the raw prompt.
STYLE_PRESETS = {
    "flat": {
        "name": "Flat",
        "template": "{prompt}, flat vector icon style, solid colors, clean shapes, minimal detail",
    },
    "3d-clay": {
        "name": "3D Claymorphism",
        "template": "{prompt}, 3D claymorphism render, soft matte clay material, rounded shapes, studio lighting",
    },
    "minimal-line": {
        "name": "Minimalist Line",
        "template": "{prompt}, minimalist line art, thin black outlines, plain white background, simple",
    },
    "pixel-art": {
        "name": "Pixel Art",
        "template": "{prompt}, pixel art, 16-bit retro game sprite style, crisp square pixels",
    },
}

# LoRA wiring stub: no LoRAs bundled, nothing downloaded.
# Hook: when LoRAs are adopted, insert a LoraLoader node between the model
# loader (node 1) and ModelSamplingFlux (node 10), routing model+clip through
# it per entry in "loras" [{name, strength}]; keep this list empty until then.
LORA_HOOK = {
    "enabled": False,
    "loras": [],
    "node": "LoraLoader",
    "hook": "insert LoraLoader between node 1 (loader) and node 10 "
             "(ModelSamplingFlux); pass model+clip through each entry",
}

# Nodes inject_params() writes (see workflows/workflow_params.md).
PROMPT_NODE = "4"
NEGATIVE_NODE = "5"
LATENT_NODE = "6"
SAMPLER_NODE = "7"
GUIDANCE_NODE = "10"

# DualCLIPLoader node + pinned encoder defaults (gen-5, IC-3 live finding
# 2026-10-17: ComfyUI rejected `t5xxl_fp16.safetensors` with
# `value_not_in_list`; env carries the 10GB-profile fp8 encoder).
CLIP_LOADER_NODE = "2"
DEFAULT_CLIP_NAME1 = "t5xxl_fp8_e4m3fn.safetensors"
DEFAULT_CLIP_NAME2 = "clip_l.safetensors"


def list_models():
    """Return model preset ids (default first)."""
    return sorted(MODEL_PRESETS, key=lambda m: (not MODEL_PRESETS[m].get("default", False), m))


def list_styles():
    """Return style preset ids."""
    return list(STYLE_PRESETS)


def _apply_style(prompt, style):
    if style is None:
        return prompt
    try:
        preset = STYLE_PRESETS[style]
    except KeyError:
        raise ValueError(
            "UNKNOWN_STYLE: style=%r known=%s" % (style, sorted(STYLE_PRESETS))
        )
    return preset["template"].format(prompt=prompt)


def _default_model_for_workflow(workflow_id):
    """Return the MODEL_PRESETS id wired to *workflow_id* (default first match)."""
    for mid, preset in MODEL_PRESETS.items():
        if preset.get("workflow_id") == workflow_id:
            return mid
    return DEFAULT_MODEL_ID


def build_txt2img_params(prompt, negative=None, workflow_id=DEFAULT_WORKFLOW_ID,
                         width=DEFAULT_SIZE, height=DEFAULT_SIZE,
                         steps=DEFAULT_STEPS, seed=None,
                         model_id=None, style=None,
                         guidance=FIXED_GUIDANCE):
    """Build and validate txt2img params. Unknown workflow -> UNKNOWN_WORKFLOW.

    ``model_id`` defaults to the MODEL_PRESETS id wired to ``workflow_id``
    (GGUF-Q4 default per assignment gen-2); an explicit ``model_id`` still
    overrides the pairing.
    """
    if workflow_id not in WORKFLOW_FILES:
        raise UnknownWorkflowError(
            "UNKNOWN_WORKFLOW: workflow_id=%r known=%s"
            % (workflow_id, sorted(WORKFLOW_FILES)),
            payload={"workflow_id": workflow_id, "known": sorted(WORKFLOW_FILES)},
        )
    if not prompt or not str(prompt).strip():
        raise ValueError("EMPTY_PROMPT: prompt is required")
    if guidance != FIXED_GUIDANCE:
        raise ValueError(
            "GUIDANCE_NOT_SUPPORTED: FLUX-schnell requires guidance 0.0, got %r"
            % (guidance,)
        )
    if not isinstance(steps, int) or not 1 <= steps <= 4:
        raise ValueError("INVALID_STEPS: schnell steps must be int 1-4, got %r" % (steps,))
    for label, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or value <= 0:
            raise ValueError("INVALID_SIZE: %s must be a positive int, got %r"
                             % (label, value))
    if seed is None:
        seed = random.randint(0, 0xFFFFFFFF)
    elif not isinstance(seed, int) or seed < 0:
        raise ValueError("INVALID_SEED: seed must be a non-negative int, got %r" % (seed,))
    if model_id is None:
        model_id = _default_model_for_workflow(workflow_id)
    if model_id in MODEL_PRESETS and MODEL_PRESETS[model_id].get("stub"):
        raise ValueError(
            "MODEL_NOT_WIRED: model_id=%r is a non-default stub with no workflow yet"
            % (model_id,)
        )
    return {
        "prompt": _apply_style(str(prompt), style),
        "negative": "" if negative is None else str(negative),
        "workflow_id": workflow_id,
        "width": width,
        "height": height,
        "steps": steps,
        "seed": seed,
        "model_id": model_id,
        "style": style,
        "guidance": FIXED_GUIDANCE,
    }


def _validate_clip_name(value, label):
    """Validate an encoder filename override: non-empty basename, no traversal."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "INVALID_CLIP_NAME: %s must be a non-empty string, got %r"
            % (label, value)
        )
    cleaned = value.strip()
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError(
            "INVALID_CLIP_NAME: %s must be a basename without path traversal, got %r"
            % (label, value)
        )
    return cleaned


def inject_params(workflow_json, params, clip_name1=None, clip_name2=None):
    """Return a submittable prompt dict: copy workflow, strip _meta, set W/H/seed/etc.

    Does not mutate the input. Missing expected nodes -> WORKFLOW_NODE_MISMATCH.

    Encoder overrides: ``clip_name1``/``clip_name2`` (kwargs, or ``params``
    keys of the same name when the kwarg is None) select the DualCLIPLoader
    (node "2") filenames; each defaults to the pinned value
    (``DEFAULT_CLIP_NAME1``/``DEFAULT_CLIP_NAME2``). Overrides must be
    non-empty strings without path traversal, else INVALID_CLIP_NAME.
    Workflows without node "2" (e.g. the FP8 checkpoint workflow, whose
    CLIP comes from the checkpoint) are left untouched on encoders.
    """
    if clip_name1 is None and isinstance(params, dict):
        clip_name1 = params.get("clip_name1")
    if clip_name2 is None and isinstance(params, dict):
        clip_name2 = params.get("clip_name2")
    if clip_name1 is None:
        clip_name1 = DEFAULT_CLIP_NAME1
    if clip_name2 is None:
        clip_name2 = DEFAULT_CLIP_NAME2
    clip_name1 = _validate_clip_name(clip_name1, "clip_name1")
    clip_name2 = _validate_clip_name(clip_name2, "clip_name2")
    prompt = copy.deepcopy(workflow_json)
    for key in [k for k in prompt if k.startswith("_")]:
        del prompt[key]
    try:
        prompt[PROMPT_NODE]["inputs"]["text"] = params["prompt"]
        prompt[NEGATIVE_NODE]["inputs"]["text"] = params.get("negative", "")
        prompt[LATENT_NODE]["inputs"]["width"] = params["width"]
        prompt[LATENT_NODE]["inputs"]["height"] = params["height"]
        prompt[SAMPLER_NODE]["inputs"]["seed"] = params["seed"]
        prompt[SAMPLER_NODE]["inputs"]["steps"] = params["steps"]
        if GUIDANCE_NODE in prompt:
            prompt[GUIDANCE_NODE]["inputs"]["guidance"] = FIXED_GUIDANCE
            prompt[GUIDANCE_NODE]["inputs"]["width"] = params["width"]
            prompt[GUIDANCE_NODE]["inputs"]["height"] = params["height"]
        clip_node = prompt.get(CLIP_LOADER_NODE)
        if isinstance(clip_node, dict) and isinstance(clip_node.get("inputs"), dict):
            clip_inputs = clip_node["inputs"]
            if "clip_name1" in clip_inputs:
                clip_inputs["clip_name1"] = clip_name1
            if "clip_name2" in clip_inputs:
                clip_inputs["clip_name2"] = clip_name2
    except KeyError as exc:
        raise ValueError("WORKFLOW_NODE_MISMATCH: expected node/input missing: %s" % (exc,))
    return prompt
