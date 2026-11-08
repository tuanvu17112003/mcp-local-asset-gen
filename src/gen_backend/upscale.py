"""Real model upscale: node-chain injection (contract `C2-gen-backend-job` v0.2).

`txt2img` ends `VAEDecode "8" -> SaveImage "9"`; P1 (v0.8.0) splices an
`ImageUpscaleWithModel` pass between them so ComfyUI itself returns an
upscaled PNG instead of the postprocessor enlarging a 512 px image:

    node "14" UpscaleModelLoader      inputs{model_name}
    node "15" ImageUpscaleWithModel   inputs{upscale_model: ["14", 0],
                                              image: <SaveImage images ref>}
    node "9"  SaveImage               inputs{images: ["15", 0]}

The factor contract is `UPSCALE_FACTORS = (1, 2, 4)`: `1` means off (the
graph comes back unchanged) while `2`/`4` select the wires above.
`ImageUpscaleWithModel` applies the model's own nominal factor, so the
effective pixel size is `width * model_scale` (2x/4x for the usual
RealESRGAN x2/x4 weights); `RealESRGAN_x4.pth` in ComfyUI
`models/upscale_models/` is the 4x reference used by the live checks.

Reserved node ids: `11`/`12` belong to img2img
(`img2img.IMG2IMG_NODE_MAP`), `13` to the LoRA loader
(`presets.LORA_NODE`); `14`/`15` belong to this module and must not be
reused elsewhere. Nothing here touches the filesystem: whether the model
file exists is ComfyUI's call (`/object_info`), and
:func:`resolve_upscale_model` only picks a name from a caller-supplied
list (pure, no I/O).
"""

from __future__ import annotations

import copy

#: Allowed `upscale` factors: 1 = off, 2/4 = model upscale pass.
UPSCALE_FACTORS = (1, 2, 4)

#: Nodes :func:`inject_upscale` writes. `save_node` is the txt2img
#: SaveImage node; the chain flows model loader ("14") -> upscale node
#: ("15") -> SaveImage ("9").
UPSCALE_NODE_MAP = {
    "loader_node": "14",
    "loader_class": "UpscaleModelLoader",
    "upscale_node": "15",
    "upscale_class": "ImageUpscaleWithModel",
    "save_node": "9",
}

_INVALID_FACTOR = "INVALID_UPSCALE: upscale must be one of (1, 2, 4), got %r"
_INVALID_MODEL = (
    "INVALID_UPSCALE_MODEL: upscale_model must be a basename without path "
    "traversal, got %r"
)


def validate_upscale_factor(value):
    """Validate the `upscale` factor; return `1`/`2`/`4`.

    `None` normalizes to `1` (off). `bool` is rejected even though it
    subclasses `int` (`True` is not an upscale factor); floats, strings
    and any other int outside :data:`UPSCALE_FACTORS` raise `ValueError`
    `INVALID_UPSCALE`.
    """
    if value is None:
        return 1
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in UPSCALE_FACTORS
    ):
        raise ValueError(_INVALID_FACTOR % (value,))
    return value


