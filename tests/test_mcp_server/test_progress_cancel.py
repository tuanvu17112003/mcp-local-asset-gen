"""C1 v0.6: cancel_asset_job, phase progress ticks, remove_bg_model.

Orchestrator-level tests with fake backend/postprocess (no network, no
fastmcp), plus one MCP-surface test for the new cancel tool wiring.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


@pytest.fixture(autouse=True)
def _no_fastmcp_leak():
    """Slice3 asserts ``fastmcp not in sys.modules``; don't pollute it."""
    before = {k for k in sys.modules if k == "fastmcp" or k.startswith("fastmcp.")}
    yield
    for k in [k for k in sys.modules
              if (k == "fastmcp" or k.startswith("fastmcp.")) and k not in before]:
        del sys.modules[k]


class FakeBackend:
    def __init__(self):
        self.cancel_calls = []

    def submit_txt2img(self, **kwargs):
        return "backend-job-1"

    def submit_img2img(self, **kwargs):
        return "backend-job-2"

    def fetch_result(self, job_id):
        return {"png_bytes": FAKE_PNG, "seed": 7}

    def cancel(self, prompt_id=None, client_id=None):
        self.cancel_calls.append(prompt_id)
        return True


def fake_postprocess(png_bytes, **kwargs):
    stem = kwargs.get("stem", "icon")
    return {
        "files": [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}],
        "alpha": True,
        "model_used": kwargs.get("model", "none"),
    }


def _writer(store: dict):
    def _write(path, data: bytes) -> None:
        store[str(path)] = bytes(data)

    return _write


def _orch(**kwargs):
    from src.mcp_server.orchestrator import AssetOrchestrator

    backend = kwargs.pop("backend", None) or FakeBackend()
    return backend, AssetOrchestrator(
        backend, postprocess=fake_postprocess, writer=_writer({}), **kwargs
    )


def _gen_args(**overrides):
    from src.mcp_server.validation import validate_tool_args

    return validate_tool_args(
        prompt="bear", category="avatar", save_path="a/bear.png", **overrides
    )


# -- remove_bg_model -------------------------------------------------------


def test_remove_bg_model_default_is_u2net():
    from src.mcp_server.validation import validate_tool_args

    args = validate_tool_args(prompt="bear", category="avatar", save_path="a/bear.png")
    assert args["remove_bg_model"] == "u2net"


def test_remove_bg_model_invalid_refused():
    from src.mcp_server.validation import validate_tool_args

    with pytest.raises(ValueError, match="INVALID_REMOVE_BG_MODEL"):
        validate_tool_args(
            prompt="bear",
            category="icon",
            save_path="a/bear.png",
            remove_bg_model="bria-rmbg",
        )


def test_remove_bg_model_refine_invalid_refused():
    from src.mcp_server.validation import validate_refine_args

    with pytest.raises(ValueError, match="INVALID_REMOVE_BG_MODEL"):
        validate_refine_args(
            asset_path="p.png", instruction="x", remove_bg_model="sd-net"
        )


def test_generate_passes_remove_bg_model_to_postprocess(tmp_path):
    captured = {}

    def capturing_postprocess(png_bytes, **kwargs):
        captured.update(kwargs)
        return fake_postprocess(png_bytes, **kwargs)

    from src.mcp_server.orchestrator import AssetOrchestrator

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=capturing_postprocess, writer=_writer({})
    )
    orch.generate(_gen_args(remove_bg_model="birefnet-general"), tmp_path)
    assert captured["model"] == "birefnet-general"


def test_refine_passes_remove_bg_model_to_postprocess(tmp_path):
    (tmp_path / "p.png").write_bytes(FAKE_PNG)
    captured = {}

    def capturing_postprocess(png_bytes, **kwargs):
        captured.update(kwargs)
        return fake_postprocess(png_bytes, **kwargs)

    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_refine_args

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=capturing_postprocess, writer=_writer({})
    )
    args = validate_refine_args(
        asset_path="p.png", instruction="x", remove_bg=True,
        remove_bg_model="birefnet-general-lite",
    )
    orch.refine(args, tmp_path)
    assert captured["model"] == "birefnet-general-lite"


# -- phase progress --------------------------------------------------------


def test_generate_emits_phase_progress(tmp_path):
    ticks = []
    _, orch = _orch()
    orch.generate(_gen_args(), tmp_path, progress=lambda v, t, m: ticks.append((v, t)))
    assert [v for v, _ in ticks] == [0, 1, 2, 3, 4]
    assert all(t == 4 for _, t in ticks)


