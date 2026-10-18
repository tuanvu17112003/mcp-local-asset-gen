# Setup notes — gen_backend (ComfyUI + models)

DOCUMENT ONLY. Never executed here: no installs, no downloads (no covering
authority in this slice). Contract: C2-gen-backend-job v0.1.0.

## Python route (env here is 3.10.11; floor is 3.11)

```bash
uv venv --python 3.11 .venv        # or: python3.11 -m venv .venv
# activate .venv, then install the project's pinned deps (see project docs)
```

## ComfyUI install pointer

- Install ComfyUI portable or from source (upstream `comfyanonymous/ComfyUI`),
  plus the **ComfyUI-GGUF** custom extension (city96) for the default Q4
  workflow (`UnetLoaderGGUF` node). The FP8 scale-up workflow needs no custom
  nodes.
- Serve locally: default endpoint `http://127.0.0.1:8188` (localhost only;
  no remote host without explicit authority + TLS decision).
- Verify with `/system_stats` or queue a pinned workflow before IC-1.

## Model placement (nothing downloaded by this slice)

| Variant | File | Size | Placement | VRAM |
|---|---|---|---|---|
| GGUF-Q4 **(default, 10 GB target)** | `flux1-schnell-Q4_K_S.gguf` | ~6.8 GB | `models/unet/` (GGUF loader dir) | ~6.5 GB peak, T5-XXL on CPU |
| GGUF-Q4 text encoders | `t5xxl_fp16.safetensors` + `clip_l.safetensors` | — | `models/clip/` | CPU (`device=cpu`) |
| GGUF-Q4 VAE | `ae.safetensors` | — | `models/vae/` | tiling / CPU-VAE fallback |
| FP8 (scale-up) | `flux1-schnell-fp8.safetensors` | ~17.2 GB | `models/checkpoints/` | >=12-16 GB |

Missing FP8 file surfaces as `MODEL_NOT_FOUND` with the
`models/checkpoints/` placement hint.

## VRAM flags (per target machine)

- 10 GB (RTX 3080): `--lowvram`, optionally `--reserve-vram <GB>`; VAE
  tiling or CPU-VAE for the GGUF path.
- Tight fits: `--novram` (slowest, fully offloaded) or `--vram-headroom`.
- Actual peak VRAM + s/image are measured at PQM0 IC-1 on the RTX 3080
  before acceptance; flags above are starting points, not results.
