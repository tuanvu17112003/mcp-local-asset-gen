"""Packaging contract checks (v0.8.0 packaging deliverable).

Covers the distribution metadata that must stay in lockstep with the
server code:

* ``pyproject.toml`` parses as TOML and stays a setuptools ``src``-layout
  project with the three top-level packages and the console script.
* The version is DYNAMIC and resolves to
  ``mcp_server.config.SERVER_VERSION`` (single source of truth); no release
  version literal is duplicated in the metadata file.
* Package data covers every workflow JSON and setup_notes markdown actually
  present in the source tree.
* The repo-root ``conftest.py`` keeps both import styles working and its
  ``sys.path`` bootstrapping is idempotent.
* A built wheel contains the workflow JSONs and the setup_notes markdown.

No network is needed unless the interpreter has no ``setuptools`` (then the
wheel build uses pip build isolation and the test skips if that needs the
network and cannot reach it).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
ROOT_CONFTEST = ROOT / "conftest.py"
SRC = ROOT / "src"

REQUIRED_PACKAGES = ("mcp_server", "gen_backend", "postprocess")


def _pyproject() -> dict:
    """Parse ``pyproject.toml`` (stdlib ``tomllib``; no packaging dependency)."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _dynamic_version_target() -> str:
    """Return the ``{attr = "..."}`` target of the dynamic version entry."""
    dynamic = _pyproject()["tool"]["setuptools"]["dynamic"]["version"]
    assert set(dynamic) == {"attr"}, dynamic
    return dynamic["attr"]


def _import_attr(dotted: str) -> object:
    """Import ``package.module.NAME`` from the source tree (no install needed)."""
    module_name, _, attr = dotted.rpartition(".")
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _workflow_files() -> list:
    """Every workflow JSON shipped under ``gen_backend/workflows``."""
    return sorted((SRC / "gen_backend" / "workflows").glob("*.json"))


def _setup_notes() -> list:
    """Every ``setup_notes.md`` shipped inside a package directory."""
    return sorted(SRC.glob("*/setup_notes.md"))


def _package_data_globs() -> dict:
    """``package -> [glob, ...]`` from ``[tool.setuptools.package-data]``."""
    return _pyproject()["tool"]["setuptools"]["package-data"]


# -- metadata -----------------------------------------------------------------


def test_pyproject_parses_and_declares_src_layout():
    data = _pyproject()
    project = data["project"]
    assert project["name"] == "mcp-local-asset-gen"
    assert project["requires-python"] == ">=3.11"
    assert data["build-system"]["build-backend"] == "setuptools.build_meta"
    tool = data["tool"]["setuptools"]
    assert tool["package-dir"] == {"": "src"}
    assert tuple(tool["packages"]) == REQUIRED_PACKAGES
    # The layout fact: there is no ``src`` package (no src/__init__.py).
    assert not (SRC / "__init__.py").exists()


def test_version_is_dynamic_and_resolves_to_server_version():
    project = _pyproject()["project"]
    assert project.get("dynamic") == ["version"]
    assert "version" not in project, "version must not be hardcoded"
    target = _dynamic_version_target()
    assert target == "mcp_server.config.SERVER_VERSION"
    resolved = _import_attr(target)
    assert isinstance(resolved, str) and resolved
    # The same string the running server reports.
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from mcp_server import config as config_module

    assert resolved == config_module.SERVER_VERSION


def test_no_version_literal_duplicated_in_pyproject():
    from mcp_server import config as config_module

    text = PYPROJECT.read_text(encoding="utf-8")
    version = config_module.SERVER_VERSION
    assert f'"{version}"' not in text, (
        "pyproject.toml must not duplicate the release version literal; "
        "it is read dynamically from mcp_server.config.SERVER_VERSION"
    )
    assert f"'{version}'" not in text


def test_console_script_declared():
    scripts = _pyproject()["project"]["scripts"]
    assert scripts["asset-gen"] == "mcp_server.server:main"


def test_runtime_dependencies_match_requirements_pins():
    """pyproject dependencies mirror requirements.txt (same names + pins)."""
    declared = _pyproject()["project"]["dependencies"]
    required = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert [dep.replace(" ", "") for dep in declared] == [
        req.replace(" ", "") for req in required
    ]


# -- package data -------------------------------------------------------------


def test_package_data_covers_workflow_json_and_setup_notes():
    globs = _package_data_globs()
    backend_globs = globs["gen_backend"]
    assert any(glob.endswith("workflows/*.json") for glob in backend_globs), globs
    assert "setup_notes.md" in backend_globs, globs
    assert "setup_notes.md" in globs["postprocess"], globs
    # Every workflow JSON and setup_notes actually on disk must be matched.
    workflows = _workflow_files()
    assert workflows, "expected the C2 workflow JSONs in gen_backend/workflows"
    assert {path.parent for path in _setup_notes()} <= {
        SRC / "gen_backend",
        SRC / "postprocess",
    }


# -- root conftest ------------------------------------------------------------


def test_root_conftest_exists_and_bootstraps_both_import_styles():
    assert ROOT_CONFTEST.is_file(), (
        "repo-root conftest.py is required so `pytest tests/ -q` resolves "
        "both `from src.mcp_server...` and the top-level shim imports"
    )
    spec = importlib.util.spec_from_file_location(
        "_root_conftest_probe", ROOT_CONFTEST
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.ensure_repo_paths)
    assert str(SRC) in sys.path
    assert str(ROOT) in sys.path


