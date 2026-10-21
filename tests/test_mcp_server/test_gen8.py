"""Gen-8 tests: CWD-jail fix (C1 v0.1.3).

Fakes only: stub backend (canned PNG bytes) + canned ``process()`` echo;
no network, no model downloads. ``fastmcp`` IS required for the
``create_server`` fallback-path tests (present in this venv); ``main()``
is tested with a stubbed ``create_server`` so no server ever runs.
"""

from __future__ import annotations

import logging
import os
import sys

import pytest

from src.mcp_server.config import ServerConfig
from src.mcp_server.errors import PolicyDeniedError
from src.mcp_server.orchestrator import AssetOrchestrator

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes-no-decode-needed"


class FakeBackend:
    """Stub backend: canned job_id + canned PNG bytes, call recording."""

    def __init__(self, png_bytes: bytes = FAKE_PNG, seed: int = 7) -> None:
        self.png_bytes = png_bytes
        self.seed = seed
        self.txt2img_calls: list = []
        self.img2img_calls: list = []
        self.fetch_calls: list = []

    def submit_txt2img(self, **kwargs):
        self.txt2img_calls.append(kwargs)
        return "fake-txt2img-1"

    def submit_img2img(self, **kwargs):
        self.img2img_calls.append(kwargs)
        return "fake-img2img-1"

    def fetch_result(self, job_id):
        self.fetch_calls.append(job_id)
        return {"png_bytes": self.png_bytes, "seed": self.seed}


def fake_postprocess(png_bytes, **kwargs):
    stem = kwargs.get("stem", "icon")
    return {
        "files": [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}],
        "alpha": True,
        "model_used": "none",
    }


def gen_args(**overrides):
    args = {
        "prompt": "cute bear avatar",
        "category": "avatar",
        "save_path": "assets/images/bear_avatar.png",
        "seed": 42,
    }
    args.update(overrides)
    return args


@pytest.fixture(autouse=True)
def _no_fastmcp_leak():
    """Slice3 asserts ``fastmcp not in sys.modules``; don't pollute it."""
    before = {k for k in sys.modules if k == "fastmcp" or k.startswith("fastmcp.")}
    yield
    for k in [k for k in sys.modules
              if (k == "fastmcp" or k.startswith("fastmcp.")) and k not in before]:
        del sys.modules[k]


# -- (a) absolute normalization + non-directory rejection ---------------------

def test_config_normalizes_relative_subdir_to_absolute(tmp_path, monkeypatch):
    sub = tmp_path / "proj"
    sub.mkdir()
    monkeypatch.chdir(tmp_path)
    cfg = ServerConfig(project_root="proj")
    assert cfg.project_root == os.path.abspath("proj")
    assert os.path.isabs(cfg.project_root)


def test_config_normalizes_dot_to_absolute_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = ServerConfig(project_root=".")
    assert cfg.project_root == os.path.abspath(os.getcwd())
    assert os.path.isabs(cfg.project_root)


def test_config_rejects_file_path_as_root(tmp_path):
    blob = tmp_path / "file.txt"
    blob.write_bytes(b"x")
    with pytest.raises(ValueError, match="INVALID_PROJECT_ROOT"):
        ServerConfig(project_root=str(blob))


def test_config_rejects_nonexistent_path_as_root(tmp_path):
    with pytest.raises(ValueError, match="INVALID_PROJECT_ROOT"):
        ServerConfig(project_root=str(tmp_path / "nope-missing"))


# -- (b) cwd-fallback warning --------------------------------------------------

def _fallback_records(caplog):
    return [
        r
        for r in caplog.records
        if r.name == "mcp_server.asset_gen"
        and "falling back to cwd" in r.getMessage().lower()
    ]


def test_create_server_fallback_warns(caplog):
    import src.mcp_server.server as server

    with caplog.at_level(logging.WARNING, logger="mcp_server.asset_gen"):
        server.create_server(
            config=None,
            backend_factory=FakeBackend(),
            postprocess_fn=fake_postprocess,
        )
    hits = _fallback_records(caplog)
    assert hits, "expected a cwd-fallback warning from create_server(config=None)"
    assert "explicit" in hits[0].getMessage().lower()


def test_create_server_explicit_root_no_warning(caplog, tmp_path):
    import src.mcp_server.server as server

    cfg = ServerConfig(project_root=str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="mcp_server.asset_gen"):
        server.create_server(
            config=cfg,
            backend_factory=FakeBackend(),
            postprocess_fn=fake_postprocess,
        )
    assert _fallback_records(caplog) == []


def test_main_fallback_warns_and_explicit_root_silent(
    monkeypatch, caplog, tmp_path
):
    import src.mcp_server.server as server

    seen: dict = {}

    class FakeMCP:
        def run(self, *args, **kwargs) -> None:
            seen["ran"] = (args, kwargs)

    def fake_create_server(config, backend_factory=None, postprocess_fn=None):
        seen["project_root"] = config.project_root
        return FakeMCP()

    monkeypatch.setattr(server, "create_server", fake_create_server)

    with caplog.at_level(logging.WARNING, logger="mcp_server.asset_gen"):
        assert server.main([]) == 0
    assert seen.pop("ran") is not None
    hits = _fallback_records(caplog)
    assert hits, "expected a cwd-fallback warning from main([])"
    assert "explicit" in hits[0].getMessage().lower()

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="mcp_server.asset_gen"):
        assert server.main(["--project-root", str(tmp_path)]) == 0
    assert seen["project_root"] == os.path.abspath(os.fspath(tmp_path))
    assert _fallback_records(caplog) == []


def test_main_explicit_equals_form_no_warning(monkeypatch, caplog, tmp_path):
    import src.mcp_server.server as server

    class FakeMCP:
        def run(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(
        server, "create_server", lambda *a, **k: FakeMCP()
    )
    with caplog.at_level(logging.WARNING, logger="mcp_server.asset_gen"):
        assert (
            server.main(["--project-root=%s" % tmp_path]) == 0
        )
    assert _fallback_records(caplog) == []


# -- (c) project_root echoed absolute ------------------------------------------

def test_server_info_project_root_explicit_and_default(tmp_path, monkeypatch):
    import src.mcp_server.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_probe_comfyui_queue", lambda url: (True, 0))
    cfg = ServerConfig(project_root=str(tmp_path))
    assert os.path.isabs(cfg.project_root)
    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, config=cfg
    )
    assert orch.server_info()["project_root"] == os.path.abspath(
        os.fspath(tmp_path)
    )
    default_orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess
    )
    info = default_orch.server_info()
    assert info["project_root"] == os.path.abspath(os.getcwd())
    assert os.path.isabs(info["project_root"])


# -- (d) jail still holds with absolute-normalized config -----------------------

def test_jail_holds_with_absolute_config(tmp_path):
    cfg = ServerConfig(project_root=str(tmp_path))
    assert os.path.isabs(cfg.project_root)
    backend = FakeBackend()
    orch = AssetOrchestrator(backend, postprocess=fake_postprocess)

    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(gen_args(save_path="../../etc/pass.png"), cfg.project_root)
    assert excinfo.value.code == "POLICY_DENIED"
    assert backend.txt2img_calls == []
    assert list(tmp_path.rglob("*")) == []

    orch.generate(gen_args(save_path="assets/once.png"), cfg.project_root)
    with pytest.raises(PolicyDeniedError) as excinfo2:
        orch.generate(gen_args(save_path="assets/once.png"), cfg.project_root)
    assert excinfo2.value.code == "POLICY_DENIED"
    assert "overwrite" in str(excinfo2.value).lower()
