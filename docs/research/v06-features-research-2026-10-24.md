# v0.7 feature research — WS progress, CI, PNG metadata, LoRA (2026-10-24)

Intent: verify fix paths for the four accepted follow-ups from the
2026-10-24 proposal list: (1) per-node WebSocket progress, (2) GitHub
Actions CI, (3) PNG tEXt metadata, (5) generic LoRA support. Research
only — no code changed. Sources accessed 2026-10-24.

## F1 — Per-node progress via ComfyUI WebSocket

**Facts (docs.comfy.org `comms_routes` + `comms_messages`; verified against
third-party write-ups):**
- `GET ws://{host}/ws?clientId=<uuid>` upgrades to a WebSocket; the server
  pushes JSON text frames keyed by `type`: `status`, `execution_start`,
  `executing` (`data.prompt_id`, `data.node`, null node = done),
  `progress` (`data.value`, `data.max`, `data.prompt_id`, `data.node`),
  `executed`, plus BINARY preview frames.
- Frames arrive for all clients; filter by `prompt_id`.
- History polling stays the source of truth (unchanged decision from the
  architecture draft).

**Design:** `websocket-client==1.9.2` (Apache-2.0, pure-Python, sync,
Python 3.10+; latest stable on PyPI, verified) — a hand-rolled RFC 6455
client (handshake + frame parsing + ping/pong) is ~150 lines and unsafe
to maintain; the dependency is justified. `ComfyClient.submit` already
accepts `client_id`; it now auto-generates one (uuid4) per submit and
remembers it; `poll(prompt_id, on_progress=None)` optionally opens the
WS for that client id and drains text frames each poll iteration,
forwarding `value/max` + node to the callback. Any WS failure (import
error, connect timeout, bad frame) silently disables the WS path —
progress is best-effort, polling keeps working. Binary frames ignored
(mid-run images cannot be delivered to an MCP caller without background
tasks — out of scope).

**Orchestrator bridge:** `_fetch_png_and_seed` detects
`on_progress` in `inspect.signature(backend.fetch_result).parameters`
(fake backends keep their 1-arg signature) and maps fraction `f` ∈ [0,1]
to progress value `1 + f` on the existing 0..4 phase scale (0 submitted,
1..2 generating, 2 postprocessing, 3 writing, 4 complete). MCP progress
notifications accept floats.

## F2 — GitHub Actions CI

The suite (391 tests) runs CPU-only: fake backend + canned fixtures;
`requirements-dev.txt` installs everything (`vtracer` ships manylinux +
win wheels for 3.7–3.14 per its PyPI page; `rembg[cpu]` pulls
`onnxruntime` with 3.11/3.13 wheels). Matrix: ubuntu-latest +
windows-latest × Python 3.11 + 3.13 (Windows matters: the path jail has
NTFS-specific branches). Steps: checkout → setup-python →
`pip install -r requirements-dev.txt` → `pip check` → `pytest tests/ -q`.

## F3 — PNG tEXt metadata

Pillow `PngInfo` (`pnginfo=` on save) writes tEXt chunks; the base PNG
re-encodes losslessly (same pixel data, added text chunks). Embed at the
orchestrator layer (pipeline stays pure): keys `software`,
`prompt`, `negative`, `category`, `style_preset`, `seed`, `job_id`,
`width`, `height`, `remove_bg_model` (refine: `instruction`, `strength`,
`parent_job_id`). Best-effort: any Pillow failure returns the original
bytes (canned/fake PNGs in tests must keep flowing through).

## F5 — Generic LoRA support (bring your own weights)

**Facts:**
- `LoraLoaderModelOnly` is a ComfyUI core node; verified chain
  `UnetLoaderGGUF → LoraLoaderModelOnly → ModelSamplingFlux → KSampler`
  works with GGUF backbones (ComfyUI-GGUF patches quantized weights;
  Medium/lyleaf walkthrough + r/comfyui). Both pinned workflows wire
  MODEL via node "10" `ModelSamplingFlux` with `inputs.model = ["1", 0]`,
  so injection is: add node "13" (`LoraLoaderModelOnly`,
  `model=["1",0]`, `lora_name`, `strength_model`) and re-point node 10's
  `model` to `["13", 0]`. (Node id "13" avoids the img2img ids 11/12.)
- **Licensing:** FLUX.1-schnell is Apache-2.0, but nearly all public
  style LoRAs (pixel art, flat, clay) found on Civitai/HF are trained on
  **FLUX.1-dev** (non-commercial) — the pinned schnell-only decision
  (Q3) forbids bundling recommendations. The server therefore supports
  **generic** LoRAs: the user drops any `*.safetensors` into
  `models/loras/` and passes its filename; the server neither bundles,
  downloads, nor recommends weights, and the docs say to verify the
  LoRA's own license.
- `check_model` gains kind `lora` → `LoraLoaderModelOnly`
  (`models/loras/`); the loader's file input is `lora_name` (ends with
  `_name`), which fits the existing `loader_files` file-list convention.

**Design:** generate-only (`refine_asset` unchanged). New inputs
`lora` (basename, no traversal — same rule as the clip-name overrides)
and `lora_strength` (0 < s ≤ 2, default 1.0) on `generate_app_asset`;
`build_txt2img_params` carries them through, `inject_params` performs
the node-13 injection when `lora` is set (missing node 10 →
`WORKFLOW_NODE_MISMATCH`). MCP validation: `INVALID_LORA` /
`INVALID_LORA_STRENGTH`.

## Reuse check

| Need | Path | New dep? |
|---|---|---|
| WS client | `websocket-client==1.9.2` | Yes (Apache-2.0, justified) |
| CI | GitHub Actions, existing suite | No |
| PNG metadata | Pillow `PngInfo` (installed) | No |
| LoRA node | `LoraLoaderModelOnly` (ComfyUI core) | No |

## Sources

docs.comfy.org (`comms_routes`, `comms_messages`);
[pypi.org/project/websocket-client](https://pypi.org/project/websocket-client);
[lyleaf.medium.com GGUF+LoRA walkthrough](https://lyleaf.medium.com/run-flux-model-gguf-with-lora-in-comfyui-50877c2c703a);
[civitai pixel-art LoRA (dev-based)](https://civitai.com/models/1095276/flux1-or-pixel-art-lora);
[digitalcreativeai schnell LoRA guide](https://www.digitalcreativeai.net/en/post/use-lora-comfyui-flux-1-schnell).
