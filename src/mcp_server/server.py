"""FastMCP server entrypoint (contract ``C1-mcp-asset-tool`` v0.1.5).

``fastmcp`` is an OPTIONAL runtime dependency: it is imported lazily
inside :func:`create_server` only, so this module (and the whole
``src.mcp_server`` package) imports cleanly where ``fastmcp`` is not
installed. :func:`create_server` raises a clear ``RuntimeError`` there
instead of an ``ImportError`` crash at module import.

Same degrade-at-call-time policy for the sibling stages: the real
``ComfyClient`` backend and the real ``process`` postprocess callable
are resolved with guarded imports. When a sibling is absent this module
still imports; the stub raises ``BACKEND_UNAVAILABLE`` /
``POSTPROCESS_FAILED`` only when a tool call actually needs it.

Python floor: this module imports on 3.10, but logs a warning below
3.11 — live diffusion/postprocess model paths need >= 3.11 while
stub/canned paths keep working.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Callable, Dict, Optional

from .config import DEFAULT_COMFYUI_URL, ServerConfig
from .errors import (
    BackendUnavailableError,
    McpServerError,
    PostprocessFailedError,
)
from .orchestrator import AssetOrchestrator

log = logging.getLogger("mcp_server.asset_gen")

if sys.version_info < (3, 11):  # pragma: no cover - env-dependent
    log.warning(
        "asset-gen: running on Python %s; live diffusion/postprocess model "
        "paths need Python >= 3.11, stub/canned paths still work.",
        ".".join(str(p) for p in sys.version_info[:3]),
    )

SERVER_NAME = "asset-gen"

#: Server-level usage guidance, exposed via the standard MCP
#: initialization mechanism (``InitializeResult.instructions``) so MCP
#: clients can place it in the agent's initial context. Clients are not
#: required to do so — the text is written to stay useful however it is
#: presented (system prompt, preamble, or on-demand reference).
SERVER_INSTRUCTIONS = """\
# asset-gen — local AI asset generation (4 tools)

Purpose: generate app assets (icons, illustrations, avatars, splash,
seamless patterns/ornaments) with a LOCAL ComfyUI + rembg pipeline. No
cloud, no uploads.

Tools — call exactly these, with these shapes:
- generate_app_asset({prompt*, category*, save_path*, width=512,
  height=512, format="png", remove_bg=null, style_preset="flat", seed=null,
  overwrite=false, job_id=null, icon_sizes=null, ico=false,
  workspace="default", include_image=false, seamless=false, palette=null,
  symmetry=null, negative=null}): text-to-image,
  then transparent PNG (+@2x/@3x) written under save_path. remove_bg defaults
  true for icon/avatar. icon_sizes e.g. [32,64] adds -32px/-64px renders;
  ico:true adds a multi-size .ico. format:"svg" traces a vector asset
  (save_path leaf must be <stem>.svg; only that file is written).
  include_image:true attaches the @1x PNG as an image block so you can
  see the result. width/height max 1024. seamless:true makes a tileable
  pattern (edge cross-fade + <stem>-tile.png 2x2 preview; pair with
  category pattern/texture + style_preset "pattern").
  palette:["#hex",…] (2-8) recolors the result to EXACT brand colors;
  symmetry "mirror-x"|"mirror-quad"|"radial:<n>" (n 2-12) enforces
  ornament symmetry.
- refine_asset({instruction*, asset_id|asset_path, save_path, strength=0.6,
  job_id=null, workspace="default", include_image=false, remove_bg=false}):
  image-to-image tweak; writes a NEW file, never mutates the
  parent (default save is <stem>_refined.png). strength is (0,1]; the
  source PNG is uploaded automatically; remove_bg:true strips the new
  background (default keeps it).
- check_model({name*, kind}): is a weight file present in a ComfyUI loader?
  kind in unet|clip|vae|checkpoint (default all). Use before generating
- server_info({}): {backend, comfyui_url, models, version, project_root,
  workspaces, allow_any_path, reachable, queue_depth}. Call FIRST: if
  reachable=false, do not call generate.

Workflow: server_info → (check_model for non-default weights) →
generate_app_asset → embed the returned asset_path in code → refine_asset
to iterate (pass seed to reproduce).

Rules: YOU choose the output path.
- save_path may be ABSOLUTE ("C:/proj/src/assets/icon.png") or relative
  ("assets/icons/icon.png"): absolute is used exactly as given, relative
  resolves under the selected workspace root.
