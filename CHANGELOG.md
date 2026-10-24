# Changelog

All notable changes to this project are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).
Copy the relevant entry into the GitHub Release notes when tagging.

## [Unreleased]

### Added
- **Pattern slice (P1+P2+P7)** for họa tiết / hoa văn (C1/C3 v0.3;
  research `docs/research/pattern-features-research-2026-10-24.md`):
  new `pattern`/`texture` categories (remove_bg defaults false), a
  `style_preset:"pattern"` seamless/tileable prompt template, and
  `seamless:true` — an edge cross-fade (feather 32px) makes the result
  tileable, trim is skipped, and a `<stem>-tile.png` 2x2 preview file is
  emitted (`include_image` attaches the preview for self-checking seams).
- **`seamless` on `generate_app_asset`** (C1 v0.3): opt-in tileability
  via pure-Pillow cross-fade — no ComfyUI-side changes, no new
  dependency.
- **`width`/`height` capped at 1024** (P7): `INVALID_WIDTH` /
  `INVALID_HEIGHT` above the cap (OOM guard for the 10 GB GGUF-Q4
  target); schema gains `maximum: 1024`.
- **`format:"svg"` is real vector output** (C1/C3 v0.2; Q4 deferral
  lifted): `save_path` leaf must be `<stem>.svg` with `format:"svg"`
  (leaf rule is now format-matched; `.svg` + `format:"png"` and
  `.png` + `format:"svg"` are refused pre-backend with
  `POLICY_DENIED INVALID_SAVE_PATH`). For SVG only the `<stem>.svg`
  file is written — no PNG siblings. Traced with `vtracer==0.6.15`
  (new runtime dependency in `requirements.txt`; stable PyPI pin, MIT);
  fully transparent pixels are not traced, so transparent backgrounds
  carry into the SVG.
- **`include_image` on `generate_app_asset` and `refine_asset`**
  (C1 v0.2): opt-in flag (default `false`) that attaches the @1x PNG as
  an MCP image content block under the result's optional `image` key, so
  multimodal agents can view the generated asset. Default result shape
  is unchanged.
- **`refine_asset` now uploads the source PNG to ComfyUI**
  (C2 v0.1.3): new `ComfyClient.upload_image` (`POST /upload/image`,
  stdlib hand-rolled multipart — no new dependency) runs before the
  img2img submit; the returned `subfolder/name` is wired into LoadImage
  node "11" under a server-side `asset-gen/` input subfolder with a
  unique per-upload name. The former precondition — the parent basename
  had to pre-exist in the ComfyUI `input/` dir — is gone; refining a
  project asset no longer fails or picks up a stale same-named input
  file.
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
- Server instructions updated for the SVG leaf rule, the automatic
  img2img upload and `include_image`; still under the 4 KB token budget
  (tested).
- Contracts `docs/contracts/…/{C1,C2,C3}` gained additive addenda
  (v0.2 / v0.1.3 / v0.2) instead of rewrites; no required key or error
  code changed.
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
- **Fresh install no longer fails on a dependency conflict.** `rembg[cli]`
  pins `python-multipart<0.0.22` while `fastmcp 4.1.0` (via
  `fastmcp-slim[server]`) requires `python-multipart>=0.0.26`; pip could not
  satisfy both, so `pip install -r requirements.txt` failed with
  `ResolutionImpossible` on a clean environment. The `cli` extra is dropped
  (`rembg[cpu]==2.0.85`): the server only uses rembg as a library
  (`new_session`/`remove`). Pre-download the model with
  `python -c "from rembg import new_session; new_session('u2net')"` instead
  of `rembg d`; the docs, setup notes and the runtime error message say so.
- Published wiring docs corrected (`README.md` OpenCode snippet and test
  count, `src/mcp_server/opencode_wiring.md`, `asset-gen.py` docstring):
  they no longer teach the pattern that pinned the asset jail to the MCP
  server's own checkout.
- The agent guide and the setup guide now state the leaf rule, the
  refused path forms, and a "verify the jail root" step (the failure mode
  when a client launches the server outside the project).

### Verified
- 366 passed + 2 env-conditional skips + 11 subtests (venv, Python 3.13,
  2026-10-24 — pattern slice included); live check on RTX 3080: seamless
  floral pattern tile + 2x2 preview generated through the MCP tool surface
  and visually verified (repeat continuous; mild cross-fade ghosting as
  documented).
- 353 passed + 2 env-conditional skips + 11 subtests (venv, Python 3.13,
  2026-10-24 — svg/include_image/upload changes included; `pip check`
  clean with the added `vtracer==0.6.15` pin).
- 343 passed + 2 env-conditional skips + 11 subtests (venv, Python 3.13).
- Fresh-install proof (2026-10-23): a brand-new empty venv installing
  `requirements-dev.txt` resolves cleanly (fastmcp 4.1.0, rembg 2.0.85
  without the `cli` extra, Pillow 12.3.0, python-multipart 0.0.32),
  `pip check` reports no broken requirements, the suite passes (343/2/11)
  and the live stdio E2E passes in that venv.
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
