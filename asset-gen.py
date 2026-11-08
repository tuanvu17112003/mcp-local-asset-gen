"""Foreign-cwd launcher for the asset-gen MCP server.

Run as ``<python> <root>/asset-gen.py`` from any working directory; no
PYTHONPATH setup needed. All CLI behavior lives in
``src.mcp_server.server:main``.

With no ``--project-root`` the asset jail follows the server's launch
directory — for an MCP client that is the client's workspace (your
project). Pass ``--project-root <dir>`` to pin a different tree, or
``--workspace name=<dir>`` to approve a second one.

``--selftest`` is the offline smoke test: it builds the server with stub
backend/postprocess stages (no ComfyUI, no GPU, no rembg model), asserts the
expected tool set is registered, drives one generate + one refine +
``server_info`` + ``check_model`` against a throwaway temp jail, prints a JSON
report ``{ok, tools, checks, version}`` and exits 0 on success / 1 on
failure. It never starts a transport. Any other invocation keeps the
historical behavior: delegate to ``src.mcp_server.server:main``.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.mcp_server.server import main

#: 1x1 RGBA PNG (valid decodable bytes for the offline stub render).
_STUB_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "pfZFQAAAAABJRU5ErkJggg=="
)

#: Tools the server must always register (C1 contract surface).
_EXPECTED_TOOLS = (
    "generate_app_asset",
    "refine_asset",
    "cancel_asset_job",
    "check_model",
    "server_info",
)


class _StubBackend:
    """In-memory C2 stand-in: canned job ids + a 1x1 PNG, no ComfyUI."""

    def submit_txt2img(self, **kwargs):
        return "selftest-txt2img"

    def submit_img2img(self, **kwargs):
        return "selftest-img2img"

    def fetch_result(self, job_id, **kwargs):
        return {"png_bytes": _STUB_PNG, "seed": 1234, "elapsed_s": 0.0}

    def cancel(self, prompt_id=None, client_id=None):
        return True

    def loader_files(self, loader):
        """C2 introspection shape: file-list inputs only."""
        return {"unet_name": ["selftest-model.safetensors"]}


def _stub_postprocess(png_bytes, **kwargs):
    """C3 stand-in: one base PNG entry, no Pillow/rembg work."""
    stem = kwargs.get("stem", "asset")
    return {
        "files": [{"filename": "%s.png" % (stem,), "png_bytes": bytes(png_bytes)}],
        "alpha": True,
        "model_used": "none",
    }


def _selftest() -> int:
    """Offline end-to-end smoke test; print a JSON report and return 0/1.

    Every check is recorded instead of raised: the JSON report always lists
    all checks with ``ok`` flags, so a CI log shows exactly which stage broke.
    ``fastmcp`` is required for tool serving; when it is absent the tool
    checks fail with the clear install message and the exit code is 1.
    """
    import asyncio
    import json
    import tempfile

    from src.mcp_server.config import SERVER_VERSION
    from src.mcp_server.server import create_server

    checks = []
    tools = []

    def record(name, fn):
        """Run one check and record ``{name, ok, detail}`` (never aborts)."""
        try:
            detail = fn()
            checks.append({"name": name, "ok": True, "detail": detail})
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            checks.append(
                {"name": name, "ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
            )

    def build(config):
        """Minimal FastMCP app over the stub siblings (no network, no GPU)."""
        return create_server(
            config=config,
            backend_factory=_StubBackend(),
            postprocess_fn=_stub_postprocess,
        )

    def call_tool(name, arguments):
        """Call one MCP tool through the in-process FastMCP client."""
        from fastmcp import Client

        async def _call():
            async with Client(build(config)) as client:
                result = await client.call_tool(name, arguments)
                return result.structured_content or {}

        return asyncio.run(_call())

    def check_tools():
        """The server must register exactly the expected contract tools."""
        registered = sorted(tool.name for tool in asyncio.run(build(config).list_tools()))
        tools.extend(registered)
        missing = [name for name in _EXPECTED_TOOLS if name not in registered]
        if missing:
            raise AssertionError("missing tools %r (registered %r)" % (missing, registered))
        return registered

    def check_generate():
        """generate_app_asset must land the base PNG inside the temp jail."""
        payload = call_tool(
            "generate_app_asset",
            {
                "prompt": "selftest bear icon",
                "category": "icon",
                "save_path": "selftest/icon.png",
                "width": 64,
                "height": 64,
                "remove_bg": False,
            },
        )
        asset_path = payload.get("asset_path")
        if not asset_path:
            raise AssertionError("no asset_path in %r" % (payload,))
        if not Path(payload["asset_path_absolute"]).is_file():
            raise AssertionError("asset missing at %r" % (payload["asset_path_absolute"],))
        return {"asset_path": asset_path, "seed": payload.get("seed")}

    def check_refine():
        """refine_asset must write a NEW file beside the generated parent."""
        payload = call_tool(
            "refine_asset",
            {
                "asset_path": "selftest/icon.png",
                "instruction": "warmer colors",
                "strength": 0.7,
            },
        )
        asset_path = payload.get("asset_path")
        if not asset_path:
            raise AssertionError("no asset_path in %r" % (payload,))
        if not Path(payload["asset_path_absolute"]).is_file():
            raise AssertionError("refined asset missing: %r" % (payload,))
        return {"asset_path": asset_path}

    def check_server_info():
        """server_info must answer offline and report the server version."""
        payload = call_tool("server_info", {})
        if payload.get("version") != SERVER_VERSION:
            raise AssertionError(
                "version %r != SERVER_VERSION %r" % (payload.get("version"), SERVER_VERSION)
            )
        return {"reachable": payload.get("reachable"), "version": payload.get("version")}

    def check_model():
        """check_model must resolve the stubbed loader file (no ComfyUI)."""
        payload = call_tool(
            "check_model", {"name": "selftest-model.safetensors", "kind": "unet"}
        )
        if payload.get("available") is not True:
            raise AssertionError("model not found: %r" % (payload,))
        return {"available": True, "loader": payload.get("loader")}

    with tempfile.TemporaryDirectory(prefix="asset-gen-selftest-") as root:
        from src.mcp_server.config import ServerConfig

        config = ServerConfig(project_root=root)
        record("tools", check_tools)
        record("generate_app_asset", check_generate)
        record("refine_asset", check_refine)
        record("server_info", check_server_info)
        record("check_model", check_model)

    report = {
        "ok": bool(checks) and all(check["ok"] for check in checks),
        "tools": tools,
        "checks": checks,
        "version": SERVER_VERSION,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__" and "--selftest" in sys.argv[1:]:
    raise SystemExit(_selftest())

raise SystemExit(main())
