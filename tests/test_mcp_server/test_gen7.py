"""Gen-7 tests: C3 v0.1.1 icon scale labels in ``_write_files``.

Fakes only: stub backend (canned PNG bytes) + canned ``process()``
echoes emitting REAL C3 v0.1.1 labels (``scale="icon<N>"``); no network,
no model downloads, no ``fastmcp`` import. ``tmp_path`` is the project
root.

Live failure closed: postprocess gen-6 Partial
``POSTPROCESS_FAILED ... got 'icon32'`` raised solely by consumer-side
``orchestrator._write_files`` (producer output already matches C3
v0.1.1). This delta accepts ``^icon([1-9][0-9]*)$`` (size derived from
``width``/``height``) while keeping the ``@Nx`` integer path
byte-identical.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.mcp_server.errors import PostprocessFailedError
from src.mcp_server.orchestrator import AssetOrchestrator
from src.mcp_server.validation import validate_tool_args

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes-no-decode-needed"
FAKE_ICO = b"\x00\x00\x01\x00fake-ico-bytes"


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


def write_one(tmp_path, entry):
    """Drive ``_write_files`` with a single entry beside a dummy target.

    Uses a recording writer that ALSO writes to disk, so both the
    in-memory ``store`` length and the on-disk bytes are assertable
    (regression: dict-only writer made disk asserts FileNotFoundError).
    """
    store: dict = {}

    def _both(path, data: bytes) -> None:
        store[str(path)] = bytes(data)
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bytes(data))

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=lambda b, **k: {"files": []}, writer=_both
    )
    target = tmp_path / "assets" / "dummy.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    orch._write_files([entry], target, tmp_path)
    return store


# -- icon labels accepted ----------------------------------------------------


@pytest.mark.parametrize("n", [1, 16, 32, 48, 256, 512])
def test_icon_label_accepted(tmp_path, n):
    store = write_one(
        tmp_path,
        {
            "filename": "bear-%dpx.png" % n,
            "width": n,
            "height": n,
            "scale": "icon%d" % n,
            "png_bytes": FAKE_PNG,
        },
    )
    assert (tmp_path / "assets" / ("bear-%dpx.png" % n)).read_bytes() == FAKE_PNG
    assert len(store) == 1


def test_icon_label_size_derived_from_dims_not_parsed(tmp_path):
    # Well-formed label with N != width/height is still accepted: size
    # comes from width/height, the label is only well-formedness-gated.
    store = write_one(
        tmp_path,
        {
            "filename": "bear-32px.png",
            "width": 32,
            "height": 32,
            "scale": "icon16",
            "png_bytes": FAKE_PNG,
        },
    )
    assert (tmp_path / "assets" / "bear-32px.png").read_bytes() == FAKE_PNG
    assert len(store) == 1


def test_live_icon32_repro_accepted(tmp_path):
    # Exact live failure shape: producer emitted scale 'icon32'.
    store = write_one(
        tmp_path,
        {
            "filename": "icon-32px.png",
            "width": 32,
            "height": 32,
            "scale": "icon32",
            "png_bytes": FAKE_PNG,
        },
    )
    assert (tmp_path / "assets" / "icon-32px.png").read_bytes() == FAKE_PNG
    assert len(store) == 1


# -- malformed icon labels rejected ------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["icon0", "icon01", "icon", "Icon16", "ICON16", "icon-1", "icon1.5",
     "icon ", " icon16", "", "icoN16", "icon16x", "1", "16"],
)
def test_icon_label_malformed_rejected(tmp_path, bad):
    orch, _ = make_orch(FakeBackend(), lambda b, **k: {"files": []})
    target = tmp_path / "assets" / "dummy.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(PostprocessFailedError, match="POSTPROCESS_FAILED"):
        orch._write_files(
            [
                {
                    "filename": "bear-16px.png",
                    "width": 16,
                    "height": 16,
                    "scale": bad,
                    "png_bytes": FAKE_PNG,
                }
            ],
            target,
            tmp_path,
        )


@pytest.mark.parametrize("bad", [0, -1, True, False, 1.5, None, b"icon16"])
def test_icon_scale_wrong_type_rejected(tmp_path, bad):
    orch, _ = make_orch(FakeBackend(), lambda b, **k: {"files": []})
    target = tmp_path / "assets" / "dummy.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(PostprocessFailedError, match="POSTPROCESS_FAILED"):
        orch._write_files(
            [
                {
                    "filename": "bear-16px.png",
                    "width": 16,
                    "height": 16,
                    "scale": bad,
                    "png_bytes": FAKE_PNG,
                }
            ],
            target,
            tmp_path,
        )


# -- @Nx integer path byte-identical -----------------------------------------


@pytest.mark.parametrize("s", [1, 2, 3])
def test_at_nx_integers_still_accepted(tmp_path, s):
    store = write_one(
        tmp_path,
        {
            "filename": "bear.png" if s == 1 else "bear@%dx.png" % s,
            "width": 8 * s,
            "height": 8 * s,
            "scale": s,
            "png_bytes": FAKE_PNG,
        },
    )
    assert len(store) == 1


@pytest.mark.parametrize("bad", [0, -1, True, False, "2", "1", 1.5, None])
def test_at_nx_integers_still_strict(tmp_path, bad):
    orch, _ = make_orch(FakeBackend(), lambda b, **k: {"files": []})
    target = tmp_path / "assets" / "dummy.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(PostprocessFailedError, match="POSTPROCESS_FAILED"):
        orch._write_files(
            [
                {
                    "filename": "bear.png",
                    "width": 8,
                    "height": 8,
                    "scale": bad,
                    "png_bytes": FAKE_PNG,
                }
            ],
            target,
            tmp_path,
        )


def test_ico_scale_still_accepted(tmp_path):
    store = write_one(
        tmp_path,
        {"filename": "bear.ico", "scale": "ico", "png_bytes": FAKE_ICO},
    )
    assert (tmp_path / "assets" / "bear.ico").read_bytes() == FAKE_ICO
    assert len(store) == 1


# -- generate passthrough with REAL icon labels -------------------------------


def test_generate_passthrough_real_icon_labels(tmp_path):
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
            files.append(
                {"filename": "%s.ico" % stem, "scale": "ico", "png_bytes": FAKE_ICO}
            )
        return {"files": files, "alpha": True, "model_used": "none"}

    orch = AssetOrchestrator(FakeBackend(), postprocess=fake_process)
    args = validate_tool_args(
        "bear", "avatar", "assets/bear.png", icon_sizes=[16, 32], ico=True
    )
    res = orch.generate(args, tmp_path, job_id="gen7-ico")
    assert res["asset_path"] == "assets/bear.png"
    base = tmp_path / "assets"
    assert (base / "bear.png").read_bytes() == FAKE_PNG
    assert (base / "bear@2x.png").read_bytes() == FAKE_PNG
    assert (base / "bear-16px.png").read_bytes() == FAKE_PNG
    assert (base / "bear-32px.png").read_bytes() == FAKE_PNG
    assert (base / "bear.ico").read_bytes() == FAKE_ICO


def test_gen5_fake_uses_real_icon_labels():
    """Guard the gen-7 fake fix: test_gen5's icon fake must use icon<N>."""
    import pathlib

    src = pathlib.Path("tests/test_mcp_server/test_gen5.py").read_text()
    assert re.search(r'"scale":\s*"icon%d"\s*%\s*n', src), (
        "test_gen5 icon fake must emit real C3 v0.1.1 labels"
    )
    assert '"scale": 1,\n                    "png_bytes": png_bytes,\n                }\n            )\n        if kwargs.get("ico")' not in src, (
        "stale integer icon scale still present in test_gen5 fake"
    )
