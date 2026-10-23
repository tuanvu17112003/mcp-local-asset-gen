"""Install-route guards for the published dependency set.

These are text-level checks, not a dependency resolver: the real
clean-install proof is `pip install -r requirements.txt` in an empty venv
(recorded in `.workflow/artifacts/install-dependency-conflict/`). What these
tests can catch cheaply is a regression that reintroduces the known
unsatisfiable pair:

    rembg[cli] 2.0.85  -> python-multipart<0.0.22
    fastmcp 4.1.0      -> fastmcp-slim[server] -> python-multipart>=0.0.26

The checks parse the requirement lines instead of comparing exact strings,
so any spelling that reintroduces the conflict is caught.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "requirements.txt"

_NAME_RE = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?")


def _requirement_lines() -> list:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _split_requirement(line):
    """Return ``(name, extras_lower_set, rest)`` for a requirement line."""
    match = _NAME_RE.match(line)
    assert match, "unparseable requirement line: %r" % (line,)
    name = match.group(1).lower()
    extras_raw = match.group(2) or ""
    extras = {
        extra.strip().lower() for extra in extras_raw.strip("[]").split(",") if extra.strip()
    }
    rest = line[match.end():].lower()
    return name, extras, rest


def test_rembg_cli_extra_is_not_required():
    """`rembg[cli]` pins python-multipart<0.0.22 and breaks the install."""
    rembg_lines = [
        line for line in _requirement_lines() if _split_requirement(line)[0] == "rembg"
    ]
    assert rembg_lines, "requirements.txt must pin rembg"
    for line in rembg_lines:
        name, extras, rest = _split_requirement(line)
        assert "cli" not in extras, (
            "rembg[cli] conflicts with fastmcp's python-multipart>=0.0.26: %r"
            % (line,)
        )
        assert "cli" not in rest, (
            "any rembg line mentioning the cli extra reintroduces the "
            "python-multipart conflict: %r" % (line,)
        )
        assert "cpu" in extras, "use the [cpu] extra for onnxruntime: %r" % (line,)


def test_known_good_pins_present():
    by_name = {}
    for line in _requirement_lines():
        name, _extras, rest = _split_requirement(line)
        by_name.setdefault(name, []).append((line, rest))
    assert "fastmcp" in by_name, sorted(by_name)
    assert "rembg" in by_name, sorted(by_name)
    assert "pillow" in by_name, sorted(by_name)
    assert any("==4.1.0" in rest for _line, rest in by_name["fastmcp"]), by_name["fastmcp"]


def test_requirements_do_not_pin_python_multipart_directly():
    """Pinning it here would fight whatever the two libraries negotiate."""
    for line in _requirement_lines():
        name, _extras, _rest = _split_requirement(line)
        assert name != "python-multipart", (
            "do not pin python-multipart directly (fastmcp needs >=0.0.26, "
            "rembg's cli extra needed <0.0.22): %r" % (line,)
        )
