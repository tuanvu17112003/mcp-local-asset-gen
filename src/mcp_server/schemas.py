"""JSON-schema dicts for the four C1 tools (contract v0.1.6, Operations).

Plain dicts only — no third-party schema library. Mirrors contract
section "Operations / inputs / outputs" exactly:

* ``generate_app_asset({prompt*, category*, save_path*, width?, height?,
  format?, remove_bg?, style_preset?, seed?, overwrite?, job_id?,
  icon_sizes?, ico?, workspace?})``
  returns ``{asset_path, asset_path_absolute, asset_root, width, height,
  format, seed, style_preset, job_id}``
* ``refine_asset({asset_id|asset_path, instruction*, save_path?, strength?, job_id?,
  workspace?})``
  returns ``{asset_path, asset_path_absolute, asset_root, job_id, parent_job_id}``
* ``server_info({})`` returns
  ``{backend, comfyui_url, models, version, project_root, workspaces,
  allow_any_path, reachable, queue_depth}``
* ``check_model({name*, kind?})`` returns ``{available, loader, checked_at}``

C1 v0.1.6 (user request, 2026-10-22): ``save_path`` may be ABSOLUTE —
the agent chooses the output location — as long as it lands inside an
approved root (the project root or a named workspace). Relative paths keep
resolving under the selected workspace root. The leaf must be
``<stem>.png`` so the requested path is the written path.

The contract's golden call is kept as :data:`BEAR_AVATAR_EXAMPLE`, a
documented valid ``generate_app_asset`` input.
"""

from __future__ import annotations

from typing import Any, Dict

GENERATE_APP_ASSET_SCHEMA: Dict[str, Any] = {
    "name": "generate_app_asset",
    "description": (
        "Generate an app asset (icon, illustration, avatar, splash) with local "
        "ComfyUI diffusion plus local postprocessing. Writes exactly one asset "
        "tree under the project root (plus @2x/@3x siblings)."
    ),
    "input_schema": {
        "type": "object",
        "required": ["prompt", "category", "save_path"],
        "additionalProperties": False,
        "properties": {
            "prompt": {
                "type": "string",
                "minLength": 1,
                "description": "Text prompt describing the desired asset.",
            },
            "category": {
                "type": "string",
                "enum": ["icon", "illustration", "avatar", "splash"],
                "description": "Asset category (required).",
            },
            "save_path": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Output path (required). May be ABSOLUTE "
                    "(e.g. \"C:/proj/src/assets/icon.png\" — used exactly as "
                    "given, must land inside an approved root) or relative "
                    "(resolved under the selected workspace root). Must name "
                    "a .png file (the server writes PNG assets); no '..' "
                    "traversal; Windows backslashes are accepted."
                ),
            },
            "width": {
                "type": "integer",
                "minimum": 1,
                "default": 512,
                "description": "Width in px (default 512).",
            },
            "height": {
                "type": "integer",
                "minimum": 1,
                "default": 512,
                "description": "Height in px (default 512).",
            },
            "format": {
                "type": "string",
                "enum": ["png", "svg"],
                "default": "png",
                "description": "Output format (default png).",
            },
            "remove_bg": {
                "type": "boolean",
                "description": "Remove background (default true for icon/avatar).",
            },
            "style_preset": {
                "type": "string",
                "enum": ["flat", "clay", "line", "pixel"],
                "default": "flat",
                "description": "Style preset (default flat).",
            },
            "seed": {
                "type": "integer",
                "minimum": 0,
                "description": "Optional non-negative generation seed.",
            },
            "overwrite": {
                "type": "boolean",
                "default": False,
                "description": "Must be true to overwrite an existing file.",
            },
            "job_id": {
                "type": "string",
                "minLength": 1,
                "description": "Optional idempotency key; re-generate with the same job_id retries idempotently.",
            },
            "icon_sizes": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1, "maximum": 512},
                "description": (
                    "Optional extra square icon sizes in px (each 1..512 and "
                    "<= max(width,height)); emits <stem>-<N>px.png siblings."
                ),
            },
            "ico": {
                "type": "boolean",
                "default": False,
                "description": "Also emit a <stem>.ico file (default false).",
            },
            "workspace": {
                "type": "string",
                "minLength": 1,
                "default": "default",
                "description": (
                    "Named server-side root for this call (default "
                    "\"default\"); unknown names fail with INVALID_WORKSPACE."
                ),
            },
        },
    },
    "output_schema": {
        "type": "object",
        "required": [
            "asset_path",
            "asset_path_absolute",
            "asset_root",
            "width",
            "height",
            "format",
            "seed",
            "style_preset",
            "job_id",
        ],
        "properties": {
            "asset_path": {"type": "string"},
            "asset_path_absolute": {"type": "string"},
            "asset_root": {"type": ["string", "null"]},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "format": {"type": "string"},
            "seed": {"type": "integer"},
            "style_preset": {"type": "string"},
            "job_id": {"type": "string"},
        },
    },
}

