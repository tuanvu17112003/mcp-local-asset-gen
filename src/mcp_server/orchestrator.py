"""C1 orchestration: generate/refine flows over C2 + C3 (contract v0.1.0).

:class:`AssetOrchestrator` wires the frozen sibling interfaces with
injectable deps so every path is testable with fakes (no network, no
model downloads, no ``fastmcp`` import):

* ``backend`` — either an object exposing ``submit_txt2img`` /
  ``submit_img2img`` + ``fetch_result`` callables (fake stubs), or a
  C2 ``ComfyClient``. The client path goes through ONLY the thin
  helpers ``src.gen_backend.submit_txt2img`` / ``submit_img2img``
  (lazily imported); raw ``client.submit`` prompt-dict building never
  happens here. ``fetch_result`` is called with the ``job_id`` those
  helpers return.
* ``postprocess`` — a callable like ``src.postprocess.pipeline.process``
  (default: the real one, guarded import). Called with
  ``vectorize=False`` (MVP: ``True`` raises in C3, never yields files).
* ``writer`` — ``(path, bytes)`` sink; default writes to disk.

Both flows share one shape: validate -> idempotency check (stored
``job_id`` returns without re-running) -> registry slot (``QUEUED``
when full) -> :func:`resolve_save_path` BEFORE any write -> backend
submit -> fetch -> postprocess (sibling errors translated via
:func:`translate_sibling_error`) -> write base + ``@2x``/``@3x`` files
under the project jail -> record + return.

MVP notes: ``format`` is echoed metadata (PNG bytes; SVG vector output
is deferred — C3 ``vectorize=True`` raises). Refine postprocessing uses
``remove_bg=False`` / ``trim=False`` to preserve the finished parent's
composition (the parent already passed through the pipeline once).
Refine has no ``overwrite`` param: an existing target (including a
colliding derived sibling) is refused with ``POLICY_DENIED``.
"""

from __future__ import annotations

import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .config import DEFAULT_COMFYUI_URL, SERVER_VERSION, ServerConfig
from .errors import (
    BackendUnavailableError,
    GenerationFailedError,
    McpServerError,
    PolicyDeniedError,
    PostprocessFailedError,
    translate_sibling_error,
)
from .registry import JobRegistry
from .validation import (
    CHECK_MODEL_LOADERS,
    KIND_TO_LOADERS,
    derive_refined_save_path,
    resolve_save_path,
    validate_check_model_args,
    validate_refine_args,
    validate_tool_args,
)

try:
    from src.postprocess.pipeline import process as _default_process
except Exception:  # pragma: no cover - optional dep; tests/prod inject fakes
    _default_process = None

#: C3 v0.1.1 icon scale labels: ``icon<N>`` with ``N >= 1`` (no leading
#: zero). Size is derived from the entry's ``width``/``height``; the label
#: itself is only a well-formedness gate. ``@Nx`` entries keep integer
#: ``scale`` (1/2/3) byte-identical.
_ICON_SCALE_RE = re.compile(r"^icon([1-9][0-9]*)$")

#: C1 ``style_preset`` -> C2 style id (sibling ``STYLE_PRESETS`` ids:
#: ``flat``, ``3d-clay``, ``minimal-line``, ``pixel-art``).
STYLE_TO_BACKEND = {
    "flat": "flat",
    "clay": "3d-clay",
    "line": "minimal-line",
    "pixel": "pixel-art",
}

#: Models advertised by :meth:`server_info` (C2 ``MODEL_PRESETS`` ids).
SERVER_MODELS = ["flux-schnell-gguf-q4", "flux-schnell-fp8"]

_GENERATE_FIELDS = (
    "prompt",
    "category",
    "save_path",
    "width",
    "height",
    "format",
    "remove_bg",
    "style_preset",
    "seed",
    "overwrite",
    "job_id",
    "icon_sizes",
    "ico",
)

_REFINE_FIELDS = (
    "asset_id",
    "asset_path",
    "instruction",
    "save_path",
    "strength",
    "job_id",
)


def _default_writer(path: Any, data: bytes) -> None:
    """Write ``data`` to ``path``, creating parent dirs (the ``writer`` default)."""
    dest = Path(os.fspath(path))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(data))


