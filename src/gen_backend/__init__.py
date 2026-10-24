"""Local ComfyUI generation backend (contract ``C2-gen-backend-job`` v0.1.0).

Slice A: submit/poll/fetch/cancel core over ComfyUI REST (localhost:8188).
"""

import json as _json
import os as _os

from .client import ComfyClient
from .errors import (
    COMFY_UNREACHABLE,
    ERROR_CODES,
    JOB_FAILED,
    JOB_TIMEOUT,
    MODEL_NOT_FOUND,
    QUEUE_FULL,
    UNKNOWN_LOADER,
    UNKNOWN_WORKFLOW,
    ComfyUnreachableError,
    GenBackendError,
    JobFailedError,
    JobTimeoutError,
    ModelNotFoundError,
    QueueFullError,
    UnknownLoaderError,
    UnknownWorkflowError,
)
from .img2img import (
    DEFAULT_STRENGTH,
    IMG2IMG_NODE_MAP,
    build_img2img_params,
    inject_img2img,
    load_input_bytes,
)
from .presets import (
    DEFAULT_MODEL_ID,
    DEFAULT_SIZE,
    DEFAULT_STEPS,
    DEFAULT_WORKFLOW_ID,
    FIXED_GUIDANCE,
    MODEL_PRESETS,
    STYLE_PRESETS,
    WORKFLOW_FILES,
    build_txt2img_params,
    inject_params,
    list_models,
    list_styles,
)

_WORKFLOWS_DIR = _os.path.join(_os.path.dirname(__file__), "workflows")


def _load_workflow(workflow_id):
    """Load the API-format workflow JSON for *workflow_id* (no _meta strip here)."""
    try:
        filename = WORKFLOW_FILES[workflow_id]
    except KeyError:
        raise UnknownWorkflowError(
            "UNKNOWN_WORKFLOW: workflow_id=%r known=%s"
            % (workflow_id, sorted(WORKFLOW_FILES)),
            payload={"workflow_id": workflow_id, "known": sorted(WORKFLOW_FILES)},
        ) from None
    path = _os.path.join(_WORKFLOWS_DIR, filename)
    with open(path, encoding="utf-8") as fh:
        return _json.load(fh)


def submit_txt2img(client, prompt, workflow_id=DEFAULT_WORKFLOW_ID,
                   width=DEFAULT_SIZE, height=DEFAULT_SIZE,
                   steps=DEFAULT_STEPS, seed=None, model_id=None,
                   style=None, negative=None, guidance=FIXED_GUIDANCE,
                   client_id=None, lora=None, lora_strength=None):
    """C2 ``submit_txt2img`` -> build + inject -> ``ComfyClient.submit``.

    C2 op ``submit_txt2img({prompt, ...})`` maps to this helper, which calls
    ``presets.build_txt2img_params`` + ``presets.inject_params`` and then
    ``POST /prompt`` via ``client.submit``. Returns the C2 ``job_id``
    (ComfyUI ``prompt_id``). ``model_id`` omitted derives from ``workflow_id``.
    ``lora``/``lora_strength`` (optional, C2 v0.2) wire a LoraLoaderModelOnly
    node through the model chain; the file must exist in ``models/loras/``.
    """
    params = build_txt2img_params(
        prompt=prompt, negative=negative, workflow_id=workflow_id,
        width=width, height=height, steps=steps, seed=seed,
        model_id=model_id, style=style, guidance=guidance,
        lora=lora, lora_strength=lora_strength,
    )
    workflow = _load_workflow(params["workflow_id"])
    prompt_dict = inject_params(workflow, params)
    return client.submit(prompt_dict, client_id=client_id)


def submit_img2img(client, input_png_path, instruction,
                   strength=DEFAULT_STRENGTH, workflow_id=None,
                   width=DEFAULT_SIZE, height=DEFAULT_SIZE,
                   steps=DEFAULT_STEPS, seed=None, model_id=None,
                   style=None, negative=None, client_id=None):
    """C2 ``submit_img2img`` -> build + upload + inject + img2img-inject -> ``submit``.

    Maps to ``img2img.build_img2img_params`` + ``client.upload_image``
    (``POST /upload/image`` into a server-side ``asset-gen/`` input
    subfolder) + ``presets.inject_params`` + ``img2img.inject_img2img``
    and then ``POST /prompt`` via ``client.submit``. The source PNG is
    only read (never mutated, never left behind in the project); the
    uploaded ``subfolder/name`` returned by ComfyUI is wired into
    LoadImage node "11" — the unique server-side name can never collide
    with a stale input file. Returns the C2 ``job_id``.
    """
    params = build_img2img_params(
        input_png_path, instruction, strength=strength,
        workflow_id=workflow_id, width=width, height=height,
        steps=steps, seed=seed, model_id=model_id,
        style=style, negative=negative,
    )
    upload = client.upload_image(load_input_bytes(input_png_path))
    image_value = upload["name"]
    if upload.get("subfolder"):
        image_value = f"{upload['subfolder']}/{image_value}"
    workflow = _load_workflow(params["workflow_id"])
    injected = inject_params(workflow, params)
    prompt_dict = inject_img2img(injected, params, image_filename=image_value)
    return client.submit(prompt_dict, client_id=client_id)


__all__ = [
    "ComfyClient",
    "GenBackendError",
    "ComfyUnreachableError",
    "UnknownWorkflowError",
    "UnknownLoaderError",
    "ModelNotFoundError",
    "QueueFullError",
    "JobFailedError",
    "JobTimeoutError",
    "COMFY_UNREACHABLE",
    "UNKNOWN_WORKFLOW",
    "UNKNOWN_LOADER",
    "MODEL_NOT_FOUND",
    "QUEUE_FULL",
    "JOB_FAILED",
    "JOB_TIMEOUT",
    "ERROR_CODES",
    "MODEL_PRESETS",
    "STYLE_PRESETS",
    "build_txt2img_params",
    "inject_params",
    "list_models",
    "list_styles",
    "DEFAULT_MODEL_ID",
    "DEFAULT_WORKFLOW_ID",
    "DEFAULT_SIZE",
    "DEFAULT_STEPS",
    "FIXED_GUIDANCE",
    "WORKFLOW_FILES",
    "DEFAULT_STRENGTH",
    "IMG2IMG_NODE_MAP",
    "build_img2img_params",
    "inject_img2img",
    "load_input_bytes",
    "submit_txt2img",
    "submit_img2img",
]

__version__ = "0.6.0"
