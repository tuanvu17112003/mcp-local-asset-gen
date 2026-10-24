"""C1 orchestration: generate/refine flows over C2 + C3 (contract v0.1.5).

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
  ``vectorize=(format=="svg")`` (C3 v0.2: True appends the ``<stem>.svg``
  entry; for format=svg the SVG leaf is the only file written).
* ``writer`` — ``(path, bytes)`` sink; default writes to disk.

Both flows share one shape: validate -> idempotency check (stored
``job_id`` returns without re-running) -> registry slot (``QUEUED``
when full) -> :func:`resolve_save_path` BEFORE any write -> backend
submit -> fetch -> postprocess (sibling errors translated via
:func:`translate_sibling_error`) -> write base + ``@2x``/``@3x`` files
under the project jail -> record + return.

C1 v0.1.5 (user request, 2026-10-22): the AGENT chooses the output
path. A relative ``save_path`` still resolves under the selected
workspace root; an ABSOLUTE ``save_path`` is honoured as given when it
lands inside an approved root (the configured project root or a named
workspace — see :meth:`AssetOrchestrator._approved_roots`). ``..``
traversal stays refused everywhere, so containment can never be walked
out of. Results carry ``asset_path_absolute`` so the caller always
knows the exact file location.

C1 v0.2 (2026-10-24): ``format="svg"`` produces a real vector asset via
C3 vtracer — the requested ``<stem>.svg`` leaf is the only file written.
``include_image=True`` attaches the @1x PNG as MCP ``ImageContent`` under
``result["image"]`` (opt-in; default keeps the payload small).
C1 v0.5 (2026-10-24): refine gains opt-in ``remove_bg`` (default False —
the finished parent's composition is preserved; True strips the freshly
rendered background). Generate gains ``negative`` (passed to the C2
sampler's negative prompt).
Refine has no ``overwrite`` param: an existing target (including a
colliding derived sibling) is refused with ``POLICY_DENIED``.
"""

from __future__ import annotations

import os
import random
import re
import threading
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
    _is_reserved_device_name,
    _is_within,
    _norm_key,
    _real_key,
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
#: ``flat``, ``3d-clay``, ``minimal-line``, ``pixel-art``, ``pattern``).
STYLE_TO_BACKEND = {
    "flat": "flat",
    "clay": "3d-clay",
    "line": "minimal-line",
    "pixel": "pixel-art",
    "pattern": "pattern",
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
    "workspace",
    "include_image",
    "seamless",
    "palette",
    "symmetry",
    "negative",
    "remove_bg_model",
)

_REFINE_FIELDS = (
    "asset_id",
    "asset_path",
    "instruction",
    "save_path",
    "strength",
    "job_id",
    "workspace",
    "include_image",
    "remove_bg",
    "remove_bg_model",
)


def _default_writer(path: Any, data: bytes) -> None:
    """Write ``data`` to ``path``, creating parent dirs (the ``writer`` default)."""
    dest = Path(os.fspath(path))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(data))


def _image_content(png_bytes: bytes) -> Any:
    """MCP ``ImageContent`` for the base PNG (lazy fastmcp import).

    Nested dict returns are not auto-converted by FastMCP, so the tool
    result embeds the converted content object directly (documented
    nested pattern: ``Image(...).to_image_content()``).
    """
    from fastmcp.utilities.types import Image

    return Image(data=png_bytes, format="png").to_image_content()


