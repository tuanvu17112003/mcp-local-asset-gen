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
assets/images/<stem>@2x.png      # exact 2x  (e.g. bear_avatar@2x.png, 1024x1024)
assets/images/<stem>@3x.png      # exact 3x  (e.g. bear_avatar@3x.png, 1536x1536)
assets/images/<stem>.svg         # optional vector, post-MVP only
```

Naming rule:

```text
<stem>[@Nx].{png,svg}      # N = 2, 3 for retina variants; no other suffixes
```

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
      "local-asset-gen": {
        "type": "local",
        "command": ["python", "-m", "mcp_server", "--root", "."]
      }
    }
  }
}
```

General form: `mcp.servers.<name> = {type:"local", command:[...]}`.

NOTE: there is NO `enabled` field in V2. To pause a server without
removing it, set `"disabled": true` on that server entry.
