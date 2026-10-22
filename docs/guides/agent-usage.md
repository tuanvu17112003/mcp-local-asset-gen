# Agent usage guide — `asset-gen` MCP tools

Copy-pasteable reference for AI agents (and the humans configuring them).
Authoritative behavior: C1 v0.1.6; server help text mirrors this file.

## The one rule that matters: you choose the output path

`save_path` may be **absolute or relative**, and the server writes exactly
where you say:

- **Absolute** — `"C:/my-project/src/assets/icons/robot.png"` (POSIX
  `/home/me/proj/icon.png` and Windows `\` separators work too). Used
  verbatim; the file lands at that exact path.
- **Relative** — `"assets/icons/robot.png"`. Resolved under the selected
  workspace root (the server's `project_root` unless you pass
  `workspace:"<name>"`).

Two hard rules on the name itself:

- The leaf must be a **lowercase `.png` file** with a safe stem
  (`[A-Za-z0-9._-]`, at least one letter or digit). The server writes PNG
  assets, so `"icon.webp"`, `"icon"`, `"icon.PNG"` or `"mon icône.png"` are
  refused pre-backend with `POLICY_DENIED INVALID_SAVE_PATH` — the
  requested path and the written file are always the same path.
- `..` traversal is never accepted; NUL bytes, Windows reserved device
  names (`NUL`, `COM1`, … — Windows only) and NTFS alternate-data-stream
  forms (`icon.png:evil` — Windows only) are refused too.

An absolute path must land inside an **approved root**: the server's
`project_root` or one of the named `workspaces` (see `server_info`). If your
target tree is not approved, the call is refused with `POLICY_DENIED` and the
message names the approved roots — the human then adds the tree
(`--workspace name=path`) or starts the server with `--allow-any-path`
(which removes *every* containment check, including the resolved-path one).
`..` traversal is never accepted. Nothing is written on a refusal.

Check once per project with `server_info` (it returns `project_root`,
`workspaces` and `allow_any_path`) — no guessing, no per-call probing.

## Tool calls (exact shapes)

```jsonc
// 0. Always first: which roots are approved, is the backend up?
// → {backend, comfyui_url, models, version, reachable, queue_depth,
//    project_root, workspaces, allow_any_path}
{}  // server_info takes no arguments

// 0b. Non-default weights only: is the file visible to ComfyUI?
{"name": "flux1-schnell-Q4_K_S.gguf", "kind": "unet"}  // check_model
// → {available: true, loader: "UnetLoaderGGUF", checked_at: "..."}
// kind in unet|clip|vae|checkpoint (default: all four)

// 1. Generate (text-to-image → transparent PNG + @2x/@3x, returns asset_path)
{
  "prompt": "teal delivery robot icon, flat design, centered",
  "category": "icon",            // icon|illustration|avatar|splash
  "save_path": "assets/icons/robot.png",   // absolute or relative, must be .png
  "width": 512, "height": 512,
  "remove_bg": true,             // default true for icon/avatar
  "icon_sizes": [32, 64],        // optional extra PNGs: -32px, -64px
  "ico": true                    // optional multi-size .ico container
}
// → {"asset_path": "assets/icons/robot.png",
//     "asset_path_absolute": "C:/my-project/assets/icons/robot.png",
//     "asset_root": "C:/my-project",
//     "width": 512, ..., "seed": 458204358, "job_id": "925fab…"}
// asset_path is relative to asset_root (the approved root that owns the
// file); asset_path_absolute is the exact location. Embed whichever fits
// your code, e.g. <img src={robotIcon} alt="Robot" />.

// 2. Iterate without mutating the parent (image-to-image)
{
  "asset_path": "assets/icons/robot.png",
  "instruction": "recolor the robot orange, keep the shape",
  "save_path": "assets/icons/robot-orange.png",  // optional; default <stem>_refined.png
  "strength": 0.6                                // (0,1]: higher = more change
}
// Without save_path the refined file is the parent's sibling
// (<stem>_refined.png) inside the parent's own approved root.
// LIVE img2img precondition: the parent's BASENAME must already exist in
// ComfyUI's input folder (copy it there first), or the job fails validation.
```

## Errors (machine-readable CODE prefix — fix, don't blindly retry)

| Code | Meaning | Do this |
|---|---|---|
| `BACKEND_UNAVAILABLE` | ComfyUI down (url/port checked at call time) | Call `server_info`; if `reachable:false`, tell the human to start ComfyUI. Do not retry in a loop. |
| `GENERATION_FAILED` | ComfyUI rejected the prompt (payload attached: `JOB_FAILED`, `JOB_TIMEOUT`, `UNKNOWN_WORKFLOW`, `MODEL_NOT_FOUND`…) | Read the payload: unknown model → `check_model`, then ask human to install it. Timeout → record `job_id`, retry once later. |
| `POLICY_DENIED` | Path outside every approved root (the message lists them), `..` traversal, a link that resolves outside, a non-`.png` leaf, NUL bytes, a reserved device name, or an existing file without `overwrite:true` | Fix `save_path` (a `.png` file inside `server_info.project_root` / `workspaces`), or ask the human to widen the server's roots. Deliberately overwrite → set `overwrite:true`. |
| `INVALID_*` | Bad argument (`INVALID_ICON_SIZES`, `INVALID_STRENGTH`, `INVALID_ASSET_REF`…) | Fix the argument; rejected pre-backend, nothing ran. |
| `POSTPROCESS_FAILED` | Post-step failed (`SVG-DEFERRED`: vector output not built yet; `LICENSE_REQUIRED`: bria-rmbg is opt-in non-commercial — use the default model) | Drop `format:"svg"`, or drop the bria request. |
| `QUEUED` | >2 concurrent jobs (VRAM guard) | Wait for the earlier `job_id`, then call again. Reuse `job_id` for idempotent retries. |

## Practical notes

- `seed` reproduces a composition (same model/settings); omit it to explore.
- `style_preset`: flat | clay | line | pixel (prompt templates, not a model switch).
- Negative prompts: pass `negative` only where supported; schnell workflows ignore it by design.
- Generations take ~10–60 s on a 10 GB GPU; `check_model`/`server_info` answer instantly — use them to fail fast.
- The server never deletes or overwrites without `overwrite:true`, and `refine_asset` always writes a new file. Safe to experiment.
- Known limits: containment is path-based (a hard link inside an approved root is not detected) and the check-then-write gap is narrow; `asset_path_absolute` echoes your spelling (it is not case-normalized).
