# Setup and first asset — 15-minute run

This guide takes you from an empty checkout to a rendered avatar image in
the React sample. The proof run is the AC-4 15-minute run: start the
server, generate the golden bear avatar, check the files, embed the
result in `UserProfile.tsx`, and see it render.

Plain-prose note on honesty: the timed steps below describe the live
run. Steps that need a GPU and a running ComfyUI backend are marked
LIVE where they appear. Everything in the run-log appendix was actually
executed in a GPU-free environment and is marked DRY-RUN-ON-FAKES.
Nothing in this guide is a fabricated live output.

## Prerequisites

Allow about 5 minutes of one-off setup before the timed run. This is
not part of the 15-minute budget.

- **Python 3.11 or newer, via uv or a venv.** The background-removal
  library requires Python ≥ 3.11. Create isolated environments with
  `uv venv` (or `python -m venv`) so the project toolchain never
  touches your system Python. If `python --version` reports 3.10 or
  older, stop and upgrade first — the postprocessing step will fail on
  the old interpreter (see Troubleshooting).
- **Node.** Needed only to build and view the React sample. Any recent
  LTS release works; this guide was dry-checked against Node v24.14.0.
- **ComfyUI plus a diffusion model.** Run ComfyUI on `127.0.0.1:8188`
  (the default address the server polls). Place your model file where
  your ComfyUI install expects it — TBD-for-PQM0: the exact `models/`
  subdirectory and loader filename for the blessed checkpoint are not
  pinned in this guide's source context, so follow your ComfyUI
  install's layout and record the filename you used.
- **Disk and VRAM.** The default working point targets a 10 GB VRAM
  card such as the RTX 3080: the GGUF-Q4 quantized model (~6.8 GB on
  disk) generating at 512 px, 4 steps, guidance 0. That leaves headroom
  for the ComfyUI host process and the background-removal pass on the
  same card. If you have 12–16 GB or more, you can scale up to the FP8
  checkpoint (~17.2 GB on disk) for higher fidelity. Budget the model
  download plus a few hundred megabytes for generated PNGs and the
  per-user `rembg` model cache (`U2NET_HOME`, pre-downloadable with
  `python -c "from rembg import new_session; new_session('u2net')"`; the
  `rembg` CLI extra is not installed — see `requirements.txt`).

## OpenCode V2 configuration

Add the server to your OpenCode V2 native config (`opencode.json`).
The V2 shape nests local servers under `mcp.servers.<name>` with
`{type: "local", command: [...]}`. There is deliberately NO `enabled`
field in V2 — to pause a server without removing it, set
`"disabled": true` on that server entry. Secrets, if you ever need
them, go in environment variables (`{env:NAME}` substitution), never
in the JSON file.

```json
{
  "mcp": {
    "servers": {
      "local-asset-gen": {
        "type": "local",
        "command": ["python", "/path/to/mcp-local-asset-gen/asset-gen.py"]
      }
    }
  }
}
```

The `asset-gen.py` launcher works from any working directory (no
`PYTHONPATH`, no `cwd` pin). With no `--project-root`, the server jails
every relative `save_path` under its launch directory — which, for an MCP
client that starts the server in your project, is your project. Agents may
also pass an absolute `save_path`; it is honoured as given when it lands
inside an approved root (`server_info.project_root` plus the named
`workspaces`). Add `"--project-root", "<dir>"` to pin a specific root, or
`"--workspace", "name=<dir>"` to approve a second tree, or
`"--allow-any-path"` to lift the containment check for absolute paths.
This uses the stdio default; HTTP is opt-in only (`"--transport", "http",
"--port", "8000"`). Server module and flags confirmed against
`src/mcp_server/server.py` (`build_arg_parser`); see
`src/mcp_server/opencode_wiring.md` and the server README for the full
flag list (`--comfyui-url`, `--allow-remote`).

## The timed run (total ≤ 15 minutes)

Each step carries a minute budget. The budgets sum to exactly
15 minutes (2 + 5 + 2 + 3 + 3). Keep a clock running; if a step
overruns, note where and continue — the appendix log is part of the
AC-4 evidence.

### Step 1 — Start the server (2 min, LIVE)

Launch the MCP server from the project root with your 3.11+ venv
active, and confirm OpenCode lists the `local-asset-gen` tools:
`generate_app_asset`, `refine_asset`, and `server_info`. A quick
`server_info` call is the cheapest health check — if it reports the
backend unreachable, fix ComfyUI first (see Troubleshooting on
BACKEND_UNAVAILABLE) rather than burning generation minutes.

**Verify the jail root (once per project).** `server_info` reports
`project_root` — the directory every relative `save_path` resolves
under. With the recommended wiring (the `asset-gen.py` launcher, no
`cwd` pin) the server starts in the **client's workspace**, i.e. your
project. If `project_root` is *not* your project, either launch the
client from the project or add `--project-root <dir>` to the command.
Absolute `save_path` values are honoured as given, but only inside an
approved root (`project_root` plus any named `--workspace` root).

