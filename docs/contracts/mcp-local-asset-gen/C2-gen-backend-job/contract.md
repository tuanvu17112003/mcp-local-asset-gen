# Interface contract — C2-gen-backend-job

Authoritative owner: PQM0. BASELINED v0.1.2 — controlled amendments only.

- ID / version / content hash or immutable revision:
  `C2-gen-backend-job` / `v0.1.2` /
  `sha256:73ED6F4AECA7E9B3B22B4206FC1C5BF17DD79154B0DC5ECB9B25DEEB6B55206D`
  frozen 2026-10-18; re-frozen 2026-10-23 (documentation erratum: the
  recorded value was no longer reproducible with the documented hashing
  script; normative content unchanged).
  (v0.1.1: `sha256:C4744A42…`; v0.1.0: `sha256:E3EB35CF…`.)
  v0.1.2 amendment 2026-10-18: loader-files query, authorized by user
  "implement #2".
- Status: Baselined v0.1.2 (minor-additive 2026-10-18: read-only
  loader-files query for check_model; supersedes v0.1.1; all prior behavior
  preserved. v0.1.1 = CR-001 GGUF-Q4 default; v0.1.0 = original freeze.)
- Producer / consumers / owner: Producer `mod-gen-backend`; consumers
  `mod-mcp-core`, `mod-postprocess`; PQM0 owns.
- Related project criteria / assignment generations: AC-2 in master PLAN.md;
  affects `mod-gen-backend gen-1`, `mod-mcp-core gen-1` (Held).
- Transport or language boundary: In-process Python call + ComfyUI REST:
  `POST /prompt` (`{"prompt": {api-format workflow}}, client_id?`) →
  `{prompt_id}`; poll `GET /history/{prompt_id}` (+ `GET /queue` while
  queued/running); fetch `GET /view?filename=&subfolder=&type=`; cancel
  `POST /interrupt`. ComfyUI at `http://127.0.0.1:8188` (decided Q2).
  API-format = numeric node IDs, no layout (File → Export Workflow (API)).
  Research F3 (2026-10-17).
- Operations / inputs / outputs / schema locations:
  `submit_txt2img({prompt, negative?, workflow_id, width, height, steps:1-4,
  seed?, model_id}) → {job_id}`; `submit_img2img({input_png, instruction,
  strength?, ...}) → {job_id}`; `fetch_result({job_id}) →
  {png_bytes, width, height, seed, model_id, elapsed_s}`.
  Read-only introspection (no queue/submit side effects):
  `loader_files({loader}) → {input_name: [filenames]}` via
  `GET /object_info/{loader}` for `UnetLoaderGGUF|DualCLIPLoader|VAELoader|
  CheckpointLoaderSimple` (verified live 2026-10-18). Unknown loader →
  `UNKNOWN_LOADER`; unreachable → `COMFY_UNREACHABLE`.
  Adapter code `src/gen_backend/`; workflow JSONs `src/gen_backend/workflows/`.
  MVP default `workflow_id="txt2img-flux-schnell-gguf-q4"` (ComfyUI-GGUF
  loader, Q4_K_S backbone ~6.8 GB, T5-XXL/CLIP on CPU, VAE tiling or
  CPU-VAE, 512 px, 4 steps) for the 10 GB target; scale-up alternative
  `workflow_id="txt2img-flux-schnell-fp8"` (Load Checkpoint
  `flux1-schnell-fp8.safetensors`). (v0.1.1 correction per CR-001:
  GGUF-Q4 is the default, FP8 the alternative.)
  10 GB target variant (adopted 2026-10-17):
  `workflow_id="txt2img-flux-schnell-gguf-q4"` (ComfyUI-GGUF loader,
  Q4_K_S backbone ~6.8 GB, T5-XXL/CLIP on CPU, VAE tiling or CPU-VAE,
  512 px, 4 steps). Both variants pinned by content hash at dispatch;
  IC-1 measures actual peak VRAM + s/image on the RTX 3080 before
  acceptance.
  Poll: 1 s interval, up to 300 s, then `JOB_TIMEOUT`; `GET /queue` checked
  first for running/queued vs completed/error/not_found.
- Field types / units / encodings / nullability / defaults:
  `prompt required`; `steps default 4` (schnell; range 1–4 MVP);
  `guidance 0.0` fixed for schnell; `seed nullable, random if null`;
  `model_id` defaults to the selected workflow's model preset
  (`flux-schnell-gguf-q4` under the default workflow); PNG bytes; times seconds.
