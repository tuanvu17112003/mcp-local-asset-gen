"""End-to-end checks against the GPU-less fake ComfyUI server.

Wiring under test: ``fixtures/fake_comfyui.py`` serves the C2 REST surface
(``fixtures/c2/fake_comfyui.md``) on an ephemeral loopback port while the
REAL ``gen_backend.ComfyClient``, the REAL ``AssetOrchestrator`` and the real
postprocess pipeline drive it. Nothing is mocked beyond the server itself, so
a regression in the HTTP map (submit / queue / history / view / upload /
object_info) fails here instead of only on a GPU box.

No live ComfyUI, no GPU, no model download: the served PNG is a synthetic
512x512 RGBA render, and the end-to-end generate runs with ``remove_bg``
off so the rembg live path is never entered.
"""

from __future__ import annotations

import io
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

pillow = pytest.importorskip("PIL.Image")  # skip cleanly without Pillow

ROOT = Path(__file__).resolve().parents[2]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixtures.fake_comfyui import OBJECT_INFO, PNG_SIZE, start_fake_comfyui  # noqa: E402

from gen_backend import submit_txt2img  # noqa: E402
from gen_backend.client import ComfyClient  # noqa: E402
from mcp_server.config import ServerConfig  # noqa: E402
from mcp_server.orchestrator import AssetOrchestrator  # noqa: E402


@pytest.fixture()
def fake():
    """Running fake ComfyUI on an ephemeral loopback port."""
    handle = start_fake_comfyui()
    try:
        yield handle
    finally:
        handle.stop()


def _get_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as response:
        import json

        return json.loads(response.read().decode("utf-8"))


# -- server basics ------------------------------------------------------------


def test_fake_serves_512_rgba_png(fake):
    with urllib.request.urlopen(fake.url + "/view?filename=x.png", timeout=10) as response:
        blob = response.read()
    assert response.headers.get_content_type() == "image/png"
    assert blob.startswith(b"\x89PNG\r\n\x1a\n"), "not a real PNG"
    image = pillow.open(io.BytesIO(blob))
    image.load()
    assert image.size == (PNG_SIZE, PNG_SIZE)
    assert image.mode == "RGBA"


def test_fake_object_info_is_real_shaped(fake):
    for node in (
        "UnetLoaderGGUF",
        "DualCLIPLoader",
        "VAELoader",
        "UpscaleModelLoader",
        "LoaderImage",
        "LoaderOutput",
    ):
        assert node in OBJECT_INFO, node
    payload = _get_json(fake.url + "/object_info/UnetLoaderGGUF")
    assert isinstance(payload, dict)
    required = payload["UnetLoaderGGUF"]["input"]["required"]
    assert required["unet_name"][0] == ["flux1-schnell-Q4_K_S.gguf"]


def test_fake_stop_is_idempotent():
    handle = start_fake_comfyui()
    url = handle.url
    handle.stop()
    handle.stop()  # second stop must not raise
    with pytest.raises(Exception):
        urllib.request.urlopen(url + "/queue", timeout=2)


# -- gen_backend against the fake --------------------------------------------


def test_submit_history_view_roundtrip_returns_png(fake):
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=30)
    prompt_id = submit_txt2img(client, prompt="a bear icon", seed=1234)
    assert prompt_id.startswith("prompt-")
    result = client.fetch_result(prompt_id)
    blob = result["png_bytes"]
    assert blob.startswith(b"\x89PNG\r\n\x1a\n")
    image = pillow.open(io.BytesIO(blob))
    image.load()
    assert image.size == (PNG_SIZE, PNG_SIZE)
    assert result["seed"] == 1234


def test_upload_image_roundtrips_name(fake):
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=30)
    png = fake_png_bytes()
    response = client.upload_image(png, filename="source-asset.png")
    assert response == {
        "name": "source-asset.png",
        "subfolder": "asset-gen",
        "type": "input",
    }


def test_loader_files_reads_object_info(fake):
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=30)
    files = client.loader_files("VAELoader")
    assert files == {"vae_name": ["ae.safetensors"]}


def test_interrupt_cancels_history_entry(fake):
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=30)
    prompt_id = submit_txt2img(client, prompt="cancel me")
    assert client.cancel(prompt_id=prompt_id) is True
    assert client.queue_status(prompt_id) == "not_found"


def fake_png_bytes() -> bytes:
    """Real PNG bytes for upload tests (also the fake server render)."""
    buffer = io.BytesIO()
    pillow.new("RGBA", (16, 16), (10, 20, 30, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


# -- orchestrator against the fake -------------------------------------------


def test_server_info_reports_fake_reachable(fake, tmp_path):
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=30)
    orch = AssetOrchestrator(
        client,
        config=ServerConfig(project_root=str(tmp_path), comfyui_url=fake.url),
    )
    info = orch.server_info()
    assert info["reachable"] is True
    assert info["queue_depth"] == 0
    assert info["comfyui_url"] == fake.url
    assert info["project_root"] == str(tmp_path)


def test_generate_end_to_end_writes_assets(fake, tmp_path):
    """Full generate against the fake: submit -> poll -> view -> postprocess -> disk."""
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=30)
    orch = AssetOrchestrator(
        client,
        config=ServerConfig(project_root=str(tmp_path), comfyui_url=fake.url),
    )
    result = orch.generate(
        {
            "prompt": "flat bear icon",
            "category": "illustration",
            "save_path": "assets/bear.png",
            "width": 64,
            "height": 64,
            "remove_bg": False,
        },
        str(tmp_path),
    )
    base = Path(result["asset_path_absolute"])
    assert base.is_file()
    assert result["asset_path"] == "assets/bear.png"
    written = sorted(path.name for path in base.parent.iterdir())
    assert "bear.png" in written
    assert "bear@2x.png" in written
    assert "bear@3x.png" in written
    image = pillow.open(base)
    image.load()
    assert image.mode == "RGBA"


def test_refine_end_to_end_uses_uploaded_source(fake, tmp_path):
    """refine_asset uploads the parent, then writes a NEW file next to it."""
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=30)
    orch = AssetOrchestrator(
        client,
        config=ServerConfig(project_root=str(tmp_path), comfyui_url=fake.url),
    )
    generated = orch.generate(
        {
            "prompt": "flat bear icon",
            "category": "illustration",
            "save_path": "assets/bear.png",
            "width": 64,
            "height": 64,
            "remove_bg": False,
        },
        str(tmp_path),
    )
    refined = orch.refine(
        {
            "asset_path": generated["asset_path"],
            "instruction": "make it warmer",
            "strength": 0.7,
        },
        str(tmp_path),
    )
    assert refined["asset_path"] == "assets/bear_refined.png"
    assert Path(refined["asset_path_absolute"]).is_file()
    assert Path(generated["asset_path_absolute"]).is_file(), "parent must survive"


def test_check_model_against_fake(fake, tmp_path):
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=30)
    orch = AssetOrchestrator(
        client,
        config=ServerConfig(project_root=str(tmp_path), comfyui_url=fake.url),
    )
    found = orch.check_model("flux1-schnell-Q4_K_S.gguf", "unet")
    assert found["available"] is True
    assert found["loader"] == "UnetLoaderGGUF"
    missing = orch.check_model("ghost.safetensors", "vae")
    assert missing["available"] is False


def test_fake_is_not_reachable_after_stop(fake):
    client = ComfyClient(base_url=fake.url, poll_interval=0.01, max_wait_s=5)
    fake.stop()
    from gen_backend.errors import ComfyUnreachableError

    with pytest.raises(ComfyUnreachableError):
        client.loader_files("VAELoader")
