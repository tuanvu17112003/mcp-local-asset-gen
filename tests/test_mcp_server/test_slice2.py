"""Slice 2 tests: registry + orchestration + error mapping.

Fakes only: stub backend (canned job_id + canned PNG bytes, plus
per-sibling-code error fakes), stub postprocess (canned ``process()``
echo). No network, no model downloads, no ``fastmcp`` import.
``tmp_path`` is the project root (pathlib).
"""

from __future__ import annotations

import os

import pytest

from src.mcp_server.config import ServerConfig
from src.mcp_server.errors import (
    BackendUnavailableError,
    GenerationFailedError,
    ModelMissingError,
    PolicyDeniedError,
    PostprocessFailedError,
    QueuedError,
)
from src.mcp_server.orchestrator import AssetOrchestrator
from src.mcp_server.registry import JobRegistry
from src.mcp_server.validation import (
    DEFAULT_REFINE_STRENGTH,
    derive_refined_save_path,
    validate_refine_args,
)

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes-no-decode-needed"


class SiblingError(Exception):
    """Fake sibling (C2/C3) error carrying a machine-readable ``.code``."""

    def __init__(self, code, message="boom"):
        super().__init__("[%s] %s" % (code, message))
        self.code = code
        self.job_id = None


class FakeBackend:
    """Stub backend: canned job_id + canned PNG bytes, call recording."""

    def __init__(self, png_bytes=FAKE_PNG, seed=7):
        self.png_bytes = png_bytes
        self.seed = seed
        self.txt2img_calls = []
        self.img2img_calls = []
        self.fetch_calls = []
        self._n = 0

    def submit_txt2img(self, *, prompt, width, height, seed=None, style=None):
        self.txt2img_calls.append(
            {"prompt": prompt, "width": width, "height": height,
             "seed": seed, "style": style}
        )
        self._n += 1
        return "fake-txt2img-%d" % self._n

    def submit_img2img(self, *, input_png_path, instruction, strength=0.6):
        self.img2img_calls.append(
            {"input_png_path": input_png_path, "instruction": instruction,
             "strength": strength}
        )
        self._n += 1
        return "fake-img2img-%d" % self._n

    def fetch_result(self, job_id):
        self.fetch_calls.append(job_id)
        return {
            "png_bytes": self.png_bytes,
            "width": 512,
            "height": 512,
            "seed": self.seed,
            "model_id": "flux-schnell-gguf-q4",
        }


class SubmitErrorBackend(FakeBackend):
    """Fake backend whose submit raises a sibling-coded error."""

    def __init__(self, code):
        super().__init__()
        self.code = code

    def submit_txt2img(self, **kwargs):
        raise SiblingError(self.code)

    def submit_img2img(self, **kwargs):
        raise SiblingError(self.code)


class FetchErrorBackend(FakeBackend):
    """Fake backend whose fetch_result raises a sibling-coded error."""

    def __init__(self, code):
        super().__init__()
        self.code = code

    def fetch_result(self, job_id):
        raise SiblingError(self.code)


class HelperStyleBackend:
    """ComfyClient-shaped fake: ``submit`` + ``fetch_result``, no stub submits.

    Exercises the orchestrator's thin-helper path (real C2
    ``submit_txt2img`` param building offline; no HTTP).
    """

    def __init__(self, png_bytes=FAKE_PNG, seed=11):
        self.png_bytes = png_bytes
        self.seed = seed
        self.submits = []

    def submit(self, prompt_dict, client_id=None):
        assert isinstance(prompt_dict, dict) and "4" in prompt_dict
        self.submits.append(prompt_dict)
        return "helper-job-1"

    def fetch_result(self, job_id):
        assert job_id == "helper-job-1"
        return {"png_bytes": self.png_bytes, "seed": self.seed}


