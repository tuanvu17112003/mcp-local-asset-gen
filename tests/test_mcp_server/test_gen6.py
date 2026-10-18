"""Gen-6 tests: user-facing kind → ComfyUI loader-node mapping for check_model.

Fakes only: backend ``loader_files`` is faked with call recording (mirrors
the test_gen5.py LoaderBackend/SiblingError pattern); no network, no model
downloads, no ``fastmcp`` import.
"""

from __future__ import annotations

import pytest

from src.mcp_server.errors import BackendUnavailableError
from src.mcp_server.orchestrator import AssetOrchestrator
from src.mcp_server.schemas import CHECK_MODEL_SCHEMA
from src.mcp_server.validation import CHECK_MODEL_LOADERS, KIND_TO_LOADERS

EXPECTED_NODES = {
    "CheckpointLoaderSimple",
    "DualCLIPLoader",
    "UnetLoaderGGUF",
    "VAELoader",
}


class SiblingError(Exception):
    def __init__(self, code, message="boom"):
        super().__init__("[%s] %s" % (code, message))
        self.code = code
        self.job_id = None


class FakeBackend:
    def submit_txt2img(self, **kwargs):
        return "backend-job-1"

    def submit_img2img(self, **kwargs):
        return "backend-job-2"

    def fetch_result(self, job_id):
        return {"png_bytes": b"x", "seed": 7}


class LoaderBackend(FakeBackend):
    """Fake backend with a ``loader_files`` map + call recording."""

    def __init__(self, files_map, **kwargs):
        super().__init__(**kwargs)
        self._files_map = dict(files_map)
        self.loader_calls = []

    def loader_files(self, loader):
        self.loader_calls.append(loader)
        if loader not in self._files_map:
            raise SiblingError("UNKNOWN_LOADER", "no loader %r" % (loader,))
        return self._files_map[loader]


def make_orch(backend):
    return AssetOrchestrator(
        backend, postprocess=lambda b, **k: {"files": []}, writer=lambda p, d: None
    )


def test_kind_to_loaders_contract():
    assert KIND_TO_LOADERS == {
        "unet": ["UnetLoaderGGUF"],
        "clip": ["DualCLIPLoader"],
        "vae": ["VAELoader"],
        "checkpoint": ["CheckpointLoaderSimple"],
    }
    assert CHECK_MODEL_LOADERS == frozenset(KIND_TO_LOADERS)
    props = CHECK_MODEL_SCHEMA["input_schema"]["properties"]
    assert props["kind"]["enum"] == ["checkpoint", "clip", "unet", "vae"]


@pytest.mark.parametrize(
    "kind,node",
    [
        ("unet", "UnetLoaderGGUF"),
        ("clip", "DualCLIPLoader"),
        ("vae", "VAELoader"),
        ("checkpoint", "CheckpointLoaderSimple"),
    ],
)
def test_all_four_kinds_mapped(kind, node):
    backend = LoaderBackend({node: {"slot": ["hit-%s.safetensors" % kind]}})
    orch = make_orch(backend)
    out = orch.check_model("hit-%s.safetensors" % kind, kind)
    assert backend.loader_calls == [node]
    assert out["available"] is True
    assert out["loader"] == node
    assert isinstance(out["checked_at"], str) and out["checked_at"]


@pytest.mark.parametrize("bad", ["nope-loader", "checkpoints", "loras"])
def test_unknown_kind_pre_backend_no_call(bad):
    backend = LoaderBackend(
        {
            "CheckpointLoaderSimple": {"ckpt": ["a.safetensors"]},
            "DualCLIPLoader": {"clip": ["a.safetensors"]},
            "UnetLoaderGGUF": {"unet": ["a.safetensors"]},
            "VAELoader": {"vae": ["a.safetensors"]},
        }
    )
    orch = make_orch(backend)
    with pytest.raises(ValueError, match="UNKNOWN_LOADER"):
        orch.check_model("a.safetensors", bad)
    assert backend.loader_calls == []


def test_default_queries_all_four_nodes_basename_match():
    files_map = {
        "CheckpointLoaderSimple": {"ckpt": ["other.safetensors"]},
        "DualCLIPLoader": {"clip": ["other2.gguf"]},
        "UnetLoaderGGUF": {"unet": ["unrelated.gguf"]},
        "VAELoader": {"vae": ["sub/dir/deep-vae.safetensors"]},
    }
    backend = LoaderBackend(files_map)
    orch = make_orch(backend)
    out = orch.check_model("deep-vae.safetensors")
    assert set(backend.loader_calls) == EXPECTED_NODES
    assert out["available"] is True
    assert out["loader"] == "VAELoader"


def test_default_skips_per_loader_unknown_loader():
    class PartialBackend(FakeBackend):
        def loader_files(self, loader):
            if loader != "VAELoader":
                raise SiblingError("UNKNOWN_LOADER", loader)
            return {"vae": ["my-vae.safetensors"]}

    orch = make_orch(PartialBackend())
    out = orch.check_model("my-vae.safetensors")
    assert out["available"] is True
    assert out["loader"] == "VAELoader"


def test_unreachable_still_backend_unavailable():
    class UnreachableBackend(FakeBackend):
        def loader_files(self, loader):
            raise SiblingError("COMFY_UNREACHABLE", "down")

    orch = make_orch(UnreachableBackend())
    with pytest.raises(BackendUnavailableError) as excinfo:
        orch.check_model("x.safetensors", "clip")
    assert excinfo.value.code == "BACKEND_UNAVAILABLE"
    with pytest.raises(BackendUnavailableError) as excinfo2:
        orch.check_model("x.safetensors")
    assert excinfo2.value.code == "BACKEND_UNAVAILABLE"
