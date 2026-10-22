"""Argument validation and project-root jail (C1 v0.1.5).

Two layers:

* :func:`validate_tool_args` — pure string/shape validation for
  ``generate_app_asset`` params. Path *shape* problems (empty, ``..``,
  trailing separator, drive-relative) raise :class:`PolicyDeniedError`;
  param problems raise ``ValueError`` with an ``INVALID_*`` message.
  Filesystem containment and the overwrite check need ``project_root`` and
  live in ...
* :func:`resolve_save_path` — ... which resolves the path (relative under
  ``project_root``; absolute as given), verifies containment against the
  approved roots, and refuses existing files unless ``overwrite=True``.

C1 v0.1.5 (user request, 2026-10-22): the AGENT chooses the output path.
An absolute ``save_path`` is accepted when it lands inside an approved root
(the configured project root or a named workspace); relative paths keep
resolving under the selected workspace root. ``..`` traversal is refused in
every form, so containment can never be walked out of.

``validate_tool_args`` intentionally does not touch the filesystem, so the
golden-shape check stays hermetic; ``resolve_save_path`` is the enforcing
gate the slice-2 orchestrator must call before any write.
"""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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

#: Absolute Windows drive path after separator normalization (``C:/x``).
_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:/")


def _normalize_separators(save_path: str) -> str:
    """Fold Windows separators into POSIX ones (``\\`` -> ``/``).

    ``C:\\proj\\assets\\icon.png`` and ``C:/proj/assets/icon.png`` are the
    same path, so the agent may use whichever form it produces.
    """
    return save_path.replace("\\", "/")


