"""Gen-11 tests: the AGENT chooses the output path (C1 v0.1.5).

Fakes only: stub backend (canned PNG bytes) + canned ``process()`` echo;
no network, no model downloads. ``fastmcp`` is never imported.

Covers the C1 v0.1.5 amendment (user request, 2026-10-22):

* an absolute ``save_path`` inside an approved root is honoured exactly;
* an absolute ``save_path`` outside every approved root is refused
  (``POLICY_DENIED``, pre-backend) unless the server was started with
  ``--allow-any-path``;
* relative paths, ``..`` refusal, overwrite refusal and the workspace
  semantics are unchanged;
* results carry ``asset_path_absolute`` (exact file location).
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


def make_orchestrator(default_root, named=None, allow_any_path=False):
    """Orchestrator over a fake backend; returns (orch, backend, post_calls)."""
    cfg = ServerConfig(
        project_root=str(default_root),
        project_roots=dict(named or {}),
        allow_any_path=allow_any_path,
    )
    post_calls: list = []
    backend = FakeBackend()
    orch = AssetOrchestrator(
        backend, postprocess=make_postprocess(post_calls), config=cfg
    )
    return orch, backend, post_calls


@pytest.fixture(autouse=True)
def _no_fastmcp_leak():
    """Slice3 asserts ``fastmcp not in sys.modules``; don't pollute it."""
    before = {k for k in sys.modules if k == "fastmcp" or k.startswith("fastmcp.")}
    yield
    for k in [
        k
        for k in sys.modules
        if (k == "fastmcp" or k.startswith("fastmcp.")) and k not in before
    ]:
        del sys.modules[k]


# -- (a) absolute save_path inside an approved root ----------------------------


def test_absolute_save_path_inside_default_root_honoured(tmp_path):
    orch, backend, _ = make_orchestrator(tmp_path)
    target = tmp_path / "assets" / "icons" / "robot.png"
    res = orch.generate(
        gen_args(save_path=os.fspath(target)), tmp_path, job_id="abs-1"
    )
    assert target.is_file()
    assert target.read_bytes() == FAKE_PNG
    assert res["asset_path_absolute"] == os.fspath(target)
    assert res["asset_path"] == "assets/icons/robot.png"
    assert len(backend.txt2img_calls) == 1


def test_absolute_save_path_posix_style_accepted(tmp_path):
    """A ``/``-separated absolute path is honoured verbatim."""
    orch, _, _ = make_orchestrator(tmp_path)
    target = tmp_path / "out" / "icon.png"
    posix = target.as_posix()
    res = orch.generate(gen_args(save_path=posix), tmp_path, job_id="abs-2")
    assert target.is_file()
    assert res["asset_path_absolute"] == os.fspath(target)


def test_absolute_save_path_windows_backslashes_normalized(tmp_path):
    orch, _, _ = make_orchestrator(tmp_path)
    target = tmp_path / "out" / "icon.png"
    win = str(target).replace("/", "\\")
    res = orch.generate(gen_args(save_path=win), tmp_path, job_id="abs-3")
    assert target.is_file()
    assert res["asset_path_absolute"] == os.fspath(target)


def test_absolute_save_path_inside_named_workspace_honoured(tmp_path):
    named = {"alt": str(tmp_path / "alt")}
    (tmp_path / "alt").mkdir()
    orch, backend, _ = make_orchestrator(tmp_path, named)
    target = tmp_path / "alt" / "assets" / "icon.png"
    res = orch.generate(
        gen_args(save_path=os.fspath(target), workspace="alt"), tmp_path, job_id="abs-4"
    )
    assert target.is_file()
    assert res["asset_path_absolute"] == os.fspath(target)
    assert res["asset_path"] == "assets/icon.png"
    assert not (tmp_path / "assets").exists()


# -- (b) absolute save_path outside every approved root -------------------------


