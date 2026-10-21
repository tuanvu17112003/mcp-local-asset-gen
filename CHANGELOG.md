# Changelog

All notable changes to this project are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).
Copy the relevant entry into the GitHub Release notes when tagging.

## [Unreleased]

_Add the next batch here. Keep entries user-facing; link contracts where
behavior is pinned._

## [v0.1.1] — 2026-10-21 (tag: `v0.1.1`)

Patch release. Contract: C1 v0.1.1 → v0.1.3 (additive only; C2 v0.1.2,
C3 v0.1.1 unchanged).

### Added
- MCP initialization instructions (`InitializeResult.instructions`): the
  server now teaches agents its 4 tools, shapes, workflow order
  (`server_info` first), path-jail rules, and error codes on connect.
  Token-budget guarded (< 4 KB, tested).
- Explicit project root: `--project-root` is normalized to absolute,
  validated (non-directory rejected), and reported back in `server_info`
  as `project_root`, so agents can verify the asset jail before generating.
- Root `asset-gen.py` launcher: foreign-working-directory clients can run
  `<python> <root>/asset-gen.py --project-root <root>` with no
  `PYTHONPATH` setup (`python -m` still works with client `cwd` = root).

### Fixed
- Save path no longer silently follows the server process's working
  directory: without an explicit root the server logs a warning, and
  `server_info.project_root` exposes the effective jail.
- Foreign-cwd launch (`ModuleNotFoundError: No module named 'src'`)
  resolved via the new launcher entrypoint.

### Verified
- 253 passed + 3 env-conditional skips + 11 subtests (venv, Python 3.13).
- Live foreign-cwd end-to-end on RTX 3080: `server_info` (reachable,
  correct absolute root) → 512 px generate → icons + `.ico` (magic
  verified), file lands in project root, nothing leaks into the launch dir.

## [v0.1.0] — 2026-10-18 (initial public snapshot, squashed import)

- Local MCP server (FastMCP, stdio): `generate_app_asset`,
  `refine_asset`, `check_model`, `server_info` (live reachability +
  queue depth).
- ComfyUI adapter (FLUX.1-schnell GGUF-Q4 default + FP8 scale-up,
  submit/poll/fetch/cancel, `loader_files` introspection).
- Postprocess: `rembg` removal (u2net default, BRIA opt-in gated),
  trim/pad, `@1x/@2x/@3x`, icon pixel sizes, `.ico` export.
- React sample (`UserProfile.tsx`), setup guide, OpenCode wiring doc.
- Live-verified on RTX 3080 10 GB: txt2img, img2img refine, full chain,
  MCP-protocol end-to-end (see `docs/` research notes in local history).
- License: Apache-2.0.
