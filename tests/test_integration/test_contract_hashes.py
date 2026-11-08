"""Contract hash reproducibility (C1/C2/C3 v0.8 freezes).

The documented scheme (see `scripts/hash_contract.py`): SHA256 over the
contract file's LF bytes with every `sha256:<64hex>` field normalized out,
so the recorded value stays stable when it is written into the file.

This module makes the freeze machine-checkable from a TRACKED path: before
v0.8 the verifier lived in `.workflow/`, which is gitignored, so a reader of
the public repo could not re-verify a recorded hash.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "docs" / "contracts" / "mcp-local-asset-gen"
SCRIPT = ROOT / "scripts" / "hash_contract.py"

HASH_FIELD = re.compile(r"sha256:[0-9a-fA-F]{64}")

#: Recorded freeze per contract family, keyed by the doc's v0.8 marker.
EXPECTED = {
    "C1-mcp-asset-tool": "FFD49605348D5BC5CDB098B985C26A33DC55AB1CD1B3C79124C3C3AAC3252BA5",
    "C2-gen-backend-job": "50624C3EA22F0CD9BC6D4A97D8E583566E7F674AA7D84253BB235B7AC6C7C28A",
    "C3-processed-asset": "47A8A9E911072EF20485B44CFAE6A25FEB9CE9A1938C5E7291712FAA7A9A2B2B",
}


def _content_hash(path: Path) -> str:
    """Re-implement the documented scheme independently of the script."""
    import hashlib

    text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = HASH_FIELD.sub("sha256:<64hex>", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def test_hash_script_is_tracked_and_runnable():
    assert SCRIPT.is_file(), "scripts/hash_contract.py must ship with the repo"
    assert "hashlib" in SCRIPT.read_text(encoding="utf-8")


@pytest.mark.parametrize("family,expected", sorted(EXPECTED.items()))
def test_recorded_freeze_hash_matches_file(family, expected):
    path = CONTRACTS / family / "contract.md"
    assert path.is_file(), path
    assert _content_hash(path) == expected, (
        "contract %s changed without re-freezing its recorded hash" % (family,)
    )


@pytest.mark.parametrize("family,expected", sorted(EXPECTED.items()))
def test_recorded_hash_appears_in_the_document(family, expected):
    text = (CONTRACTS / family / "contract.md").read_text(encoding="utf-8")
    assert "sha256:" + expected in text