REFINE_ASSET_SCHEMA: Dict[str, Any] = {
    "name": "refine_asset",
    "description": (
        "Refine an existing asset with an instruction. Creates a new file, "
        "never mutates the parent."
    ),
    "input_schema": {
        "type": "object",
        "required": ["instruction"],
        "anyOf": [{"required": ["asset_id"]}, {"required": ["asset_path"]}],
        "additionalProperties": False,
        "properties": {
            "asset_id": {
                "type": "string",
                "minLength": 1,
                "description": "Job/asset id of the parent (alternative to asset_path).",
            },
            "asset_path": {
                "type": "string",
                "minLength": 1,
                "description": "Path of the parent asset (alternative to asset_id).",
            },
            "instruction": {
                "type": "string",
                "minLength": 1,
                "description": "Refinement instruction (required).",
            },
            "save_path": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Output path for the refined asset (may be absolute "
                    "inside an approved root; relative resolves under the "
                    "selected workspace root)."
                ),
            },
            "strength": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Optional img2img strength hint (0..1).",
            },
            "job_id": {
                "type": "string",
                "minLength": 1,
                "description": "Optional idempotency key; re-refine with the same job_id retries idempotently.",
            },
            "workspace": {
                "type": "string",
                "minLength": 1,
                "default": "default",
                "description": (
                    "Named server-side root for this call (default "
                    "\"default\"); unknown names fail with INVALID_WORKSPACE."
                ),
            },
        },
    },
    "output_schema": {
        "type": "object",
        "required": ["asset_path", "asset_path_absolute", "asset_root", "job_id", "parent_job_id"],
        "properties": {
            "asset_path": {"type": "string"},
            "asset_path_absolute": {"type": "string"},
            "asset_root": {"type": ["string", "null"]},
            "job_id": {"type": "string"},
            "parent_job_id": {"type": "string"},
        },
    },
}

SERVER_INFO_SCHEMA: Dict[str, Any] = {
    "name": "server_info",
    "description": "Report backend reachability, ComfyUI URL, models and version.",
    "input_schema": {
        "type": "object",
        "required": [],
        "additionalProperties": False,
        "properties": {},
    },
    "output_schema": {
        "type": "object",
        "required": ["backend", "comfyui_url", "models", "version", "project_root", "workspaces", "allow_any_path", "reachable", "queue_depth"],
        "properties": {
            "backend": {"type": "string"},
            "comfyui_url": {"type": "string"},
            "models": {"type": "array", "items": {"type": "string"}},
            "version": {"type": "string"},
            "project_root": {"type": "string"},
            "workspaces": {"type": "object", "additionalProperties": {"type": "string"}},
            "allow_any_path": {"type": "boolean"},
            "reachable": {"type": "boolean"},
            "queue_depth": {"type": ["integer", "null"]},
        },
    },
}

CHECK_MODEL_SCHEMA: Dict[str, Any] = {
    "name": "check_model",
    "description": (
        "Check whether a model file is available in a ComfyUI loader folder."
    ),
    "input_schema": {
        "type": "object",
        "required": ["name"],
        "additionalProperties": False,
        "properties": {
            "name": {
                "type": "string",
                "minLength": 1,
                "description": "Model filename to look up (exact or basename match).",
            },
            "kind": {
                "type": "string",
                "enum": [
                    "checkpoint",
                    "clip",
                    "unet",
                    "vae",
                ],
                "description": "Optional model kind to narrow the search (maps to ComfyUI loader nodes; default: all).",
            },
        },
    },
    "output_schema": {
        "type": "object",
        "required": ["available", "loader", "checked_at"],
        "properties": {
            "available": {"type": "boolean"},
            "loader": {"type": ["string", "null"]},
            "checked_at": {"type": "string"},
        },
    },
}

#: Golden valid ``generate_app_asset`` call from C1 contract section
#: "Valid and invalid examples". Must pass :func:`validate_tool_args`.
BEAR_AVATAR_EXAMPLE: Dict[str, Any] = {
    "prompt": "cute bear avatar, 3D claymorphism, soft lighting",
    "category": "avatar",
    "save_path": "assets/images/bear_avatar.png",
    "remove_bg": True,
}

#: Invalid golden call: must be rejected with POLICY_DENIED.
PATH_ESCAPE_EXAMPLE: Dict[str, Any] = {
    "prompt": "cute bear avatar, 3D claymorphism, soft lighting",
    "category": "avatar",
    "save_path": "../../etc/pass.png",
}

TOOL_SCHEMAS = (
    GENERATE_APP_ASSET_SCHEMA,
    REFINE_ASSET_SCHEMA,
    SERVER_INFO_SCHEMA,
    CHECK_MODEL_SCHEMA,
)

__all__ = [
    "GENERATE_APP_ASSET_SCHEMA",
    "REFINE_ASSET_SCHEMA",
    "SERVER_INFO_SCHEMA",
    "CHECK_MODEL_SCHEMA",
    "BEAR_AVATAR_EXAMPLE",
    "PATH_ESCAPE_EXAMPLE",
    "TOOL_SCHEMAS",
]
