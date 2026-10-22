"""Gen-10 tests: named workspaces (C1 v0.1.4).

Fakes only: stub backend (canned PNG bytes) + canned ``process()`` echo;
no network, no model downloads. ``fastmcp`` is never imported (the
``create_server`` CLI tests stub it, mirroring test_gen8.py); ``main()``
is tested with a stubbed ``create_server`` so no server ever runs.
"""

from __future__ import annotations

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


def make_postprocess(calls: list):
    def fake_postprocess(png_bytes, **kwargs):
        calls.append(kwargs)
        stem = kwargs.get("stem", "icon")
        return {
            "files": [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}],
            "alpha": True,
            "model_used": "none",
        }

    return fake_postprocess


def gen_args(**overrides):
    args = {
        "prompt": "cute bear avatar",
        "category": "avatar",
        "save_path": "assets/images/bear_avatar.png",
        "seed": 42,
    }
    args.update(overrides)
    return args


def make_dirs(base, *names):
    roots = {}
    for name in names:
        path = base / name
        path.mkdir(parents=True, exist_ok=True)
        roots[name] = str(path)
    return roots


@pytest.fixture(autouse=True)
def _no_fastmcp_leak():
    """Slice3 asserts ``fastmcp not in sys.modules``; don't pollute it."""
    before = {k for k in sys.modules if k == "fastmcp" or k.startswith("fastmcp.")}
    yield
    for k in [k for k in sys.modules
              if (k == "fastmcp" or k.startswith("fastmcp.")) and k not in before]:
        del sys.modules[k]


# -- (a) config normalization / rejection ---------------------------------------

def test_config_normalizes_relative_subdir_workspace(tmp_path, monkeypatch):
    sub = tmp_path / "alt"
    sub.mkdir()
    monkeypatch.chdir(tmp_path)
    cfg = ServerConfig(project_root=str(tmp_path), project_roots={"alt": "alt"})
    assert cfg.project_roots == {"alt": os.path.abspath("alt")}
    assert os.path.isabs(cfg.project_roots["alt"])


def test_config_rejects_file_and_missing_workspace_roots(tmp_path):
    blob = tmp_path / "file.txt"
    blob.write_bytes(b"x")
    with pytest.raises(ValueError, match="INVALID_PROJECT_ROOT"):
        ServerConfig(
            project_root=str(tmp_path), project_roots={"bad": str(blob)}
        )
    with pytest.raises(ValueError, match="INVALID_PROJECT_ROOT"):
        ServerConfig(
            project_root=str(tmp_path),
            project_roots={"ghost": str(tmp_path / "nope-missing")},
        )


def test_config_rejects_default_and_empty_workspace_names(tmp_path):
    with pytest.raises(ValueError, match="INVALID_PROJECT_ROOT"):
        ServerConfig(
            project_root=str(tmp_path), project_roots={"default": str(tmp_path)}
        )
    with pytest.raises(ValueError, match="INVALID_PROJECT_ROOT"):
        ServerConfig(
            project_root=str(tmp_path), project_roots={"": str(tmp_path)}
        )


def test_config_copies_caller_project_roots_dict(tmp_path):
    given = {"alt": str(tmp_path)}
    cfg = ServerConfig(project_root=str(tmp_path), project_roots=given)
    given["alt"] = "/elsewhere"
    given["late"] = str(tmp_path)
    assert cfg.project_roots == {"alt": os.path.abspath(os.fspath(tmp_path))}


def test_workspace_root_method(tmp_path):
    roots = make_dirs(tmp_path, "alt")
    cfg = ServerConfig(project_root=str(tmp_path), project_roots=roots)
    assert cfg.workspace_root("default") == cfg.project_root
    assert cfg.workspace_root("alt") == os.path.abspath(roots["alt"])
    with pytest.raises(ValueError, match="INVALID_WORKSPACE"):
        cfg.workspace_root("nope")


# -- (b) generate alias resolution / pre-backend rejection ---------------------

def _orch_with_workspaces(default_root, named, post_calls, backend=None):
    cfg = ServerConfig(project_root=str(default_root), project_roots=named)
    backend = backend if backend is not None else FakeBackend()
    return (
        AssetOrchestrator(
            backend, postprocess=make_postprocess(post_calls), config=cfg
        ),
        backend,
        cfg,
    )


def test_generate_named_workspace_receives_file(tmp_path):
    named = make_dirs(tmp_path, "alt")
    post_calls: list = []
    orch, backend, _ = _orch_with_workspaces(tmp_path, named, post_calls)
    res = orch.generate(gen_args(workspace="alt"), tmp_path, job_id="ws-1")
    assert res["asset_path"] == "assets/images/bear_avatar.png"
    assert (tmp_path / "alt" / "assets" / "images" / "bear_avatar.png").read_bytes() == FAKE_PNG
    assert not (tmp_path / "assets").exists()  # nothing leaked into default root
    assert len(backend.txt2img_calls) == 1
    assert len(post_calls) == 1


