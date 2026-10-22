# Changelog

All notable changes to this project are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).
Copy the relevant entry into the GitHub Release notes when tagging.

## [Unreleased]

### Added
- **The agent chooses the output path** (C1 v0.1.5, user request
  2026-10-22): `save_path` may now be absolute. An absolute path is used
  exactly as given — the asset lands at that path — as long as it lands
  inside an approved root (the project root plus any named workspace).
  Relative paths behave exactly as before (resolved under the selected
  workspace root). Windows `\` separators are folded to `/`.
- New server flag `--allow-any-path`: lifts every containment check for
  absolute paths (default OFF, reported as `server_info.allow_any_path`).
- New result fields: `asset_path_absolute` (exact file location) and
  `asset_root` (the approved root owning `asset_path`) on
  `generate_app_asset` / `refine_asset`, and `allow_any_path` on
  `server_info`.

### Changed
- The jail follows the client: with no `--project-root`, the server uses
  its launch directory (the client's workspace for a client that starts the
  server in the project) instead of the MCP server's own checkout.
  Recommended OpenCode wiring is now the `asset-gen.py` launcher with no
  pinned `cwd`.
- `POLICY_DENIED` for an absolute path outside the approved roots now
  names the approved roots and the two ways to widen them
  (`--workspace name=path`, `--allow-any-path`).
- Containment is now decided on the **resolved** path: a link inside an
  approved root that points outside it is refused instead of writing
  outside the root.
- Refused save paths: NUL bytes, Windows reserved device names (`NUL`,
  `COM1`, …) and NTFS alternate-data-stream forms (`icon.png:evil`).
  A failing write is reported as `POSTPROCESS_FAILED` instead of a bare
  `OSError`.
- **The requested leaf is the written file** (C1 v0.1.6): the leaf must be
  `<stem>.png` with a PNG-safe stem (`[A-Za-z0-9._-]`, at least one letter
  or digit) and a lowercase extension. `icon.webp`, `icon.PNG` or
  `mon icône.png` are refused pre-backend with
  `POLICY_DENIED INVALID_SAVE_PATH` instead of silently writing `icon.png`
  and reporting the requested name — the tool no longer returns a path that
  does not exist.
- `refine_asset` with an `asset_id` now resolves the stored absolute
  location, so refining an asset that lives in another approved root works
  instead of failing with "parent missing"; the refined file is written
  next to its parent, in that same root.

### Fixed
- Published wiring docs corrected (`README.md` OpenCode snippet and test
  count, `src/mcp_server/opencode_wiring.md`, `asset-gen.py` docstring):
  they no longer teach the pattern that pinned the asset jail to the MCP
  server's own checkout.
- The agent guide and the setup guide now state the leaf rule, the
  refused path forms, and a "verify the jail root" step (the failure mode
  when a client launches the server outside the project).

### Verified
- 339 passed + 3 env-conditional skips + 11 subtests (venv, Python 3.13).
- Live MCP stdio end-to-end with the configured launcher argv from a
  foreign working directory: `project_root` follows the client, an absolute
  `save_path` lands exactly there, a relative one lands under the root,
  and an absolute path outside the roots is refused with nothing written.

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
