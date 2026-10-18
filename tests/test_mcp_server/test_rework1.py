"""Rework-1 tests: M3 refine discriminators + L7 UNKNOWN_WORKFLOW.

Fakes only: stub backend/postprocess, ``tmp_path`` as project root.
No network, no model downloads, no ``fastmcp`` import.
"""

from __future__ import annotations

import pytest

from src.mcp_server.errors import (
    GenerationFailedError,
    PolicyDeniedError,
    QueuedError,
    error_class_for_sibling_code,
)
from src.mcp_server.orchestrator import AssetOrchestrator

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes-no-decode-needed"


class SiblingError(Exception):
    def __init__(self, code, message="boom"):
        super().__init__("[%s] %s" % (code, message))
        self.code = code
        self.job_id = None


class FakeBackend:
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
        return {"png_bytes": self.png_bytes, "seed": self.seed}


class SubmitErrorBackend(FakeBackend):
    def __init__(self, code):
        super().__init__()
        self.code = code

    def submit_txt2img(self, **kwargs):
        raise SiblingError(self.code)

    def submit_img2img(self, **kwargs):
        raise SiblingError(self.code)


def make_process(calls):
    def fake_process(png_bytes, **kwargs):
        calls.append(kwargs)
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
    return AssetOrchestrator(backend, postprocess=make_process(calls), **kwargs), backend, calls


def gen_args(**overrides):
    args = {
        "prompt": "cute bear avatar",
        "category": "avatar",
        "save_path": "assets/images/bear_avatar.png",
        "seed": 42,
    }
    args.update(overrides)
    return args


# -- M3a: refine idempotency -------------------------------------------------

def test_rework_refine_same_job_id_no_rerun(tmp_path):
    orch, backend, _ = make_orchestrator()
    orch.generate(gen_args(save_path="assets/rw_parent.png"), tmp_path, job_id="rw-p1")
    refine_args = {
        "asset_path": "assets/rw_parent.png",
        "instruction": "add a tiny hat",
        "save_path": "assets/rw_hat.png",
    }
    first = orch.refine(refine_args, tmp_path, job_id="rw-ref-1")
    second = orch.refine(refine_args, tmp_path, job_id="rw-ref-1")
    assert second == first
    assert second["asset_path"] == "assets/rw_hat.png"
    assert len(backend.img2img_calls) == 1  # no second backend run
    assert len(backend.fetch_calls) == 2  # 1 generate fetch + 1 refine fetch


# -- M3b: refine queued when registry full ------------------------------------

def test_rework_refine_queued_when_full(tmp_path):
    orch, backend, _ = make_orchestrator()
    orch.generate(gen_args(save_path="assets/rw_qparent.png"), tmp_path, job_id="rw-qp")
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert before  # parent files exist
    orch._registry.register("rw-hold-1")
    orch._registry.register("rw-hold-2")
    try:
        with pytest.raises(QueuedError) as excinfo:
            orch.refine(
                {
                    "asset_path": "assets/rw_qparent.png",
                    "instruction": "warmer",
                    "save_path": "assets/rw_qref.png",
                },
                tmp_path,
            )
        assert excinfo.value.code == "QUEUED"
    finally:
        orch._registry.fail("rw-hold-1")
        orch._registry.fail("rw-hold-2")
    assert backend.img2img_calls == []  # slot refused before any backend call
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert after == before  # no refine files written


# -- M3c: refine evil save_path -----------------------------------------------

def test_rework_refine_evil_save_path_denied(tmp_path):
    orch, backend, _ = make_orchestrator()
    orch.generate(gen_args(save_path="assets/rw_eparent.png"), tmp_path, job_id="rw-ep")
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.refine(
            {
                "asset_path": "assets/rw_eparent.png",
                "instruction": "warmer",
                "save_path": "../../etc/pass.png",
            },
            tmp_path,
        )
    assert excinfo.value.code == "POLICY_DENIED"
    assert backend.img2img_calls == []
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert after == before  # no files written


# -- M3d: refine colliding target ---------------------------------------------

def test_rework_refine_colliding_target_denied(tmp_path):
    orch, backend, _ = make_orchestrator()
    orch.generate(gen_args(save_path="assets/rw_cparent.png"), tmp_path, job_id="rw-cp")
    orch.refine(
        {
            "asset_path": "assets/rw_cparent.png",
            "instruction": "cooler",
            "save_path": "assets/rw_child.png",
        },
        tmp_path,
        job_id="rw-c1",
    )
    assert len(backend.img2img_calls) == 1
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.refine(
            {
                "asset_path": "assets/rw_cparent.png",
                "instruction": "cooler",
                "save_path": "assets/rw_child.png",
            },
            tmp_path,
            job_id="rw-c2",
        )
    assert excinfo.value.code == "POLICY_DENIED"
    assert len(backend.img2img_calls) == 1  # refused before second submit


# -- L7: UNKNOWN_WORKFLOW ------------------------------------------------------

def test_rework_unknown_workflow_maps_to_generation_failed():
    assert error_class_for_sibling_code("UNKNOWN_WORKFLOW") is GenerationFailedError


def test_rework_unknown_workflow_submit_end_to_end(tmp_path):
    orch, _, _ = make_orchestrator(backend=SubmitErrorBackend("UNKNOWN_WORKFLOW"))
    with pytest.raises(GenerationFailedError) as excinfo:
        orch.generate(gen_args(save_path="assets/rw_u.png"), tmp_path, job_id="rw-u1")
    assert excinfo.value.code == "GENERATION_FAILED"
    assert list(tmp_path.rglob("*")) == []
    assert orch._registry.active_count == 0
