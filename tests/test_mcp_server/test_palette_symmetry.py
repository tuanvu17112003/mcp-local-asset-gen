"""P3 palette + P4 symmetry tests: postprocess units, validation, passthrough."""

from __future__ import annotations

import io

import pytest
from PIL import Image

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


def _rgba(w=32, h=32):
    img = Image.new("RGBA", (w, h), (12, 200, 90, 255))
    img.putpixel((5, 5), (250, 30, 30, 255))
    img.putpixel((20, 15), (0, 0, 0, 0))  # one transparent pixel
    return img


# -- postprocess units ------------------------------------------------------

def test_recolor_output_uses_only_palette_colors():
    from src.postprocess.palette import recolor_to_palette

    out = recolor_to_palette(_rgba(), ["#ff0000", "#00ff00", "#0000ff"])
    assert out.mode == "RGBA" and out.size == (32, 32)
    allowed = {(255, 0, 0), (0, 255, 0), (0, 0, 255)}
    raw = out.tobytes()
    rgb = {(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 4)}
    assert rgb <= allowed
    # Alpha survives (the transparent pixel stayed transparent).
    assert out.getpixel((20, 15))[3] == 0


def test_recolor_is_deterministic_and_nearest():
    from src.postprocess.palette import recolor_to_palette

    src = _rgba()
    a = recolor_to_palette(src, ["#ff0000", "#00ff00", "#0000ff"])
    b = recolor_to_palette(src, ["#ff0000", "#00ff00", "#0000ff"])
    assert a.tobytes() == b.tobytes()
    # (12,200,90) is nearest to pure green; (250,30,30) nearest to red.
    assert a.getpixel((0, 0))[:3] == (0, 255, 0)
    assert a.getpixel((5, 5))[:3] == (255, 0, 0)


def test_symmetrize_mirror_x():
    from src.postprocess.symmetry import symmetrize

    img = Image.new("RGBA", (8, 4), (0, 0, 0, 255))
    img.putpixel((1, 1), (255, 0, 0, 255))
    out = symmetrize(img, "mirror-x")
    assert out.size == (8, 4)
    # Mirror: out[x] == out[w-1-x].
    for x in range(8):
        assert out.getpixel((x, 1)) == out.getpixel((7 - x, 1))


def test_symmetrize_mirror_quad_both_axes():
    from src.postprocess.symmetry import symmetrize

    img = Image.new("RGBA", (8, 8), (0, 0, 0, 255))
    img.putpixel((1, 1), (0, 255, 0, 255))
    out = symmetrize(img, "mirror-quad")
    for x in range(8):
        for y in range(8):
            assert out.getpixel((x, y)) == out.getpixel((7 - x, 7 - y))


def test_symmetrize_radial_fourfold():
    from src.postprocess.symmetry import symmetrize

    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    # Red dot inside the first wedge (angle 45 degrees, radius ~30).
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            img.putpixel((71 + dx, 71 + dy), (255, 0, 0, 255))
    out = symmetrize(img, "radial:4")
    assert out.size == (100, 100)
    # The dot must repeat at 90-degree steps around the center.
    for x, y in [(71, 71), (71, 29), (29, 29), (29, 71)]:
        r, g, b, a = out.getpixel((x, y))
        assert r > 200 and g < 60, (x, y, out.getpixel((x, y)))


def test_symmetrize_unknown_mode_raises():
    from src.postprocess.symmetry import symmetrize

    with pytest.raises(ValueError, match="UNKNOWN_SYMMETRY"):
        symmetrize(_rgba(), "spin")


# -- validation ---------------------------------------------------------------

def test_palette_validation():
    from src.mcp_server.validation import validate_tool_args

    args = validate_tool_args(
        prompt="x", category="icon", save_path="a/p.png",
        palette=["#FF0000", "#0f0", "#0000AA"],
    )
    assert args["palette"] == ["#ff0000", "#00ff00", "#0000aa"]
    for bad in (
        ["#ff0000"],                      # 1 color
        ["#ff0000"] * 9,                  # 9 colors
        ["red"],                          # not hex
        "#ff0000",                        # bare string
        ["#gg0000"],                      # bad digits
    ):
        with pytest.raises(ValueError, match="INVALID_PALETTE"):
            validate_tool_args(
                prompt="x", category="icon", save_path="a/p.png", palette=bad
            )


def test_symmetry_validation():
    from src.mcp_server.validation import validate_tool_args

    for good in ("mirror-x", "mirror-quad", "radial:6", "Radial:12"):
        args = validate_tool_args(
            prompt="x", category="icon", save_path="a/p.png", symmetry=good
        )
    assert args["symmetry"] == "radial:12"
    for bad in ("spin", "radial:1", "radial:13", "radial:x", 42):
        with pytest.raises(ValueError, match="INVALID_SYMMETRY"):
            validate_tool_args(
                prompt="x", category="icon", save_path="a/p.png", symmetry=bad
            )


# -- pipeline + orchestrator passthrough --------------------------------------

def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_pipeline_applies_palette_last():
    from src.postprocess.pipeline import process

    png = _png_bytes(Image.new("RGBA", (512, 512), (90, 90, 90, 255)))
    res = process(
        png, remove_bg=False, trim=False,
        palette=["#112233", "#445566"],
    )
    base = res["files"][0]
    img = Image.open(io.BytesIO(base["png_bytes"])).convert("RGBA")
    raw = img.tobytes()
    rgb = {(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 4)}
    assert rgb <= {(17, 34, 51), (68, 85, 102)}


def test_orchestrator_passes_palette_and_symmetry(tmp_path):
    from src.mcp_server.orchestrator import AssetOrchestrator
    from src.mcp_server.validation import validate_tool_args

    calls = {}

    class FakeBackend:
        def submit_txt2img(self, **kwargs):
            return "backend-job-1"

        def fetch_result(self, job_id):
            return {"png_bytes": FAKE_PNG, "seed": 7}

    def fake_postprocess(png_bytes, **kwargs):
        calls.update(kwargs)
        stem = kwargs.get("stem", "icon")
        return {
            "files": [{"filename": "%s.png" % stem, "png_bytes": bytes(png_bytes)}],
            "alpha": True,
            "model_used": "none",
        }

    orch = AssetOrchestrator(
        FakeBackend(), postprocess=fake_postprocess, writer=lambda p, d: None
    )
    args = validate_tool_args(
        prompt="mandala", category="illustration", save_path="a/m.png",
        palette=["#000000", "#ffffff"], symmetry="radial:8",
    )
    orch.generate(args, tmp_path)
    assert calls["palette"] == ["#000000", "#ffffff"]
    assert calls["symmetry"] == "radial:8"