def _norm_key(path: Any) -> str:
    """Case-normalized absolute key used for containment comparisons."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _real_key(path: Any) -> str:
    """Case-normalized key of the REAL path (symlinks/junctions resolved).

    Containment is decided on these keys, not on the lexical ones: a
    link inside an approved root that points outside it must not become a
    write outside that root.
    """
    return os.path.normcase(os.path.realpath(os.fspath(path)))


#: Windows reserved device names — ``NUL.png`` still resolves to the null
#: device, so these are refused by name (never a real asset file).
_WINDOWS_DEVICE_NAMES = frozenset(
    ["nul", "con", "prn", "aux"]
    + ["com%d" % i for i in range(1, 10)]
    + ["lpt%d" % i for i in range(1, 10)]
)

#: File-name stem charset accepted by the PNG writer (mirrors
#: :func:`src.postprocess.export.scale_filename`). The server writes PNG
#: bytes only, so the requested leaf must be ``<stem>.png`` — otherwise the
#: written file and the reported path would differ.
_PNG_SAFE_STEM_RE = re.compile(r"[A-Za-z0-9._-]+")


def _is_reserved_device_name(name: str) -> bool:
    """True for a Windows device name (``NUL``, ``COM1``, ... with any suffix)."""
    if os.name != "nt":
        return False
    stem = name.split(".", 1)[0].strip().lower()
    return stem in _WINDOWS_DEVICE_NAMES


def _is_within(root_key: str, candidate_key: str) -> bool:
    """True when ``candidate_key`` is strictly inside ``root_key``.

    Both arguments are :func:`_norm_key` values (absolute, case-folded on
    Windows). A candidate equal to the root is NOT inside it — a save path
    must name a file, never the root itself.
    """
    if candidate_key == root_key:
        return False
    prefix = root_key if root_key.endswith(os.sep) else root_key + os.sep
    return candidate_key.startswith(prefix)


def _split_save_path(save_path: Any) -> Tuple[bool, str]:
    """Validate the shape of ``save_path``; return ``(is_absolute, normalized)``.

    Windows separators are folded to ``/``. Absolute paths (POSIX ``/x``,
    Windows ``C:/x``, UNC ``//host/x``) are ACCEPTED here — the agent may
    name the exact output location; containment against the approved roots
    is enforced later by :func:`resolve_save_path`.

    Refused in every form: empty/non-string values, ``..`` traversal, a
    trailing separator, drive-relative paths (``C:foo``), and paths that do
    not name a file.
    """
    if not isinstance(save_path, str) or not save_path:
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must be a non-empty "
            "path string, got %r" % (save_path,)
        )
    if "\x00" in save_path:
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must not contain NUL "
            "bytes, got %r" % (save_path,)
        )
    normalized = _normalize_separators(save_path)
    if not normalized.strip():
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must be a non-empty "
            "path string, got %r" % (save_path,)
        )
    if ".." in normalized.split("/"):
        raise PolicyDeniedError(
            "POLICY_DENIED: '..' traversal is never accepted in save_path, "
            "got %r" % (save_path,)
        )
    if _DRIVE_LETTER_RE.match(normalized) and not _DRIVE_ABS_RE.match(normalized):
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: drive-relative paths are not "
            "accepted (use an absolute path with a separator after the drive "
            "letter), got %r" % (save_path,)
        )
    if normalized.endswith("/"):
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must name a file, got %r"
            % (save_path,)
        )
    tail = normalized.rsplit("/", 1)[-1]
    if not tail or tail == ".":
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must name a file, got %r"
            % (save_path,)
        )
    if _is_reserved_device_name(tail):
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must not name a "
            "reserved device, got %r" % (save_path,)
        )
    if os.name == "nt":
        # A ':' inside a component is an NTFS alternate data stream
        # ("icon.png:evil"): the write would bypass the overwrite guard and
        # the reported path would not exist as a file. Refused on Windows;
        # POSIX allows ':' in file names, so it stays legal there.
        _parts = normalized.split("/")
        _checked = _parts[1:] if _DRIVE_ABS_RE.match(normalized) else _parts
        if any(":" in part for part in _checked):
            raise PolicyDeniedError(
                "POLICY_DENIED INVALID_SAVE_PATH: ':' is not allowed inside a "
                "path component on Windows (alternate data stream), got %r"
                % (save_path,)
            )
    _check_asset_leaf(tail, save_path)
    is_absolute = normalized.startswith("/") or bool(_DRIVE_ABS_RE.match(normalized))
    return is_absolute, normalized


def _check_asset_leaf(tail: str, save_path: Any) -> None:
    """Refuse a leaf the server cannot write under the requested name.

    The pipeline writes PNG bytes named ``<stem>.png`` (plus ``@2x``/``@3x``
    siblings), so the requested leaf must BE ``<stem>.png`` with a
    PNG-safe stem — otherwise the written file and the path the tool
    reports would differ. Refused pre-backend, with a machine-readable
    code.
    """
    stem, dot, ext = tail.rpartition(".")
    if not dot or ext != "png":
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path must name a .png file "
            "(lowercase; the server writes PNG assets), got %r" % (save_path,)
        )
    if (
        not stem
        or ".." in stem
        or _PNG_SAFE_STEM_RE.fullmatch(stem) is None
        or not any(char.isalnum() for char in stem)
    ):
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_SAVE_PATH: save_path file name must be "
            "<stem>.png with a stem of [A-Za-z0-9._-] containing at least one "
            "letter or digit, got %r" % (save_path,)
        )


def _check_path_shape(save_path: Any) -> str:
    """Shape check for ``save_path``; returns the normalized path.

    Absolute paths pass the shape check (C1 v0.1.5) — they are contained
    later against the approved roots by :func:`resolve_save_path`.
    """
    _is_absolute, normalized = _split_save_path(save_path)
    return normalized


def resolve_save_path(
    save_path: str,
    project_root: Any,
    overwrite: bool = False,
    allowed_roots: Optional[Iterable[Any]] = None,
    allow_any_path: bool = False,
) -> Path:
    """Resolve ``save_path`` to an absolute :class:`Path` inside an approved root.

    * A **relative** path resolves under ``project_root`` (the selected
      workspace root) — unchanged C1 v0.1.4 behavior.
    * An **absolute** path is honoured as given (the agent chooses the exact
      output location) but must land inside one of ``allowed_roots``
      (default: ``project_root`` alone). ``allow_any_path=True`` lifts that
      containment check — it is an explicit server-side opt-in
      (``--allow-any-path``), never a per-call decision.

    Refused in every form: absolute paths outside the approved roots, ``..``
    traversal, paths that do not name a file, and clobbering an existing
    file unless ``overwrite`` is ``True`` (all ``POLICY_DENIED``).
    """
    is_absolute, normalized = _split_save_path(save_path)
    if not isinstance(overwrite, bool):
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_OVERWRITE: overwrite must be a bool, got %r"
            % (overwrite,)
        )
    root_real = os.path.abspath(os.fspath(project_root))
    roots_real: List[str] = []
    roots_lex: List[str] = []
    roots_shown: List[str] = []
    for candidate in list(allowed_roots or []) + [project_root]:
        shown = os.path.abspath(os.fspath(candidate))
        lex = _norm_key(candidate)
        real = _real_key(candidate)
        if real not in roots_real:
            roots_real.append(real)
            roots_lex.append(lex)
            roots_shown.append(shown)
    if is_absolute:
        target_abs = os.path.abspath(normalized)
        if not allow_any_path and not any(
            _is_within(root, _real_key(target_abs)) for root in roots_real
        ):
            lex_inside = any(
                _is_within(root, _norm_key(target_abs)) for root in roots_lex
            )
            if lex_inside:
                raise PolicyDeniedError(
                    "POLICY_DENIED: absolute save_path %r is inside an approved "
                    "root but RESOLVES outside it (a link points outside); ask "
                    "the human to point the save path at a real directory, to "
                    "add that tree as a workspace (--workspace name=path), or "
                    "to start the server with --allow-any-path"
                    % (save_path,)
                )
            raise PolicyDeniedError(
                "POLICY_DENIED: absolute save_path %r is outside every approved "
                "root (%s); ask the human to add that tree as a workspace "
                "(--workspace name=path) or to start the server with "
                "--allow-any-path" % (save_path, ", ".join(roots_shown))
            )
    else:
        target_abs = os.path.abspath(
            os.path.join(root_real, *posixpath.normpath(normalized).split("/"))
        )
        if not _is_within(_real_key(root_real), _real_key(target_abs)):
            if _is_within(_norm_key(root_real), _norm_key(target_abs)):
                raise PolicyDeniedError(
                    "POLICY_DENIED: save_path %r is inside the project root but "
                    "RESOLVES outside it (a link points outside); use a real "
                    "directory inside the root" % (save_path,)
                )
            raise PolicyDeniedError(
                "POLICY_DENIED: save_path escapes project root, got %r" % (save_path,)
            )
    if os.path.exists(target_abs) and not overwrite:
        raise PolicyDeniedError(
            "POLICY_DENIED INVALID_OVERWRITE: file exists and overwrite is not "
            "set, got %r" % (save_path,)
        )
    return Path(target_abs)


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
    workspace: Any = "default",
) -> Dict[str, Any]:
    """Validate ``generate_app_asset`` params; return normalized args dict.

    Applies C1 defaults: ``width``/``height`` 512, ``format`` ``"png"``,
    ``style_preset`` ``"flat"``, ``workspace`` ``"default"`` (a named
    server-side root; unknown names fail downstream with
    ``INVALID_WORKSPACE``), and ``remove_bg`` defaulting to ``True`` for
    ``icon``/``avatar`` else ``False``. ``save_path`` may be relative
    (resolved under the selected workspace root) or absolute (honoured as
    given when it lands inside an approved root — C1 v0.1.5); Windows
    separators are normalized to ``/``.
    Path-shape violations raise
    :class:`PolicyDeniedError`; all other param violations raise
    ``ValueError`` with an ``INVALID_*`` message.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("INVALID_PROMPT: prompt must be a non-empty string")
    if category not in CATEGORIES:
        raise ValueError(
            "INVALID_CATEGORY: must be one of %s, got %r" % (sorted(CATEGORIES), category)
        )
    save_path = _check_path_shape(save_path)
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
    if not isinstance(workspace, str) or not workspace:
        raise ValueError(
            "INVALID_WORKSPACE: workspace must be a non-empty string, got %r"
            % (workspace,)
        )

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
        "workspace": workspace,
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
    workspace: Any = "default",
) -> Dict[str, Any]:
    """Validate ``refine_asset`` params; return a normalized args dict.

    Requires one of ``asset_id`` | ``asset_path`` (``ValueError`` with
    ``INVALID_ASSET_REF`` when both are missing) and a non-empty
    ``instruction``. ``save_path`` defaults to the derived sibling
    (:func:`derive_refined_save_path`) when ``asset_path`` is given and
    stays ``None`` for id-only calls (the orchestrator derives it from
    the stored parent path). ``strength`` must satisfy ``0 < s <= 1``
    (default 0.6). ``workspace`` selects a named server-side root
    (default ``"default"``; unknown names fail downstream with
    ``INVALID_WORKSPACE``). ``asset_path``/``save_path`` may be relative
    (resolved under the selected workspace root) or absolute (honoured as
    given when it lands inside an approved root — C1 v0.1.5).
    Path-shape violations raise :class:`PolicyDeniedError`;
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
        asset_path = _check_path_shape(asset_path)
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("INVALID_INSTRUCTION: instruction must be a non-empty string")
    if save_path is None and asset_path is not None:
        save_path = derive_refined_save_path(asset_path)
    if save_path is not None:
        save_path = _check_path_shape(save_path)
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
    if not isinstance(workspace, str) or not workspace:
        raise ValueError(
            "INVALID_WORKSPACE: workspace must be a non-empty string, got %r"
            % (workspace,)
        )

    return {
        "asset_id": asset_id,
        "asset_path": asset_path,
        "instruction": instruction,
        "save_path": save_path,
        "strength": float(strength),
        "job_id": job_id,
        "workspace": workspace,
    }
