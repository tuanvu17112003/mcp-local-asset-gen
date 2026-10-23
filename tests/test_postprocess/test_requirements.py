"""Install-route guards for the published dependency set.

These are text-level checks, not a dependency resolver: the real
clean-install proof is `pip install -r requirements.txt` in an empty venv
(recorded in `.workflow/artifacts/install-dependency-conflict/`). What these
tests can catch cheaply is a regression that reintroduces the known
unsatisfiable pair:

    rembg[cli] 2.0.85  -> python-multipart<0.0.22
    fastmcp 4.1.0      -> fastmcp-slim[server] -> python-multipart>=0.0.26
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "requirements.txt"


def _requirement_lines() -> list:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_rembg_cli_extra_is_not_required():
    """`rembg[cli]` pins python-multipart<0.0.22 and breaks the install."""
    lines = _requirement_lines()
    rembg = [line for line in lines if line.split("==")[0].startswith("rembg")]
    assert rembg, "requirements.txt must pin rembg"
    for line in rembg:
        extras = line.split("==")[0]
        assert "cli" not in extras.replace(" ", "").split("["), (
            "rembg[cli] conflicts with fastmcp's python-multipart>=0.0.26: %r"
            % (line,)
        )
        assert "cpu" in extras, "use the [cpu] extra for onnxruntime: %r" % (line,)


def test_known_good_pins_present():
    lines = {line.split("==")[0].strip(): line for line in _requirement_lines()}
    assert "fastmcp" in lines, lines
    assert "rembg[cpu]" in lines, lines
    assert "Pillow" in lines or "pillow" in lines, lines
    assert "==4.1.0" in lines["fastmcp"]


def test_requirements_do_not_pin_python_multipart_directly():
    """Pinning it here would fight whatever the two libraries negotiate."""
    assert not any(
        line.split("==")[0].strip().lower() == "python-multipart"
        for line in _requirement_lines()
    )