def validate_upscale_model(value):
    """Validate an `upscale_model` override; return the cleaned basename or `None`.

    `None` passes through (auto-pick is the orchestrator's job via
    :func:`resolve_upscale_model`). Any other value must be a non-empty
    string naming a plain basename: a `/` or backslash separator or a
    `..` segment is refused with `ValueError` `INVALID_UPSCALE_MODEL`
    (the value is later handed to ComfyUI's `UpscaleModelLoader`, which
    resolves it inside `models/upscale_models/`). Surrounding whitespace
    is stripped; existence is ComfyUI's job, not ours.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(_INVALID_MODEL % (value,))
    cleaned = value.strip()
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError(_INVALID_MODEL % (value,))
    return cleaned


def _require_node_ref(prompt, ref, label):
    """Return a normalized `[node_id, output_index]` ref found in `prompt`.

    `WORKFLOW_NODE_MISMATCH` when `ref` is not a `[node_id, output_index]`
    pair or points at a node the prompt does not contain (a dangling wire
    would make ComfyUI reject the whole graph).
    """
    if (
        not isinstance(ref, (list, tuple))
        or len(ref) != 2
        or not isinstance(ref[0], str)
        or isinstance(ref[1], bool)
        or not isinstance(ref[1], int)
    ):
        raise ValueError(
            "WORKFLOW_NODE_MISMATCH: %s must be a [node_id, output_index] ref, "
            "got %r" % (label, (ref,))
        )
    if ref[0] not in prompt:
        raise ValueError(
            "WORKFLOW_NODE_MISMATCH: %s references missing node %r"
            % (label, (ref[0],))
        )
    return [ref[0], ref[1]]


def inject_upscale(prompt_dict, *, factor, model_name):
    """Splice the upscale chain into an injected txt2img prompt; return a new dict.

    `prompt_dict` is the output of :func:`inject_params` (a raw workflow
    also works - `_`-prefixed keys are stripped before the wires are
    added). The input is never mutated: everything works on a deep copy.

    `factor == 1` returns the deep copy unchanged - no nodes are added and
    no `_` keys are stripped - so callers can run the injection
    unconditionally.

    `factor in (2, 4)` strips `_` keys and writes
    :data:`UPSCALE_NODE_MAP`: `14` UpscaleModelLoader(`model_name`) ->
    `15` ImageUpscaleWithModel(`upscale_model=["14", 0]`,
    `image=<SaveImage's current images ref>`) -> SaveImage `9` repointed
    to `["15", 0]`. `model_name` must then be a non-empty basename
    (`INVALID_UPSCALE_MODEL`); a missing SaveImage node, a missing
    `images` input or a dangling referenced node raise
    `WORKFLOW_NODE_MISMATCH` (same style as `img2img.inject_img2img`).

    Idempotent-ish: re-injecting into an already-upscaled prompt reuses the
    existing node `15` (its `image` wiring is kept) instead of adding a
    second upscale node, so the SaveImage repoint can never form a cycle
    (`15 -> 15`). The loader node `14` is rewritten with the current
    `model_name` so a later call may switch upscale models.
    """
    if not isinstance(prompt_dict, dict) or not prompt_dict:
        raise ValueError(
            "WORKFLOW_NODE_MISMATCH: prompt_dict must be a non-empty dict"
        )
    factor = validate_upscale_factor(factor)
    if factor == 1:
        return copy.deepcopy(prompt_dict)

    model = validate_upscale_model(model_name)
    if model is None:
        raise ValueError(_INVALID_MODEL % (model_name,))

    prompt = copy.deepcopy(prompt_dict)
    for key in [k for k in prompt if k.startswith("_")]:
        del prompt[key]

    save_node = UPSCALE_NODE_MAP["save_node"]
    try:
        save_inputs = prompt[save_node]["inputs"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "WORKFLOW_NODE_MISMATCH: expected SaveImage node %s with an inputs "
            "mapping: %s" % (save_node, (exc,))
        )
    if not isinstance(save_inputs, dict) or "images" not in save_inputs:
        raise ValueError(
            "WORKFLOW_NODE_MISMATCH: SaveImage node %s has no images input"
            % (save_node,)
        )
    images_ref = save_inputs["images"]
    image_source = _require_node_ref(
        prompt, images_ref, "SaveImage node %s images" % (save_node,)
    )

    upscale_node = UPSCALE_NODE_MAP["upscale_node"]
    existing = prompt.get(upscale_node)
    if existing is None:
        prompt[upscale_node] = {
            "class_type": UPSCALE_NODE_MAP["upscale_class"],
            "inputs": {
                "upscale_model": [UPSCALE_NODE_MAP["loader_node"], 0],
                "image": image_source,
            },
        }
    else:
        if not isinstance(existing, dict) or not isinstance(
            existing.get("inputs"), dict
        ):
            raise ValueError(
                "WORKFLOW_NODE_MISMATCH: node %s exists but is not an upscale "
                "node with inputs" % (upscale_node,)
            )
        if existing.get("class_type") not in (
            None,
            UPSCALE_NODE_MAP["upscale_class"],
        ):
            raise ValueError(
                "WORKFLOW_NODE_MISMATCH: node %s already exists as %r, expected %r"
                % (
                    upscale_node,
                    existing.get("class_type"),
                    UPSCALE_NODE_MAP["upscale_class"],
                )
            )
        # Reuse: keep the existing image source (never re-point a node at
        # itself, which the SaveImage repoint below would otherwise create).
        existing_inputs = existing["inputs"]
        if existing_inputs.get("image") is None:
            if image_source[0] == upscale_node:
                raise ValueError(
                    "WORKFLOW_NODE_MISMATCH: node %s exists without an image "
                    "source and SaveImage already points at it"
                    % (upscale_node,)
                )
            existing_inputs["image"] = image_source
        else:
            _require_node_ref(
                prompt,
                existing_inputs["image"],
                "node %s image" % (upscale_node,),
            )

    prompt[UPSCALE_NODE_MAP["loader_node"]] = {
        "class_type": UPSCALE_NODE_MAP["loader_class"],
        "inputs": {"model_name": model},
    }
    save_inputs["images"] = [upscale_node, 0]
    return prompt


def resolve_upscale_model(requested, available):
    """Pick the upscale model name to send to ComfyUI; pure, no I/O.

    `requested` is a value already validated by
    :func:`validate_upscale_model`; when it is given it wins as-is
    (existence is ComfyUI's job). Otherwise the first non-empty name in
    `available` is used, so `None` means "no model installed" and the
    caller falls back to `upscale=1`.

    `available` accepts the shapes a caller realistically has: a plain
    list/tuple of names (first non-empty wins), the `{input_name: [names]}`
    mapping returned by `ComfyClient.loader_files("UpscaleModelLoader")`
    (names flattened in input order), or a single name string.
    """
    if requested is not None:
        return requested
    if not available:
        return None
    if isinstance(available, str):
        return available or None
    if isinstance(available, dict):
        flattened = []
        for value in available.values():
            if isinstance(value, str):
                flattened.append(value)
            elif isinstance(value, (list, tuple)):
                flattened.extend(value)
        return next(
            (name for name in flattened if isinstance(name, str) and name),
            None,
        )
    try:
        names = [name for name in available if isinstance(name, str) and name]
    except TypeError:
        return None
    return names[0] if names else None


__all__ = [
    "UPSCALE_FACTORS",
    "UPSCALE_NODE_MAP",
    "inject_upscale",
    "resolve_upscale_model",
    "validate_upscale_factor",
    "validate_upscale_model",
]
