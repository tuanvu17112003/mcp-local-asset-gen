# Quick research — mcp-local-asset-gen (round 2, 2026-10-17)

Owner: PQM0 (direct research; no Explorer subagent — bounded follow-up,
planning-only, no sessions created). Intent: refine held drafts, not to
install/add dependencies (research ≠ authorization).

Decided context (user answers 2026-10-17): Python FastMCP · ComfyUI API ·
FLUX.1-schnell · PNG-first MVP (SVG deferred, React-only) · Nested topology.

## 1. Verified facts (source-backed claims)

### F1 — FastMCP 2.x server shape
- Finding: `from fastmcp import FastMCP; mcp = FastMCP("Name"); @mcp.tool`
  `def f(...): ...; mcp.run()` defaults to **stdio**; `mcp.run(transport="http"
  |"streamable-http"|"sse", host, port)` serves HTTP (`/mcp`). CLI:
  `fastmcp run server.py [--transport http --port 8000] [--python 3.11]
  [--with pkg]`. SSE is superseded (do not build on it).
- Sources: gofastmcp.com welcome + CLI patterns + running-server guide;
  modelcontextprotocol/python-sdk `run/` doc (v2.3.0); PrefectHQ/fastmcp
  `test_streamable_http.py`. Accessed 2026-10-17.
- Limitation: versions move; pin at dispatch (`pip freeze`).
- Affects: C1 transport, mod-mcp-core slice 1.

### F2 — OpenCode V2 MCP wiring (corrects earlier draft)
- Finding: V2 servers live under **`mcp.servers.<name>`** with
  `{type:"local", command:[...], cwd?, environment?, disabled?}` for stdio
  subprocesses, or `{type:"remote", url, headers?, oauth?}` for HTTP.
  There is **no V2 `enabled` field** (`disabled:true` to keep without
  connecting). `{env:NAME}` substitution; secrets stay in env, not JSON.
- Sources: v2.opencode.ai `mcp.md` / `mcp-servers`; dev.opencode.ai V2
  `mcp-servers`. Accessed 2026-10-17.
- Limitation: V1 `mcp.<name>` + `enabled` shape seen in older docs does NOT
  apply to V2 — earlier C1 text citing `127.0.0.1:9000/mcp` was a
  joenorton-example leftover, corrected in refinement.
- Affects: C1, mod-integration docs (AC-4 15-min run).

### F3 — ComfyUI server API surface
- Finding: Submit API-format workflow via **`POST /prompt`** body
  `{"prompt": {<numeric-id>: {class_type, inputs, _meta}}, client_id?, ...}` →
  `{prompt_id}`. Poll **`GET /history/{prompt_id}`** (+ `GET /queue`,
  `GET /prompt` status); fetch files via **`GET /view?filename=&subfolder=&type=`**;
  cancel via **`POST /interrupt`** (native) / `/queue` mgmt. API format =
  numeric node IDs, no layout/position data; export via File → Export
  Workflow (API). WebSocket (`/ws`) is a live convenience; polling is the
  source of truth (1 s interval is the proven default; joenorton impl: 1 s ×
  30 attempts; local MVP should allow up to 300 s for slow GPUs).
- Sources: docs.comfy.org workflow-api-format, api-examples
  (`basic_api_example.py`, `websockets_api_example.py`), comms_routes table,
  cloud/overview; joenorton/comfyui-mcp-server `docs/ARCHITECTURE.md`;
  ComfyUI_frontend `api.ts` (`queuePrompt`); Comfy-Org/comfy-api-proxy
  (fake_comfyui stand-in for GPU-less tests). Accessed 2026-10-17.
- Limitation: no live ComfyUI probed in this env.
- Affects: C2 operations/endpoints/polling/fixtures, IC-1, fake-ComfyUI test plan.

