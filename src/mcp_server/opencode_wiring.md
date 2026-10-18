# OpenCode wiring (asset-gen MCP server)

Server-side wiring reference. Transport contract (C1): **stdio is primary**,
served via `mcp.run()`; streamable-http is opt-in.

## opencode.json snippet

```json
{
  "mcp": {
    "servers": {
      "asset-gen": {
        "type": "local",
        "command": ["python", "-m", "src.mcp_server.server", "--project-root", "."]
      }
    }
  }
}
```

Notes:

- Run from the project root so `--project-root "."` jails every `save_path`
  under it (use an absolute path when the working directory differs).
- This uses the **stdio** default (`mcp.run()`). No extra transport flags.
- HTTP is opt-in only: append `"--transport", "http", "--port", "8000"`
  to `command` to serve streamable-http (`mcp.run(transport="streamable-http")`).
- To pause the server without deleting the entry, set `"disabled": true`
  on the server object. There is **no `enabled` field** in OpenCode V2
  wiring — do not add one.
- `comfyui-url` defaults to `http://127.0.0.1:8188` and stays
  **localhost-only** unless the server is started with `--allow-remote`
  (non-loopback URLs are refused without that explicit opt-in).
- Asset writes never escape the project root: absolute paths and `..`
  traversal are refused with `POLICY_DENIED`, and existing files need
  explicit `overwrite: true`.
