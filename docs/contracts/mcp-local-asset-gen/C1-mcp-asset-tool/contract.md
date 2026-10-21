# Interface contract — C1-mcp-asset-tool

Authoritative owner: PQM0. BASELINED v0.1.3 — controlled amendments only.
(v0.1.2: sha256:EAE4D1F8…; v0.1.1: sha256:AC9192C6…; v0.1.0: sha256:B21A372C….
v0.1.3 amendment 2026-10-21: server_info.project_root + explicit-root
launcher rule (CWD-jail fix, user-reported). Additive; prior acks stand.)

- ID / version / content hash or immutable revision:
  `C1-mcp-asset-tool` / `v0.1.3` / sha256:3EF9E64CBA465E5815BD701F8A7B6BEAFB9E32773151DEC0D91147F1A65B2681 frozen 2026-10-21
  (LF bytes, sha256 fields excluded — see master PLAN.md registry).
- Status: Baselined v0.1.3 (was v0.1.2; additive — prior acks stand).
- Producer / consumers / owner:
  Producer `mod-mcp-core`; consumers `mod-integration`, external AI agents;
  PQM0 owns.
- Related project criteria / assignment generations:
  Project `mcp-local-asset-gen`; AC-1..AC-4 in master PLAN.md; affects
  `mod-mcp-core gen-1`, `mod-integration gen-1` (both Held).
- Transport or language boundary: MCP over stdio (primary — OpenCode V2
  `mcp.servers.<name> = {type:"local", command:[...]}`) + streamable-HTTP
  optional (`mcp.run(transport="http")`, `/mcp`). SSE not used (superseded).
  Research F1/F2 (2026-10-17).
- Operations / inputs / outputs / schema locations:
  - `generate_app_asset({prompt, category: icon|illustration|avatar|splash, save_path, width?, height?, format?: png|svg, remove_bg?: bool, style_preset?: flat|clay|line|pixel, seed?, icon_sizes?: int[], ico?: bool}) → {asset_path, width, height, format, seed, style_preset, job_id}`
  - `refine_asset({asset_id|asset_path, instruction, save_path?, strength?}) → {asset_path, job_id, parent_job_id}`
  - `server_info() → {backend, comfyui_url, models, version, reachable: bool, queue_depth: int|null, project_root: string}` — live: GET /prompt ok → reachable true + queue_remaining; unreachable → reachable false, queue_depth null (NOT an error). `project_root` is the ABSOLUTE server-side jail root every save_path resolves inside — agents MUST compare it with their working directory before generating (mismatch = launcher misconfiguration, not a per-call error).
  - `check_model({name, kind?: unet|clip|vae|checkpoint}) → {available: bool, loader: string, checked_at: string}` — live: name membership in the pinned loader file list (UnetLoaderGGUF→unet_name, DualCLIPLoader→clip_name1/2, VAELoader→vae_name, CheckpointLoaderSimple→ckpt_name); kind narrows the loader set (default: all four). ComfyUI unreachable → BACKEND_UNAVAILABLE (existing code, consistent with generate).
  Schemas to live at `src/mcp_server/schemas/` (owner mod-mcp-core).
- Server initialization instructions: `src/mcp_server/server.py`
  `SERVER_INSTRUCTIONS` wired as FastMCP `instructions=` (MCP
  `InitializeResult.instructions`; verified live via client handshake).
  Content: purpose, 4 tool shapes, workflow order (server_info first),
  jail/overwrite/refine-precondition/concurrency rules, CODE-prefixed
  error guide, localhost/512px/stochastic limits. Token-budget guarded
  (<4000 chars, `test_instructions_token_budget`). Clients decide
  placement; text stays useful however presented.