### F4 — FLUX.1-schnell model facts (Apache-2.0, FP8 single file)
- Finding: **FLUX.1-schnell = Apache-2.0**, 12 B params, **4 steps**,
  guidance **0.0**. Comfy-Org single-file FP8 checkpoint
  `Comfy-Org/flux1-schnell/flux1-schnell-fp8.safetensors` ≈ **17.2 GB**,
  loaded via **Load Checkpoint** node (CLIP+VAE merged). Full-precision
  variant ≈ 23 GB UNet + encoders (t5xxl 9.2 GB fp16 / 4.6 GB fp8, clip_l
  235 MB, ae VAE 320 MB). VRAM rule of thumb: ~24 GB FP16, ~12 GB FP8,
  6–8 GB GGUF-Q4 possible; 512 px icon MVP is the light end. Dev variant is
  NON-commercial — schnell is the correct FOSS default.
- Sources: docs.comfy.org flux tutorial; huggingface.co/Comfy-Org/flux1-schnell
  (17.2 GB file page); black-forest-labs/FLUX.1-schnell (apache-2.0) +
  discussions 18/89; marcinbogdanski/comfyui-art-gen (FP8 path +
  `flux_schnell_fp8.png` workflow); willitrunai + localaimaster VRAM tables.
  Accessed 2026-10-17.
- Limitation: download needs HF ToS/token for official files; 17 GB disk +
  RAM/VRAM unverified here.
- Affects: C2 defaults (workflow_id `flux-schnell-fp8`, steps 4), dispatch
  env check, model-placement docs.

### F5 — Background-removal licensing (MATERIAL correction)
- Finding: `rembg` **code = MIT** (danielgatis), Python `>=3.11,<3.14`
  (onnxruntime-bound). BUT the **default model `bria-rmbg` / RMBG-1.4 is
  source-available NON-commercial** (`bria-rmbg-1.4` license; commercial use
  needs a paid BRIA agreement). RMBG-2.0 likewise commercial-gated. The
  original idea's "rembg / briaai/RMBG-1.4 … offline" stack is therefore NOT
  FOSS-by-default. FOSS-safe in-repo alternatives: **`u2net / u2netp /
  u2net_human_seg` and `isnet-general-use`** (long-standing rembg options;
  u2net* is the small/fast classic, isnet-general-use the quality pick),
  plus `birefnet-*` family. rembg caches models per-user (`~/.u2net` /
  `U2NET_HOME`), `rembg d` pre-downloads, `new_session()` reuse avoids
  reloads. bria-rmbg ONNX ≈ 1 GB @1024 — slower than u2net.