def test_refine_emits_phase_progress(tmp_path):
    (tmp_path / "p.png").write_bytes(FAKE_PNG)
    from src.mcp_server.validation import validate_refine_args

    ticks = []
    _, orch = _orch()
    args = validate_refine_args(asset_path="p.png", instruction="x")
    orch.refine(args, tmp_path, progress=lambda v, t, m: ticks.append((v, t)))
    assert [v for v, _ in ticks] == [0, 1, 2, 3, 4]


def test_progress_callback_failure_never_breaks_generation(tmp_path):
    def bad_cb(value, total, message):
        raise RuntimeError("progress sink exploded")

    _, orch = _orch()
    result = orch.generate(_gen_args(), tmp_path, progress=bad_cb)
    assert result["asset_path"].endswith("bear.png")


# -- cancel_asset_job ------------------------------------------------------


def test_cancel_unknown_job_reports_unknown():
    _, orch = _orch()
    res = orch.cancel_job("no-such-job")
    assert res == {"job_id": "no-such-job", "cancelled": False, "status": "unknown"}


def test_cancel_invalid_job_id_raises():
    _, orch = _orch()
    with pytest.raises(ValueError, match="INVALID_JOB_ID"):
        orch.cancel_job("")
    with pytest.raises(ValueError, match="INVALID_JOB_ID"):
        orch.cancel_job(None)


def test_cancel_running_job_interrupts_backend_prompt_id(tmp_path):
    release = threading.Event()
    backend = FakeBackend()
    orig_fetch = backend.fetch_result

    def blocking_fetch(job_id):
        release.wait(timeout=5)
        return orig_fetch(job_id)

    backend.fetch_result = blocking_fetch
    from src.mcp_server.orchestrator import AssetOrchestrator

    orch = AssetOrchestrator(
        backend, postprocess=fake_postprocess, writer=_writer({})
    )
    outcome = {}

    def run():
        outcome["result"] = orch.generate(_gen_args(), tmp_path)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        jid = None
        for _ in range(500):
            with orch._active_lock:
                jid = next(iter(orch._active_backends), None)
            if jid:
                break
            time.sleep(0.01)
        assert jid is not None, "job was not tracked while running"
        res = orch.cancel_job(jid)
        assert res["status"] == "cancelling"
        assert res["cancelled"] is True
        assert backend.cancel_calls == ["backend-job-1"]
    finally:
        release.set()
        thread.join(timeout=10)
    assert outcome["result"]["asset_path"].endswith("bear.png")
    # Once finished, the same cancel reports completed (no double interrupt).
    with orch._active_lock:
        assert jid not in orch._active_backends
    assert orch.cancel_job(jid)["status"] == "completed"


def test_cancel_completed_job_reports_completed(tmp_path):
    _, orch = _orch()
    result = orch.generate(_gen_args(job_id="known-job"), tmp_path)
    assert result["job_id"] == "known-job"
    res = orch.cancel_job("known-job")
    assert res == {"job_id": "known-job", "cancelled": False, "status": "completed"}


def test_cancel_backend_without_cancel_method_maps_to_backend_unavailable(tmp_path):
    release = threading.Event()

    class NoCancelBackend(FakeBackend):
        cancel = None  # attribute lookup finds None -> not callable

    backend = NoCancelBackend()
    orig_fetch = backend.fetch_result

    def blocking_fetch(job_id):
        release.wait(timeout=5)
        return orig_fetch(job_id)

    backend.fetch_result = blocking_fetch
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.errors import BackendUnavailableError

    orch = AssetOrchestrator(
        backend, postprocess=fake_postprocess, writer=_writer({})
    )
    thread = threading.Thread(
        target=lambda: orch.generate(_gen_args(), tmp_path), daemon=True
    )
    thread.start()
    try:
        jid = None
        for _ in range(500):
            with orch._active_lock:
                jid = next(iter(orch._active_backends), None)
            if jid:
                break
            time.sleep(0.01)
        assert jid, "job was not tracked while running"
        with pytest.raises(BackendUnavailableError):
            orch.cancel_job(jid)
    finally:
        release.set()
        thread.join(timeout=10)


# -- MCP surface -----------------------------------------------------------


def test_cancel_tool_over_mcp_reports_unknown_for_untracked_id():
    import asyncio

    from fastmcp import Client

    from src.mcp_server.config import ServerConfig
    from src.mcp_server.server import create_server

    async def main():
        mcp = create_server(
            config=ServerConfig(project_root="."),
            backend_factory=FakeBackend(),
            postprocess_fn=fake_postprocess,
        )
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return tools

    tools = asyncio.run(main())
    names = {t.name for t in tools}
    assert {"generate_app_asset", "refine_asset", "cancel_asset_job",
            "check_model", "server_info"} <= names
