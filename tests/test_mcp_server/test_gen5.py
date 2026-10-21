"""Gen-5 tests: live server_info, check_model, icon_sizes/ico.

Fakes only: the ComfyUI ``/prompt`` probe is mocked via the orchestrator
helper; backend ``loader_files`` is faked; no network, no model downloads,
no ``fastmcp`` import. ``tmp_path`` is the project root.
"""

from __future__ import annotations

import os

import pytest

from src.mcp_server.errors import BackendUnavailableError
from src.mcp_server.orchestrator import AssetOrchestrator
from src.mcp_server.validation import validate_tool_args

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes-no-decode-needed"
FAKE_ICO = b"\x00\x00\x01\x00fake-ico-bytes"


class SiblingError(Exception):
    def __init__(self, code, message="boom"):
        super().__init__("[%s] %s" % (code, message))
        self.code = code
        self.job_id = None


class FakeBackend:
    def __init__(self, png_bytes=FAKE_PNG, seed=7):
        self.png_bytes = png_bytes
        self.seed = seed

    def submit_txt2img(self, **kwargs):
        return "backend-job-1"

    def submit_img2img(self, **kwargs):
        return "backend-job-2"

    def fetch_result(self, job_id):
        return {"png_bytes": self.png_bytes, "seed": self.seed}


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


def dict_writer(store: dict):
    def _write(path, data: bytes) -> None:
        store[str(path)] = bytes(data)

    return _write


def make_orch(backend, postprocess):
    store: dict = {}
    orch = AssetOrchestrator(
        backend, postprocess=postprocess, writer=dict_writer(store)
    )
    return orch, store


# -- server_info live probe (mocked helper) -----------------------------------

def test_server_info_reachable_path(monkeypatch):
    import src.mcp_server.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_probe_comfyui_queue", lambda url: (True, 3))
    orch, _ = make_orch(FakeBackend(), lambda b, **k: {"files": []})
    info = orch.server_info()
    assert info["backend"] == "comfyui"
    assert info["reachable"] is True
    assert info["queue_depth"] == 3
    assert info["project_root"] == os.path.abspath(os.getcwd())
    assert os.path.isabs(info["project_root"])


def test_server_info_unreachable_path(monkeypatch):
    import src.mcp_server.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_probe_comfyui_queue", lambda url: (False, None))
    orch, _ = make_orch(FakeBackend(), lambda b, **k: {"files": []})
    info = orch.server_info()
    assert info["reachable"] is False
    assert info["queue_depth"] is None
    assert info["project_root"] == os.path.abspath(os.getcwd())
    assert os.path.isabs(info["project_root"])


def test_probe_prefers_exec_info_and_never_raises(monkeypatch):
    import json
    import urllib.request

    import src.mcp_server.orchestrator as orch_mod

    class FakeResp:
        def __init__(self, payload: bytes):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self._payload

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda url, timeout=None: FakeResp(
            json.dumps({"exec_info": {"queue_remaining": 5}}).encode()
        ),
    )
    assert orch_mod._probe_comfyui_queue("http://127.0.0.1:8188") == (True, 5)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda url, timeout=None: FakeResp(
            json.dumps({"queue_remaining": 2}).encode()
        ),
    )
    assert orch_mod._probe_comfyui_queue("http://127.0.0.1:8188") == (True, 2)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda url, timeout=None: FakeResp(json.dumps({"ok": True}).encode()),
    )
    # JSON ok but no recognizable count -> documented 0 fallback.
    assert orch_mod._probe_comfyui_queue("http://127.0.0.1:8188") == (True, 0)

    def _boom(url, timeout=None):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert orch_mod._probe_comfyui_queue("http://127.0.0.1:8188") == (False, None)


# -- check_model ----------------------------------------------------------------

def test_check_model_found_explicit_kind():
    backend = LoaderBackend(
        {"CheckpointLoaderSimple": {"ckpt": ["flux/model.safetensors", "other.gguf"]}}
    )
    orch, _ = make_orch(backend, lambda b, **k: {"files": []})
    out = orch.check_model("model.safetensors", "checkpoint")
    assert out["available"] is True
    assert out["loader"] == "CheckpointLoaderSimple"
    assert isinstance(out["checked_at"], str) and out["checked_at"]


def test_check_model_found_basename_and_default_all():
    backend = LoaderBackend({"UnetLoaderGGUF": {"unet": ["sub/dir/cool-lora.safetensors"]}})
    orch, _ = make_orch(backend, lambda b, **k: {"files": []})
    out = orch.check_model("cool-lora.safetensors")
    assert out == {
        "available": True,
        "loader": "UnetLoaderGGUF",
        "checked_at": out["checked_at"],
    }


def test_check_model_missing():
    backend = LoaderBackend({"CheckpointLoaderSimple": {"ckpt": ["a.safetensors"]}})
    orch, _ = make_orch(backend, lambda b, **k: {"files": []})
    out = orch.check_model("ghost.safetensors", "checkpoint")
    assert out["available"] is False
    assert out["loader"] is None
    assert isinstance(out["checked_at"], str)


def test_check_model_unknown_kind_pre_backend_no_call():
    backend = LoaderBackend({"checkpoints": {"ckpt": ["a.safetensors"]}})
    orch, _ = make_orch(backend, lambda b, **k: {"files": []})
    with pytest.raises(ValueError, match="UNKNOWN_LOADER"):
        orch.check_model("a.safetensors", "nope-loader")
    assert backend.loader_calls == []