- Sources: huggingface.co/briaai/RMBG-1.4 (LICENSE/README: "non-commercial
  use… purchase a commercial license"); danielgatis/rembg README + LICENSE
  (MIT) + open-mit/rembg mirror; cran/rembg port (model list). Accessed
  2026-10-17.
- Limitation: per-model weight licenses should be re-pinned at dispatch
  (check exact ONNX card); legal review for any commercial distribution.
- Affects: C3 default model, MVP quality expectation, new residual risk +
  user-facing license note. RECOMMENDATION: MVP default
  `u2net` (fast) with `isnet-general-use` quality option; `bria-rmbg` as
  explicit opt-in with license-acceptance flag. (No new user interview:
  falls inside decided PNG-first MVP; recorded as PQM provisional pending
  dispatch freeze.)

### F6 — vtracer (deferred, but verified for later)
- Finding: visioncortex **vtracer = MIT** ("VTracer 1 stays open. Forever."),
  `pip install vtracer` (legacy 0.6.x `convert_image_to_svg_py` file-to-file;
  1.0.0a4 `convert_file/convert_bytes/convert_pixels` + `Config`
  presets `bw/poster/photo`, palette, hierarchical cutout). Handles color
  (unlike potrace binary-only). Python `>=3.7` — no 3.11 floor problem.
- Sources: visioncortex/vtracer README + crates/vtracer-py + PyPI vtracer;
  vtracer.visioncortex.org (VTracer 2 page, MIT statement). Accessed 2026-10-17.
- Affects: post-MVP SVG re-activation only; no C3-MVP change.

### F7 — Env gap (re-measured, unchanged)
- Finding: this checkout remains non-Git; `python --version` = 3.10.11
  (below rembg floor 3.11); Node v24.14.0. `uv run --python 3.11` /
  `fastmcp run --python 3.11` or a dedicated venv is the documented route;
  ComfyUI itself needs its own Python env + GPU.
- Source: direct shell observation 2026-10-17 (both rounds).
- Affects: dispatch env probe + mod-postprocess prerequisite.

## 2. Reuse evaluation (need → … → minimum custom)

| Need | Selected path | Alternatives rejected (why) | License/provenance | Maintenance/security | Compat/footprint/cost |
|---|---|---|---|---|---|
| MCP transport | FastMCP 2.x, stdio primary | Node SDK (extra port, no ComfyUI-pattern reuse); hand-rolled JSON-RPC (protocol burden) | FastMCP (PrefectHQ, Apache-2.0-series) + MCP SDK; pin at dispatch | Active (2.x); stdio = no open port by default; validate Host/Origin on HTTP | Thin; local single-user |
| ComfyUI submit/poll | `urllib`/`httpx` + `/prompt`→`/history`→`/view`, 1 s poll ≤300 s, API-format JSON | Cloud queue (needs GPU-less but costs + uploads); websocket-only (fragile w/o poll fallback) | ComfyUI (GPL-3.0 server, local use) + joenorton/comfyui-mcp-server (reference, Apache-2.0) | ComfyUI actively maintained; localhost-only default; no creds in params | 1 job ≤2 concurrent; fake_comfyui stand-in for CI |
| Diffusion weights | FLUX.1-schnell FP8 single file, 4 steps, guidance 0 | Dev (non-commercial — excluded); SDXL-Turbo (lighter but 2nd choice per Q3) | Apache-2.0, Black Forest Labs / Comfy-Org | Pinned hash at dispatch; 17 GB disk | ~12 GB VRAM FP8; 512 px MVP |
| Bg removal | rembg lib, default `u2net`, quality opt `isnet-general-use`, opt-in `bria-rmbg` (license-flagged) | Hosted removal APIs (upload + cost — excluded by scope); custom seg training (absurd) | rembg MIT; u2net/isnet weights FOSS-compatible; BRIA non-commercial (flag) | Pinned .onnx hash; offline cache; CPU ok | Session reuse; ≤15 s/512 px budget |
| Vector (deferred) | vtracer 1.0.0a4 pinned at re-activation | potrace (binary-only, weaker for color icons) | MIT visioncortex | Pin version (0.6 vs 1.0 API differs!) | File-exact SVG check |
| Resize/export | Pillow (stdlib-adjacent, MIT) | OpenCV (heavy) / sharp-Node (2nd runtime) | Pillow (HPND) | Ubiquitous, no service | Exact-multiple `@2x/@3x` |

Custom code stays thin: tool schemas + validation, workflow pinning +
param injection, pipeline glue, naming/layout. (Prior spec already said
this; research confirms no smaller path.)

## 3. Inference vs choice record
- Observed/sourced: F1–F7 above (with limits).
- Inference (PQM): 512 px schnell-FP8 + u2net keeps MVP inside 12 GB VRAM /
  CPU-postprocess envelope; quality risk is soft-edged masks on hair/fur —
  acceptable for flat/clay icons, mitigated by isnet option.
- Design choices (within decided scope, no new interview): C3 default flip
  bria→u2net/isnet + BRIA opt-in flag; C2 workflow pin flux-schnell-fp8;
  C1 OpenCode-V2 config correction; fake-ComfyUI + canned-history fixtures
  for GPU-less CI. Frozen only at dispatch.

## 4. Unresolved (blocks nothing until dispatch)
- U1: live ComfyUI presence + VRAM/disk on target machine (dispatch probe).
- U2: Python 3.11+ route (`uv`/venv) on target (dispatch probe).
- U3: exact pinned versions/hashes (fastmcp, rembg, onnxruntime, vtracer-later,
  .onnx weights, ComfyUI commit) — pin at dispatch freeze.
- U4: target working root / Git init authority (Q5 follow-through at dispatch).
- U5 (new): commercial-distribution intent — decides whether BRIA opt-in can
  ever default on (needs explicit user + legal authority; default stays OFF).

Next action: PQM0 applies §5 refinements to ARCHITECTURE + PLAN + C1/C2/C3
drafts (versions unchanged, still unfrozen), then returns to
`/u3-dispatch .workflow/master/mcp-local-asset-gen/PLAN.md`.
