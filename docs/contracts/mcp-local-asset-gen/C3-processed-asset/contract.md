# Interface contract — C3-processed-asset

Authoritative owner: PQM0. BASELINED v0.1.1 — controlled amendments only.
(v0.1.0: sha256:A7540BE3…9017. v0.1.1 amendment 2026-10-18: icon_sizes +
.ico export, authorized by user "implement #3".)

- ID / version / content hash: `C3-processed-asset` / `v0.1.1` /
  `sha256:A1B822676A413700A5822DACFE830335ECF5BC98E0AD28B9205372D36877F0EE`
  frozen 2026-10-18.
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
  pre-download via `rembg d`); no upload to hosted removal APIs. License
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
