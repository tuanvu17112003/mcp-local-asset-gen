"""FastMCP server entrypoint (contract ``C1-mcp-asset-tool`` v0.1.0).

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

    mcp = FastMCP(SERVER_NAME)

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
            )
            return orchestrator.generate(args, project_root)
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
            )
            return orchestrator.refine(args, project_root)
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
        help="Asset jail root every save_path must stay inside (default: cwd).",
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


def main(argv: Optional[Any] = None) -> int:
    """Parse args, wire real backend/postprocess, and run the server."""
    args = build_arg_parser().parse_args(argv)
    config = ServerConfig(
        project_root=args.project_root,
        comfyui_url=args.comfyui_url,
        allow_remote=args.allow_remote,
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
    "SERVER_NAME",
    "build_arg_parser",
    "create_server",
    "load_backend",
    "load_postprocess",
    "main",
]