### Step 2 — Generate the golden bear avatar (5 min, LIVE)

Call `generate_app_asset` with the C1 golden parameters:

```json
{
  "category": "avatar",
  "prompt": "cute bear avatar, 3D claymorphism, soft lighting",
  "remove_bg": true,
  "save_path": "assets/images/bear_avatar.png"
}
```

This is the AC-1 call. Expect a result shaped like
`{"asset_path": "assets/images/bear_avatar.png", ...}` with the
512 × 512 job metadata. Each generation job may take up to 300 s
(per-job timeout) and the server runs at most 2 jobs concurrently,
so run this call alone. The canned echo of this exact call and result
is preserved in the fixtures (`fixtures/c1/bear_avatar_call.json`,
`fixtures/c1/bear_avatar_result.json`) for offline comparison.

### Step 3 — Check the files on disk (2 min, LIVE or DRY-RUN-ON-FAKES)

Verify the asset layout the React sample expects:

```text
assets/images/bear_avatar.png        # 1x base, 512x512
assets/images/bear_avatar@2x.png     # exact 2x, 1024x1024
assets/images/bear_avatar@3x.png     # exact 3x, 1536x1536
```

The `@2x`/`@3x` files must be exact pixel multiples of the base, and
the join rule is `path = output_dir / filename` — the pipeline
returns the filename leaf and the caller joins it onto the output
directory. Confirm every path is a project-root-relative POSIX path
with no `..` segments; anything escaping the root is rejected with
POLICY_DENIED. (The `.svg` vector variant is live since the C1/C3 v0.2
update: pass `format:"svg"` and a `<stem>.svg` leaf — it traces the result
with `vtracer`; only that file is written.)
### Step 4 — Embed the asset in UserProfile.tsx (3 min)

The sample component already imports the 1x leaf with a relative
import:

```tsx
import bearAvatar from '../../assets/images/bear_avatar.png';
// renders as: <img src={bearAvatar} alt="Cute bear avatar" />
```

After your live generation, the import resolves to your new file
with no code change needed — this step is just confirming the
import path matches the `asset_path` your generation returned.
If they disagree, fix the path (never the join rule) and re-check.

### Step 5 — Render check (3 min, LIVE)

Start the React sample and open the profile view. You should see the
bear avatar image rendered. Dependency-free: the sample needs `react`
only, no UI framework. If the image is missing, re-verify Step 3
(file actually on disk at the imported path) before suspecting the
component. Record pass/fail with a screenshot or a one-line note in
your run log.

## Dry run on fakes (no GPU required)

You can rehearse every step except actual diffusion without a GPU.
The documented fake path is:

1. Run ComfyUI-shaped checks against the canned fixtures instead of
   `127.0.0.1:8188`: `POST /prompt` → poll `GET /history/{id}` at
   1 s intervals up to 300 s → fetch bytes via `GET /view` and assert
   PNG magic (see `fixtures/c2/fake_comfyui.md` and
   `fixtures/c2/history_success.json`).
2. Replay the golden call offline: compare your tool arguments
   against `fixtures/c1/bear_avatar_call.json` and your result shape
   against `fixtures/c1/bear_avatar_result.json`.
3. Walk the full chain offline with
   `fixtures/integration/bear_avatar_chain.json`, which echoes the
   C1 golden result plus the C3-style `@1x/@2x/@3x` file entries.

Explicit CI statement: live ComfyUI is EXPECTED ABSENT in CI — the
dry-run-on-fakes path above is the supported offline check. Real
diffusion proof belongs to PQM0's integration check IC-2, and IC-2
never blocks a local Ready verdict. A dry-run pass proves wiring
and shapes; it never proves image quality.

## Troubleshooting

- **BACKEND_UNAVAILABLE.** The server cannot reach ComfyUI at
  `127.0.0.1:8188`. Start ComfyUI first, confirm the port, then retry
  `server_info`. In CI or on a machine without a GPU this error is
  expected — use the dry-run-on-fakes path instead.
- **Python 3.10 floor.** If your interpreter is 3.10.x (this guide's
  dry-run environment reported exactly that), the `rembg` step is
  unsupported. Switch to a Python ≥ 3.11 venv (the `uv`/venv route)
  and re-run. Do not attempt to force-install the library on 3.10.
- **VRAM pressure.** On a 10 GB card, stay on the GGUF-Q4 default at
  512 px / 4 steps / guidance 0. Out-of-memory or crawl-speed
  generation usually means the FP8 checkpoint is loaded on a card
  that cannot hold it — switch back to GGUF-Q4. Close other
  GPU-resident apps before the timed run.
- **Path-escape POLICY_DENIED.** Asset paths must stay inside an approved
  root (`server_info.project_root` plus the named `workspaces`). Relative
  paths resolve under the selected workspace root; absolute paths are used
  as given but must land inside an approved root. If a call is denied, the
  message lists the approved roots — retry with a path inside one, drop
  the `..` segments, or ask the human to add the tree (`--workspace
  name=path`) or to start the server with `--allow-any-path`.
