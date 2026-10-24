# Completion research — mcp-local-asset-gen (2026-10-24)

Intent: survey the shipped v0.1.x codebase against its architecture/contracts,
identify what is unfinished, and verify fix paths with sources. Research only —
no code changed. Method: CodeGraph index (54 files) + targeted source reads +
web verification (sources accessed 2026-10-24).

## 0. Shipped state (verified)

All three modules are complete and tested (343 passed per CHANGELOG):
4 MCP tools (stdio, FastMCP), path jail with named workspaces + absolute
`save_path` + `--allow-any-path`, ComfyUI adapter (submit/poll/fetch/cancel,
GGUF-Q4 + FP8 workflows, loader introspection), postprocess (rembg u2net /
isnet / bria-gated, trim/pad, `@1x/@2x/@3x`, icon sizes, `.ico`), style
presets, job registry with idempotency + `QUEUED` backpressure. No TODO/FIXME
left in `src/`. The gaps below are the documented deferrals plus one
unshipped seam found by reading the img2img path.

## F1 — img2img refine never uploads the source image (FUNCTIONAL GAP)

**Finding.** `refine_asset` → `orchestrator.refine()` → `_submit_img2img()`
passes the project-local absolute path of the parent asset to
`gen_backend.submit_img2img` → `build_img2img_params`, which records only
`input_png_name = os.path.basename(input_png_path)`; `inject_img2img` writes
that basename into the LoadImage node ("11"). **Nothing ever sends the bytes
to ComfyUI.** The docstring states it: "no upload is performed here — the
referenced basename must already exist in the ComfyUI input dir, and live
`/upload/image` wiring is confirmed only against a live ComfyUI at IC-2."

Consequence on a real install: `refine_asset` on any project asset fails
(generation uses a missing input), or silently uses a *same-named* stale
file in `ComfyUI/input/`. This is the only tool flow whose live-verification
row (IC-2) is still open.

**Verified fix path — ComfyUI `POST /upload/image`** (self-hosted, local
ComfyUI; sources: Runflow ComfyUI API guide; 9elements ComfyUI API hosting
walkthrough; Comfy-Org issue #4352):

- `POST {base}/upload/image`, `multipart/form-data`:
  - `image` (file, required)
  - `overwrite` (string `"true"`/`"false"`, default `"false"` → ComfyUI
    appends a numeric suffix, e.g. `example_1.png`, on collision)
  - `subfolder` (string, relative to the server's `input/` dir)
  - `type` (string: `input` (default) | `temp` | `output`)
- Response: `{"name": "...", "subfolder": "...", "type": "input"}`.
- LoadImage input value format: `[subfolder/]name` (optionally
  ` [type]` suffix); files uploaded with `subfolder` need the joined
  `subfolder/name` string, not the bare basename.

**Recommended minimal change** (research recommendation, not implemented):
1. Add `upload_image(png_bytes, *, subfolder, overwrite=False, type="input")`
   to `ComfyClient` returning `{name, subfolder}`; on collision either pass
   `overwrite=true` under a per-job unique subfolder (preferred:
   `subfolder="asset-gen"` + job-scoped stem, so nothing user-visible is
   overwritten) or use the response `name`.
2. `_submit_img2img` uploads first, then threads the returned
   `subfolder/name` through `inject_img2img(image_filename=...)` — that
   parameter already exists and accepts the joined form.
3. Transport note: the current `_UrllibTransport` is JSON-only;
   `multipart/form-data` needs ~20 lines of hand-rolled stdlib multipart
   (no new dependency) — consistent with the zero-dep transport choice.
4. Fake backend + fixtures need a matching canned `/upload/image` route.

**Limitation:** endpoint facts verified against third-party write-ups of the
current ComfyUI code, not the ComfyUI source file itself in this session;
pin against the installed ComfyUI (0.41.0) at implementation time.

## F2 — SVG output deferred (known decision; re-activation path updated)

**Finding.** `format="svg"` raises `SVG-DEFERRED` pre-backend
(`orchestrator.generate`), `vectorize_rgba` is a stub that raises
(`vectorize.py`: "Q4 PNG-first decision (vtracer deferred)"). This is a
recorded user decision (Q4), not an accident — but it is the largest
unshipped feature promised by the schema (`schemas.py` still advertises
`enum: ["png","svg"]`, so agents see an option that always errors).

**Updated facts (2026-10-24):**
- PyPI **stable is `vtracer 0.6.15`** (released 2026-03-23, Python ≥3.7,
  wheels for CPython 3.7–3.14): its API is the **legacy**
  `convert_image_to_svg_py(...)` file-to-file form. The `convert_file /
  convert_bytes / convert_pixels` + `Config` preset API noted in the
  2026-10-17 research belongs to the **1.0.0a4 pre-release**, which has
  still not reached stable PyPI.
- Architecture doc said "pin at re-activation" — the correct pin today is
  either `vtracer==0.6.15` (stable, legacy API, MIT) or a pinned
  `1.0.0a*` (alpha). Stable is the lower-risk choice; the stub seam
  (`vectorize_rgba`) already isolates the API choice to one file.
- Open design point when re-activating: vtracer traces RGB rasters; for
  transparent icon output, decide between (a) flatten RGBA onto a matte
  before tracing (simplest; opaque SVG) or (b) trace color + alpha mask
  separately and merge (transparent SVG, more work). Until then, the
  honest cleanup is to remove `"svg"` from the advertised enum or label it
  reserved, so agents stop choosing an option that can only fail.

## F3 — Tool results are paths-only; agents never see the asset

**Finding.** `generate_app_asset` / `refine_asset` return
`{asset_path, asset_path_absolute, asset_root, job_id, ...}` dicts. A
multimodal client gets no image block, so the agent cannot self-check what
it generated (style match, background actually removed) without a second
file-read tool that renders the PNG.

**Verified fix path — FastMCP image results**
(source: goastmcp.com/servers/tools): FastMCP ships
`from fastmcp.utilities.types import Image` (also `Audio`, `File`);
`Image(data=<bytes>, format="png")` or `Image(path=...)` converts to an MCP
`ImageContent` block with correct MIME + base64 handled by FastMCP.
**Caveat:** auto-conversion happens only when the helper is returned
directly or in a list — **not nested inside a dict**; nested use requires
explicit `Image(...).to_image_content()` in the dict.

**Recommended minimal change:** add opt-in `include_image: bool = False` to
both tools; when true, merge `{"image": Image(data=base_png_bytes,
format="png").to_image_content()}` into the result dict. Opt-in keeps the
default payload small (vision tokens are not free) and keeps the C1 result
schema backward compatible.

## Reuse check (nothing new to add)

| Need | Path | New dep? |
|---|---|---|
| Upload source PNG | hand-rolled stdlib multipart in `_UrllibTransport` + `client.upload_image` | No |
| See the asset | `fastmcp.utilities.types.Image` (already installed via fastmcp 4.1.0) | No |
| SVG | `vtracer` (MIT) — only when the user un-defers Q4 | Yes (then) |

## Unresolved / decisions needed from user

1. **F1 implement now?** It closes the only broken live flow (IC-2). Recommended
   next concrete task.
2. **F2**: un-defer SVG (pick vtracer pin + matte vs alpha strategy), or
   stop advertising `"svg"` in the schema until then.
3. **F3**: opt-in `include_image` — wanted?
4. ComfyUI version pin: verify `/upload/image` field names against the
   installed 0.41.0 instance at implementation time.
