# Architecture — mcp-local-asset-gen

Project: `mcp-local-asset-gen` (alt: `opencode-asset-designer`).
Status: Refined draft v0.2 (2026-10-17 quick research) — user decisions
Q1–Q5 recorded in master plan; contracts still unfrozen until dispatch.
Research: `docs/research/mcp-local-asset-gen-quick-research-2026-10-17.md`.

## 1. Goal
Local MCP server / OpenCode plugin letting coding agents call
`generate_app_asset` / `refine_asset`, generate via local ComfyUI,
post-process (transparent PNG, optional SVG, multi-res), save into the
codebase, and return a relative path for direct embedding.

## 2. End-to-end flow (as proposed, unchanged)
Agent → MCP tool → local ComfyUI API (`127.0.0.1:8188`) →
PNG → rembg/RMBG background removal → trim/pad → optional
vtracer/potrace SVG → `@1x/@2x/@3x` export → saved file →
relative path returned → agent embeds in code.

## 3. Selected reuse path (refined 2026-10-17; freeze at dispatch)
- **MCP core:** Python `FastMCP` 2.x (decided Q1). `from fastmcp import
  FastMCP; @mcp.tool; mcp.run()` = stdio by default; `transport="http" /
  "streamable-http"` for HTTP (`/mcp`); SSE is superseded — do not use.
  OpenCode V2 wiring is `mcp.servers.<name> = {type:"local", command:[...]}`
  (no `enabled` field; `disabled:true` to pause). No custom transport code.
- **Backend:** ComfyUI API-format workflow JSON (decided Q2). `POST /prompt`
  `{"prompt": {...numeric IDs...}}` → `prompt_id`; poll
  `GET /history/{id}` (1 s, up to 300 s); fetch `GET /view`; cancel
  `POST /interrupt`. WebSocket is convenience only, never the source of
  truth. GPU-less CI uses a `fake_comfyui` stand-in + canned history.
- **Models:** FLUX.1-schnell (decided Q3, Apache-2.0). MVP default for the
  confirmed RTX 3080 10 GB target (adopted 2026-10-17): GGUF Q4_K_S backbone
  (~6.8 GB file, ~6.5 GB peak with T5-XXL offloaded to CPU), 512 px, 4 steps,
  guidance 0.0, VAE tiling / CPU-VAE fallback. Scale-up alternative: Comfy-Org
  FP8 single file (`flux1-schnell-fp8.safetensors`, ~17.2 GB) for ≥12–16 GB
  GPUs. Full FP16 (~23 GB + encoders) is the documented further scale-up.
  Dev variant is non-commercial — excluded. ComfyUI-GGUF loader (city96) +
  `--lowvram`/`--novram`/`--reserve-vram`/`--vram-headroom` flags per target.
- **Background removal:** `rembg` library (MIT) with **FOSS-safe default
  `u2net`** (fast) + quality option `isnet-general-use`; **`bria-rmbg /
  RMBG-1.4` is NON-commercial (paid BRIA agreement needed) → explicit
  opt-in only, default OFF**, flagged in C3. Note: `rembg` needs Python
  `>=3.11` (env here is 3.10.11 → `uv`/venv route at dispatch); models
  cache per-user (`U2NET_HOME`), offline pre-download (see the setup guide), session reuse.
- **Vectorization:** DEFERRED post-MVP per Q4. Verified for later:
  visioncortex `vtracer` (MIT, `pip install vtracer`; 1.0.0a4 API
  `convert_file/convert_bytes` + `Config` presets — differs from legacy
  0.6.x `convert_image_to_svg_py`, so pin at re-activation).
- **Style consistency:** preset prompt templates + local LoRAs (Flat, 3D
  Claymorphism, Minimalist Line, Pixel Art).

Sources (accessed 2026-10-17): Comfy-Org/comfy-mcp README (40 tools,
stdio, wraps `comfy-cli`, beta); `comfyui-mcp` PyPI (FastMCP,
`--comfyui.host 127.0.0.1:8188`); joenorton/comfyui-mcp-server README
(`generate_image`/`regenerate`/`view_image`, streamable-http
`127.0.0.1:9000/mcp`); danielgatis/rembg README (Python `>=3.11,<3.14`,
`bria-rmbg` default). Full URLs in master plan discovery record.

## 4. Module decomposition
| Module | Owns | Produces → consumes |
|---|---|---|
| `mod-mcp-core` | MCP server, tool schemas, config, OpenCode wiring | C1 provider; orchestrates C2/C3 |
| `mod-gen-backend` | ComfyUI adapter, workflows, presets, txt2img/img2img | C2 provider → core + postprocess |
| `mod-postprocess` | rembg, trim/pad, multi-res, SVG | C3 provider → core + integration |
| `mod-integration` | File layout, sample `UserProfile.tsx`, docs, consumer checks | C1/C3 consumer, early + final integration evidence |

Tight cycle core↔backend↔postprocess broken by contract-first order:
C1/C2/C3 drafted → backend slice → early integration → postprocess →
full integration. No arbitrary folder-count split.

## 5. Directory ownership (proposed, new repo — root TBD per Q5)
| Path | Owner |
|---|---|
| `src/mcp_server/` | mod-mcp-core (exclusive) |
| `src/gen_backend/workflows/` | mod-gen-backend (exclusive) |
| `src/postprocess/` | mod-postprocess (exclusive) |
| `examples/react/` | mod-integration (exclusive) |
| `docs/architecture/mcp-local-asset-gen/` | PQM0 |
| `docs/contracts/mcp-local-asset-gen/*/` | PQM0 |
| `.workflow/master/mcp-local-asset-gen/` | PQM0 |
| `.workflow/modules/<id>/` | owning Module PQM after handoff |
| Root build/config/lockfiles/fixtures | single owner assigned at dispatch (default mod-mcp-core proposes, PQM0 confirms) |

Shared resources: ComfyUI endpoint (`127.0.0.1:8188`), GPU/VRAM, model
cache, output dirs — serialized/reserved per assignment; ports recorded
in contracts.

## 6. Non-goals / exclusions (refined)
No cloud GPU execution, no hosted background-removal API, no IDE
marketplace publish, no mobile `@1x/@2x/@3x` beyond file export +
sample wiring (React-only MVP per Q4). `bria-rmbg` commercial use excluded
from MVP (opt-in, default OFF). No Git init/commit/push without
covering authority (PROJECT_START: currently non-Git root).