def make_process(calls, error_code=None):
    """Canned ``process()`` echo honouring ``stem``/``sizes``."""

    def fake_process(png_bytes, **kwargs):
        calls.append(kwargs)
        if error_code is not None:
            raise SiblingError(error_code)
        stem = kwargs.get("stem", "icon")
        sizes = kwargs.get("sizes", (1, 2, 3))
        files = [
            {
                "filename": "%s.png" % stem if s == 1 else "%s@%dx.png" % (stem, s),
                "width": 8 * s,
                "height": 8 * s,
                "scale": s,
                "png_bytes": png_bytes,
            }
            for s in sizes
        ]
        return {"files": files, "alpha": True, "model_used": kwargs.get("model")}
    return fake_process


def make_orchestrator(backend=None, calls=None, **kwargs):
    calls = calls if calls is not None else []
    backend = backend if backend is not None else FakeBackend()
    orch = AssetOrchestrator(
        backend, postprocess=make_process(calls), **kwargs
    )
    return orch, backend, calls


def gen_args(**overrides):
    args = {
        "prompt": "cute bear avatar",
        "category": "avatar",
        "save_path": "assets/images/bear_avatar.png",
        "seed": 42,
    }
    args.update(overrides)
    return args


# -- registry -------------------------------------------------------------

def test_registry_capacity_release_and_autoid():
    reg = JobRegistry(max_concurrent=2)
    assert reg.register("a") == "a"
    assert reg.register("b") == "b"
    assert reg.active_count == 2
    with pytest.raises(QueuedError) as excinfo:
        reg.register("c")
    assert excinfo.value.code == "QUEUED"
    assert "QUEUED" in str(excinfo.value)
    reg.complete("a", {"asset_path": "x.png"})
    assert reg.get("a") == {"asset_path": "x.png"}
    assert reg.get("missing") is None
    assert reg.register("a") == "a"  # finished id needs no new slot
    assert reg.active_count == 1
    assert reg.register("c") == "c"
    reg.fail("b")
    reg.fail("c")
    assert reg.active_count == 0
    auto1 = reg.register()
    auto2 = reg.register()
    assert len(auto1) == 32 and auto1 != auto2
    int(auto1, 16)  # uuid4 hex
    with pytest.raises(ValueError, match="INVALID_MAX_CONCURRENT"):
        JobRegistry(max_concurrent=0)


# -- generate happy path ----------------------------------------------------

def test_generate_happy_path(tmp_path):
    orch, backend, calls = make_orchestrator()
    res = orch.generate(gen_args(), tmp_path)
    assert res["asset_path"] == "assets/images/bear_avatar.png"
    assert (res["width"], res["height"]) == (512, 512)
    assert res["format"] == "png"
    assert res["seed"] == 42
    assert res["style_preset"] == "flat"
    assert len(res["job_id"]) == 32
    base = tmp_path / "assets" / "images" / "bear_avatar.png"
    assert base.read_bytes() == FAKE_PNG
    assert (tmp_path / "assets" / "images" / "bear_avatar@2x.png").read_bytes() == FAKE_PNG
    assert (tmp_path / "assets" / "images" / "bear_avatar@3x.png").read_bytes() == FAKE_PNG
    assert len(backend.txt2img_calls) == 1
    assert backend.txt2img_calls[0]["prompt"] == "cute bear avatar"
    assert backend.txt2img_calls[0]["style"] == "flat"
    assert len(calls) == 1
    assert calls[0]["remove_bg"] is True  # avatar default
    assert calls[0]["model"] == "u2net"
    assert calls[0]["stem"] == "bear_avatar"
    assert calls[0]["sizes"] == (1, 2, 3)
    assert calls[0]["vectorize"] is False


@pytest.mark.parametrize(
    "preset,backend_style",
    [("flat", "flat"), ("clay", "3d-clay"),
     ("line", "minimal-line"), ("pixel", "pixel-art")],
)
def test_style_preset_mapping(tmp_path, preset, backend_style):
    orch, backend, _ = make_orchestrator()
    orch.generate(gen_args(style_preset=preset), tmp_path)
    assert backend.txt2img_calls[0]["style"] == backend_style