def test_generate_unknown_workspace_pre_backend(tmp_path):
    named = make_dirs(tmp_path, "alt")
    post_calls: list = []
    orch, backend, _ = _orch_with_workspaces(tmp_path, named, post_calls)
    with pytest.raises(ValueError, match="INVALID_WORKSPACE"):
        orch.generate(gen_args(workspace="ghost"), tmp_path, job_id="ws-e1")
    assert backend.txt2img_calls == []
    assert backend.fetch_calls == []
    assert post_calls == []
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []
    assert orch._registry.active_count == 0


def test_generate_unknown_workspace_config_none_pre_backend(tmp_path):
    post_calls: list = []
    orch = AssetOrchestrator(
        FakeBackend(), postprocess=make_postprocess(post_calls)
    )
    with pytest.raises(ValueError, match="INVALID_WORKSPACE"):
        orch.generate(gen_args(workspace="ghost"), tmp_path, job_id="ws-e2")
    assert post_calls == []
    assert list(tmp_path.rglob("*")) == []


def test_generate_default_unchanged(tmp_path):
    named = make_dirs(tmp_path, "alt")
    post_calls: list = []
    orch, backend, _ = _orch_with_workspaces(tmp_path, named, post_calls)
    omitted = orch.generate(
        gen_args(save_path="assets/omitted.png"), tmp_path, job_id="ws-d1"
    )
    explicit = orch.generate(
        gen_args(save_path="assets/explicit.png", workspace="default"),
        tmp_path,
        job_id="ws-d2",
    )
    assert omitted["asset_path"] == "assets/omitted.png"
    assert explicit["asset_path"] == "assets/explicit.png"
    assert (tmp_path / "assets" / "omitted.png").is_file()
    assert (tmp_path / "assets" / "explicit.png").is_file()
    assert not (tmp_path / "alt" / "assets").exists()


def test_generate_per_call_isolation_a_then_b(tmp_path):
    named = make_dirs(tmp_path, "wa", "wb")
    post_calls: list = []
    orch, _, _ = _orch_with_workspaces(tmp_path, named, post_calls)
    orch.generate(
        gen_args(save_path="assets/same.png", workspace="wa"), tmp_path, job_id="ws-i1"
    )
    orch.generate(
        gen_args(save_path="assets/same.png", workspace="wb"), tmp_path, job_id="ws-i2"
    )
    first = tmp_path / "wa" / "assets" / "same.png"
    second = tmp_path / "wb" / "assets" / "same.png"
    assert first.is_file() and second.is_file()
    assert first != second
    assert not (tmp_path / "assets").exists()


def test_generate_workspace_jail_still_holds(tmp_path):
    named = make_dirs(tmp_path, "alt")
    post_calls: list = []
    orch, backend, _ = _orch_with_workspaces(tmp_path, named, post_calls)
    with pytest.raises(PolicyDeniedError):
        orch.generate(
            gen_args(save_path="../../etc/pass.png", workspace="alt"),
            tmp_path,
            job_id="ws-j1",
        )
    assert backend.txt2img_calls == []
    assert [p for p in (tmp_path / "alt").rglob("*") if p.is_file()] == []


# -- (c) refine with workspace ---------------------------------------------------

def test_refine_with_workspace(tmp_path):
    named = make_dirs(tmp_path, "alt")
    post_calls: list = []
    orch, backend, _ = _orch_with_workspaces(tmp_path, named, post_calls)
    parent = orch.generate(
        gen_args(save_path="assets/parent.png", workspace="alt"),
        tmp_path,
        job_id="ws-r0",
    )
    parent_base = tmp_path / "alt" / "assets" / "parent.png"
    before = parent_base.read_bytes()
    res = orch.refine(
        {
            "asset_path": "assets/parent.png",
            "instruction": "add a tiny hat",
            "save_path": "assets/parent_hat.png",
            "strength": 0.8,
            "workspace": "alt",
        },
        tmp_path,
        job_id="ws-r1",
    )
    assert res == {
        "asset_path": "assets/parent_hat.png",
        "asset_path_absolute": os.fspath(
            tmp_path / "alt" / "assets" / "parent_hat.png"
        ),
        "asset_root": os.path.abspath(named["alt"]),
        "job_id": "ws-r1",
        "parent_job_id": "ws-r0",
    }
    assert parent["job_id"] == "ws-r0"
    assert parent_base.read_bytes() == before
    assert (tmp_path / "alt" / "assets" / "parent_hat.png").read_bytes() == FAKE_PNG
    assert not (tmp_path / "assets").exists()
    call = backend.img2img_calls[0]
    assert call["input_png_path"] == os.fspath(parent_base)
    assert os.path.isabs(call["input_png_path"])