def test_check_model_invalid_name():
    backend = LoaderBackend({})
    orch, _ = make_orch(backend, lambda b, **k: {"files": []})
    with pytest.raises(ValueError, match="INVALID_MODEL_NAME"):
        orch.check_model("")
    with pytest.raises(ValueError, match="INVALID_MODEL_NAME"):
        orch.check_model(None)


def test_check_model_unreachable_becomes_backend_unavailable():
    class UnreachableBackend(FakeBackend):
        def loader_files(self, loader):
            raise SiblingError("COMFY_UNREACHABLE", "down")

    orch, _ = make_orch(UnreachableBackend(), lambda b, **k: {"files": []})
    with pytest.raises(BackendUnavailableError) as excinfo:
        orch.check_model("x.safetensors", "checkpoint")
    assert excinfo.value.code == "BACKEND_UNAVAILABLE"


def test_check_model_default_all_skips_unknown_loader():
    class PartialBackend(FakeBackend):
        def loader_files(self, loader):
            if loader != "VAELoader":
                raise SiblingError("UNKNOWN_LOADER", loader)
            return {"vae": ["my-vae.safetensors"]}

    orch, _ = make_orch(PartialBackend(), lambda b, **k: {"files": []})
    out = orch.check_model("my-vae.safetensors")
    assert out["available"] is True
    assert out["loader"] == "VAELoader"


def test_check_model_no_loader_files_is_unavailable():
    orch, _ = make_orch(FakeBackend(), lambda b, **k: {"files": []})
    with pytest.raises(BackendUnavailableError):
        orch.check_model("x.safetensors")


# -- icon_sizes / ico validation -------------------------------------------------

@pytest.mark.parametrize("bad", ["16", 16, {"a": 1}, True, 16.0])
def test_icon_sizes_non_list_rejected(bad):
    with pytest.raises(ValueError, match="INVALID_ICON_SIZES"):
        validate_tool_args("p", "icon", "a/b.png", icon_sizes=bad)


@pytest.mark.parametrize("bad", [True, "16", 16.5, None])
def test_icon_sizes_non_int_element_rejected(bad):
    with pytest.raises(ValueError, match="INVALID_ICON_SIZES"):
        validate_tool_args("p", "icon", "a/b.png", icon_sizes=[16, bad])


@pytest.mark.parametrize("bad", [0, -1, -16])
def test_icon_sizes_zero_negative_rejected(bad):
    with pytest.raises(ValueError, match="INVALID_ICON_SIZES"):
        validate_tool_args("p", "icon", "a/b.png", icon_sizes=[bad])


def test_icon_sizes_over_512_rejected():
    with pytest.raises(ValueError, match="INVALID_ICON_SIZES"):
        validate_tool_args("p", "icon", "a/b.png", icon_sizes=[513])


def test_icon_sizes_oversize_vs_max_dim_rejected():
    with pytest.raises(ValueError, match="INVALID_ICON_SIZES"):
        validate_tool_args(
            "p", "icon", "a/b.png", width=64, height=64, icon_sizes=[128]
        )


def test_icon_sizes_empty_list_is_valid_noop():
    args = validate_tool_args("p", "icon", "a/b.png", icon_sizes=[])
    assert args["icon_sizes"] == []


def test_icon_sizes_valid_and_ico_flag():
    args = validate_tool_args("p", "icon", "a/b.png", icon_sizes=[16, 32], ico=True)
    assert args["icon_sizes"] == [16, 32]
    assert args["ico"] is True
    args2 = validate_tool_args("p", "icon", "a/b.png")
    assert args2["icon_sizes"] is None
    assert args2["ico"] is False


def test_ico_non_bool_rejected():
    with pytest.raises(ValueError, match="INVALID_ICO"):
        validate_tool_args("p", "icon", "a/b.png", ico="yes")
    with pytest.raises(ValueError, match="INVALID_ICO"):
        validate_tool_args("p", "icon", "a/b.png", ico=1)


# -- generate passthrough incl .ico entry on the png_bytes key -------------------

def test_generate_passthrough_icon_files_and_ico(tmp_path):
    seen: dict = {}

    def fake_process(png_bytes, **kwargs):
        seen.update(kwargs)
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
        for n in kwargs.get("icon_sizes") or []:
            files.append(
                {
                    "filename": "%s-%dpx.png" % (stem, n),
                    "width": n,
                    "height": n,
                    "scale": "icon%d" % n,
                    "png_bytes": png_bytes,
                }
            )
        if kwargs.get("ico"):
            # Postprocess gen-5 reuses the png_bytes key for ICO bytes.
            files.append(
                {"filename": "%s.ico" % stem, "scale": "ico", "png_bytes": FAKE_ICO}
            )
        return {"files": files, "alpha": True, "model_used": "none"}

    # Default disk writer: files must join into the saved tree on disk.
    orch = AssetOrchestrator(FakeBackend(), postprocess=fake_process)
    args = validate_tool_args(
        "bear", "avatar", "assets/bear.png", icon_sizes=[16], ico=True
    )
    res = orch.generate(args, tmp_path, job_id="gen5-ico")
    assert res["asset_path"] == "assets/bear.png"
    assert seen["icon_sizes"] == [16]
    assert seen["ico"] is True
    assert seen["sizes"] == (1, 2, 3)
    base = tmp_path / "assets"
    assert (base / "bear.png").read_bytes() == FAKE_PNG
    assert (base / "bear-16px.png").read_bytes() == FAKE_PNG
    assert (base / "bear.ico").read_bytes() == FAKE_ICO