def test_absolute_save_path_outside_roots_refused_pre_backend(tmp_path):
    orch, backend, post_calls = make_orchestrator(tmp_path)
    outside = tmp_path.parent / "evil-outside" / "icon.png"
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(
            gen_args(save_path=os.fspath(outside)), tmp_path, job_id="abs-5"
        )
    assert "POLICY_DENIED" in str(excinfo.value)
    assert backend.txt2img_calls == []
    assert backend.fetch_calls == []
    assert post_calls == []
    assert not outside.exists()
    assert orch._registry.active_count == 0


def test_absolute_refusal_message_names_approved_roots(tmp_path):
    orch, _, _ = make_orchestrator(tmp_path)
    outside = tmp_path.parent / "evil-outside" / "icon.png"
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(
            gen_args(save_path=os.fspath(outside)), tmp_path, job_id="abs-6"
        )
    message = str(excinfo.value)
    assert "approved root" in message
    assert os.path.normcase(os.path.abspath(os.fspath(tmp_path))) in message.lower()


def test_allow_any_path_lifts_containment(tmp_path):
    orch, backend, _ = make_orchestrator(tmp_path, allow_any_path=True)
    outside = tmp_path.parent / "evil-allowed" / "icon.png"
    res = orch.generate(
        gen_args(save_path=os.fspath(outside)), tmp_path, job_id="abs-7"
    )
    assert outside.is_file()
    assert res["asset_path_absolute"] == os.fspath(outside)
    # Nothing is inside the root any more: the relative path is the absolute
    # one (no owning root), so the caller still learns the real location.
    assert res["asset_path"] == outside.as_posix()


def test_allow_any_path_is_reported_by_server_info(tmp_path, monkeypatch):
    import src.mcp_server.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_probe_comfyui_queue", lambda url: (True, 0))
    orch, _, _ = make_orchestrator(tmp_path, allow_any_path=True)
    assert orch.server_info()["allow_any_path"] is True
    orch2, _, _ = make_orchestrator(tmp_path)
    assert orch2.server_info()["allow_any_path"] is False


# -- (c) traversal / shape rules stay strict -----------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        "../../etc/pass.png",
        "a/../../b.png",
        "..\\windows\\x.png",
        "C:/root/../evil.png",
        "C:\\root\\..\\evil.png",
    ],
)
def test_traversal_refused_in_every_form(tmp_path, evil):
    orch, backend, post_calls = make_orchestrator(tmp_path)
    with pytest.raises(PolicyDeniedError):
        orch.generate(gen_args(save_path=evil), tmp_path, job_id="trav-1")
    assert backend.txt2img_calls == []
    assert post_calls == []


@pytest.mark.parametrize("evil", ["C:evil.png", "assets/", "."])
def test_invalid_shapes_refused(tmp_path, evil):
    orch, backend, _ = make_orchestrator(tmp_path)
    with pytest.raises(PolicyDeniedError):
        orch.generate(gen_args(save_path=evil), tmp_path, job_id="shape-1")
    assert backend.txt2img_calls == []


# -- (d) relative behaviour + overwrite are unchanged ---------------------------


def test_relative_save_path_still_resolves_under_workspace_root(tmp_path):
    named = {"alt": str(tmp_path / "alt")}
    (tmp_path / "alt").mkdir()
    orch, _, _ = make_orchestrator(tmp_path, named)
    res = orch.generate(
        gen_args(save_path="assets/rel.png", workspace="alt"), tmp_path, job_id="rel-1"
    )
    assert (tmp_path / "alt" / "assets" / "rel.png").is_file()
    assert res["asset_path"] == "assets/rel.png"
    assert res["asset_path_absolute"] == os.fspath(
        tmp_path / "alt" / "assets" / "rel.png"
    )


