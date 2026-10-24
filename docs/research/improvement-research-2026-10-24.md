# Improvement research — mcp-local-asset-gen (2026-10-24)

Intent: after v0.5 shipped every item from
`asset-gen-completion-research-2026-10-24.md` (upload_image, SVG, include_image)
and the pattern slice (P1–P4, P7), find the next round of completion/improvement
work and verify each fix path. Research only — no code changed. Method: local
venv introspection (primary evidence) + FastMCP docs (Context7, `/prefecthq/fastmcp`)
+ web verification. Sources accessed 2026-10-24.

## 0. Shipped state (verified)

377 tests green; 4 tools (`generate_app_asset`, `refine_asset`, `check_model`,
`server_info`); pinned `fastmcp==4.1.0` (latest stable on PyPI is **4.1.3**,
verified via `pip index versions`), `rembg[cpu]==2.0.85`, `vtracer==0.6.15`.
No TODO/FIXME in `src/`. Nothing from the previous research docs is open.

## I1 — Long generations are silent and uncancellable (UX gap)

**Finding.** `generate_app_asset` blocks the tool call for the whole
submit/poll loop (up to `job_timeout_s`, ~300 s; a 512 px icon ≈ 30 s on the
RTX 3080 target). During the run the agent receives nothing, and there is no
MCP tool to cancel a stuck or unwanted job — `ComfyClient` already has
cancel (`POST /interrupt`) but it is not exposed as a tool.

**Verified fix path (a) — MCP progress notifications** (works on the pinned
version; verified in the project venv: `fastmcp 4.1.0`, `hasattr(Context,
'report_progress') == True`):

- Add `ctx: Context` to the tool signature; during the poll loop call
  `await ctx.report_progress(progress, total, message)`.
- Per FastMCP docs, calls are safe no-ops when the client sent no
  progressToken; also works inside background (Docket task) contexts.
- Progress source 1 (zero new deps): poll-loop ticks (queue position from
  `/queue`, elapsed/timeout as fraction).
- Progress source 2 (true per-node progress): ComfyUI WebSocket
  `ws://{base}/ws?clientId=<uuid>` pushes JSON frames keyed by `type` —
  `status`, `execution_start`, `executing` (`prompt_id`, node or null when
  done), `progress` (`value`/`max`), `executed`; filter frames by `prompt_id`
  (sources: docs.comfy.org `comms_routes` + `comms_messages`; 9elements
  walkthrough). Note: the current `_UrllibTransport` is HTTP-only; a WS
  client is stdlib-able but non-trivial — recommend tick-based first,
  WS as a verified upgrade.

**Verified fix path (b) — expose cancel**: new tool
`cancel_asset_job(job_id)` delegating to the existing client cancel path
(`POST /interrupt`). Smallest complete change; closes the uncancellable case.

**Fix path (c) — MCP background tasks** (`@mcp.tool(task=True)`) exists in
FastMCP 4 (protocol 2026-07-28 revision) but requires the separate
`fastmcp_tasks` / `fastmcp[tasks]` extra — **not installed** in the venv
(verified), and its in-memory backend + client polling support varies by
MCP client (OpenCode support unverified). Defer unless the user wants
non-blocking tool calls.

## I2 — Background removal quality: BiRefNet already ships in the pinned rembg

**Finding.** Default `u2net` is ~5 years old; edge quality on hair/thin
structures is the known weakness. Third-party benchmarks (Cloudflare
2025-08 evaluation; lofttools browser-model comparison; aireiter 2026
five-pipeline comparison) consistently rank **BiRefNet** best on edges, with
`isnet-general-use` the mid tier.

**Verified in the project venv (primary evidence, no new dependency):**
installed rembg 2.0.85 exposes session modules
`birefnet_general`, `birefnet_general_lite`, `birefnet_portrait`,
`birefnet_massive`, `dis_general_use`, `ben_custom` (plus the existing
`u2net`, `isnet_*`, `bria_rmbg`).

**Recommended minimal change:** new opt-in param
`remove_bg_model: str = "u2net"` (validation whitelist, same gate style as
`bria-rmbg`: default FOSS, anything else explicit). First use downloads the
ONNX model per user cache — document sizes (birefnet-general is ~900 MB;
`birefnet-general-lite` ~170 MB for slower machines). Mapping:
`"birefnet-general"` → session name `birefnet-general`, etc. Tool schema,
C3 addendum, tests.

## I3 — Patch bump `fastmcp==4.1.0 → 4.1.3`

Latest stable (verified `pip index versions`). 4.1.x is a fix sweep (OpenAPI,
proxies, auth, tasks, CLI, Python 3.15 support). Low risk; `pip check` +
suite rerun is the whole cost. Not urgent — 4.1.0 works.

## Candidates considered, not recommended now

- **True seamless via `spinagon/ComfyUI-seamless-tiling`** — already
  recorded as P5 in `pattern-features-research-2026-10-24.md`; only if the
  cross-fade ghosting disappoints (GPL-3.0 custom node, unverified with
  FLUX GGUF).
- **Style LoRAs** (Flat, 3D Claymorphism, Minimalist Line, Pixel Art) —
  needs per-style ComfyUI workflow JSONs with LoRA loader nodes + user-side
  weight downloads; prompt-template presets cover the same ground today.
- **Batch/variants (`n` images per call)** — orchestrator is single-job;
  agents can loop instead. Skip until asked.
- **WebSocket mid-generation preview images** (binary frames on `/ws`) —
  nice-to-have, big transport change; same seam as I1 source 2.

## Reuse check

| Need | Path | New dep? |
|---|---|---|
| Progress notifications | `fastmcp.Context.report_progress` (already installed) | No |
| Cancel | `ComfyClient` cancel → `POST /interrupt` (already implemented) | No |
| Better matte quality | rembg 2.0.85 `birefnet_*` sessions (already installed) | No |
| Non-blocking calls | `fastmcp_tasks` extra | Yes (defer) |

## Unresolved / decisions needed from user

1. **I1**: implement `cancel_asset_job` + tick-based progress now (S, no
   deps)? WebSocket per-node progress later?
2. **I2**: add `remove_bg_model` param (default `u2net`, opt-in
   `birefnet-general` / `birefnet-general-lite` / `isnet-general-use`)?
3. **I3**: bump fastmcp to 4.1.3 in the same pass or leave pinned?
