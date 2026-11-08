# React sample — asset file layout

Sample consumer for AC-1: `UserProfile.tsx` embeds the C1
`generate_app_asset` golden result at `assets/images/bear_avatar.png`
(category `"avatar"`, prompt `"cute bear avatar, 3D claymorphism,
soft lighting"`, `remove_bg: true`).

Dependency-free: `react` only. No UI framework, no extra packages.

## Asset file layout

All generated image assets live under the project-root-relative POSIX
directory:

```text
assets/images/<stem>.png        # 1x base (e.g. bear_avatar.png, 512x512)
assets/images/<stem>@2x.png      # @2x copy (scale of the base)
assets/images/<stem>@3x.png      # @3x copy (scale of the base)
assets/images/<stem>.svg         # vector variant (format:"svg" only)
assets/images/<stem>-32px.png    # optional icon_sizes export
assets/images/<stem>.ico         # optional multi-size icon container
assets/images/<stem>-v2.png      # optional extra variant (variants >= 2)
assets/images/<stem>-sheet.png   # optional contact-sheet grid
```

Naming rule:

```text
<stem>[@Nx].{png,svg} | <stem>-<N>px.png | <stem>.ico
                        | <stem>-vN.png | <stem>-sheet.png|.json
```

With `upscale: 2|4` the base is a REAL model-upscaled render, so `@2x/@3x`
derive from larger pixels rather than interpolating a 512 px image.

Join rule (postprocess pipeline note): C3 returns the **filename leaf**
only; the caller joins it onto the output dir:

```text
path = output_dir / filename
```

Example: `output_dir = "assets/images"`, `filename = "bear_avatar@2x.png"`
→ `assets/images/bear_avatar@2x.png`.

Path safety: all asset paths stay inside the project root, are stored as
relative POSIX paths, and MUST NOT contain `..` traversal segments.

The sample import resolves to the 1x leaf via a relative import:

```tsx
import bearAvatar from '../../assets/images/bear_avatar.png';
// renders as: <img src={bearAvatar} alt="Cute bear avatar" />
```

## MCP wiring (OpenCode V2)

Add the local MCP server to OpenCode V2 native config (`opencode.json`).
V2 shape (source: research F2):

```json
{
  "mcp": {
    "servers": {
      "asset-gen": {
        "type": "local",
        "command": ["<your-venv-python>", "<this-repo>/asset-gen.py",
                    "--comfyui-url", "http://127.0.0.1:8188"]
      }
    }
  }
}
```

Use the `asset-gen.py` launcher (no `PYTHONPATH`, no pinned `cwd`): with no
`--project-root` the asset jail follows the client's workspace, so a relative
`save_path` lands in YOUR project instead of the MCP checkout. There is no
`--root` flag (it was documented here in error).

General form: `mcp.servers.<name> = {type:"local", command:[...]}`.

NOTE: there is NO `enabled` field in V2. To pause a server without
removing it, set `"disabled": true` on that server entry.