def test_existing_file_still_refused_without_overwrite(tmp_path):
    orch, _, _ = make_orchestrator(tmp_path)
    target = tmp_path / "assets" / "dup.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(
            gen_args(save_path="assets/dup.png"), tmp_path, job_id="ow-1"
        )
    assert "overwrite" in str(excinfo.value).lower()
    res = orch.generate(
        gen_args(save_path="assets/dup.png", overwrite=True),
        tmp_path,
        job_id="ow-2",
    )
    assert res["asset_path_absolute"] == os.fspath(target)
    assert target.read_bytes() == FAKE_PNG


# -- (e) refine with absolute paths ---------------------------------------------


def test_refine_absolute_parent_and_absolute_save_path(tmp_path):
    orch, backend, _ = make_orchestrator(tmp_path)
    parent = tmp_path / "assets" / "parent.png"
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"old-parent")
    refined = tmp_path / "assets" / "parent_hat.png"
    res = orch.refine(
        {
            "asset_path": os.fspath(parent),
            "instruction": "add a hat",
            "save_path": os.fspath(refined),
        },
        tmp_path,
        job_id="ref-abs-1",
    )
    assert refined.is_file()
    assert res["asset_path_absolute"] == os.fspath(refined)
    assert res["asset_path"] == "assets/parent_hat.png"
    assert parent.read_bytes() == b"old-parent"  # parent never mutated
    assert backend.img2img_calls[0]["input_png_path"] == os.fspath(parent)


def test_refine_absolute_parent_derives_absolute_sibling(tmp_path):
    orch, _, _ = make_orchestrator(tmp_path)
    parent = tmp_path / "assets" / "parent.png"
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"old-parent")
    res = orch.refine(
        {"asset_path": os.fspath(parent), "instruction": "warmer"},
        tmp_path,
        job_id="ref-abs-2",
    )
    assert (tmp_path / "assets" / "parent_refined.png").is_file()
    assert res["asset_path_absolute"] == os.fspath(
        tmp_path / "assets" / "parent_refined.png"
    )


def test_refine_absolute_parent_outside_roots_refused(tmp_path):
    orch, backend, _ = make_orchestrator(tmp_path)
    outside = tmp_path.parent / "evil-outside" / "parent.png"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"x")
    with pytest.raises(PolicyDeniedError):
        orch.refine(
            {"asset_path": os.fspath(outside), "instruction": "warmer"},
            tmp_path,
            job_id="ref-abs-3",
        )
    assert backend.img2img_calls == []


# -- (f) sibling outputs (@2x/@3x) stay inside the approved roots --------------


def test_absolute_target_siblings_written_next_to_it(tmp_path):
    orch, _, _ = make_orchestrator(tmp_path)
    target = tmp_path / "assets" / "icons" / "robot.png"
    orch.generate(gen_args(save_path=os.fspath(target)), tmp_path, job_id="sib-1")
    assert target.is_file()
    # The canned postprocess echoes one file; the real pipeline adds @2x/@3x
    # siblings next to the target (never outside the approved roots).
    siblings = sorted(p.name for p in target.parent.iterdir())
    assert siblings == ["robot.png"]


def test_postprocess_filename_cannot_escape_approved_roots(tmp_path):
    orch, _, _ = make_orchestrator(tmp_path)
    target = tmp_path / "assets" / "icon.png"
    target.parent.mkdir(parents=True)
    with pytest.raises(PolicyDeniedError):
        orch._write_files(
            [{"filename": "../../escape.png", "png_bytes": FAKE_PNG}],
            target,
            [tmp_path],
        )


# -- (g) containment is PHYSICAL (symlinks/junctions) --------------------------


