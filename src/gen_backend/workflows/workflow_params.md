# Workflow parameterization — C2-gen-backend-job v0.1.0

Both MVP workflows are ComfyUI **API-format**: numeric string node IDs, no
layout keys (`pos`, `widgets_values`, `size`). Submitted via
`POST /prompt` as `{"prompt": {<nodes>}}`.

`presets.inject_params()` loads one of these files, overwrites the nodes
below, **strips the human-only `_meta` key** (never submitted — ComfyUI
expects numeric node IDs only), and returns the submittable prompt dict.

## Shared node-ID map (both workflows)

| Node | class_type | Takes parameter |
|---|---|---|
| `4` | CLIPTextEncode (positive) | `prompt` (+ style template applied by `build_txt2img_params`) |
| `5` | CLIPTextEncode (negative) | `negative` (default `""`) |
| `6` | EmptyLatentImage | `width`, `height` (default 512x512) |
| `7` | KSampler | `seed`, `steps` (1-4, default 4); `cfg` stays 1.0, `denoise` 1.0 for txt2img |
| `10` | ModelSamplingFlux | `guidance` fixed `0.0` (schnell, enforced); `width`/`height` echoed |
| `8` | VAEDecode | — (wired) |
| `9` | SaveImage | — (output; `fetch_result` reads `GET /view` refs from `/history`) |

## Per-workflow loader nodes (differ)

GGUF-Q4 (`txt2img-flux-schnell-gguf-q4`, DEFAULT):

| Node | class_type | Notes |
|---|---|---|
| `1` | UnetLoaderGGUF | `unet_name="flux1-schnell-Q4_K_S.gguf"` in `models/unet/` (ComfyUI-GGUF extension dir) |
| `2` | DualCLIPLoader | T5-XXL + CLIP-L, `device="cpu"` (encoders offloaded) |
| `3` | VAELoader | `ae.safetensors` in `models/vae/`; tile VAE / CPU-VAE on low VRAM |

FP8 (`txt2img-flux-schnell-fp8`, scale-up):

| Node | class_type | Notes |
|---|---|---|
| `1` | CheckpointLoaderSimple | `ckpt_name="flux1-schnell-fp8.safetensors"` in `models/checkpoints/` |
| — | (no nodes 2/3) | CLIP (`["1",1]`) and VAE (`["1",2]`) come from the checkpoint |

## img2img wiring note (no JSON pinned yet)

img2img reuses a txt2img graph with two added nodes: `11` LoadImage
(`image` = basename of the input PNG, which must pre-exist in the ComfyUI
input dir under that basename — no upload is performed by this adapter;
live `/upload/image` wiring is an IC-2 item, unconfirmed without a live
ComfyUI) → `12` VAEEncode
(`vae` = same source as node `8`) → node `7` KSampler takes
`latent_image=["12",0]` and `denoise=<strength>` (0..1, default 0.6).
See `img2img.IMG2IMG_NODE_MAP`. Source file is only read, never mutated.
