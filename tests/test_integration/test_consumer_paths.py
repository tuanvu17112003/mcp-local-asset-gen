"""Consumer path-resolves + join-rule checks (mod-integration, slice 2).

Offline consumer-expectation checks only: the React sample import must
resolve to the C1 golden shape, and the ``output_dir / filename`` join
rule must reproduce the contract ``path`` for every canned chain entry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
TSX = ROOT / "examples" / "react" / "UserProfile.tsx"
C1_CALL = ROOT / "fixtures" / "c1" / "bear_avatar_call.json"
C1_RESULT = ROOT / "fixtures" / "c1" / "bear_avatar_result.json"
CHAIN = ROOT / "fixtures" / "integration" / "bear_avatar_chain.json"
MANIFEST = ROOT / "fixtures" / "integration" / "layout_manifest.json"

EXPECTED_ASSET_PATH = "assets/images/bear_avatar.png"
EXPECTED_IMPORT = "../../assets/images/bear_avatar.png"

NAMING_RULE = re.compile(r"[A-Za-z0-9._-]+(@[23]x)?\.(png|svg)")


def test_tsx_import_resolves_to_c1_golden():
    src = TSX.read_text(encoding="utf-8")
    assert EXPECTED_IMPORT in src
    assert "<img src={bearAvatar}" in src
    call = json.loads(C1_CALL.read_text(encoding="utf-8"))
    result = json.loads(C1_RESULT.read_text(encoding="utf-8"))
    assert result["asset_path"] == EXPECTED_ASSET_PATH
    assert call["save_path"] == EXPECTED_ASSET_PATH
    assert call["category"] == "avatar"
    assert call["remove_bg"] is True


def test_join_rule_produces_contract_path():
    chain = json.loads(CHAIN.read_text(encoding="utf-8"))
    output_dir = chain["output_dir"]
    assert chain["c1_golden_echo"]["asset_path"] == EXPECTED_ASSET_PATH
    entries = chain["c3_style_files"]
    assert len(entries) == 3
    for entry in entries:
        joined = str(PurePosixPath(output_dir) / entry["filename"])
        assert entry["path"] == joined
        assert NAMING_RULE.fullmatch(entry["filename"]), entry["filename"]
        assert ".." not in entry["path"].split("/")


def test_retina_variants_are_exact_multiples():
    chain = json.loads(CHAIN.read_text(encoding="utf-8"))
    by_scale = {e["scale"]: e for e in chain["c3_style_files"]}
    base = by_scale["1x"]
    assert (base["width"], base["height"]) == (512, 512)
    assert base["filename"] == "bear_avatar.png"
    for scale, name in (("2x", "bear_avatar@2x.png"), ("3x", "bear_avatar@3x.png")):
        entry = by_scale[scale]
        assert entry["filename"] == name
        factor = int(scale[0])
        assert entry["width"] == base["width"] * factor
        assert entry["height"] == base["height"] * factor


def test_layout_manifest_matches_chain():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    chain = json.loads(CHAIN.read_text(encoding="utf-8"))
    assert manifest["join_rule"] == "path = output_dir / filename"
    assert manifest["output_dir"] == chain["output_dir"]
    assert manifest["stem"] == chain["stem"] == "bear_avatar"
    chain_paths = {(e["path"], e["width"], e["height"], e["scale"]) for e in chain["c3_style_files"]}
    manifest_paths = {(e["path"], e["width"], e["height"], e["scale"]) for e in manifest["expected"]}
    assert manifest_paths == chain_paths