def test_generate_seed_fallback_when_backend_silent(tmp_path):
    orch, _, _ = make_orchestrator(backend=FakeBackend(seed=None))
    res = orch.generate(gen_args(seed=None), tmp_path)
    assert isinstance(res["seed"], int) and res["seed"] >= 0


def test_generate_via_c2_thin_helpers(tmp_path):
    """ComfyClient-shaped backend routes through real C2 helper building."""
    orch, backend, _ = make_orchestrator(backend=HelperStyleBackend())
    res = orch.generate(gen_args(seed=None), tmp_path)
    assert len(backend.submits) == 1  # one injected prompt dict, never raw submit
    assert res["asset_path"] == "assets/images/bear_avatar.png"
    assert res["seed"] == 11  # caller-omitted seed filled from backend meta
    assert (tmp_path / "assets" / "images" / "bear_avatar.png").exists()


# -- idempotency + QUEUED -----------------------------------------------------

def test_idempotency_same_job_id_no_rerun(tmp_path):
    orch, backend, _ = make_orchestrator()
    first = orch.generate(gen_args(), tmp_path, job_id="job-1")
    second = orch.generate(gen_args(), tmp_path, job_id="job-1")
    assert second == first
    assert second["asset_path"] == first["asset_path"]
    assert len(backend.txt2img_calls) == 1  # no second backend run
    assert len(backend.fetch_calls) == 1


def test_queued_beyond_two_concurrent(tmp_path):
    reg = JobRegistry(max_concurrent=2)
    reg.register("hold-1")
    reg.register("hold-2")
    orch, backend, _ = make_orchestrator(registry=reg)
    with pytest.raises(QueuedError) as excinfo:
        orch.generate(gen_args(save_path="assets/q.png"), tmp_path)
    assert excinfo.value.code == "QUEUED"
    assert backend.txt2img_calls == []  # slot refused before any backend call
    assert list(tmp_path.rglob("*")) == []
    reg.fail("hold-1")
    reg.fail("hold-2")
    res = orch.generate(gen_args(save_path="assets/q.png"), tmp_path)
    assert res["asset_path"] == "assets/q.png"


def test_overwrite_refused_without_flag(tmp_path):
    orch, backend, _ = make_orchestrator()
    orch.generate(gen_args(save_path="assets/once.png"), tmp_path, job_id="job-a")
    with pytest.raises(PolicyDeniedError):
        orch.generate(gen_args(save_path="assets/once.png"), tmp_path, job_id="job-b")
    assert len(backend.txt2img_calls) == 1


# -- error mapping ------------------------------------------------------------

@pytest.mark.parametrize(
    "code,cls,c1",
    [
        ("COMFY_UNREACHABLE", BackendUnavailableError, "BACKEND_UNAVAILABLE"),
        ("MODEL_NOT_FOUND", ModelMissingError, "MODEL_MISSING"),
        ("JOB_FAILED", GenerationFailedError, "GENERATION_FAILED"),
        ("JOB_TIMEOUT", GenerationFailedError, "GENERATION_FAILED"),
        ("QUEUE_FULL", QueuedError, "QUEUED"),
    ],
)
def test_backend_submit_error_mapping(tmp_path, code, cls, c1):
    orch, _, _ = make_orchestrator(backend=SubmitErrorBackend(code))
    with pytest.raises(cls) as excinfo:
        orch.generate(gen_args(save_path="assets/e.png"), tmp_path, job_id="job-e1")
    assert excinfo.value.code == c1
    assert c1 in str(excinfo.value)
    assert list(tmp_path.rglob("*")) == []
    assert orch._registry.active_count == 0
    assert orch._registry.get("job-e1") is None