def test_symlink_out_of_root_refused(tmp_path):
    """A link inside the root that points outside must not become a write
    outside the root (containment is decided on the resolved path)."""
    outside = tmp_path.parent / "evil-link-target"
    outside.mkdir(parents=True, exist_ok=True)
    link = tmp_path / "link"
    try:
        os.symlink(str(outside), str(link), target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - env
        pytest.skip("symlink creation unavailable: %s" % (exc,))
    orch, backend, _ = make_orchestrator(tmp_path)
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(
            gen_args(save_path=os.fspath(link / "escape.png")),
            tmp_path,
            job_id="link-1",
        )
    assert "RESOLVES" in str(excinfo.value)
    assert backend.txt2img_calls == []
    assert not (outside / "escape.png").exists()


@pytest.mark.skipif(os.name != "nt", reason="NTFS alternate data streams")
def test_alternate_data_stream_form_refused(tmp_path):
    """``icon.png:evil`` is an NTFS stream, not a file: it would bypass the
    overwrite guard and report a path that does not exist."""
    orch, backend, _ = make_orchestrator(tmp_path)
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(
            gen_args(save_path="assets/icon.png:evil"), tmp_path, job_id="ads-1"
        )
    assert "POLICY_DENIED" in str(excinfo.value)
    assert backend.txt2img_calls == []


def test_nul_byte_in_save_path_refused(tmp_path):
    orch, backend, _ = make_orchestrator(tmp_path)
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(
            gen_args(save_path="assets/evil\x00.png"), tmp_path, job_id="nul-1"
        )
    assert "POLICY_DENIED" in str(excinfo.value)
    assert backend.txt2img_calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows device names")
@pytest.mark.parametrize("name", ["NUL.png", "con.png", "COM1.png"])
def test_reserved_device_name_refused(tmp_path, name):
    orch, backend, _ = make_orchestrator(tmp_path)
    with pytest.raises(PolicyDeniedError):
        orch.generate(gen_args(save_path="assets/%s" % name), tmp_path, job_id="dev-1")
    assert backend.txt2img_calls == []


def test_postprocess_device_name_and_nul_refused(tmp_path):
    orch, _, _ = make_orchestrator(tmp_path)
    target = tmp_path / "assets" / "icon.png"
    target.parent.mkdir(parents=True)
    for filename in ("NUL.png", "evil\x00.png"):
        with pytest.raises(PolicyDeniedError):
            orch._write_files(
                [{"filename": filename, "png_bytes": FAKE_PNG}], target, [tmp_path]
            )


@pytest.mark.skipif(os.name != "nt", reason="NTFS alternate data streams")
def test_postprocess_alternate_data_stream_refused(tmp_path):
    orch, _, _ = make_orchestrator(tmp_path)
    target = tmp_path / "assets" / "icon.png"
    target.parent.mkdir(parents=True)
    with pytest.raises(PolicyDeniedError):
        orch._write_files(
            [{"filename": "icon.png:evil", "png_bytes": FAKE_PNG}], target, [tmp_path]
        )
    assert not (tmp_path / "assets" / "icon.png").exists()


def test_relative_path_through_link_reports_resolve(tmp_path):
    """A relative path that leaves the root through a link says so."""
    outside = tmp_path.parent / "evil-link-target-2"
    outside.mkdir(parents=True, exist_ok=True)
    link = tmp_path / "link"
    try:
        os.symlink(str(outside), str(link), target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - env
        pytest.skip("symlink creation unavailable: %s" % (exc,))
    orch, backend, _ = make_orchestrator(tmp_path)
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(
            gen_args(save_path="link/escape.png"), tmp_path, job_id="link-2"
        )
    assert "RESOLVES" in str(excinfo.value)
    assert backend.txt2img_calls == []
    assert not (outside / "escape.png").exists()


# -- (h) refine save_path containment (restored coverage) ----------------------


def test_refine_absolute_save_path_outside_roots_refused(tmp_path):
    orch, backend, _ = make_orchestrator(tmp_path)
    parent = tmp_path / "assets" / "parent.png"
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"old-parent")
    outside = tmp_path.parent / "evil-outside" / "refined.png"
    with pytest.raises(PolicyDeniedError):
        orch.refine(
            {
                "asset_path": os.fspath(parent),
                "instruction": "warmer",
                "save_path": os.fspath(outside),
            },
            tmp_path,
            job_id="ref-outside-1",
        )
    assert backend.img2img_calls == []
    assert not outside.exists()


def test_refine_relative_save_path_escape_still_refused(tmp_path):
    orch, backend, _ = make_orchestrator(tmp_path)
    parent = tmp_path / "assets" / "parent.png"
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"old-parent")
    with pytest.raises(PolicyDeniedError):
        orch.refine(
            {
                "asset_path": os.fspath(parent),
                "instruction": "warmer",
                "save_path": "../../etc/pass.png",
            },
            tmp_path,
            job_id="ref-outside-2",
        )
    assert backend.img2img_calls == []