def test_refine_unknown_workspace_pre_backend(tmp_path):
    named = make_dirs(tmp_path, "alt")
    post_calls: list = []
    orch, backend, _ = _orch_with_workspaces(tmp_path, named, post_calls)
    orch.generate(
        gen_args(save_path="assets/p.png"), tmp_path, job_id="ws-r9p"
    )
    with pytest.raises(ValueError, match="INVALID_WORKSPACE"):
        orch.refine(
            {
                "asset_path": "assets/p.png",
                "instruction": "warmer",
                "workspace": "ghost",
            },
            tmp_path,
            job_id="ws-r9",
        )
    assert backend.img2img_calls == []


# -- (d) validation units --------------------------------------------------------

def test_validate_workspace_defaults_and_rejections():
    from src.mcp_server.validation import (
        validate_refine_args,
        validate_tool_args,
    )

    assert validate_tool_args("p", "avatar", "a/b.png")["workspace"] == "default"
    assert (
        validate_refine_args(asset_path="a/b.png", instruction="x")["workspace"]
        == "default"
    )
    for bad in ("", None, 123):
        with pytest.raises(ValueError, match="INVALID_WORKSPACE"):
            validate_tool_args("p", "avatar", "a/b.png", workspace=bad)
        with pytest.raises(ValueError, match="INVALID_WORKSPACE"):
            validate_refine_args(
                asset_path="a/b.png", instruction="x", workspace=bad
            )


# -- (e) server_info workspaces map ----------------------------------------------

def test_server_info_workspaces_map(tmp_path, monkeypatch):
    import src.mcp_server.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_probe_comfyui_queue", lambda url: (True, 0))
    named = make_dirs(tmp_path, "a", "b")
    cfg = ServerConfig(project_root=str(tmp_path), project_roots=named)
    orch = AssetOrchestrator(
        FakeBackend(), postprocess=make_postprocess([]), config=cfg
    )
    info = orch.server_info()
    assert info["workspaces"] == {
        "default": os.path.abspath(os.fspath(tmp_path)),
        "a": os.path.abspath(named["a"]),
        "b": os.path.abspath(named["b"]),
    }


def test_server_info_config_none_default_only(monkeypatch):
    import src.mcp_server.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_probe_comfyui_queue", lambda url: (False, None))
    orch = AssetOrchestrator(FakeBackend(), postprocess=make_postprocess([]))
    assert orch.server_info()["workspaces"] == {
        "default": os.path.abspath(os.getcwd())
    }


# -- (f) schema shapes ------------------------------------------------------------

def test_schema_workspace_fields():
    from src.mcp_server.schemas import (
        GENERATE_APP_ASSET_SCHEMA,
        REFINE_ASSET_SCHEMA,
        SERVER_INFO_SCHEMA,
    )

    gen_props = GENERATE_APP_ASSET_SCHEMA["input_schema"]["properties"]
    assert gen_props["workspace"]["default"] == "default"
    assert gen_props["workspace"]["minLength"] == 1
    ref_props = REFINE_ASSET_SCHEMA["input_schema"]["properties"]
    assert ref_props["workspace"]["default"] == "default"
    out = SERVER_INFO_SCHEMA["output_schema"]
    assert "workspaces" in out["required"]
    assert out["properties"]["workspaces"]["type"] == "object"


# -- (g) CLI parsing ---------------------------------------------------------------

def test_cli_workspace_forms_land_in_config(tmp_path, monkeypatch):
    import src.mcp_server.server as server

    seen: dict = {}

    class FakeMCP:
        def run(self, *args, **kwargs) -> None:
            pass

    def fake_create_server(config, backend_factory=None, postprocess_fn=None):
        seen["config"] = config
        return FakeMCP()

    monkeypatch.setattr(server, "create_server", fake_create_server)
    named = make_dirs(tmp_path, "a", "b")
    assert (
        server.main(
            [
                "--project-root", str(tmp_path),
                "--workspace", "a=%s" % named["a"],
                "--workspace=b=%s" % named["b"],
            ]
        )
        == 0
    )
    assert seen["config"].project_roots == {
        "a": os.path.abspath(named["a"]),
        "b": os.path.abspath(named["b"]),
    }


@pytest.mark.parametrize(
    "flags",
    [
        ["--workspace", "missing-equals"],
        ["--workspace", "=empty-name"],
        ["--workspace", "empty-path="],
        ["--workspace", "default=/tmp"],
        ["--workspace", "dup=/tmp", "--workspace", "dup=/tmp"],
    ],
)
def test_cli_bad_workspace_shapes_rejected(tmp_path, monkeypatch, flags):
    import src.mcp_server.server as server

    class FakeMCP:
        def run(self, *args, **kwargs) -> None:
            pass  # pragma: no cover - must never run on bad shape

    monkeypatch.setattr(
        server, "create_server", lambda *a, **k: FakeMCP()
    )
    argv = ["--project-root", str(tmp_path), *[
        f.replace("/tmp", str(tmp_path)) for f in flags
    ]]
    with pytest.raises(ValueError, match="INVALID_PROJECT_ROOT"):
        server.main(argv)