def test_backend_fetch_error_mapping(tmp_path):
    orch, _, _ = make_orchestrator(backend=FetchErrorBackend("JOB_FAILED"))
    with pytest.raises(GenerationFailedError) as excinfo:
        orch.generate(gen_args(save_path="assets/e.png"), tmp_path, job_id="job-e2")
    assert excinfo.value.code == "GENERATION_FAILED"
    assert orch._registry.active_count == 0


@pytest.mark.parametrize(
    "code",
    ["DECODE_FAILED", "SEGMENTATION_FAILED", "LICENSE_REQUIRED", "VECTORIZE_FAILED"],
)
def test_postprocess_error_mapping(tmp_path, code):
    backend = FakeBackend()
    proc_calls = []
    orch = AssetOrchestrator(
        backend, postprocess=make_process(proc_calls, error_code=code)
    )
    with pytest.raises(PostprocessFailedError) as excinfo:
        orch.generate(gen_args(save_path="assets/e.png"), tmp_path, job_id="job-e3")
    assert excinfo.value.code == "POSTPROCESS_FAILED"
    assert "POSTPROCESS_FAILED" in str(excinfo.value)
    assert list(tmp_path.rglob("*")) == []
    assert orch._registry.active_count == 0


# -- path escape end-to-end -----------------------------------------------------

def test_path_escape_end_to_end(tmp_path):
    orch, backend, _ = make_orchestrator()
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(gen_args(save_path="../../etc/pass.png"), tmp_path)
    assert excinfo.value.code == "POLICY_DENIED"
    assert backend.txt2img_calls == []
    assert list(tmp_path.rglob("*")) == []  # no file written anywhere


# -- refine ----------------------------------------------------------------------

def test_refine_creates_new_file_parent_untouched(tmp_path):
    orch, backend, _ = make_orchestrator()
    parent = orch.generate(
        gen_args(save_path="assets/parent.png"), tmp_path, job_id="parent-1"
    )
    parent_base = tmp_path / "assets" / "parent.png"
    before = parent_base.read_bytes()
    res = orch.refine(
        {
            "asset_path": "assets/parent.png",
            "instruction": "add a tiny hat",
            "save_path": "assets/parent_hat.png",
            "strength": 0.8,
        },
        tmp_path,
        job_id="ref-1",
    )
    assert res == {
        "asset_path": "assets/parent_hat.png",
        "asset_path_absolute": os.fspath(tmp_path / "assets" / "parent_hat.png"),
        "asset_root": os.path.abspath(os.fspath(tmp_path)),
        "job_id": "ref-1",
        "parent_job_id": "parent-1",  # reverse-looked-up from stored generate
    }
    assert parent["job_id"] == "parent-1"
    assert parent_base.read_bytes() == before  # parent never mutated
    assert (tmp_path / "assets" / "parent_hat.png").read_bytes() == FAKE_PNG
    assert (tmp_path / "assets" / "parent_hat@2x.png").exists()
    assert len(backend.img2img_calls) == 1
    call = backend.img2img_calls[0]
    assert call["input_png_path"] == os.fspath(parent_base)
    assert os.path.isabs(call["input_png_path"])
    assert call["instruction"] == "add a tiny hat"
    assert call["strength"] == 0.8


def test_refine_defaults_derived_sibling_and_strength(tmp_path):
    orch, backend, calls = make_orchestrator()
    orch.generate(gen_args(save_path="assets/p2.png"), tmp_path, job_id="p2")
    res = orch.refine({"asset_path": "assets/p2.png", "instruction": "warmer"}, tmp_path)
    assert res["asset_path"] == "assets/p2_refined.png"
    assert res["parent_job_id"] == "p2"
    assert backend.img2img_calls[0]["strength"] == DEFAULT_REFINE_STRENGTH == 0.6
    assert calls[-1]["remove_bg"] is False  # finished parent composition preserved