class AssetOrchestrator:
    """Generate/refine orchestrator with injectable backend/postprocess/writer."""

    def __init__(
        self,
        backend: Any,
        *,
        postprocess: Optional[Callable[..., Dict[str, Any]]] = None,
        writer: Optional[Callable[[Any, bytes], None]] = None,
        config: Optional[ServerConfig] = None,
        registry: Optional[JobRegistry] = None,
    ) -> None:
        if backend is None or not callable(getattr(backend, "fetch_result", None)):
            raise TypeError(
                "backend must expose fetch_result(job_id) plus submit_txt2img/ "
                "submit_img2img callables (or be a ComfyClient)"
            )
        self._backend = backend
        self._txt2img = getattr(backend, "submit_txt2img", None)
        self._img2img = getattr(backend, "submit_img2img", None)
        if postprocess is None:
            postprocess = _default_process
        if postprocess is None:
            raise ValueError(
                "no postprocess callable given and src.postprocess.pipeline "
                "is unavailable (pillow missing?)"
            )
        self._postprocess = postprocess
        self._writer = writer or _default_writer
        self._config = config
        if registry is None:
            max_concurrent = config.max_concurrent if config is not None else 2
            registry = JobRegistry(max_concurrent=max_concurrent)
        self._registry = registry

    # -- backend adapters -------------------------------------------------

    def _submit_txt2img(
        self, *, prompt: str, width: int, height: int, seed: Any, style: str
    ) -> str:
        """Submit txt2img via the stub method or ONLY the C2 thin helper."""
        if callable(self._txt2img):
            return self._txt2img(
                prompt=prompt, width=width, height=height, seed=seed, style=style
            )
        try:  # shim layout first (src/ on sys.path), cf. server.py dual-try
            from gen_backend import submit_txt2img as submit_helper
        except ImportError:  # package layout (checkout root on sys.path)
            from src.gen_backend import submit_txt2img as submit_helper

        return submit_helper(
            self._backend,
            prompt=prompt,
            width=width,
            height=height,
            seed=seed,
            style=style,
        )

    def _submit_img2img(
        self, *, input_png_path: str, instruction: str, strength: float
    ) -> str:
        """Submit img2img via the stub method or ONLY the C2 thin helper."""
        if callable(self._img2img):
            return self._img2img(
                input_png_path=input_png_path,
                instruction=instruction,
                strength=strength,
            )
        try:  # shim layout first (src/ on sys.path), cf. server.py dual-try
            from gen_backend import submit_img2img as submit_helper
        except ImportError:  # package layout (checkout root on sys.path)
            from src.gen_backend import submit_img2img as submit_helper

        return submit_helper(
            self._backend,
            input_png_path=input_png_path,
            instruction=instruction,
            strength=strength,
        )

    def _fetch_png_and_seed(self, backend_job_id: str) -> Any:
        """Fetch the backend result; require PNG bytes (else GENERATION_FAILED)."""
        raw = self._backend.fetch_result(backend_job_id)
        if not isinstance(raw, dict) or not isinstance(
            raw.get("png_bytes"), (bytes, bytearray)
        ):
            raise GenerationFailedError(
                "GENERATION_FAILED: backend returned no PNG bytes for job %r"
                % (backend_job_id,)
            )
        return raw

    # -- shared flow pieces -------------------------------------------------

    def _write_files(
        self, files: Any, target: Path, project_root: Any
    ) -> "Path":
        """Write postprocess ``files`` beside ``target``; return ``target``.

        ``filename`` leaves come from ``process()`` and are joined as
        ``output_dir / filename``. Non-leaf or jail-escaping names are
        refused with ``POLICY_DENIED`` (defense in depth: the stem came
        from a jailed path, but a hostile postprocess must not write
        outside the root). An empty file list is ``POSTPROCESS_FAILED``.
        Malformed entries (non-dict, missing ``filename``/``png_bytes``,
        non-bytes ``png_bytes``, or insane ``width``/``height``/``scale``
        when present) are ``POSTPROCESS_FAILED``. ``scale`` accepts the
        ``@Nx`` integers (1/2/3, byte-identical), the C3 v0.1.1 icon
        labels ``icon<N>`` (``N >= 1``, size derived from
        ``width``/``height``), and ``"ico"`` for ``.ico`` entries.
        """
        if not isinstance(files, (list, tuple)) or not files:
            raise PostprocessFailedError(
                "POSTPROCESS_FAILED: postprocess returned no files"
            )
        root_abs = os.path.abspath(os.fspath(project_root))
        out_dir = target.parent
        for entry in files:
            if not isinstance(entry, dict):
                raise PostprocessFailedError(
                    "POSTPROCESS_FAILED: postprocess file entry must be "
                    "a dict, got %r" % (entry,)
                )
            if "filename" not in entry:
                raise PostprocessFailedError(
                    "POSTPROCESS_FAILED: postprocess file entry missing "
                    "'filename': %r" % (entry,)
                )
            filename = entry["filename"]
            if (
                not isinstance(filename, str)
                or not filename
                or "/" in filename
                or "\\" in filename
                or filename in (".", "..")
            ):
                raise PolicyDeniedError(
                    "POLICY_DENIED: postprocess filename must be a leaf, got %r"
                    % (filename,)
                )
            if "png_bytes" not in entry:
                raise PostprocessFailedError(
                    "POSTPROCESS_FAILED: postprocess file entry missing "
                    "'png_bytes': %r" % (entry,)
                )
            blob = entry["png_bytes"]
            if not isinstance(blob, (bytes, bytearray, memoryview)):
                raise PostprocessFailedError(
                    "POSTPROCESS_FAILED: postprocess png_bytes must be "
                    "bytes-like, got %r" % (type(blob).__name__,)
                )
            # ICO entries reuse the ``png_bytes`` key for ICO bytes: branch
            # on ``scale == "ico"`` / ``.ico`` filename, never a separate key.
            # For those entries ``scale == "ico"`` is permitted and
            # ``width``/``height`` are optional; non-ico entries keep the
            # strict positive-int checks. C3 v0.1.1 icon PNGs carry string
            # labels ``icon<N>`` (N >= 1, no leading zero); size comes from
            # width/height, so the label is only well-formedness-gated.
            _is_ico = filename.lower().endswith(".ico") or entry.get("scale") == "ico"
            for _dim in ("width", "height", "scale"):
                if _dim not in entry:
                    continue
                _val = entry[_dim]
                if _dim == "scale" and _is_ico and _val == "ico":
                    continue
                if (
                    _dim == "scale"
                    and isinstance(_val, str)
                    and _ICON_SCALE_RE.match(_val)
                ):
                    continue
                if (
                    isinstance(_val, bool)
                    or not isinstance(_val, int)
                    or _val < 1
                ):
                    raise PostprocessFailedError(
                        "POSTPROCESS_FAILED: postprocess %s must be a "
                        "positive int, got %r" % (_dim, _val)
                    )
            dest_abs = os.path.abspath(
                os.path.join(os.fspath(out_dir), filename)
            )
            if dest_abs == root_abs or os.path.commonpath([root_abs, dest_abs]) != root_abs:
                raise PolicyDeniedError(
                    "POLICY_DENIED: postprocess filename escapes project root, "
                    "got %r" % (filename,)
                )
            self._writer(os.path.join(os.fspath(out_dir), filename), blob)
        return target

    @staticmethod
    def _relative_posix(target: Path, project_root: Any) -> str:
        root_abs = os.path.abspath(os.fspath(project_root))
        return Path(os.path.relpath(os.fspath(target), root_abs)).as_posix()

    # -- public flows ----------------------------------------------------------

    def generate(
        self,
        validated_args: Dict[str, Any],
        project_root: Any,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the generate flow; return the C1 ``generate_app_asset`` output."""
        if not isinstance(validated_args, dict):
            raise ValueError(
                "INVALID_ARGS: validated_args must be a dict, got %r"
                % (validated_args,)
            )
        args = validate_tool_args(
            **{k: validated_args[k] for k in _GENERATE_FIELDS if k in validated_args}
        )
        if args["format"] == "svg":
            # Q4 defers SVG vector output (C3 ``vectorize=True`` raises and
            # never yields files): refuse loudly instead of echoing svg
            # metadata beside PNG bytes. ``format`` stays echoed for png.
            raise PostprocessFailedError(
                "POSTPROCESS_FAILED SVG-DEFERRED: format='svg' is deferred to "
                "Q4 (no vector output yet); retry with format='png'"
            )
        jid = job_id or args.get("job_id") or JobRegistry.new_job_id()
        stored = self._registry.get(jid)
        if stored is not None:
            return stored
        self._registry.register(jid)
        try:
            target = resolve_save_path(
                args["save_path"], project_root, overwrite=args["overwrite"]
            )
            backend_job_id = self._submit_txt2img(
                prompt=args["prompt"],
                width=args["width"],
                height=args["height"],
                seed=args["seed"],
                style=STYLE_TO_BACKEND[args["style_preset"]],
            )
            fetched = self._fetch_png_and_seed(backend_job_id)
            seed = args["seed"]
            if seed is None:
                seed = fetched.get("seed")
            if seed is None:  # neither caller nor backend supplied one (mirrors C2)
                seed = random.randint(0, 0xFFFFFFFF)
            stem = Path(args["save_path"].replace("\\", "/")).stem
            processed = self._postprocess(
                bytes(fetched["png_bytes"]),
                remove_bg=args["remove_bg"],
                model="u2net",
                trim=True,
                sizes=(1, 2, 3),
                stem=stem,
                vectorize=False,
                icon_sizes=args.get("icon_sizes"),
                ico=args.get("ico", False),
            )
            self._write_files(processed["files"], target, project_root)
            result = {
                "asset_path": self._relative_posix(target, project_root),
                "width": args["width"],
                "height": args["height"],
                "format": args["format"],
                "seed": seed,
                "style_preset": args["style_preset"],
                "job_id": jid,
            }
        except McpServerError:
            self._registry.fail(jid)
            raise
        except Exception as exc:
            self._registry.fail(jid)
            code = getattr(exc, "code", None)
            if isinstance(code, str):
                raise translate_sibling_error(exc) from exc
            raise
        self._registry.complete(jid, result)
        return result

    def refine(
        self,
        validated_args: Dict[str, Any],
        project_root: Any,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the refine flow; return the C1 ``refine_asset`` output.

        Creates a NEW file; the parent is only read, never mutated.
        """
        if not isinstance(validated_args, dict):
            raise ValueError(
                "INVALID_ARGS: validated_args must be a dict, got %r"
                % (validated_args,)
            )
        args = validate_refine_args(
            **{k: validated_args[k] for k in _REFINE_FIELDS if k in validated_args}
        )
        parent_rel, parent_abs = self._resolve_parent(args, project_root)
        save_path = args["save_path"]
        if save_path is None:  # asset_id-only call: derive from the stored parent
            save_path = derive_refined_save_path(parent_rel)
        parent_job_id = (
            args["asset_id"]
            or self._registry.find_job_by_asset(parent_rel)
            or parent_rel
        )
        jid = job_id or args.get("job_id") or JobRegistry.new_job_id()
        stored = self._registry.get(jid)
        if stored is not None:
            return stored
        self._registry.register(jid)
        try:
            target = resolve_save_path(save_path, project_root, overwrite=False)
            backend_job_id = self._submit_img2img(
                input_png_path=os.fspath(parent_abs),
                instruction=args["instruction"],
                strength=args["strength"],
            )
            fetched = self._fetch_png_and_seed(backend_job_id)
            stem = Path(save_path.replace("\\", "/")).stem
            processed = self._postprocess(
                bytes(fetched["png_bytes"]),
                remove_bg=False,
                model="u2net",
                trim=False,
                sizes=(1, 2, 3),
                stem=stem,
                vectorize=False,
            )
            self._write_files(processed["files"], target, project_root)
            result = {
                "asset_path": self._relative_posix(target, project_root),
                "job_id": jid,
                "parent_job_id": parent_job_id,
            }
        except McpServerError:
            self._registry.fail(jid)
            raise
        except Exception as exc:
            self._registry.fail(jid)
            code = getattr(exc, "code", None)
            if isinstance(code, str):
                raise translate_sibling_error(exc) from exc
            raise
        self._registry.complete(jid, result)
        return result

    def _resolve_parent(
        self, args: Dict[str, Any], project_root: Any
    ) -> Any:
        """Resolve the refine parent to ``(posix_rel, abs_path)`` inside the jail.

        ``asset_path`` inputs must exist (missing -> ``ValueError``);
        ``asset_id`` inputs resolve through the registry's stored results.
        """
        if args["asset_path"] is not None:
            parent_abs = resolve_save_path(
                args["asset_path"], project_root, overwrite=True
            )
            if not parent_abs.is_file():
                raise ValueError(
                    "INVALID_ASSET_PATH: no asset file at %r"
                    % (args["asset_path"],)
                )
            return self._relative_posix(parent_abs, project_root), parent_abs
        stored = self._registry.get(args["asset_id"])
        if not isinstance(stored, dict) or not stored.get("asset_path"):
            raise ValueError(
                "INVALID_ASSET_REF: unknown asset_id %r" % (args["asset_id"],)
            )
        parent_abs = resolve_save_path(
            stored["asset_path"], project_root, overwrite=True
        )
        if not parent_abs.is_file():
            raise ValueError(
                "INVALID_ASSET_PATH: stored parent for asset_id %r is missing "
                "at %r" % (args["asset_id"], stored["asset_path"])
            )
        return stored["asset_path"], parent_abs

    def server_info(self) -> Dict[str, Any]:
        """Return the C1 ``server_info`` output with a live reachability probe.

        Read-only stdlib ``urllib`` GET ``{comfyui_url}/prompt`` (timeout
        ~3s, never POST). Any success means ``reachable True`` plus an int
        ``queue_depth`` (``0`` fallback when the JSON is ok but carries no
        recognizable count). ANY exception (URLError/OSError/timeout/
        HTTPError/bad JSON) means ``reachable False``, ``queue_depth None``
        — never raises.
        """
        cfg = self._config
        url = cfg.comfyui_url if cfg is not None else DEFAULT_COMFYUI_URL
        version = cfg.version if cfg is not None else SERVER_VERSION
        if cfg is not None:
            project_root = os.path.abspath(os.fspath(cfg.project_root))
        else:
            project_root = os.path.abspath(os.getcwd())
        reachable, queue_depth = _probe_comfyui_queue(url)
        return {
            "backend": "comfyui",
            "comfyui_url": url,
            "models": list(SERVER_MODELS),
            "version": version,
            "project_root": project_root,
            "reachable": reachable,
            "queue_depth": queue_depth,
        }

    # -- model availability ----------------------------------------------------

    def _fetch_loader_files(self, loader: str) -> Any:
        """Call ``backend.loader_files`` flexibly for one ``loader``.

        Tries ``loader_files(loader)`` positionally, then ``loader=`` kw,
        then a no-arg full-map call with the ``loader`` key extracted.
        A backend without a callable ``loader_files`` is
        ``BACKEND_UNAVAILABLE``. Backend-coded failures propagate with
        their ``.code`` for :meth:`check_model` to classify.
        """
        fn = getattr(self._backend, "loader_files", None)
        if fn is None or not callable(fn):
            raise BackendUnavailableError(
                "BACKEND_UNAVAILABLE: backend has no loader_files() "
                "model-listing support"
            )
        try:
            return fn(loader)
        except TypeError:
            pass
        except Exception:
            raise
        try:
            return fn(loader=loader)
        except TypeError:
            pass
        except Exception:
            raise
        try:
            full = fn()
        except Exception as exc:
            code = getattr(exc, "code", None)
            if isinstance(code, str):
                raise
            raise BackendUnavailableError(
                "BACKEND_UNAVAILABLE: backend loader_files() signature "
                "incompatible (%s)" % (exc,)
            ) from exc
        if isinstance(full, dict) and loader in full:
            return full[loader]
        return {}

    def check_model(
        self, name: Any, kind: Any = None
    ) -> Dict[str, Any]:
        """Check model ``name`` availability via ``backend.loader_files``.

        ``kind`` is a user-facing kind (``checkpoint`` | ``clip`` |
        ``unet`` | ``vae``) mapped through :data:`KIND_TO_LOADERS` to
        ComfyUI loader node class name(s); the default searches all four
        nodes in sorted-kind order. Returns
        ``{available, loader, checked_at}`` with ``checked_at`` as
        ``datetime.now(timezone.utc).isoformat()``. ``available False``
        yields ``loader None``. Backend ``COMFY_UNREACHABLE`` becomes
        ``BACKEND_UNAVAILABLE``; backend ``UNKNOWN_LOADER`` for an
        explicit ``kind`` re-raises ``ValueError`` ``UNKNOWN_LOADER``
        while the default-all search skips that loader. Name matching is
        exact string equality against flattened filename lists, plus
        basename equality.
        """
        args = validate_check_model_args(name, kind)
        checked_at = datetime.now(timezone.utc).isoformat()
        wanted = args["name"]
        explicit = args["kind"] is not None
        loaders = (
            tuple(KIND_TO_LOADERS[args["kind"]])
            if explicit
            else tuple(
                loader
                for kind in sorted(KIND_TO_LOADERS)
                for loader in KIND_TO_LOADERS[kind]
            )
        )
        for loader in loaders:
            try:
                raw = self._fetch_loader_files(loader)
            except Exception as exc:
                code = getattr(exc, "code", None)
                text = ""
                try:
                    text = str(exc)
                except Exception:
                    text = ""
                is_unknown = code == "UNKNOWN_LOADER" or "UNKNOWN_LOADER" in text
                is_unreachable = code == "COMFY_UNREACHABLE" or "COMFY_UNREACHABLE" in text
                if is_unknown:
                    if explicit:
                        raise ValueError(
                            "UNKNOWN_LOADER: backend reports unknown loader %r"
                            % (loader,)
                        ) from exc
                    continue
                if is_unreachable:
                    raise translate_sibling_error(exc) from exc
                if isinstance(exc, McpServerError):
                    raise
                if isinstance(code, str):
                    try:
                        raise translate_sibling_error(exc) from exc
                    except (KeyError, TypeError):
                        pass
                raise
            for candidate in _flatten_loader_names(raw):
                if wanted == candidate or wanted == _basename(candidate):
                    return {
                        "available": True,
                        "loader": loader,
                        "checked_at": checked_at,
                    }
        return {"available": False, "loader": None, "checked_at": checked_at}


def _basename(filename: str) -> str:
    """POSIX-and-Windows basename for model filename matching."""
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def _flatten_loader_names(raw: Any) -> list:
    """Flatten a ``loader_files`` result to a list of filename strings.

    Accepts the C2 shape ``{input_name: [filenames]}`` (plus one extra
    nesting level for full-map fallbacks) or a plain list of names.
    """
    names: list = []
    if isinstance(raw, dict):
        for value in raw.values():
            if isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, str):
                        names.append(item)
            elif isinstance(value, str):
                names.append(value)
            elif isinstance(value, dict):
                for nested in value.values():
                    if isinstance(nested, (list, tuple)):
                        for item in nested:
                            if isinstance(item, str):
                                names.append(item)
                    elif isinstance(nested, str):
                        names.append(nested)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str):
                names.append(item)
    return names