- The leaf must be a lowercase .png file (or .svg with format:"svg") with
  a safe stem ([A-Za-z0-9._-]): the leaf names the written file, so
  "icon.webp" is refused pre-backend (POLICY_DENIED INVALID_SAVE_PATH).
- An absolute path must land inside an approved root (project_root or a
  named workspace — see server_info.workspaces), checked on the RESOLVED
  path. Windows backslashes are accepted; ".." traversal, NUL bytes,
  ':' (NTFS streams) and reserved device names (NUL, COM1, …) are not.
  --allow-any-path removes every containment check (opt-in, default off).
- The default project_root is the server's start directory (your
  workspace) unless configured otherwise — compare once via server_info.
  If your target tree is not an approved root, the human must add it
  (--workspace name=path).
- Result: asset_path (relative to asset_root), asset_path_absolute
  (exact location), asset_root (the approved root owning the file).
Existing files need overwrite:true. Refine parents must exist. At most
2 concurrent jobs (excess → QUEUED with job_id; reuse job_id for
idempotent retry).

Errors (machine-readable CODE prefix; fix the cause, don't blindly retry):
BACKEND_UNAVAILABLE (ComfyUI down);
GENERATION_FAILED (covers JOB_FAILED/JOB_TIMEOUT payloads); POLICY_DENIED
(bad path/overwrite); INVALID_* (bad args, rejected pre-backend);
POSTPROCESS_FAILED (includes LICENSE_REQUIRED: bria-rmbg is
postprocess-internal opt-in — use the default model).

Limits: localhost ComfyUI only (allow_remote opt-in); 512px default;
postprocess trims/pads and center-crops icons.
"""



def _ensure_src_on_sys_path() -> None:
    """Fallback: put the ``src/`` layout parent on ``sys.path``.

    Lets the ``import gen_backend`` / ``import postprocess`` shim style
    resolve when this file runs from a checkout without the package
    install. The package-style layout fix is tracked as CR-MCP-001;
    this fallback never raises.
    """
    here = os.path.abspath(os.path.dirname(__file__))
    src_dir = os.path.abspath(os.path.join(here, ".."))
    if os.path.basename(src_dir) == "src" and src_dir not in sys.path:
        sys.path.insert(0, os.path.dirname(src_dir))


def load_backend(config: ServerConfig) -> Any:
    """Build the real ``ComfyClient`` or a degrade-at-call-time stub.

    Never raises for a missing backend: absence degrades to a stub whose
    ``submit_*``/``fetch_result`` raise ``BACKEND_UNAVAILABLE`` when a
    tool call actually needs the backend.
    """
    try:
        try:
            from src.gen_backend.client import ComfyClient
        except ImportError:
            _ensure_src_on_sys_path()
            from gen_backend.client import ComfyClient  # type: ignore[no-redef]

        return ComfyClient(
            base_url=config.comfyui_url,
            max_wait_s=config.job_timeout_s,
            allow_remote=config.allow_remote,
        )
    except Exception as exc:  # missing dep or unreachable import layout
        log.warning("asset-gen: real backend unavailable (%s); using stub.", exc)

        class _UnavailableBackend:
            def _fail(self, what: str) -> Any:
                raise BackendUnavailableError(
                    "BACKEND_UNAVAILABLE: ComfyUI backend is not available "
                    "(%s); start ComfyUI or check the install" % (what,)
                )

            def submit_txt2img(self, **kwargs: Any) -> Any:
                return self._fail("submit_txt2img")

            def submit_img2img(self, **kwargs: Any) -> Any:
                return self._fail("submit_img2img")

            def fetch_result(self, job_id: Any) -> Any:
                return self._fail("fetch_result")

        return _UnavailableBackend()


def load_postprocess() -> Callable[..., Dict[str, Any]]:
    """Return the real ``process`` callable or a degrade-at-call-time stub.

    Never raises for a missing stage: absence degrades to a stub that
    raises ``POSTPROCESS_FAILED`` when a tool call actually needs it.
    """
    try:
        try:
            from src.postprocess.pipeline import process
        except ImportError:
            _ensure_src_on_sys_path()
            from postprocess.pipeline import process  # type: ignore[no-redef]

        return process
    except Exception as exc:
        log.warning("asset-gen: real postprocess unavailable (%s); using stub.", exc)

        def _unavailable_postprocess(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            raise PostprocessFailedError(
                "POSTPROCESS_FAILED: postprocess stage is not available "
                "(pillow/stage missing); install it to generate assets"
            )

        return _unavailable_postprocess


def _with_image_block(result):
    """Split an orchestrator result into an MCP image block + small dict.

    FastMCP converts a returned ``Image`` into a real image content
    block only when it is NOT nested inside a dict, so ``result["image"]``
    (the include_image payload) is moved into ``ToolResult.content`` —
    the structured JSON stays small (no megabytes of base64 in-band).
    """
    image = result.get("image")
    if image is None:
        return result
    from fastmcp.tools import ToolResult

    structured = {k: v for k, v in result.items() if k != "image"}
    return ToolResult(content=[image], structured_content=structured)


def create_server(
    config: Optional[ServerConfig] = None,
    backend_factory: Any = None,
    postprocess_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Any:
    """Build and return the FastMCP app (requires ``fastmcp`` installed).

    ``backend_factory`` is either a backend instance (exposing
    ``fetch_result``) or a zero-arg callable returning one; ``None``
    builds the real backend via :func:`load_backend`. ``postprocess_fn``
    defaults to :func:`load_postprocess`. Tool functions delegate to
    :class:`AssetOrchestrator` and translate :class:`McpServerError`
    into clean error strings that always carry the machine-readable
    ``CODE`` (``str(exc)`` already embeds it).
    """
    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "FastMCP is not installed: `pip install fastmcp` then rerun "
            "this server (src/mcp_server imports cleanly without it; only "
            "live serving needs it)."
        ) from exc

    if config is None:
        config = ServerConfig(project_root=os.getcwd())
        log.warning(
            "asset-gen: no ServerConfig given; falling back to cwd %r as "
            "project_root — pass an explicit ServerConfig(project_root=...) "
            "for a stable asset jail.",
            os.getcwd(),
        )
    backend = (
        backend_factory()
        if callable(backend_factory)
        and not callable(getattr(backend_factory, "fetch_result", None))
        else backend_factory
    )
    if backend is None:
        backend = load_backend(config)
    if postprocess_fn is None:
        postprocess_fn = load_postprocess()

    orchestrator = AssetOrchestrator(
        backend, postprocess=postprocess_fn, config=config
    )
    project_root = config.project_root

    mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    @mcp.tool
    def generate_app_asset(
        prompt: str,
        category: str,
        save_path: str,
        width: int = 512,
        height: int = 512,
        format: str = "png",  # noqa: A002 - contract field name
        remove_bg: Optional[bool] = None,
        style_preset: str = "flat",
        seed: Optional[int] = None,
        overwrite: bool = False,
        job_id: Optional[str] = None,
        icon_sizes: Optional[Any] = None,
        ico: bool = False,
        workspace: str = "default",
        include_image: bool = False,
        seamless: bool = False,
        palette: Optional[Any] = None,
        symmetry: Optional[str] = None,
        negative: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate an app asset with local ComfyUI + postprocessing."""
        from .validation import validate_tool_args

        try:
            args = validate_tool_args(
                prompt=prompt,
                category=category,
                save_path=save_path,
                width=width,
                height=height,
                format=format,
                remove_bg=remove_bg,
                style_preset=style_preset,
                seed=seed,
                overwrite=overwrite,
                job_id=job_id,
                icon_sizes=icon_sizes,
                ico=ico,
                workspace=workspace,
                include_image=include_image,
                seamless=seamless,
                palette=palette,
                symmetry=symmetry,
                negative=negative,
            )
            return _with_image_block(orchestrator.generate(args, project_root))
        except McpServerError as exc:
            raise RuntimeError(str(exc)) from exc

    @mcp.tool
    def refine_asset(
        instruction: str,
        asset_id: Optional[str] = None,
        asset_path: Optional[str] = None,
        save_path: Optional[str] = None,
        strength: float = 0.6,
        job_id: Optional[str] = None,
        workspace: str = "default",
        include_image: bool = False,
        remove_bg: bool = False,
    ) -> Dict[str, Any]:
        """Refine an existing asset; creates a new file, never mutates."""
        from .validation import validate_refine_args

        try:
            args = validate_refine_args(
                asset_id=asset_id,
                asset_path=asset_path,
                instruction=instruction,
                save_path=save_path,
                strength=strength,
                job_id=job_id,
                workspace=workspace,
                include_image=include_image,
                remove_bg=remove_bg,
            )
            return _with_image_block(orchestrator.refine(args, project_root))
        except McpServerError as exc:
            raise RuntimeError(str(exc)) from exc

    @mcp.tool
    def server_info() -> Dict[str, Any]:
        """Report backend reachability, ComfyUI URL, models and version."""
        return orchestrator.server_info()

    @mcp.tool
    def check_model(name: str, kind: Optional[str] = None) -> Dict[str, Any]:
        """Check whether a model file is available in a loader folder."""
        try:
            return orchestrator.check_model(name, kind)
        except McpServerError as exc:
            raise RuntimeError(str(exc)) from exc

    return mcp


def build_arg_parser() -> argparse.ArgumentParser:
    """CLI parser: stdio default, HTTP opt-in."""
    parser = argparse.ArgumentParser(
        prog="asset-gen",
        description="Local asset-gen MCP server (stdio default; --transport http opts in).",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio runs over MCP stdio (default); http serves streamable-http.",
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port for --transport http."
    )
    parser.add_argument(
        "--project-root",
        default=os.getcwd(),
        help=(
            "Asset jail root every save_path must stay inside "
            "(default: the server's launch directory, i.e. the client's "
            "workspace)."
        ),
    )
    parser.add_argument(
        "--workspace",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Named extra asset jail root (repeatable: --workspace name=path).",
    )
    parser.add_argument(
        "--allow-any-path",
        action="store_true",
        help=(
            "Allow an absolute save_path OUTSIDE every approved root "
            "(default off: absolute paths must stay inside project_root or "
            "a named workspace)."
        ),
    )
    parser.add_argument(
        "--comfyui-url",
        default=DEFAULT_COMFYUI_URL,
        help="ComfyUI base URL, localhost-only unless --allow-remote.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Opt in to a non-loopback --comfyui-url.",
    )
    return parser


def _parse_workspace_args(entries: Optional[Any]) -> Dict[str, str]:
    """Parse repeatable ``--workspace NAME=PATH`` values into a dict.

    Raises ``ValueError`` ``INVALID_PROJECT_ROOT`` on bad shape (missing
    ``=``, empty name, empty path, duplicate name, reserved ``default``);
    directory existence is enforced by :class:`ServerConfig`.
    """
    parsed: Dict[str, str] = {}
    for entry in entries or []:
        if not isinstance(entry, str) or "=" not in entry:
            raise ValueError(
                "INVALID_PROJECT_ROOT: --workspace must be NAME=PATH, got %r"
                % (entry,)
            )
        name, _, path = entry.partition("=")
        if not name:
            raise ValueError(
                "INVALID_PROJECT_ROOT: --workspace name must be non-empty, "
                "got %r" % (entry,)
            )
        if name == "default":
            raise ValueError(
                "INVALID_PROJECT_ROOT: workspace name 'default' is reserved "
                "(it maps to --project-root)"
            )
        if not path:
            raise ValueError(
                "INVALID_PROJECT_ROOT: --workspace %r path must be non-empty"
                % (name,)
            )
        if name in parsed:
            raise ValueError(
                "INVALID_PROJECT_ROOT: duplicate --workspace name %r" % (name,)
            )
        parsed[name] = path
    return parsed


def main(argv: Optional[Any] = None) -> int:
    """Parse args, wire real backend/postprocess, and run the server."""
    raw = sys.argv[1:] if argv is None else argv
    try:
        explicit_root = any(
            arg == "--project-root"
            or (isinstance(arg, str) and arg.startswith("--project-root="))
            for arg in raw
        )
    except TypeError:
        explicit_root = False
    if not explicit_root:
        log.warning(
            "asset-gen: --project-root not given; falling back to cwd %r as "
            "the asset jail (normally the client's workspace) — pass an "
            "explicit --project-root <dir> to pin a different root.",
            os.getcwd(),
        )
    args = build_arg_parser().parse_args(argv)
    config = ServerConfig(
        project_root=args.project_root,
        comfyui_url=args.comfyui_url,
        allow_remote=args.allow_remote,
        project_roots=_parse_workspace_args(args.workspace),
        allow_any_path=args.allow_any_path,
    )
    mcp = create_server(
        config,
        backend_factory=lambda: load_backend(config),
        postprocess_fn=load_postprocess(),
    )
    if args.transport == "http":
        mcp.run(transport="streamable-http", port=args.port)
    else:
        mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SERVER_INSTRUCTIONS",
    "SERVER_NAME",
    "build_arg_parser",
    "create_server",
    "load_backend",
    "load_postprocess",
    "main",
]
