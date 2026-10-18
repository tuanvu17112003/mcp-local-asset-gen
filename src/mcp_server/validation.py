"""Argument validation and project-root jail (C1 v0.1.0).

Two layers:

* :func:`validate_tool_args` — pure string/shape validation for
  ``generate_app_asset`` params. Path *shape* problems (absolute, ``..``,
  backslash) raise :class:`PolicyDeniedError`; param problems raise
  ``ValueError`` with an ``INVALID_*`` message. Filesystem containment and
  the overwrite check need ``project_root`` and live in ...
* :func:`resolve_save_path` — ... which joins the path under
  ``project_root``, verifies containment via absolute-path comparison, and
  refuses existing files unless ``overwrite=True``.

``validate_tool_args`` intentionally does not touch the filesystem, so the
golden-shape check stays hermetic; ``resolve_save_path`` is the enforcing
gate the slice-2 orchestrator must call before any write.
"""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from typing import Any, Dict

from .errors import PolicyDeniedError

CATEGORIES = frozenset({"icon", "illustration", "avatar", "splash"})
FORMATS = frozenset({"png", "svg"})
STYLE_PRESETS = frozenset({"flat", "clay", "line", "pixel"})

#: User-facing ``check_model`` kinds mapped to ComfyUI loader node class
#: names the backend ``loader_files`` takes. Explicit ``kind`` maps
#: through this table; the default (no kind) searches all four nodes.
#: Default-all search skips per-loader UNKNOWN_LOADER so the set is safe.
KIND_TO_LOADERS = {
    "unet": ["UnetLoaderGGUF"],
    "clip": ["DualCLIPLoader"],
    "vae": ["VAELoader"],
    "checkpoint": ["CheckpointLoaderSimple"],
}

#: Allowlist of user-facing ``check_model`` kinds (keys of KIND_TO_LOADERS).
CHECK_MODEL_LOADERS = frozenset(KIND_TO_LOADERS)

DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 512
DEFAULT_FORMAT = "png"
DEFAULT_STYLE_PRESET = "flat"

#: Default img2img strength for ``refine_asset`` (mirrors C2 ``DEFAULT_STRENGTH``).
DEFAULT_REFINE_STRENGTH = 0.6

#: Categories whose default is background removal on (per C1 contract).
REMOVE_BG_DEFAULT_TRUE = frozenset({"icon", "avatar"})

_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:")


def _check_path_shape(save_path: Any) -> str:
    """String-level jail pre-check; returns the path or raises PolicyDeniedError."""
    if not isinstance(save_path, str) or not save_path:
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must be a non-empty "
            "relative POSIX path, got %r" % (save_path,)
        )
    if "\\" in save_path:
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: backslashes are not POSIX "
            "separators (possible '..\\' escape), got %r" % (save_path,)
        )
    if (
        save_path.startswith("/")
        or _DRIVE_LETTER_RE.match(save_path)
        or save_path.startswith("\\\\")
        or os.path.isabs(save_path)
    ):
        raise PolicyDeniedError(
            "POLICY_DENIED: absolute save_path escapes project root, got %r"
            % (save_path,)
        )
    parts = save_path.split("/")
    if ".." in parts:
        raise PolicyDeniedError(
            "POLICY_DENIED: '..' traversal escapes project root, got %r" % (save_path,)
        )
    normed = posixpath.normpath(save_path)
    if normed == ".." or normed.startswith("../"):
        raise PolicyDeniedError(
            "POLICY_DENIED: normalized save_path escapes project root, got %r"
            % (save_path,)
        )
    if normed in (".", "") or save_path.endswith("/"):
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must name a file, got %r"
            % (save_path,)
        )
    return save_path


def resolve_save_path(save_path: str, project_root: Any, overwrite: bool = False) -> Path:
    """Jail ``save_path`` under ``project_root`` and return the absolute Path.

    Rejects absolute paths, ``..`` traversal (including ``a/../../b.png``),
    and non-file targets with :class:`PolicyDeniedError` (``POLICY_DENIED``).
    Refuses to clobber an existing file unless ``overwrite`` is ``True``
    (also ``POLICY_DENIED`` — the contract invariant "never overwrite
    without explicit ``overwrite:true``").
    """
    _check_path_shape(save_path)
    if not isinstance(overwrite, bool):
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_OVERWRITE: overwrite must be a bool, got %r"
            % (overwrite,)
        )
    normed = posixpath.normpath(save_path)
    root_abs = os.path.abspath(os.fspath(project_root))
    candidate_abs = os.path.abspath(os.path.join(root_abs, *normed.split("/")))
    if candidate_abs == root_abs or os.path.commonpath([root_abs, candidate_abs]) != root_abs:
        raise PolicyDeniedError(
            "POLICY_DENIED: save_path escapes project root, got %r" % (save_path,)
        )
    if os.path.exists(candidate_abs) and not overwrite:
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_OVERWRITE: file exists and overwrite is not "
            "set, got %r" % (save_path,)
        )
    return Path(candidate_abs)