def _probe_comfyui_queue(comfyui_url: str) -> Tuple[bool, Optional[int]]:
    """Read-only GET ``{comfyui_url}/prompt``; return ``(reachable, depth)``.

    Prefers ``exec_info.queue_remaining`` (int), falls back to top-level
    ``queue_remaining``, then to queue-length fields, else ``0`` when the
    JSON parses but carries no recognizable count. ANY exception means
    ``(False, None)`` — never raises.
    """
    try:
        import json
        import urllib.request

        target = comfyui_url.rstrip("/") + "/prompt"
        with urllib.request.urlopen(target, timeout=3) as resp:
            raw = resp.read()
        if isinstance(raw, bytes):
            text = raw.decode("utf-8")
        else:
            text = str(raw)
        payload = json.loads(text)
        if not isinstance(payload, dict):
            return True, 0
        exec_info = payload.get("exec_info")
        if isinstance(exec_info, dict):
            candidate = exec_info.get("queue_remaining")
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                return True, int(candidate)
        candidate = payload.get("queue_remaining")
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return True, int(candidate)
        total = 0
        found = False
        for key in ("queue_running", "queue_pending", "queue"):
            value = payload.get(key)
            if isinstance(value, list):
                total += len(value)
                found = True
            elif isinstance(value, int) and not isinstance(value, bool):
                total += int(value)
                found = True
        if found:
            return True, int(total)
        return True, 0
    except Exception:
        return False, None


__all__ = [
    "AssetOrchestrator",
    "STYLE_TO_BACKEND",
    "SERVER_MODELS",
    "CHECK_MODEL_LOADERS",
    "KIND_TO_LOADERS",
]
