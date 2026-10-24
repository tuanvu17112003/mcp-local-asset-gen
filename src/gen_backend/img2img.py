"""img2img params + wiring notes. Never mutates the source image (read-only load).

Wiring (see workflows/workflow_params.md): reuse a txt2img graph, add node
"11" LoadImage (image = basename of the input PNG, which must pre-exist in
the ComfyUI input dir under that basename; live `/upload/image` wiring is an
IC-2 item, unconfirmed without a live ComfyUI) -> node "12" VAEEncode
(vae = same VAE source as node 8) -> node "7" KSampler takes
latent_image=["12", 0] with denoise=<strength>.

History/fetch shape is the same as txt2img (contract C2-gen-backend-job
v0.1.0: {prompt_id: {outputs: {node_id: {images: [...]}}}}); parsing lives in
the sibling slice client.py (not edited here).
"""

import copy
import os

try:  # package-relative first (production layout: src.gen_backend)
    from .presets import DEFAULT_SIZE, DEFAULT_STEPS, build_txt2img_params
except ImportError:  # installed/top-level layout (sys.path -> src/)
    try:
        from gen_backend.presets import DEFAULT_SIZE, DEFAULT_STEPS, build_txt2img_params
    except ImportError:  # direct-file / test-harness layout (sys.path -> src/gen_backend)
        from presets import DEFAULT_SIZE, DEFAULT_STEPS, build_txt2img_params

DEFAULT_STRENGTH = 0.6

# Which node takes the input image + strength/denoise (documented hook for client.py).
IMG2IMG_NODE_MAP = {
    "load_image_node": "11",
    "load_image_class": "LoadImage",
    "vae_encode_node": "12",
    "vae_encode_class": "VAEEncode",
    "sampler_node": "7",
    "strength_field": "denoise",
}


def load_input_bytes(input_png_path):
    """Read the source PNG read-only. Never writes to the source file."""
    with open(input_png_path, "rb") as fh:
        return fh.read()


def build_img2img_params(input_png_path, instruction, strength=DEFAULT_STRENGTH,
                         workflow_id=None, width=DEFAULT_SIZE, height=DEFAULT_SIZE,
                         steps=DEFAULT_STEPS, seed=None, model_id=None,
                         style=None, negative=None):
    """Build and validate img2img params on top of the txt2img fields."""
    if not input_png_path or not isinstance(input_png_path, str):
        raise ValueError("INVALID_INPUT: input_png_path must be a non-empty path string")
    if not os.path.isfile(input_png_path):
        raise ValueError("INPUT_NOT_FOUND: no file at %r" % (input_png_path,))
    if not isinstance(strength, (int, float)) or not 0 < strength <= 1:
        raise ValueError("INVALID_STRENGTH: strength must be in (0, 1], got %r" % (strength,))
    if not instruction or not str(instruction).strip():
        raise ValueError("EMPTY_PROMPT: instruction is required")
    kwargs = {"prompt": str(instruction)}
    if workflow_id is not None:
        kwargs["workflow_id"] = workflow_id
    if model_id is not None:
        kwargs["model_id"] = model_id
    base = build_txt2img_params(
        width=width, height=height, steps=steps, seed=seed,
        style=style, negative=negative, **kwargs
    )
    base["input_png_path"] = input_png_path
    base["input_png_name"] = os.path.basename(input_png_path)
    base["instruction"] = str(instruction)
    base["strength"] = float(strength)
    return base


def inject_img2img(prompt_dict, params, image_filename=None):
    """Add img2img nodes to an injected txt2img prompt dict; return a new dict.

    Inputs: ``prompt_dict`` is the output of ``presets.inject_params`` (a raw
    workflow also works — ``_meta`` is stripped if present); ``params`` is the
    output of :func:`build_img2img_params`; ``image_filename`` overrides
    ``params["input_png_name"]`` when given (the caller
    :func:`gen_backend.submit_img2img` uploads the source via
    ``POST /upload/image`` and passes the returned ``subfolder/name`` here).
    Never mutates inputs or the source image file (the file is only read to
    validate it exists; no upload is performed by this function itself).

    Wiring (see workflows/workflow_params.md + IMG2IMG_NODE_MAP): add node
    "11" LoadImage (image = basename) -> node "12" VAEEncode (vae = same
    source as node "8" VAEDecode) -> node "7" KSampler takes
    latent_image=["12", 0] with denoise=<strength> (default 0.6).
    Missing node "7"/"8" -> WORKFLOW_NODE_MISMATCH.
    """
    if not isinstance(prompt_dict, dict) or not prompt_dict:
        raise ValueError("WORKFLOW_NODE_MISMATCH: prompt_dict must be a non-empty dict")
    prompt = copy.deepcopy(prompt_dict)
    for key in [k for k in prompt if k.startswith("_")]:
        del prompt[key]
    filename = image_filename or (params or {}).get("input_png_name")
    if not filename and isinstance(params, dict) and params.get("input_png_path"):
        filename = os.path.basename(params["input_png_path"])
    if not filename or not isinstance(filename, str):
        raise ValueError("INVALID_INPUT: image filename is required (params['input_png_name'])")
    strength = (params or {}).get("strength", DEFAULT_STRENGTH)
    if not isinstance(strength, (int, float)) or not 0 < strength <= 1:
        raise ValueError("INVALID_STRENGTH: strength must be in (0, 1], got %r" % (strength,))
    try:
        sampler = prompt[IMG2IMG_NODE_MAP["sampler_node"]]
        vae_ref = prompt["8"]["inputs"]["vae"]
    except KeyError as exc:
        raise ValueError("WORKFLOW_NODE_MISMATCH: expected node/input missing: %s" % (exc,))
    load_node = IMG2IMG_NODE_MAP["load_image_node"]
    encode_node = IMG2IMG_NODE_MAP["vae_encode_node"]
    prompt[load_node] = {
        "class_type": IMG2IMG_NODE_MAP["load_image_class"],
        "inputs": {"image": filename},
    }
    prompt[encode_node] = {
        "class_type": IMG2IMG_NODE_MAP["vae_encode_class"],
        "inputs": {"pixels": [load_node, 0], "vae": copy.deepcopy(vae_ref)},
    }
    try:
        sampler_inputs = sampler["inputs"]
        sampler_inputs["latent_image"] = [encode_node, 0]
        sampler_inputs[IMG2IMG_NODE_MAP["strength_field"]] = float(strength)
    except (KeyError, TypeError) as exc:
        raise ValueError("WORKFLOW_NODE_MISMATCH: expected node/input missing: %s" % (exc,))
    return prompt
