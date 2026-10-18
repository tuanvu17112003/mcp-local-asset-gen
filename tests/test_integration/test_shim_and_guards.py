"""Shim-import + V2-wiring + Python-floor guard checks (slice 2).

Harness itself MUST pass on Python 3.10: the >=3.11 floor is only
documented/gated for live-model paths, never required to run these tests.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from PIL import Image

import postprocess.pipeline as pipeline_mod
from postprocess.errors import SegmentationFailedError
from postprocess.rembg_adapter import MIN_PYTHON, remove_background

ROOT = Path(__file__).resolve().parents[2]
OWNED_PY = sorted((ROOT / "tests" / "test_integration").glob("*.py"))
TSX_DIR = ROOT / "examples" / "react"
README = TSX_DIR / "README.md"

PACKAGE_STYLE = re.compile(r"^[ \t]*(import src\.|from src\.)", re.M)


def test_no_package_style_src_imports():
    scanned = []
    hits = {}
    for path in OWNED_PY + sorted(TSX_DIR.iterdir()):
        if path.suffix not in {".py", ".tsx", ".ts", ".md"}:
            continue
        text = path.read_text(encoding="utf-8")
        scanned.append(path.name)
        found = PACKAGE_STYLE.findall(text)
        if found:
            hits[path.name] = found
    assert scanned, "expected to scan owned + example files"
    assert not hits, f"package-style src imports forbidden (CR-MCP-001): {hits}"


def test_shim_imports_resolve_without_src_package():
    # Project layout ships NO regular ``src`` package (no src/__init__.py),
    # so package-style ``import src.<pkg>`` is unsupported by construction:
    # it can only accidentally resolve via a cwd namespace fallback, never
    # via the sys.path shim. The shim-style top-level import always works.
    assert not (ROOT / "src" / "__init__.py").exists()
    spec = importlib.util.find_spec("postprocess.pipeline")
    assert spec is not None and spec.origin is not None
    assert Path(spec.origin).is_relative_to(ROOT / "src")
    assert callable(pipeline_mod.process)


def test_v2_wiring_doc_has_no_enabled_field():
    text = README.read_text(encoding="utf-8")
    assert '"enabled"' not in text
    assert '"disabled"' in text


def test_python_floor_declared_for_live_model_paths():
    assert MIN_PYTHON == (3, 11)


def test_live_path_gated_below_python_311():
    """Live background-removal requires >=3.11; canned paths are unaffected."""
    if sys.version_info >= (3, 11):
        pytest.skip("interpreter already >=3.11; offline floor gate is N/A here")
    img = Image.new("RGB", (16, 16), (10, 20, 30))
    import io as _io

    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    with pytest.raises(SegmentationFailedError, match="SEGMENTATION_FAILED") as excinfo:
        remove_background(buf.getvalue(), model="u2net")
    assert "3.11" in str(excinfo.value)
