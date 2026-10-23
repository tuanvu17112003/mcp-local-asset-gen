# mcp-local-asset-gen

A local MCP server (FastMCP) that lets AI coding agents generate custom UI
assets — icons, illustrations, avatars — via a locally hosted image pipeline
(ComfyUI + FLUX.1-schnell) and embed them straight into the codebase. No cloud,
no uploads: diffusion, background removal, and vector-ready exports all run on
your machine.

## What it does

An agent call like this:

```json
{
  "prompt": "cute bear avatar, 3D claymorphism style, soft lighting",
  "category": "avatar",
  "save_path": "assets/images/bear_avatar.png",
  "remove_bg": true
}
```

triggers local ComfyUI generation → background removal (`rembg`) → trimmed,
padded, transparent PNG (+ `@2x`/`@3x`, optional pixel sizes and `.ico`) →
saved into your project, with the relative path returned for direct embedding:

```tsx
<img src={bearAvatar} alt="User Avatar" />
```

## Tools (4)

| Tool | Purpose |
|---|---|
| `generate_app_asset` | Text-to-image → postprocess → save; returns the asset path, seed, style |
| `refine_asset` | Image-to-image tweak of an existing asset (never mutates the parent) |
| `check_model` | Verify a model file is present in a ComfyUI loader (`unet`/`clip`/`vae`/`checkpoint`) |
| `server_info` | Backend reachability (`reachable`), queue depth, pinned model list, version |

Path confinement is server-side: tools can only write inside an approved
root — the project root plus any named workspace (`../../etc/pass.png` →
`POLICY_DENIED`), never overwrite without an explicit flag. The agent
chooses the output path: `save_path` may be relative (resolved under the
selected workspace root) or absolute (used exactly as given when it lands
inside an approved root; `--allow-any-path` lifts that check). The leaf
must be a lowercase `.png` file, so the requested path is the written path.
Results carry `asset_path` (relative to the owning root), `asset_root` (that
owning root) and `asset_path_absolute`.

## Prerequisites

- Python **≥ 3.11** (tested on 3.13), local ComfyUI (tested 0.41.0, any URL — default `http://127.0.0.1:8188`)
- A FLUX.1-schnell workflow: GGUF Q4_K_S (~6.8 GB, fits 10 GB VRAM) **or** the FP8 single file (~17.2 GB).
  Encoders: `t5xxl_fp8` + `clip_l`; VAE: `ae.safetensors`. GGUF needs the
  `ComfyUI-GGUF` custom node. See `src/gen_backend/setup_notes.md` + `docs/guides/`.
- GPU recommended (RTX 3080 10 GB verified: 512 px icon ≈ 30 s); CPU works, slower.

## Install

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; use bin/activate on Linux/macOS
pip install -r requirements.txt   # runtime (add -dev for pytest)
```

Download the weights into your ComfyUI `models/` folders
(`diffusion_models/`, `text_encoders/`, `vae/`) — they are **not** in this repo.

The background-removal model is downloaded once on first use (network
required); to pre-download it, run
`python -c "from rembg import new_session; new_session('u2net')"`.
Do **not** install `rembg[cpu,cli]`: its CLI extra pins
`python-multipart<0.0.22`, which conflicts with `fastmcp 4.1.0`
(`python-multipart>=0.0.26`) — the `rembg` console script is therefore not
usable; use the Python one-liner. Details: `docs/guides/setup-and-first-asset.md`.

## Run the server / register with a client

Direct:

```bash
python -m src.mcp_server.server --comfyui-url http://127.0.0.1:8000
```

OpenCode (`opencode.json`, V2 shape — adjust paths/URL to your machine):

```json
{
  "mcp": {
    "servers": {
      "asset-gen": {
        "type": "local",
        "command": ["<your-venv-python>", "<this-repo>/asset-gen.py",
                    "--comfyui-url", "http://127.0.0.1:8000"]
      }
    }
  }
}
```

Use the `asset-gen.py` launcher: it works from any working directory (no
`PYTHONPATH`, no pinned `cwd`). With no `--project-root`, the server jails
relative `save_path` values under the **client's workspace** — the project
you are working in — so the agent's chosen path lands where you expect.
Call `server_info` once to confirm `project_root` is your project; add
`"--project-root", "<dir>"` to pin a different tree.

Verify: call `server_info` → `{"backend":"comfyui", ..., "reachable":true}`.

Then generate, e.g. `generate_app_asset(prompt="...",
category="icon", save_path="assets/icons/app.png", icon_sizes=[32,64],
ico=true)` → PNG + `@2x/@3x` + `‑32px/‑64px` + `.ico`, all embedded by path.

## Verify

```bash
pytest tests/ -q   # 343 passed + environment-conditional skips on a full env
```

`server_info` unreachable never errors (`reachable:false`); generation without
ComfyUI maps to `BACKEND_UNAVAILABLE` — both covered by tests.

## Layout

- `src/mcp_server/` — FastMCP tools, validation, orchestration, OpenCode wiring doc
- `src/gen_backend/` — ComfyUI adapter (submit/poll/fetch/cancel) + pinned API-format workflows
- `src/postprocess/` — `rembg` removal, trim/pad, multi-res, icon sizes, `.ico` export
- `examples/react/` — sample `UserProfile.tsx` + layout README
- `docs/` — architecture, interface contracts, setup guides
- `fixtures/`, `tests/` — canned payloads + suites

## Licenses / third-party notes (not legal advice)

- This repo: **Apache-2.0** (`LICENSE`).
- Pinned stack: FastMCP (Apache-2.0), `rembg` lib (MIT), Pillow (HPND), FLUX.1-schnell weights (Apache-2.0, commercial OK), FLUX.1-dev weights are **not** used (non-commercial).
- `bria-rmbg` is an **opt-in only** background-removal model under a **non-commercial** BRIA license — default stays `u2net`. Check `docs/contracts/` for the pinned contract versions.