def _require_int(name: str, value: Any, *, minimum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s: %s must be an int, got %r" % (code, name, value))
    if value < minimum:
        raise ValueError("%s: %s must be >= %d, got %r" % (code, name, minimum, value))
    return value


def validate_tool_args(
    prompt: Any,
    category: Any,
    save_path: Any,
    width: Any = DEFAULT_WIDTH,
    height: Any = DEFAULT_HEIGHT,
    format: Any = DEFAULT_FORMAT,  # noqa: A002 - contract field name
    remove_bg: Any = None,
    style_preset: Any = DEFAULT_STYLE_PRESET,
    seed: Any = None,
    overwrite: Any = False,
    job_id: Any = None,
    icon_sizes: Any = None,
    ico: Any = False,
) -> Dict[str, Any]:
    """Validate ``generate_app_asset`` params; return normalized args dict.

    Applies C1 defaults: ``width``/``height`` 512, ``format`` ``"png"``,
    ``style_preset`` ``"flat"``, and ``remove_bg`` defaulting to ``True``
    for ``icon``/``avatar`` else ``False``. Path-shape violations raise
    :class:`PolicyDeniedError`; all other param violations raise
    ``ValueError`` with an ``INVALID_*`` message.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("INVALID_PROMPT: prompt must be a non-empty string")
    if category not in CATEGORIES:
        raise ValueError(
            "INVALID_CATEGORY: must be one of %s, got %r" % (sorted(CATEGORIES), category)
        )
    _check_path_shape(save_path)
    width = _require_int("width", width, minimum=1, code="INVALID_WIDTH")
    height = _require_int("height", height, minimum=1, code="INVALID_HEIGHT")
    if format not in FORMATS:
        raise ValueError(
            "INVALID_FORMAT: must be one of %s, got %r" % (sorted(FORMATS), format)
        )
    if remove_bg is None:
        remove_bg = category in REMOVE_BG_DEFAULT_TRUE
    elif not isinstance(remove_bg, bool):
        raise ValueError("INVALID_REMOVE_BG: must be a bool, got %r" % (remove_bg,))
    if style_preset not in STYLE_PRESETS:
        raise ValueError(
            "INVALID_STYLE_PRESET: must be one of %s, got %r"
            % (sorted(STYLE_PRESETS), style_preset)
        )
    if seed is not None:
        seed = _require_int("seed", seed, minimum=0, code="INVALID_SEED")
    if not isinstance(overwrite, bool):
        raise ValueError("INVALID_OVERWRITE: overwrite must be a bool, got %r" % (overwrite,))
    if job_id is not None and (not isinstance(job_id, str) or not job_id):
        raise ValueError("INVALID_JOB_ID: job_id must be a non-empty string when given")
    if icon_sizes is None:
        icon_sizes_norm = None
    else:
        # Empty list is a valid no-op (no extra icon files requested).
        if isinstance(icon_sizes, str) or not isinstance(icon_sizes, (list, tuple)):
            raise ValueError(
                "INVALID_ICON_SIZES: icon_sizes must be a list/tuple of ints, got %r"
                % (icon_sizes,)
            )
        icon_sizes_norm = list(icon_sizes)
        max_dim = max(width, height)
        for _s in icon_sizes_norm:
            if isinstance(_s, bool) or not isinstance(_s, int):
                raise ValueError(
                    "INVALID_ICON_SIZES: each icon size must be an int, got %r"
                    % (_s,)
                )
            if not 1 <= _s <= 512:
                raise ValueError(
                    "INVALID_ICON_SIZES: each icon size must be 1..512, got %r"
                    % (_s,)
                )
            if _s > max_dim:
                raise ValueError(
                    "INVALID_ICON_SIZES: icon size %r exceeds max(width,height)=%r"
                    % (_s, max_dim)
                )
    if ico is None:
        ico = False
    if not isinstance(ico, bool):
        raise ValueError("INVALID_ICO: ico must be a bool, got %r" % (ico,))

    validated: Dict[str, Any] = {
        "prompt": prompt,
        "category": category,
        "save_path": save_path,
        "width": width,
        "height": height,
        "format": format,
        "remove_bg": remove_bg,
        "style_preset": style_preset,
        "seed": seed,
        "overwrite": overwrite,
        "job_id": job_id,
        "icon_sizes": icon_sizes_norm,
        "ico": ico,
    }
    return validated


def validate_check_model_args(name: Any, kind: Any = None) -> Dict[str, Any]:
    """Validate ``check_model`` params; return normalized ``{name, kind}``.

    ``name`` must be a non-empty string (else ``ValueError``
    ``INVALID_MODEL_NAME``). ``kind`` may be ``None`` (search all four
    loader nodes) or one of the four user-facing kinds in
    :data:`KIND_TO_LOADERS` (``checkpoint`` | ``clip`` | ``unet`` |
    ``vae``), each mapping to ComfyUI loader node class name(s); any
    other kind raises ``ValueError`` ``UNKNOWN_LOADER`` pre-backend, no
    backend call.
    """
    if not isinstance(name, str) or not name:
        raise ValueError(
            "INVALID_MODEL_NAME: name must be a non-empty string, got %r" % (name,)
        )
    if kind is not None:
        if not isinstance(kind, str) or kind not in CHECK_MODEL_LOADERS:
            raise ValueError(
                "UNKNOWN_LOADER: kind must be one of %s, got %r"
                % (sorted(CHECK_MODEL_LOADERS), kind)
            )
    return {"name": name, "kind": kind}


__all__ = [
    "CATEGORIES",
    "CHECK_MODEL_LOADERS",
    "KIND_TO_LOADERS",
    "FORMATS",
    "STYLE_PRESETS",
    "DEFAULT_WIDTH",
    "DEFAULT_HEIGHT",
    "DEFAULT_FORMAT",
    "DEFAULT_STYLE_PRESET",
    "DEFAULT_REFINE_STRENGTH",
    "REMOVE_BG_DEFAULT_TRUE",
    "derive_refined_save_path",
    "resolve_save_path",
    "validate_check_model_args",
    "validate_tool_args",
    "validate_refine_args",
]


def derive_refined_save_path(parent_save_path: str) -> str:
    """Default refine target: sibling of the parent with a ``_refined`` stem.

    Pure POSIX string math (no filesystem touch), e.g.
    ``"assets/images/bear_avatar.png"`` ->
    ``"assets/images/bear_avatar_refined.png"``. A parent without an
    extension gains ``".png"``. The result always passes
    :func:`_check_path_shape` when the parent does.
    """
    head, slash, tail = parent_save_path.rpartition("/")
    root, ext = posixpath.splitext(tail)
    if not ext:
        ext = ".png"
    return "%s%s%s_refined%s" % (head, slash, root, ext)


def validate_refine_args(
    asset_id: Any = None,
    asset_path: Any = None,
    instruction: Any = None,
    save_path: Any = None,
    strength: Any = DEFAULT_REFINE_STRENGTH,
    job_id: Any = None,
) -> Dict[str, Any]:
    """Validate ``refine_asset`` params; return a normalized args dict.

    Requires one of ``asset_id`` | ``asset_path`` (``ValueError`` with
    ``INVALID_ASSET_REF`` when both are missing) and a non-empty
    ``instruction``. ``save_path`` defaults to the derived sibling
    (:func:`derive_refined_save_path`) when ``asset_path`` is given and
    stays ``None`` for id-only calls (the orchestrator derives it from
    the stored parent path). ``strength`` must satisfy ``0 < s <= 1``
    (default 0.6). Path-shape violations raise :class:`PolicyDeniedError`;
    all other param violations raise ``ValueError`` with an ``INVALID_*``
    message.
    """
    if asset_id is None and asset_path is None:
        raise ValueError(
            "INVALID_ASSET_REF: one of asset_id|asset_path is required"
        )
    if asset_id is not None and (not isinstance(asset_id, str) or not asset_id):
        raise ValueError(
            "INVALID_ASSET_REF: asset_id must be a non-empty string when given, "
            "got %r" % (asset_id,)
        )
    if asset_path is not None:
        _check_path_shape(asset_path)
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("INVALID_INSTRUCTION: instruction must be a non-empty string")
    if save_path is None and asset_path is not None:
        save_path = derive_refined_save_path(asset_path)
    if save_path is not None:
        _check_path_shape(save_path)
    if isinstance(strength, bool) or not isinstance(strength, (int, float)):
        raise ValueError(
            "INVALID_STRENGTH: strength must be a number in (0, 1], got %r"
            % (strength,)
        )
    if not 0 < strength <= 1:
        raise ValueError(
            "INVALID_STRENGTH: strength must be in (0, 1], got %r" % (strength,)
        )
    if job_id is not None and (not isinstance(job_id, str) or not job_id):
        raise ValueError("INVALID_JOB_ID: job_id must be a non-empty string when given")

    return {
        "asset_id": asset_id,
        "asset_path": asset_path,
        "instruction": instruction,
        "save_path": save_path,
        "strength": float(strength),
        "job_id": job_id,
    }