def _root_list(roots: Any) -> list:
    """Normalize a root argument (one path or an iterable of paths) to a list."""
    if roots is None:
        return []
    if isinstance(roots, (str, bytes, os.PathLike)):
        return [os.fspath(roots)]
    return [os.fspath(root) for root in roots]


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
        # C1 v0.6 cancel support: registry job_id -> backend prompt_id for
        # jobs whose backend submit succeeded and that are not finished yet.
        self._active_backends: Dict[str, str] = {}
        self._active_lock = threading.Lock()

    # -- backend adapters -------------------------------------------------

    def _submit_txt2img(
        self, *, prompt: str, width: int, height: int, seed: Any, style: str,
        negative: Any = None,
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
            negative=negative,
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

    # -- progress + cancel (C1 v0.6) -----------------------------------------

    @staticmethod
    def _emit(
        progress: Optional[Callable[[int, int, str], None]], value: int, total: int, message: str
    ) -> None:
        """Fire one phase tick; progress is best-effort and never raises."""
        if progress is None:
            return
        try:
            progress(value, total, message)
        except Exception:
            pass

    def _track_job(self, job_id: str, backend_job_id: str) -> None:
        with self._active_lock:
            self._active_backends[job_id] = backend_job_id

    def _untrack_job(self, job_id: str) -> None:
        with self._active_lock:
            self._active_backends.pop(job_id, None)

    def cancel_job(self, job_id: Any) -> Dict[str, Any]:
        """Best-effort ``POST /interrupt`` for a running job (C1 v0.6).

        Only a job whose backend submit succeeded and that has not finished
        yet can be interrupted (its backend ``prompt_id`` is still tracked).
        Finished jobs report ``status:"completed"``; unknown ids report
        ``status:"unknown"``. ComfyUI ``/interrupt`` does not synchronously
        confirm the abort — the interrupted generate/refine call fails with
        the ComfyUI error payload afterwards.
        """
        if not isinstance(job_id, str) or not job_id:
            raise ValueError(
                "INVALID_JOB_ID: job_id must be a non-empty string, got %r"
                % (job_id,)
            )
        with self._active_lock:
            backend_job_id = self._active_backends.get(job_id)
        if backend_job_id is None:
            if self._registry.get(job_id) is not None:
                return {"job_id": job_id, "cancelled": False, "status": "completed"}
            return {"job_id": job_id, "cancelled": False, "status": "unknown"}
        cancel_fn = getattr(self._backend, "cancel", None)
        if not callable(cancel_fn):
            raise BackendUnavailableError(
                "BACKEND_UNAVAILABLE: backend does not support cancel"
            )
        acknowledged = bool(cancel_fn(prompt_id=backend_job_id))
        return {
            "job_id": job_id,
            "cancelled": acknowledged,
            "status": "cancelling",
        }

    # -- shared flow pieces -------------------------------------------------

    def _write_files(
        self, files: Any, target: Path, allowed_roots: Any, allow_any_path: bool = False
    ) -> "Path":
        """Write postprocess ``files`` beside ``target``; return ``target``.

        ``filename`` leaves come from ``process()`` and are joined as
        ``output_dir / filename``. Non-leaf or jail-escaping names are
        refused with ``POLICY_DENIED`` (defense in depth: the stem came
        from a jailed path, but a hostile postprocess must not write
        outside the approved roots). An empty file list is
        ``POSTPROCESS_FAILED``. Malformed entries (non-dict, missing
        ``filename``/``png_bytes``, non-bytes ``png_bytes``, or insane
        ``width``/``height``/``scale`` when present) are
        ``POSTPROCESS_FAILED``. ``scale`` accepts the ``@Nx`` integers
        (1/2/3, byte-identical), the C3 v0.1.1 icon labels ``icon<N>``
        (``N >= 1``, size derived from ``width``/``height``), and
        ``"ico"`` for ``.ico`` entries.
        """
        if not isinstance(files, (list, tuple)) or not files:
            raise PostprocessFailedError(
                "POSTPROCESS_FAILED: postprocess returned no files"
            )
        roots = [os.path.abspath(root) for root in _root_list(allowed_roots)]
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
                or "\x00" in filename
            ):
                raise PolicyDeniedError(
                    "POLICY_DENIED: postprocess filename must be a leaf, got %r"
                    % (filename,)
                )
            if _is_reserved_device_name(filename):
                raise PolicyDeniedError(
                    "POLICY_DENIED: postprocess filename must not name a "
                    "reserved device, got %r" % (filename,)
                )
            if os.name == "nt" and ":" in filename:
                # NTFS alternate data stream ("icon.png:evil") — not a file.
                raise PolicyDeniedError(
                    "POLICY_DENIED: postprocess filename must not contain ':' "
                    "on Windows (alternate data stream), got %r" % (filename,)
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
            # C3 v0.2 SVG entries carry the ``svg`` label (no pixel size).
            _is_ico = filename.lower().endswith(".ico") or entry.get("scale") == "ico"
            for _dim in ("width", "height", "scale"):
                if _dim not in entry:
                    continue
                _val = entry[_dim]
                if _dim == "scale" and _is_ico and _val == "ico":
                    continue
                if _dim == "scale" and _val == "svg":
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
            if not allow_any_path and not any(
                _is_within(_real_key(root), _real_key(dest_abs)) for root in roots
            ):
                raise PolicyDeniedError(
                    "POLICY_DENIED: postprocess filename escapes the approved "
                    "roots, got %r" % (filename,)
                )
            try:
                self._writer(os.path.join(os.fspath(out_dir), filename), blob)
            except (OSError, ValueError) as exc:
                # Machine-readable code instead of a bare OSError/ValueError.
                raise PostprocessFailedError(
                    "POSTPROCESS_FAILED: writing %r failed: %s"
                    % (filename, exc)
                ) from exc
        return target

    @staticmethod
    def _owning_root(target: Path, allowed_roots: Any) -> Optional[str]:
        """The FIRST approved root that contains ``target`` (absolute path).

        The list is ordered: selected workspace root, default project root,
        named workspaces. ``None`` when the target is outside every
        approved root (only possible with ``--allow-any-path``).
        """
        target_key = _norm_key(os.path.abspath(os.fspath(target)))
        for root in _root_list(allowed_roots):
            if _is_within(_norm_key(root), target_key):
                return os.path.abspath(root)
        return None

    @staticmethod
    def _relative_posix(target: Path, allowed_roots: Any) -> str:
        """POSIX path of ``target`` relative to the approved root owning it.

        When the target sits outside every approved root (only possible
        with ``--allow-any-path``), the absolute path is returned as-is so
        the caller always learns the real location.
        """
        target_abs = os.path.abspath(os.fspath(target))
        owner = AssetOrchestrator._owning_root(target, allowed_roots)
        if owner is None:
            return Path(target_abs).as_posix()
        return Path(os.path.relpath(target_abs, owner)).as_posix()

    # -- public flows ----------------------------------------------------------

    def _effective_root(self, project_root: Any, workspace: Any) -> str:
        """Resolve the jail root for ``workspace`` within this call.

        ``"default"``/``None`` return the passed ``project_root``
        byte-identically; any other name resolves via
        ``config.workspace_root``. A missing config or an unknown name
        raises ``ValueError`` ``INVALID_WORKSPACE`` — always pre-backend.
        """
        if workspace is None or workspace == "default":
            return project_root
        if self._config is None:
            raise ValueError(
                "INVALID_WORKSPACE: unknown workspace %r (no named "
                "workspaces configured; see server_info workspaces)"
                % (workspace,)
            )
        return self._config.workspace_root(workspace)

    def _approved_roots(self, project_root: Any, effective_root: Any) -> list:
        """Every tree an absolute ``save_path`` may land in (C1 v0.1.5).

        Order: the selected workspace root, the default project root, then
        every named workspace. Duplicates are collapsed (case-folded on
        Windows). The set is server-side and user-approved — the agent
        picks a path inside it, never the set itself.
        """
        candidates = [effective_root, project_root]
        if self._config is not None:
            candidates.extend(self._config.project_roots.values())
        roots: list = []
        seen = set()
        for candidate in candidates:
            if candidate is None:
                continue
            root = os.path.abspath(os.fspath(candidate))
            key = _norm_key(root)
            if key not in seen:
                seen.add(key)
                roots.append(root)
        return roots

    def _allow_any_path(self) -> bool:
        """True when the server was started with ``--allow-any-path``."""
        return bool(self._config is not None and self._config.allow_any_path)

    def generate(
        self,
        validated_args: Dict[str, Any],
        project_root: Any,
        job_id: Optional[str] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Run the generate flow; return the C1 ``generate_app_asset`` output.

        ``progress`` (optional, C1 v0.6) receives ``(value, total, message)``
        phase ticks (0 submitted → 1 generating → 2 postprocessing →
        3 writing → 4 complete); it is best-effort and never raises.
        """
        if not isinstance(validated_args, dict):
            raise ValueError(
                "INVALID_ARGS: validated_args must be a dict, got %r"
                % (validated_args,)
            )
        args = validate_tool_args(
            **{k: validated_args[k] for k in _GENERATE_FIELDS if k in validated_args}
        )
        effective_root = self._effective_root(project_root, args.get("workspace"))
        approved_roots = self._approved_roots(project_root, effective_root)
        jid = job_id or args.get("job_id") or JobRegistry.new_job_id()
        stored = self._registry.get(jid)
        if stored is not None:
            return stored
        self._registry.register(jid)
        try:
            target = resolve_save_path(
                args["save_path"],
                effective_root,
                overwrite=args["overwrite"],
                allowed_roots=approved_roots,
                allow_any_path=self._allow_any_path(),
                fmt=args["format"],
            )
            self._emit(progress, 0, 4, "submitting workflow to ComfyUI")
            backend_job_id = self._submit_txt2img(
                prompt=args["prompt"],
                width=args["width"],
                height=args["height"],
                seed=args["seed"],
                style=STYLE_TO_BACKEND[args["style_preset"]],
                negative=args.get("negative"),
            )
            self._track_job(jid, backend_job_id)
            self._emit(progress, 1, 4, "generating on ComfyUI (job %s)" % backend_job_id)
            fetched = self._fetch_png_and_seed(backend_job_id)
            self._untrack_job(jid)
            seed = args["seed"]
            if seed is None:
                seed = fetched.get("seed")
            if seed is None:  # neither caller nor backend supplied one (mirrors C2)
                seed = random.randint(0, 0xFFFFFFFF)
            stem = Path(args["save_path"].replace("\\", "/")).stem
            self._emit(progress, 2, 4, "postprocessing (remove_bg, trim, exports)")
            try:
                processed = self._postprocess(
                    bytes(fetched["png_bytes"]),
                    remove_bg=args["remove_bg"],
                    model=args["remove_bg_model"],
                    trim=True,
                    sizes=(1, 2, 3),
                    stem=stem,
                    vectorize=args["format"] == "svg",
                    icon_sizes=args.get("icon_sizes"),
                    ico=args.get("ico", False),
                    seamless=args.get("seamless", False),
                    palette=args.get("palette"),
                    symmetry=args.get("symmetry"),
                )
            except (ValueError, OSError) as exc:
                # A postprocess rejection must reach the agent with a
                # machine-readable code, never as a bare ValueError/OSError
                # (Pillow raises OSError subclasses for corrupt input).
                raise PostprocessFailedError(
                    "POSTPROCESS_FAILED: postprocess rejected the request: %s"
                    % (exc,)
                ) from exc
            files = processed["files"]
            # include_image attaches the @1x PNG (the pipeline's first
            # entry) as MCP ImageContent; it exists for every format.
            # A seamless tile prefers the 2x2 preview so the caller can
            # judge the seams.
            base_png = next(
                (
                    entry.get("png_bytes")
                    for entry in files
                    if isinstance(entry, dict)
                    and entry.get("filename") == f"{stem}.png"
                ),
                None,
            )
            if args.get("seamless"):
                base_png = next(
                    (
                        entry.get("png_bytes")
                        for entry in files
                        if isinstance(entry, dict)
                        and entry.get("filename") == f"{stem}-tile.png"
                    ),
                    base_png,
                )
            if args["format"] == "svg":
                # format=svg delivers the vector asset only: the requested
                # leaf is the written file, so PNG siblings are not written.
                files = [
                    entry
                    for entry in files
                    if isinstance(entry, dict)
                    and str(entry.get("filename", "")).endswith(".svg")
                ]
                if not files:
                    raise PostprocessFailedError(
                        "POSTPROCESS_FAILED: postprocess produced no SVG entry"
                    )
            self._write_files(
                files,
                target,
                approved_roots,
                allow_any_path=self._allow_any_path(),
            )
            self._emit(progress, 3, 4, "files written, recording result")
            result = {
                "asset_path": self._relative_posix(target, approved_roots),
                "asset_path_absolute": os.fspath(target),
                "asset_root": self._owning_root(target, approved_roots),
                "width": args["width"],
                "height": args["height"],
                "format": args["format"],
                "seed": seed,
                "style_preset": args["style_preset"],
                "job_id": jid,
            }
            if args.get("include_image"):
                if base_png is None:
                    raise PostprocessFailedError(
                        "POSTPROCESS_FAILED: postprocess produced no base PNG "
                        "for include_image"
                    )
                result["image"] = _image_content(bytes(base_png))
        except McpServerError:
            self._untrack_job(jid)
            self._registry.fail(jid)
            raise
        except Exception as exc:
            self._untrack_job(jid)
            self._registry.fail(jid)
            code = getattr(exc, "code", None)
            if isinstance(code, str):
                raise translate_sibling_error(exc) from exc
            raise
        self._registry.complete(jid, result)
        self._emit(progress, 4, 4, "complete")
        return result

    def refine(
        self,
        validated_args: Dict[str, Any],
        project_root: Any,
        job_id: Optional[str] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Run the refine flow; return the C1 ``refine_asset`` output.

        Creates a NEW file; the parent is only read, never mutated.
        ``progress`` (optional, C1 v0.6) receives the same phase ticks as
        :meth:`generate`.
        """
        if not isinstance(validated_args, dict):
            raise ValueError(
                "INVALID_ARGS: validated_args must be a dict, got %r"
                % (validated_args,)
            )
        args = validate_refine_args(
            **{k: validated_args[k] for k in _REFINE_FIELDS if k in validated_args}
        )
        effective_root = self._effective_root(project_root, args.get("workspace"))
        approved_roots = self._approved_roots(project_root, effective_root)
        parent_rel, parent_abs = self._resolve_parent(args, effective_root, approved_roots)
        save_path = args["save_path"]
        if save_path is None:  # asset_id-only call: derive from the stored parent
            # Derive from the parent's ABSOLUTE location, so the refined file
            # lands NEXT TO its parent even when the parent lives in another
            # approved root (a root-relative name would resolve under the
            # selected workspace instead).
            save_path = derive_refined_save_path(
                Path(os.fspath(parent_abs)).as_posix()
            )
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
            target = resolve_save_path(
                save_path,
                effective_root,
                overwrite=False,
                allowed_roots=approved_roots,
                allow_any_path=self._allow_any_path(),
            )
            self._emit(progress, 0, 4, "submitting img2img workflow to ComfyUI")
            backend_job_id = self._submit_img2img(
                input_png_path=os.fspath(parent_abs),
                instruction=args["instruction"],
                strength=args["strength"],
            )
            self._track_job(jid, backend_job_id)
            self._emit(progress, 1, 4, "refining on ComfyUI (job %s)" % backend_job_id)
            fetched = self._fetch_png_and_seed(backend_job_id)
            self._untrack_job(jid)
            stem = Path(save_path.replace("\\", "/")).stem
            self._emit(progress, 2, 4, "postprocessing (remove_bg, exports)")
            try:
                processed = self._postprocess(
                    bytes(fetched["png_bytes"]),
                    remove_bg=args.get("remove_bg", False),
                    model=args["remove_bg_model"],
                    trim=False,
                    sizes=(1, 2, 3),
                    stem=stem,
                    vectorize=False,
                )
            except (ValueError, OSError) as exc:
                raise PostprocessFailedError(
                    "POSTPROCESS_FAILED: postprocess rejected the request: %s"
                    % (exc,)
                ) from exc
            self._write_files(
                processed["files"],
                target,
                approved_roots,
                allow_any_path=self._allow_any_path(),
            )
            self._emit(progress, 3, 4, "files written, recording result")
            result = {
                "asset_path": self._relative_posix(target, approved_roots),
                "asset_path_absolute": os.fspath(target),
                "asset_root": self._owning_root(target, approved_roots),
                "job_id": jid,
                "parent_job_id": parent_job_id,
            }
            if args.get("include_image"):
                stem = Path(save_path.replace("\\", "/")).stem
                base_png = next(
                    (
                        entry.get("png_bytes")
                        for entry in processed["files"]
                        if isinstance(entry, dict)
                        and entry.get("filename") == f"{stem}.png"
                    ),
                    None,
                )
                if base_png is None:
                    raise PostprocessFailedError(
                        "POSTPROCESS_FAILED: postprocess produced no base PNG "
                        "for include_image"
                    )
                result["image"] = _image_content(bytes(base_png))
        except McpServerError:
            self._untrack_job(jid)
            self._registry.fail(jid)
            raise
        except Exception as exc:
            self._untrack_job(jid)
            self._registry.fail(jid)
            code = getattr(exc, "code", None)
            if isinstance(code, str):
                raise translate_sibling_error(exc) from exc
            raise
        self._registry.complete(jid, result)
        self._emit(progress, 4, 4, "complete")
        return result

    def _resolve_parent(
        self, args: Dict[str, Any], project_root: Any, approved_roots: Any = None
    ) -> Any:
        """Resolve the refine parent to ``(posix_rel, abs_path)`` inside the jail.

        ``asset_path`` inputs must exist (missing -> ``ValueError``);
        ``asset_id`` inputs resolve through the registry's stored results.
        An absolute ``asset_path`` is honoured when it lands inside an
        approved root (C1 v0.1.5).
        """
        roots = list(approved_roots or []) + [project_root]
        if args["asset_path"] is not None:
            parent_abs = resolve_save_path(
                args["asset_path"],
                project_root,
                overwrite=True,
                allowed_roots=roots,
                allow_any_path=self._allow_any_path(),
            )
            if not parent_abs.is_file():
                raise ValueError(
                    "INVALID_ASSET_PATH: no asset file at %r"
                    % (args["asset_path"],)
                )
            return self._relative_posix(parent_abs, roots), parent_abs
        stored = self._registry.get(args["asset_id"])
        if not isinstance(stored, dict) or not stored.get("asset_path"):
            raise ValueError(
                "INVALID_ASSET_REF: unknown asset_id %r" % (args["asset_id"],)
            )
        # Prefer the absolute location: the stored relative path is relative
        # to the root that owned it, which may not be the selected workspace
        # (multi-root deployments) — re-resolving it there would miss.
        parent_ref = stored.get("asset_path_absolute") or stored["asset_path"]
        parent_abs = resolve_save_path(
            parent_ref,
            project_root,
            overwrite=True,
            allowed_roots=roots,
            allow_any_path=self._allow_any_path(),
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
        — never raises. ``allow_any_path`` reports whether the server was
        started with ``--allow-any-path`` (absolute paths outside every
        approved root are then accepted).
        """
        cfg = self._config
        url = cfg.comfyui_url if cfg is not None else DEFAULT_COMFYUI_URL
        version = cfg.version if cfg is not None else SERVER_VERSION
        allow_any_path = bool(cfg is not None and cfg.allow_any_path)
        if cfg is not None:
            project_root = os.path.abspath(os.fspath(cfg.project_root))
            workspaces = {"default": project_root}
            workspaces.update(cfg.project_roots)
        else:
            project_root = os.path.abspath(os.getcwd())
            workspaces = {"default": project_root}
        reachable, queue_depth = _probe_comfyui_queue(url)
        return {
            "backend": "comfyui",
            "comfyui_url": url,
            "models": list(SERVER_MODELS),
            "version": version,
            "project_root": project_root,
            "workspaces": workspaces,
            "allow_any_path": allow_any_path,
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
