# Interface contract — C3-processed-asset

Authoritative owner: PQM0. BASELINED v0.1.1 — controlled amendments only.
(v0.1.0: sha256:A7540BE3…9017. v0.1.1 amendment 2026-10-18: icon_sizes +
.ico export, authorized by user "implement #3". Documentation erratum
2026-10-23: the model pre-download is described in the setup guide instead
of the `rembg d` CLI — the `rembg` CLI extra is not installed (dependency
conflict, see requirements.txt); no normative requirement changed.)

- ID / version / content hash: `C3-processed-asset` / `v0.1.1` /
  `sha256:8563E3EA83F5129D24A6BA17A1D4F64D8E604D97A6BE5E4D1C4BF48B6345D0D3`
  frozen 2026-10-18; re-frozen 2026-10-23 after the documentation erratum
  (normative content unchanged).
- Status: Baselined v0.1.1 (supersedes v0.1.0; additive only).
- Producer / consumers / owner: Producer `mod-postprocess`; consumers
  `mod-mcp-core`, `mod-integration`; PQM0 owns.
- Related criteria / generations: AC-3; affects `mod-postprocess gen-1`,
  `mod-integration gen-1` (Held).
- Transport or language boundary: Filesystem: input PNG bytes → output files.
- Operations / inputs / outputs / schema locations:
  `process({png_bytes, remove_bg, model?: "u2net"|"isnet-general-use"|"bria-rmbg(opt-in)",
  trim, pad_px, sizes:[1,2,3], vectorize?: false(MVP),
  icon_sizes?: int[]|None, ico?: bool, stem}) →
  {files:[{filename, width, height, scale, png_bytes}], alpha, model_used}`.
  With `icon_sizes=[s…]`: additionally `{filename:"<stem>-<s>px.png",
  width:s, height:s, scale:"icon<s>"}` entries resized (Lanczos) from the
  FINAL base image (post trim/pad; center square-crop when non-square —
  icons are square by construction). With `ico:true`:
  `{filename:"<stem>.ico"}` multi-size ICO container (Pillow, embeds the
  16/32/48/64 px renders present-or-derived). Core validates sizes pre-call
  (INVALID_ICON_SIZES); postprocess assumes valid.
  Code `src/postprocess/`. MVP default `model:"u2net"` (fast), quality opt
  `"isnet-general-use"`; `"bria-rmbg"` requires explicit
  `bria_license_accepted:true` (NON-commercial otherwise). Research F5.
- Field types / units / nullability / defaults:
  `remove_bg default true (icon/avatar)`; `pad_px default 8`;
  `sizes default [1,2,3]`; `vectorize default false` provisional.
- Preconditions / invariants / postconditions:
  Pre: input is decodable PNG. Post: outputs are trimmed transparent PNGs
  (`alpha:true` when requested); `@2x/@3x` exact multiples; SVG valid XML
  when requested; all paths inside project root with naming
  `<stem>[@Nx].{png,svg}`.
- Error cases / retry: `DECODE_FAILED`, `SEGMENTATION_FAILED`,
  `LICENSE_REQUIRED (bria without acceptance)`, `VECTORIZE_FAILED`. No partial sibling sets returned as success; retry is
  fresh `process` call (idempotent, deterministic given seed+inputs).
- Authorization / trust: Offline models only, cached per-user (`U2NET_HOME`;
  offline pre-download per the setup guide); no upload to hosted removal APIs. License
  gate: `u2net`/`isnet-general-use` = FOSS-compatible default path;
  `bria-rmbg` (RMBG-1.4, `bria-rmbg-1.4` license) = NON-commercial, needs
  paid BRIA agreement for commercial use → server MUST reject
  `model:"bria-rmbg"` without `bria_license_accepted:true` (+ user-facing
  license note in docs). Research F5.
- Side effects / atomicity / idempotency: Pure transform; writes only via
  caller save step; deterministic for fixed inputs.
- Timeouts / performance: Provisional budget ≤15 s per 512×512 on CPU,
  ≤60 s with `@1x/@2x/@3x`+SVG; recalibrate at freeze.
