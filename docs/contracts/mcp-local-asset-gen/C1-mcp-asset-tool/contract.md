# Interface contract — C1-mcp-asset-tool

Authoritative owner: PQM0. BASELINED v0.1.6 — controlled amendments only.
(v0.1.5: sha256:3D06443B…; v0.1.4: no freeze hash was recorded for the
named-workspaces amendment; v0.1.3: sha256:3EF9E64C…; v0.1.2: sha256:EAE4D1F8…;
v0.1.1: sha256:AC9192C6…; v0.1.0: sha256:B21A372C…. v0.1.6 amendment
2026-10-22: the requested leaf must be the written file (`<stem>.png`),
`asset_root` names the owning root, refine-by-`asset_id` resolves across
roots — closing the v0.1.5 independent-review findings. User-requested
chain; additive + behavior change; prior acks stand.)

- v0.1.6 content hash:
  `sha256:9CA6D5AA9DE97D2323DD785CA27805442ED65A8DC852B1192C70B00038AE20BD`
  (SHA256 over the file's LF bytes with every `sha256:<64hex>` field
  normalized out, self-hash excluded; re-verify with
  `.workflow/artifacts/mcp-agent-output-path/hash_contract.py`. The earlier
  freeze prefixes above were recorded before this script existed and are not
  reproducible with it — treat only the v0.1.6 value as machine-checkable.)

- ID / version / content hash or immutable revision:
  `C1-mcp-asset-tool` / `v0.1.6` / hash recorded at freeze below
  (LF bytes, sha256 fields excluded — see master PLAN.md registry).
- Status: Baselined v0.1.6 (was v0.1.5; additive output field
  `asset_root` + deliberate path-semantics change authorized by the user
  request of 2026-10-22; the v0.1.5 review findings — requested-leaf rule,
  wiring docs, owning root, coded postprocess rejection — are addressed
  here).
- Producer / consumers / owner:
  Producer `mod-mcp-core`; consumers `mod-integration`, external AI agents;
  PQM0 owns.
- Related project criteria / assignment generations:
  Project `mcp-local-asset-gen`; AC-1..AC-4 in master PLAN.md; affects
  `mod-mcp-core gen-1`, `mod-integration gen-1` (both Held). Follow-up task
  `mcp-agent-output-path` (PQM0-direct, 2026-10-22).
- Transport or language boundary: MCP over stdio (primary — OpenCode V2
  `mcp.servers.<name> = {type:"local", command:[...]}`) + streamable-HTTP
  optional (`mcp.run(transport="http")`, `/mcp`). SSE not used (superseded).
  Research F1/F2 (2026-10-17).
- Operations / inputs / outputs / schema locations:
  - `generate_app_asset({prompt, category: icon|illustration|avatar|splash, save_path, width?, height?, format?: png|svg, remove_bg?: bool, style_preset?: flat|clay|line|pixel, seed?, icon_sizes?: int[], ico?: bool, workspace?: string}) → {asset_path, asset_path_absolute, asset_root, width, height, format, seed, style_preset, job_id}`; `workspace` selects a named root (default `"default"`, see field types); `asset_path` is relative to `asset_root` (the FIRST approved root that contains the file, in the order selected workspace root → default project root → named workspaces), `asset_path_absolute` is the exact file location, `asset_root` is that owning root (`null` when the file is outside every approved root — in the default configuration that can only happen with `--allow-any-path`).
  - `refine_asset({asset_id|asset_path, instruction, save_path?, strength?, workspace?}) → {asset_path, asset_path_absolute, asset_root, job_id, parent_job_id}` (same workspace rule). When `save_path` is omitted the target is the parent's sibling `<stem>_refined.png` **inside the parent's own approved root** (never under the selected workspace when the parent lives elsewhere). The leaf rule below also applies to `asset_path` (the parent must be a `.png` the server could have written — live img2img needs a PNG parent).
  - `server_info() → {backend, comfyui_url, models, version, reachable: bool, queue_depth: int|null, project_root: string, workspaces: {name: path}, allow_any_path: bool}` — live: GET /prompt ok → reachable true + queue_remaining; unreachable → reachable false, queue_depth null (NOT an error). `project_root` is the ABSOLUTE default jail root; `workspaces` lists every configured named root; `allow_any_path` reports whether the server was started with `--allow-any-path`. Agents MUST compare `project_root` with their working directory before generating (mismatch = launcher misconfiguration, not a per-call error).
  - `check_model({name, kind?: unet|clip|vae|checkpoint}) → {available: bool, loader: string, checked_at: string}` — live: name membership in the pinned loader file list (UnetLoaderGGUF→unet_name, DualCLIPLoader→clip_name1/2, VAELoader→vae_name, CheckpointLoaderSimple→ckpt_name); kind narrows the loader set (default: all four). ComfyUI unreachable → BACKEND_UNAVAILABLE (existing code, consistent with generate).
  Schemas to live at `src/mcp_server/schemas/` (owner mod-mcp-core).