# -- (h2) the requested path IS the written file (C1 v0.1.6) --------------------


def test_requested_path_is_the_written_file(tmp_path):
    """The reported path must exist — the leaf the agent asked for."""
    orch, _, _ = make_orchestrator(tmp_path)
    target = tmp_path / "assets" / "icons" / "robot.png"
    res = orch.generate(gen_args(save_path=os.fspath(target)), tmp_path, job_id="w-1")
    assert os.path.isfile(res["asset_path_absolute"])
    assert os.path.samefile(res["asset_path_absolute"], target)


@pytest.mark.parametrize(
    "leaf",
    [
        "assets/icon.webp",  # not a .png leaf
        "assets/icon.jpg",
        "assets/icon",  # no extension
        "assets/mon icône.png",  # not PNG-safe
        "assets/icon@2x.png",  # not PNG-safe
        "assets/.png",  # no stem
        "assets/icon.PNG",  # uppercase extension: the writer emits lowercase
    ],
)
def test_non_png_leaf_refused_pre_backend(tmp_path, leaf):
    orch, backend, post_calls = make_orchestrator(tmp_path)
    with pytest.raises(PolicyDeniedError) as excinfo:
        orch.generate(gen_args(save_path=leaf), tmp_path, job_id="leaf-1")
    assert "POLICY_DENIED" in str(excinfo.value)
    assert backend.txt2img_calls == []
    assert post_calls == []
    assert list(tmp_path.rglob("*.png")) == []


def test_refine_by_asset_id_across_roots(tmp_path):
    """A parent stored in another approved root is still found by asset_id."""
    named = {"alt": str(tmp_path / "alt")}
    (tmp_path / "alt").mkdir()
    orch, backend, _ = make_orchestrator(tmp_path, named)
    target = tmp_path / "alt" / "assets" / "parent.png"
    gen = orch.generate(
        gen_args(save_path=os.fspath(target)), tmp_path, job_id="cross-1"
    )
    assert gen["asset_path"] == "alt/assets/parent.png"  # owned by the default root
    assert gen["asset_root"] == os.path.abspath(os.fspath(tmp_path))
    res = orch.refine(
        {"asset_id": gen["job_id"], "instruction": "warmer"},
        tmp_path,
        job_id="cross-2",
    )
    assert res["asset_path_absolute"] == os.fspath(
        tmp_path / "alt" / "assets" / "parent_refined.png"
    )
    assert res["asset_root"] == os.path.abspath(os.fspath(tmp_path))
    assert backend.img2img_calls[0]["input_png_path"] == os.fspath(target)


def test_refine_by_asset_id_in_sibling_root_writes_beside_parent(tmp_path):
    """Non-nested approved roots: the refined file must land next to the
    parent, not under the selected workspace."""
    sibling = tmp_path.parent / (tmp_path.name + "-alt")
    sibling.mkdir(parents=True, exist_ok=True)
    orch, backend, _ = make_orchestrator(tmp_path, {"alt": str(sibling)})
    target = sibling / "assets" / "parent.png"
    gen = orch.generate(
        gen_args(save_path=os.fspath(target)), tmp_path, job_id="sib-1"
    )
    assert gen["asset_root"] == os.path.abspath(os.fspath(sibling))
    res = orch.refine(
        {"asset_id": gen["job_id"], "instruction": "warmer"},
        tmp_path,
        job_id="sib-2",
    )
    expected = sibling / "assets" / "parent_refined.png"
    assert res["asset_path_absolute"] == os.fspath(expected)
    assert res["asset_root"] == os.path.abspath(os.fspath(sibling))
    assert expected.is_file()
    assert not (tmp_path / "assets").exists()
    assert backend.img2img_calls[0]["input_png_path"] == os.fspath(target)