def test_root_conftest_sys_path_insertion_is_idempotent():
    """Calling the bootstrap again must not append duplicate entries.

    The absolute count is not asserted: several per-directory conftests and
    test modules insert the same directories, so only the GROWTH caused by
    this module's own repeated calls is meaningful.
    """
    spec = importlib.util.spec_from_file_location(
        "_root_conftest_probe2", ROOT_CONFTEST
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = len(sys.path)
    module.ensure_repo_paths()
    after_first = len(sys.path)
    module.ensure_repo_paths()
    assert len(sys.path) == after_first, sys.path
    assert after_first - before <= 2, sys.path
    for expected in (str(SRC), str(ROOT)):
        assert sys.path.count(expected) >= 1, sys.path


# -- built wheel --------------------------------------------------------------


def _build_wheel(tmp_path: Path) -> Path:
    """Build a wheel from a clean copy of the project; return its path.

    A copy keeps the checkout free of build artefacts. ``setuptools`` is not
    a project dependency, so when it is missing the build runs with pip
    isolation (network); that case skips instead of failing an offline box.
    """
    staging = tmp_path / "project"
    staging.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, staging / name)
    shutil.copytree(
        SRC,
        staging / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    out = tmp_path / "dist"
    out.mkdir()
    command = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        str(staging),
        "--no-deps",
        "--quiet",
        "-w",
        str(out),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if importlib.util.find_spec("setuptools") is None and (
            "connection" in detail.lower() or "temporary failure" in detail.lower()
        ):
            pytest.skip("wheel build needs pip build isolation but has no network")
        pytest.fail("wheel build failed:\n" + detail)
    wheels = sorted(out.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def test_wheel_ships_workflow_json_and_setup_notes(tmp_path):
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    for path in _workflow_files():
        assert f"gen_backend/workflows/{path.name}" in names, names
    for path in _setup_notes():
        relative = path.relative_to(SRC).as_posix()
        assert relative in names, names
    # The entry point metadata ships with it (installed console script).
    entry_points = [name for name in names if name.endswith("entry_points.txt")]
    assert entry_points, names
    payload = ""
    with zipfile.ZipFile(wheel) as archive:
        payload = archive.read(entry_points[0]).decode("utf-8")
    assert "asset-gen = mcp_server.server:main" in payload
# -- launcher --selftest ------------------------------------------------------

def test_launcher_selftest_entrypoint_is_declared_and_transport_free():
    """``asset-gen.py --selftest`` must stay a real, transport-free entrypoint.

    The launcher file is parsed, not executed: the assertions are that the
    ``--selftest`` branch exists, that it runs ``_selftest()``, and that the
    normal path still delegates to ``src.mcp_server.server:main``.
    """
    import ast

    launcher = ROOT / "asset-gen.py"
    source = launcher.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert "_selftest" in function_names, function_names
    imported_main = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "src.mcp_server.server"
        for alias in node.names
    ]
    assert "main" in imported_main, imported_main
    assert '"--selftest" in sys.argv[1:]' in source
    # Selftest must never start a transport (that would hang a CI job).
    selftest_body = source.split("def _selftest", 1)[1]
    assert "mcp.run(" not in selftest_body


def test_launcher_selftest_passes_offline_and_reports_json(tmp_path):
    """Run the real ``--selftest`` offline: exit 0 plus a machine-readable report.

    This is the CI smoke gate (no ComfyUI, no GPU, no rembg model). It runs as
    a subprocess from a FOREIGN cwd so the launcher's own ``sys.path`` setup is
    what makes it work, exactly like an MCP client invocation.
    """
    import json

    proc = subprocess.run(
        [sys.executable, str(ROOT / "asset-gen.py"), "--selftest"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["ok"] is True, report
    assert report["version"], report
    assert set(report["tools"]) >= {
        "generate_app_asset",
        "refine_asset",
        "cancel_asset_job",
        "check_model",
        "server_info",
    }, report
    checked = {check["name"] for check in report["checks"]}
    assert {"tools", "generate_app_asset", "refine_asset", "server_info",
            "check_model"} <= checked, report
    failures = [check for check in report["checks"] if not check["ok"]]
    assert not failures, failures
# -- opencode.json wiring -----------------------------------------------------

def test_opencode_json_wires_launcher_without_cwd_pin():
    """The tracked MCP wiring must call the launcher, not a cwd-dependent -m run.

    A ``cwd`` pin plus ``python -m src.mcp_server.server`` makes the asset jail
    resolve to the MCP checkout instead of the client's workspace, so the
    documented recommendation is: absolute ``asset-gen.py`` path, no ``cwd``.
    The ComfyUI URL stays the machine-verified port 8000.
    """
    import json

    payload = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    server = payload["mcp"]["servers"]["asset-gen"]
    assert server["type"] == "local"
    assert "cwd" not in server, server
    command = server["command"]
    assert isinstance(command, list) and len(command) >= 2, command
    assert command[1].replace("\\", "/").endswith("/asset-gen.py"), command
    assert "-m" not in command, command
    assert "src.mcp_server.server" not in " ".join(command), command
    url_index = command.index("--comfyui-url")
    assert command[url_index + 1] == "http://127.0.0.1:8000", command


# -- CI workflow --------------------------------------------------------------

def test_ci_workflow_gates_packaging_and_selftest():
    """The workflow must keep the OS x Python test matrix and add an install job."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for required in (
        "ubuntu-latest",
        "windows-latest",
        '"3.11"',
        '"3.13"',
        "requirements-dev.txt",
        "python -m pytest tests/ -q",
        # install job
        "pip install --no-deps -e .",
        "asset-gen --help",
        "asset-gen.py --selftest",
        "python -m build --wheel",
    ):
        assert required in text, required
    # The wheel gate must assert the shipped package data, not just build it.
    assert "gen_backend/workflows/" in text, text
    assert "setup_notes.md" in text, text