- Compatibility policy: File-naming + alpha semantics versioned; adding
  sizes minor, changing naming major.
- Valid/invalid examples / fixtures:
  Valid: 512 PNG icon → `icon.png`, `icon@2x.png` (1024), `icon@3x.png`
  (1536), optional `icon.svg`. Invalid: non-PNG input → `DECODE_FAILED`.
  Fixtures: `fixtures/c3/input-512.png` + expected manifests.
- Consumer expectation checks: alpha-presence, dimension, SVG well-formed
  checks (owners: core + integration).
- Provider verification checks: fixture golden test with canned mask
  (no model download; asserts `model_used` echo) + license-gate unit
  (bria without acceptance → `LICENSE_REQUIRED`); real-model check at IC-2
  only (dispatch env needs Python ≥3.11 via `uv`/venv — F7).
- Real-component integration checks / owner: IC-2 full chain (PQM0).
- Mock/stub limitations: Canned-mask test proves plumbing, not model quality.
- Migration/recovery: N/A greenfield; failed outputs discarded, source kept.
- Approving authority: User decision Q4 (PNG-first MVP) recorded 2026-10-17;
  BRIA opt-in default-OFF is PQM provisional within that scope (no new
  interview); freeze at dispatch.
- Supersedes / acknowledgment: Baselines v0.1.0 (frozen 2026-10-17).
  Affected modules acknowledge at startup; later changes need a new generation.

## Addendum v0.2 (2026-10-24) — vectorization activated

Amends the Q4 PNG-first deferral recorded in v0.1.x.

- `vectorize=True` now APPENDS a `<stem>.svg` entry
  (`{filename:"<stem>.svg", scale:"svg", png_bytes:<svg bytes>}` — the
  `png_bytes` key is the shared bytes carrier, same convention as the
  `.ico` entry) as the LAST file entry, after the `@Nx`/icon/`.ico`
  entries. Ordering note in the module docstring updated accordingly.
- Pin: `vtracer==0.6.15` (stable PyPI, legacy `convert_image_to_svg_py`
  API; the 1.0.0a* `convert_bytes` API is still pre-release — do not pin
  an alpha). Added to `requirements.txt`; a missing install raises
  `VECTORIZE_FAILED` at call time (lazy import — PNG-only installs work
  without it).
- Tracing mode: `color`/`stacked`/`spline`, `filter_speckle=4`. Probed
  2026-10-24: fully transparent pixels are NOT traced, so transparent
  backgrounds carry into the SVG as absence of fill; semi-transparent
  edge behavior is unprobed (visual check at IC-2).

## Addendum v0.3 (2026-10-24) — seamless tiling + tile preview

Additive to v0.2.

- `process(..., seamless=True)`: after background removal/decode, the base
  is made wrap-continuous by `postprocess.seamless.make_seamless`
  (edge cross-fade, feather 32px clamped to side//4, pure Pillow,
  deterministic, size-preserving) and trim is FORCED OFF.
- A `<stem>-tile.png` entry (2w x 2h 2x2 repeat of the final base, no
  `scale` key) is appended after the `.ico` entry and before the SVG
  entry.

## Addendum v0.4 (2026-10-24) — recolor + symmetry ops

Additive to v0.3. Pipeline order is now: decode/remove_bg →
`symmetrize` (P4, when `symmetry` set) → `make_seamless` (P2, when
`seamless`) → trim → `recolor_to_palette` (P3, when `palette` set) →
2x2 tile preview (seamless only) → `@Nx`/icon/`.ico` → SVG. New modules:
`postprocess/palette.py` (`recolor_to_palette`, FASTOCTREE quantize +
nearest-palette mapping, alpha preserved) and `postprocess/symmetry.py`
(`symmetrize`, pure-geometry mirror/radial, deterministic).

## Addendum v0.5 (2026-10-24) — birefnet background-removal models

Additive to v0.4.

- `remove_background` / `process(..., model=...)` accept two new
  session names: `birefnet-general` and `birefnet-general-lite`
  (verified present in the pinned rembg 2.0.85; models download once per
  user cache on first use). `u2net` remains the default;
  `bria-rmbg` keeps its LICENSE_REQUIRED gate.