def test_postprocess_rejection_becomes_postprocess_failed(tmp_path):
    """A postprocess ValueError must reach the agent with a CODE prefix."""
    from src.mcp_server.errors import PostprocessFailedError

    class RejectingPostprocess:
        def __call__(self, png_bytes, **kwargs):
            raise ValueError("stem has non-PNG-safe chars: 'x y'")

    cfg = ServerConfig(project_root=str(tmp_path))
    orch = AssetOrchestrator(
        FakeBackend(), postprocess=RejectingPostprocess(), config=cfg
    )
    with pytest.raises(PostprocessFailedError) as excinfo:
        orch.generate(gen_args(save_path="assets/icon.png"), tmp_path, job_id="pp-1")
    assert "POSTPROCESS_FAILED" in str(excinfo.value)


def test_postprocess_oserror_becomes_postprocess_failed(tmp_path):
    """An OSError from the postprocess (e.g. Pillow on a corrupt PNG) must
    also reach the agent with a CODE prefix, not as a bare OSError."""
    from src.mcp_server.errors import PostprocessFailedError

    class BrokenImagePostprocess:
        def __call__(self, png_bytes, **kwargs):
            raise OSError("cannot identify image file")

    cfg = ServerConfig(project_root=str(tmp_path))
    orch = AssetOrchestrator(
        FakeBackend(), postprocess=BrokenImagePostprocess(), config=cfg
    )
    with pytest.raises(PostprocessFailedError) as excinfo:
        orch.generate(gen_args(save_path="assets/icon.png"), tmp_path, job_id="pp-2")
    assert "POSTPROCESS_FAILED" in str(excinfo.value)
    assert "cannot identify image file" in str(excinfo.value)
    assert not (tmp_path / "assets").exists()


# -- (i) CLI + config plumbing ---------------------------------------------------
def test_cli_allow_any_path_lands_in_config(tmp_path, monkeypatch):
    import src.mcp_server.server as server

    seen: dict = {}

    class FakeMCP:
        def run(self, *args, **kwargs) -> None:
            pass

    def fake_create_server(config, backend_factory=None, postprocess_fn=None):
        seen["config"] = config
        return FakeMCP()

    monkeypatch.setattr(server, "create_server", fake_create_server)
    assert server.main(["--project-root", str(tmp_path)]) == 0
    assert seen["config"].allow_any_path is False
    assert server.main(["--project-root", str(tmp_path), "--allow-any-path"]) == 0
    assert seen["config"].allow_any_path is True


def test_config_rejects_non_bool_allow_any_path(tmp_path):
    with pytest.raises(ValueError, match="INVALID_ALLOW_ANY_PATH"):
        ServerConfig(project_root=str(tmp_path), allow_any_path="yes")


def test_main_without_project_root_uses_launch_directory(tmp_path, monkeypatch):
    """AC-4: with no --project-root the jail follows the client's directory."""
    import src.mcp_server.server as server

    seen: dict = {}

    class FakeMCP:
        def run(self, *args, **kwargs) -> None:
            pass

    def fake_create_server(config, backend_factory=None, postprocess_fn=None):
        seen["config"] = config
        return FakeMCP()

    monkeypatch.setattr(server, "create_server", fake_create_server)
    monkeypatch.chdir(tmp_path)
    assert server.main([]) == 0
    assert seen["config"].project_root == os.path.abspath(os.fspath(tmp_path))