- **"The jail root is not my project".** `server_info.project_root` is the
  directory the server was started in. Launch the client from your project
  (the launcher form starts the server in the client's workspace) or add
  `--project-root <dir>` to the server command. An absolute `save_path`
  outside the approved roots is refused with `POLICY_DENIED` — add the tree
  with `--workspace name=path` if the human wants it approved.
- **"My file name was rejected".** The leaf must be a lowercase `.png` file
  with a safe stem (`[A-Za-z0-9._-]`, at least one letter or digit): the
  server writes PNG assets, so `icon.webp`, `icon.PNG` and `mon icône.png`
  are refused pre-backend. Generate to a `.png` name and rename afterwards
  if you need another extension.
- **MODEL_MISSING / GENERATION_FAILED / POSTPROCESS_FAILED.** Missing
  checkpoint file (re-check model placement), diffusion failure
  (retry once, then inspect ComfyUI logs), or background-removal
  failure (confirm `rembg` installed in the 3.11 venv and the model
  cache reachable) respectively.
- **Background-removal model choice.** The default library model is
  `u2net` (fast); `isnet-general-use` is the quality opt-in. The
  `bria-rmbg` model is NON-commercial opt-in only — see the license
  note below.

## License note

`bria-rmbg` is NON-commercial by default and stays OFF unless you
explicitly opt in. Opting in requires accepting the vendor license
(`bria_license_accepted`) and, for any commercial use, a paid
agreement with the vendor. If neither applies to you, use the default
`u2net` model (or the `isnet-general-use` quality option), which carry
no such restriction in this setup.

## Appendix — run log (actual dry-run, GPU-free)

Commands below were actually executed on 2026-10-17 in the shared
checkout (Windows, no GPU, no ComfyUI). Each entry is labeled.
No live diffusion output appears here; anything requiring a live
backend is labeled LIVE-DEFERRED and was not executed.

- [DRY-RUN-ON-FAKES] `python --version` → `Python 3.10.11`
  (2026-10-17T22:41:02+07:00). Confirms the floor problem: this
  machine is below the required Python ≥ 3.11, so any `rembg` step
  would fail here — exactly the Troubleshooting case above.
- [DRY-RUN-ON-FAKES] `node --version` → `v24.14.0`
  (same timestamp). React-sample prerequisite satisfied.
- [DRY-RUN-ON-FAKES] JSON validation with `python -m json.tool`
  over all 9 fixture files → all 9 `OK`
  (2026-10-17T22:41:08+07:00): `fixtures/c1/bear_avatar_call.json`,
  `bear_avatar_result.json`, `path_escape_call.json`,
  `server_info.json`, `fixtures/c2/history_error.json`,
  `history_success.json`, `fixtures/c3/expected-manifest.json`,
  `fixtures/integration/bear_avatar_chain.json`,
  `layout_manifest.json`.
- [DRY-RUN-ON-FAKES] Read `fixtures/c1/bear_avatar_call.json` →
  `{"category": "avatar", "prompt": "cute bear avatar, 3D
  claymorphism, soft lighting", "remove_bg": true, "save_path":
  "assets/images/bear_avatar.png"}` — matches the Step 2 golden call
  verbatim.
- [DRY-RUN-ON-FAKES] Read `fixtures/c1/bear_avatar_result.json` →
  `{"asset_path": "assets/images/bear_avatar.png", ... 512x512 ...}`
  — matches the Step 2 expected result shape (AC-1).
- [DRY-RUN-ON-FAKES] Read
  `fixtures/integration/bear_avatar_chain.json` → carries the note
  "CANNED / DRY-RUN fixture … NOT live-diffusion proof (live proof is
  PQM0 IC-2)" plus the three C3-style entries
  `bear_avatar.png` / `bear_avatar@2x.png` / `bear_avatar@3x.png`
  (512 / 1024 / 1536 px) — matches the Step 3 layout check.
- [DRY-RUN-ON-FAKES] Import-guard `python -c "import rembg"` →
  `ModuleNotFoundError: No module named 'rembg'`
  (2026-10-17T22:41:12+07:00). Expected on this Python-3.10 box;
  documents that postprocessing is uninstallable here and must run
  under the 3.11 venv.
- [DRY-RUN-ON-FAKES] ComfyUI absence probe: TCP connect to
  `127.0.0.1:8188` returned Winsock `10061` (connection refused)
  (2026-10-17T22:41:16+07:00). Backend confirmed absent, as expected
  in a GPU-free environment — no further probing performed.
- [LIVE-DEFERRED] Steps 1, 2, 4-render, and 5 were NOT executed:
  no live server start, no live `generate_app_asset` call, no file
  generation, no browser render. Their procedure is documented above;
  their proof belongs to a GPU-backed run (PQM0 IC-2) and is honestly
  recorded here as deferred, not passed.