- Preconditions / invariants / postconditions:
  Pre: workflow JSON valid API format; model installed. Post: returned PNG
  matches requested W×H; metadata echoes model/seed.
- Error cases / status codes / retry behavior:
  `COMFY_UNREACHABLE`, `UNKNOWN_WORKFLOW`, `MODEL_NOT_FOUND`
  (incl. missing FP8 file + placement hint `models/checkpoints/`),
  `QUEUE_FULL`, `JOB_FAILED (with ComfyUI error payload)`, `JOB_TIMEOUT`.
  Poll 1 s with backoff allowance; cancel via `POST /interrupt`; no silent
  reinterpretation of failures. Research F3/F4.
- Authorization / trust and sensitive-data boundaries: Localhost only by
  default; no remote ComfyUI without explicit authority + TLS decision.
- Side effects / atomicity / idempotency / ordering:
  Submitting creates one queue entry; `job_id` unique; fetch is read-only;
  img2img never mutates source file.
- Timeouts / concurrency / relevant performance limits:
  Submit timeout 5 s; poll 1 s up to 300 s; ≤2 concurrent jobs (VRAM guard,
  decided envelope). VRAM guidance: schnell FP8 ≈ 12 GB workable, FP16
  ≈ 24 GB; GGUF-Q4 path possible 6–8 GB (not MVP); <8 GB local diffusion
  not recommended. Model disk: ~17.2 GB FP8 single file (+ cache).
  Research F4.
- Compatibility policy: Workflow JSON pinned by content hash; node-ID changes
  require new C2 revision + consumer ack.
- Valid and invalid examples / shared fixture identity:
  Valid: `submit_txt2img(prompt="orange delivery scooter icon, flat design",
  workflow_id="txt2img-flux-schnell-fp8", width=512, height=512)` →
  `{job_id:"..."} → fetch_result → 512×512 PNG + {seed, model_id}`.
  Invalid: unknown `workflow_id` → `UNKNOWN_WORKFLOW`.
  Fixtures: `fixtures/c2/*` (canned 1×1 PNG + `/history` payload snapshot +
  `fake_comfyui` stand-in spec for GPU-less CI). Research F3.
- Consumer expectation checks: canned-history parser test; W×H/seed
  propagation test owned by mod-mcp-core/mod-postprocess.
- Provider verification checks: unit against mocked HTTP; real check only
  against live ComfyUI at IC-1 (owner PQM0).
- Real-component integration checks / owner: IC-1 `server_info →
  run_workflow → fetch_outputs → PNG on disk` (PQM0).
- Mock/stub limitations: Mocked ComfyUI proves adapter logic only.
- Migration/recovery: Cancel queued job on timeout; record `job_id` for resume.
- Approving authority: User decisions Q2 (ComfyUI) + Q3 (FLUX-schnell)
  recorded 2026-10-17; freeze (hash + signatures) at dispatch.
- Supersedes / acknowledgment: v0.1.1 (CR-001, PQM0-approved under 10 GB
  profile authority) supersedes v0.1.0. Backend candidate (frozen on v0.1.0)
  already conforms — ack at integration. Remaining modules launch on v0.1.1.

## Addendum v0.1.3 (2026-10-24) — `/upload/image` closes the img2img precondition

Additive to v0.1.2.

- New client op `upload_image(png_bytes, *, subfolder="asset-gen",
  filename?=None, overwrite=false)` → `POST /upload/image`,
  `multipart/form-data`, fields `image` (file) + `overwrite`
  (`"true"|"false"`) + `subfolder` + `type:"input"`; response
  `{"name","subfolder","type"}` (verified against third-party write-ups of
  the current ComfyUI API; re-verify against the installed 0.41.0 at
  integration). Default `filename` is a fresh unique name, so the server
  side never collides and `overwrite` stays false.
- `submit_img2img` now uploads the source PNG first and wires the returned
  `subfolder/name` into LoadImage node "11" (via the existing
  `inject_img2img(image_filename=...)` seam). The former precondition —
  "the parent basename must already exist in the ComfyUI input dir" — is
  GONE; this closes the open IC-2 gap where refining a project asset
  failed or used a stale same-named input file.
- Transport: `_UrllibTransport` gains `post_multipart` (stdlib-only,
  hand-rolled multipart — no new dependency). Fake transports must expose
  `post_multipart(url, fields, file_field, file_name, file_bytes, timeout)`.
