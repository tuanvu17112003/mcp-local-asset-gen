# Pattern/ornament feature research — mcp-local-asset-gen (2026-10-24)

Intent: features to let agents generate seamless patterns (hoa văn),
ornaments (họa tiết), textures and brand-palette graphics for apps with the
existing stack (FastMCP + ComfyUI FLUX.1-schnell + Pillow postprocess).
Research only — no code changed. Method: current-state read via CodeGraph +
web verification (sources accessed 2026-10-24; full URLs in the report).

## 0. Current state (verified from source)

- `CATEGORIES = {icon, illustration, avatar, splash}`; no pattern/texture
  category (`validation.py:36`).
- `STYLE_PRESETS = {flat, 3d-clay, minimal-line, pixel-art}` — prompt
  templates only; a LoRA hook exists but nothing is wired
  (`presets.py:78-95`).
- `width`/`height` accept ANY int ≥ 1 — no upper cap (OOM risk on the
  10 GB GGUF-Q4 target at e.g. 2048px).
- Nothing seamless/tileable anywhere: no circular padding in the pinned
  workflow JSONs, no offset/blend postprocess, no seam check.
- Postprocess is already the right home for deterministic image math:
  trim/pad/multi-res/ico/svg all live there and are contract-tested.

## F1 — FLUX.1-schnell has NO native tiling (verified)

Community-standard workarounds, in increasing fidelity:

1. Prompt terms only ("seamless pattern, tileable, repeating, flat
   motif") — unreliable alone; schnell is not natively tileable
   (r/StableDiffusion thread + Word.Studio/pixelift both pair prompts
   with a post-process or a fine-tune).
2. **Offset + blend** (classic GIMP "make seamless"): roll the image by
   half its size, cross-fade the wrap seams. Pure Pillow, deterministic,
   no server-side changes. This is what pixelift-style tools do in
   essence (generate → fix seams in an editor).
3. **Offset + inpaint**: offset so seams sit mid-image, then img2img the
   seam away — maps 1:1 onto our existing `refine_asset` (upload already
   works).
4. **Circular padding at model/VAE level** (true seamless): custom node
   `spinagon/ComfyUI-seamless-tiling` — nodes `Seamless Tile`,
   `Make Circular VAE`, `Circular VAE Decode (tile)`, `Offset Image`;
   independent X/Y (asymmetric) tiling. License **GPL-3.0**; README does
   NOT mention FLUX or GGUF loaders (compatibility unverified); requires
   installing the node into the user's ComfyUI + new API-format workflow
   JSONs (r/comfyui reports FLUX may need extra offset passes for
   corners).
5. **`gokaygokay/Flux-Seamless-Texture-LoRA`** (trigger `smlstxtr`):
   license **apache-2.0** BUT base model is **FLUX.1-dev** (non-commercial
   weights) — conflicts with the pinned schnell-only decision (Q3). EXCLUDED
   unless the user explicitly accepts dev weights.

## F2 — Palette control is deterministic postprocess (verified pattern)

Brand-matched assets need exact colors, not prompt-hoped colors. The
reliable route is post-hoc recolor: Pillow adaptive quantize to k colors,
then map each cluster to the nearest user-supplied palette hex
(`Image.quantize` + palette remap; standard technique, Pillow HPND
already a dependency). Works for patterns AND icons; prompt color words
stay as a soft first pass.

## F3 — Symmetric ornaments are deterministic postprocess (verified pattern)

Mandala/knob/border motifs want guaranteed symmetry: mirror-x (left half
mirrored), mirror-quad (both axes), radial-N (wedge rotated N times) —
all pure Pillow geometry on the final base. Deterministic and testable,
same style as trim/pad.

## Feature proposals (size = smallest complete change)

| # | Feature | Size | New dep? | Notes |
|---|---|---|---|---|
| P1 | `category:"pattern"` (+`texture`) with `remove_bg` default false, plus a `pattern` style preset template ("seamless repeating pattern, tileable, even distribution") | S | No | Additive to CATEGORIES/STYLE_PRESETS; invalid examples need updating |
| P2 | Postprocess `seamless=true`: half-offset roll + cross-fade blend; optional `<stem>-tile.png` 2x2 preview file, `include_image` shows the tiled preview so the agent can judge seams | S | No | The workhorse; quality good for textures/flat motifs, ghosting possible on hard structures — refine pass fixes |
| P3 | `palette: ["#hex", ...]` (2..8) param: quantize-to-palette recolor in postprocess | S | No | Deterministic brand colors; applies to every category |
| P4 | `symmetry: "mirror-x"|"mirror-quad"|"radial:<n>"` postprocess for họa tiết đối xứng | S/M | No | Radial needs a wedge-angle convention (document it) |
| P5 | True seamless via `spinagon/ComfyUI-seamless-tiling` (circular padding) | M | ComfyUI-side custom node (GPL-3.0) | Only if P2 quality disappoints; FLUX+GGUF unverified; needs new workflow JSONs + server-side install doc |
| P6 | Seamless Texture LoRA | — | — | EXCLUDED: apache-2.0 LoRA but FLUX.1-dev base (non-commercial) |
| P7 | Cap `width`/`height` at 1024 (`INVALID_*` above) | S | No | OOM guard for the 10 GB GGUF-Q4 target; patterns want 512-1024 tiles anyway |

Recommended order: P1 + P7 + P2 first (one coherent "pattern" slice, all
Pillow-side, no user ComfyUI changes), then P3/P4 on demand; P5 only as a
verified upgrade path.

## Unresolved / user decisions

1. Implement P1+P2+P7 now? (one slice, ~1 module + validation + tests)
2. P3 palette + P4 symmetry — wanted in the same pass or later?
3. P5 requires installing a GPL-3.0 custom node into the user's ComfyUI —
   acceptable, or stay dependency-free with P2's blend?
4. Tile preview: separate `-tile.png` file, via `include_image`, or both?