- Server initialization instructions: `src/mcp_server/server.py`
  `SERVER_INSTRUCTIONS` wired as FastMCP `instructions=` (MCP
  `InitializeResult.instructions`; verified live via client handshake).
  Content: purpose, 4 tool shapes, workflow order (server_info first),
  path rules (absolute or relative save_path, approved roots, no `..`),
  jail/overwrite/refine-precondition/concurrency rules, CODE-prefixed
  error guide, localhost/512px/stochastic limits. Token-budget guarded
  (<4000 chars, `test_instructions_token_budget`). Clients decide
  placement; text stays useful however presented.
- Field types / units / encodings / nullability / defaults:
  `prompt: string (required)`; `category: enum (required)`;
  `save_path: string (required)` — either a RELATIVE path (resolved under the
  selected workspace root) or an ABSOLUTE path (POSIX `/x`, Windows `C:/x`,
  UNC `//host/x` — shape-accepted, refused by containment unless that share
  is an approved root; Windows `\` separators are folded to `/`). An absolute
  path is used exactly as given and must land inside an approved root
  (default project root ∪ named workspaces). `..` traversal is refused in
  every form; a path that does not name a file is refused; NUL bytes and
  Windows reserved device names (`NUL`, `COM1`, …) are refused, as are
  NTFS alternate-data-stream forms (`icon.png:evil`) on Windows. The LEAF
  must be `<stem>.png` with a PNG-safe stem (`[A-Za-z0-9._-]`, at least one
  letter or digit) and a lowercase extension — the server writes PNG
  assets, so the requested path and the written file are always the same
  path; other leaves are refused pre-backend with
  `POLICY_DENIED INVALID_SAVE_PATH`.
  `width/height: int px, default 512`; `format default png`;
  `remove_bg default true for icon/avatar`; `style_preset default flat`;
  `icon_sizes?: int[] (each 1..512 px, ≤ max(width,height), deduped+sorted;
  default unset)`; `ico?: bool default false` (writes `<stem>.ico`
  multi-size container from the base PNG via Pillow; only with png output);
  `check_model kind?: unet|clip|vae|checkpoint (default all)`;
  `workspace?: string (default "default")` — selects a NAMED root from
  the server's configured `project_roots` map (set at launch via repeatable
  `--workspace name=path`; the `default` workspace IS the configured
  project_root). Unknown name → INVALID_WORKSPACE pre-backend.
  The SELECTABLE TREE SET stays fixed server-side and user-approved: the
  agent chooses a path inside it, never the set itself. `--allow-any-path`
  (server opt-in, default OFF, reported as `server_info.allow_any_path`)
  lifts the containment check for absolute paths.
  Units px; paths UTF-8.
  Launchers SHOULD set an explicit project root (`--project-root` CLI flag);
  when it is omitted the server's launch directory is used (normally the
  client's workspace) and a warning is logged. The configured root is
  always normalized to an absolute path; a non-directory root is rejected
  at startup (`INVALID_PROJECT_ROOT`).
- Preconditions / invariants / postconditions:
  Pre: ComfyUI reachable (or queued with explicit error); save dir writable.
  Invariant: never write outside the approved roots (default project root ∪
  named workspaces) unless the server was started with `--allow-any-path`;
  containment is decided on the RESOLVED path (symlinks/junctions
  resolved), so a link inside an approved root that points outside it is
  refused; never overwrite without explicit `overwrite:true`; never accept
  `..` traversal; postprocess output names must be leaves (no path
  separators, no NUL byte, no reserved device name, no ':' on Windows).
  Post: file exists at `asset_path` / `asset_path_absolute`,
  transparent PNG when `remove_bg:true`. (`format:svg` is loudly refused with
  POSTPROCESS_FAILED SVG-DEFERRED while vector output stays deferred per
  Q4 PNG-first MVP — erratum recorded 2026-10-18 from EVAL-01.)
- Error cases / status codes / retry behavior:
  `BACKEND_UNAVAILABLE`, `MODEL_MISSING`, `POLICY_DENIED (path escape)`,
  `GENERATION_FAILED`, `POSTPROCESS_FAILED`, `INVALID_ICON_SIZES`
  (icon_sizes not a list of ints in 1..512 px, or a size exceeding the
  requested base dimensions — rejected pre-backend). `INVALID_WORKSPACE`
  (unknown workspace name — rejected pre-backend; call server_info for the
  configured map). `POLICY_DENIED` for an absolute `save_path` outside every
  approved root — the message names the approved roots and the two ways to
  widen them (`--workspace name=path`, `--allow-any-path`); rejected
  pre-backend, nothing is written. A write failure is reported as
  `POSTPROCESS_FAILED` (never a bare OSError). Retry only idempotent
  re-`generate` with same `job_id`; no auto-retry on policy denial.
  server_info never errors on unreachable backend (reachable:false instead).
- Authorization / trust and sensitive-data boundaries:
  Local-only; no API keys in tool params; prompts logged without PII;
  save paths constrained to the approved roots (enforcement: server-side
  check, not prompt prose); the approved tree set is user-approved
  configuration, never a per-call agent decision.
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
  v0.1.0 clients (3 tools, no icon_sizes) behave identically. v0.1.5 is
  additive on outputs (`asset_path_absolute`, `allow_any_path`) plus a
  deliberate behavior change on `save_path` (absolute paths now accepted
  inside the approved roots); v0.1.4 clients keep working — relative paths
  behave exactly as before. v0.1.6 adds `asset_root` (the owning root of
  `asset_path`) and requires a `<stem>.png` leaf: a client that asked for
  `icon.webp` now gets `POLICY_DENIED INVALID_SAVE_PATH` instead of a file
  named `icon.png` — that refusal is the point (the tool may no longer
  report a path that does not exist).
- Known limits (accepted, not gates): containment is path-based, so a hard
  link inside an approved root is not detected, and the check-then-write
  gap is narrow (TOCTOU); `asset_path_absolute` echoes the caller's
  spelling (not case-normalized); the overwrite guard covers the base
  target, not the `@2x`/`@3x`/`-Npx`/`.ico` siblings; the Windows
  reserved-device refusal is platform-specific (POSIX allows those names);
  the Windows `\\?\` extended-length form of an in-root path is refused
  (a false negative).
- Valid and invalid examples / shared fixture identity:
  Valid: `generate_app_asset(prompt="cute bear avatar, 3D claymorphism, soft
  lighting", category="avatar", save_path="assets/images/bear_avatar.png",
  remove_bg=true)` → `{asset_path:"assets/images/bear_avatar.png",...}`.
  Valid (v0.1.5): `save_path="C:/my-project/src/assets/icons/robot.png"`
  (inside the approved root) → the file is written exactly there and
  `asset_path_absolute` echoes it.
  Invalid: `save_path:"../../etc/pass.png"` → `POLICY_DENIED`;
  `save_path:"C:/outside/any/approved/root/x.png"` → `POLICY_DENIED`
  (unless `--allow-any-path`); `save_path:"assets/icon.webp"` (v0.1.6) →
  `POLICY_DENIED` (the leaf must be a `.png`).
  Fixtures: `fixtures/c1/*.json` (owner mod-mcp-core at dispatch).
- Consumer expectation checks: schema validation + path-escape rejection +
  golden `UserProfile.tsx` embed (`<img src={bearAvatar}>` resolves).
- Provider verification checks: FastMCP tool list matches schema; mocked
  ComfyUI returns canned PNG; real-provider check at integration only.
- Real-component integration checks / owner: PQM0 integration checkpoint IC-1
  (core+backend real ComfyUI) and IC-2 (full chain); mock-only never closes.
  Follow-up live check: `.workflow/artifacts/mcp-agent-output-path/e2e_path_run.py`
  (server spawned with the configured argv from a foreign cwd → jail follows
  the client; absolute save_path honoured; absolute path outside the roots
  refused).
- Mock/stub limitations: stubs conform to pinned C1 but prove nothing about
  real diffusion/postprocess timing or VRAM behavior.
- Migration/recovery when relevant: clients that relied on "absolute paths
  are refused" must adapt — they now get the file where they asked, and
  `asset_path` stays relative to the owning approved root. Clients that
  embedded `asset_path` verbatim keep working.
- Approving authority / instruction reference: User decisions Q1 (FastMCP) +
  Q4 (PNG-first) recorded 2026-10-17; freeze (hash + signatures) at dispatch.
  v0.1.5 authorized by the user request of 2026-10-22 ("the AI agent chooses
  the output path"), implemented by PQM0 under task `mcp-agent-output-path`.
- Supersedes / affected modules / acknowledgment requirements: Baselines
  v0.1.0 (frozen 2026-10-17). Affected modules acknowledge this generation
  at startup; later changes need a new generation + re-acknowledgment.

## Addendum v0.2 (2026-10-24) — real SVG format + include_image

Additive to v0.1.6; nothing removed.

- `format:"svg"` is now REAL output (Q4 deferral lifted; research
  `docs/research/asset-gen-completion-research-2026-10-24.md`): the
  `save_path` leaf must be `<stem>.svg` when `format:"svg"` (leaf rule is
  format-matched: `.png` for png, `.svg` for svg, still lowercase with the
  PNG-safe stem). For `format:"svg"` ONLY the `<stem>.svg` file is written
  — no `@2x`/`@3x`/icon siblings — and the requested leaf is the written
  path, as before. `format:"svg"` + `.png` leaf (and vice versa) is refused
  pre-backend with `POLICY_DENIED INVALID_SAVE_PATH`.
- New optional input `include_image: bool = false` on BOTH
  `generate_app_asset` and `refine_asset`. When true the result carries an
  extra `image` key holding an MCP image content block (`type:"image"`,
  `mimeType:"image/png"`, base64 of the @1x PNG) so multimodal clients can
  view the asset. Default false keeps result payloads unchanged; the
  required output keys are unchanged (`image` is optional).
- Implementation notes: schemas live in `src/mcp_server/schemas.py`
  (v0.2), server instructions updated; vector payload produced by C3 v0.2.

## Addendum v0.3 (2026-10-24) — pattern slice (P1+P2+P7)

Additive to v0.2. Research: `docs/research/pattern-features-research-2026-10-24.md`.

- Categories gain `pattern` and `texture` (remove_bg defaults FALSE for
  both — a pattern keeps its full frame; explicit `remove_bg:true` wins).
- New `style_preset:"pattern"` (maps to C2 style id `pattern`): prompt
  template adds "seamless repeating pattern, tileable, even distribution…".
- New optional input `seamless: bool = false`: the postprocess cross-fades
  the edge bands (feather 32px, clamped to side//4) so the tile wraps
  continuously, SKIPS trim (cropping would destroy periodicity), and emits
  an extra `<stem>-tile.png` 2x2 preview file (2w x 2h). With
  `include_image:true` the attached image block is the TILE PREVIEW (not
  the @1x base). Non-seamless calls are byte-identical to v0.2 behavior.
- `width`/`height` are now capped at 1024 (`INVALID_WIDTH` /
  `INVALID_HEIGHT` above) — OOM guard for the 10 GB GGUF-Q4 target;
  schema gains `maximum: 1024`.