def test_refine_by_asset_id(tmp_path):
    orch, backend, _ = make_orchestrator()
    orch.generate(gen_args(save_path="assets/p3.png"), tmp_path, job_id="p3")
    res = orch.refine(
        {"asset_id": "p3", "instruction": "cooler", "save_path": "assets/p3b.png"},
        tmp_path,
    )
    assert res["parent_job_id"] == "p3"
    assert res["asset_path"] == "assets/p3b.png"
    with pytest.raises(ValueError, match="INVALID_ASSET_REF"):
        orch.refine({"asset_id": "nope", "instruction": "x"}, tmp_path)
    with pytest.raises(ValueError, match="INVALID_ASSET_PATH"):
        orch.refine(
            {"asset_path": "assets/ghost.png", "instruction": "x"}, tmp_path
        )


# -- validate_refine_args units ---------------------------------------------------

def test_validate_refine_args_units():
    args = validate_refine_args(asset_path="a/b.png", instruction="do it")
    assert args["strength"] == 0.6
    assert args["save_path"] == "a/b_refined.png"
    assert validate_refine_args(
        asset_id="j1", instruction="do it", save_path="x/y.png", strength=1
    )["strength"] == 1.0
    assert derive_refined_save_path("icon.png") == "icon_refined.png"
    assert (
        derive_refined_save_path("assets/images/bear_avatar.png")
        == "assets/images/bear_avatar_refined.png"
    )
    with pytest.raises(ValueError, match="INVALID_ASSET_REF"):
        validate_refine_args(instruction="do it")
    with pytest.raises(ValueError, match="INVALID_ASSET_REF"):
        validate_refine_args(asset_id="", instruction="do it")
    with pytest.raises(ValueError, match="INVALID_INSTRUCTION"):
        validate_refine_args(asset_path="a/b.png", instruction="  ")
    for bad in (0, -0.1, 1.5, True, "0.6", None):
        with pytest.raises(ValueError, match="INVALID_STRENGTH"):
            validate_refine_args(asset_path="a/b.png", instruction="x", strength=bad)
    with pytest.raises(PolicyDeniedError):
        validate_refine_args(asset_path="../../etc/pass.png", instruction="x")
    # C1 v0.1.5: an absolute save_path is a valid shape (containment is
    # checked later by resolve_save_path), not a syntax error.
    assert (
        validate_refine_args(
            asset_path="a/b.png", instruction="x", save_path="/abs/evil.png"
        )["save_path"]
        == "/abs/evil.png"
    )
    with pytest.raises(ValueError, match="INVALID_JOB_ID"):
        validate_refine_args(asset_path="a/b.png", instruction="x", job_id="")


# -- server_info ---------------------------------------------------------------------

def test_server_info_shape(tmp_path, monkeypatch):
    import src.mcp_server.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_probe_comfyui_queue", lambda url: (True, 0))
    orch, _, _ = make_orchestrator()
    assert orch.server_info() == {
        "backend": "comfyui",
        "comfyui_url": "http://127.0.0.1:8188",
        "models": ["flux-schnell-gguf-q4", "flux-schnell-fp8"],
        "version": "0.1.0",
        "project_root": os.path.abspath(os.getcwd()),
        "workspaces": {"default": os.path.abspath(os.getcwd())},
        "allow_any_path": False,
        "reachable": True,
        "queue_depth": 0,
    }
    cfg = ServerConfig(
        project_root=str(tmp_path), comfyui_url="http://127.0.0.1:8188"
    )
    orch2, _, _ = make_orchestrator()
    orch2._config = cfg
    assert orch2.server_info()["comfyui_url"] == "http://127.0.0.1:8188"
    assert orch2.server_info()["version"] == "0.1.0"
    info2 = orch2.server_info()
    assert info2["project_root"] == os.path.abspath(os.fspath(tmp_path))
    assert os.path.isabs(info2["project_root"])