- Field types / units / encodings / nullability / defaults:
  `prompt: string (required)`; `category: enum (required)`;
  `save_path: relative POSIX path under project root (required, must stay
  inside root)`; `width/height: int px, default 512`; `format default png`;
  `remove_bg default true for icon/avatar`; `style_preset default flat`;
  `icon_sizes?: int[] (each 1..512 px, ≤ max(width,height), deduped+sorted;
  default unset)`; `ico?: bool default false` (writes `<stem>.ico`
  multi-size container from the base PNG via Pillow; only with png output);
  `check_model kind?: unet|clip|vae|checkpoint (default all)`.
  Units px; paths UTF-8, no `..` traversal.
  Launchers MUST set an explicit project root (`--project-root` CLI flag
  or client `cwd`; the server's own launch directory is only a fallback
  and the server logs a warning when it is used). The configured root is
  always normalized to an absolute path; a non-directory root is rejected
  at startup (`INVALID_PROJECT_ROOT`).
- Preconditions / invariants / postconditions:
  Pre: ComfyUI reachable (or queued with explicit error); save dir writable.
  Invariant: never write outside project root; never overwrite without
  explicit `overwrite:true`. Post: file exists at `asset_path`, transparent
  PNG when `remove_bg:true`. (`format:svg` is loudly refused with
  POSTPROCESS_FAILED SVG-DEFERRED while vector output stays deferred per
  Q4 PNG-first MVP — erratum recorded 2026-10-18 from EVAL-01.)
- Error cases / status codes / retry behavior:
  `BACKEND_UNAVAILABLE`, `MODEL_MISSING`, `POLICY_DENIED (path escape)`,
  `GENERATION_FAILED`, `POSTPROCESS_FAILED`, `INVALID_ICON_SIZES`
  (icon_sizes not a list of ints in 1..512 px, or a size exceeding the
  requested base dimensions — rejected pre-backend). Retry only idempotent
  re-`generate` with same `job_id`; no auto-retry on policy denial.
  server_info never errors on unreachable backend (reachable:false instead).
- Authorization / trust and sensitive-data boundaries:
  Local-only; no API keys in tool params; prompts logged without PII;
  save paths constrained to project root (enforcement: server-side check,
  not prompt prose).
- Side effects / atomicity / idempotency / ordering:
  Writes exactly one asset tree per call (plus `@2x/@3x` siblings, plus
  `<stem>-<N>px.png` + `<stem>.ico` when icon_sizes/ico requested);
  `job_id` idempotency key; refine creates new file, never mutates parent.
- Timeouts / concurrency / relevant performance limits:
  Provisional: per-job timeout 300 s; max 2 concurrent local jobs (VRAM
  guard); queue beyond returns `QUEUED`. Final values at freeze with Q3.
- Compatibility policy / supported version combinations:
  Semver on tool schema; additive optional fields minor; removing/renaming
  requires major + migration. Pinned at freeze. v0.1.1 is minor-additive:
  v0.1.0 clients (3 tools, no icon_sizes) behave identically.
- Valid and invalid examples / shared fixture identity:
  Valid: `generate_app_asset(prompt="cute bear avatar, 3D claymorphism, soft
  lighting", category="avatar", save_path="assets/images/bear_avatar.png",
  remove_bg=true)` → `{asset_path:"assets/images/bear_avatar.png",...}`.
  Invalid: `save_path:"../../etc/pass.png"` → `POLICY_DENIED`.
  Fixtures: `fixtures/c1/*.json` (owner mod-mcp-core at dispatch).
- Consumer expectation checks: schema validation + path-escape rejection +
  golden `UserProfile.tsx` embed (`<img src={bearAvatar}>` resolves).
- Provider verification checks: FastMCP tool list matches schema; mocked
  ComfyUI returns canned PNG; real-provider check at integration only.
- Real-component integration checks / owner: PQM0 integration checkpoint IC-1
  (core+backend real ComfyUI) and IC-2 (full chain); mock-only never closes.
- Mock/stub limitations: stubs conform to pinned C1 but prove nothing about
  real diffusion/postprocess timing or VRAM behavior.
- Migration/recovery when relevant: N/A at v0.1 (greenfield); later versions
  record migration here.
- Approving authority / instruction reference: User decisions Q1 (FastMCP) +
  Q4 (PNG-first) recorded 2026-10-17; freeze (hash + signatures) at dispatch.
- Supersedes / affected modules / acknowledgment requirements: Baselines
  v0.1.0 (frozen 2026-10-17). Affected modules acknowledge this generation
  at startup; later changes need a new generation + re-acknowledgment.
