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
        "command": [
          "python",
          "/path/to/mcp-local-asset-gen/asset-gen.py",
          "--comfyui-url",
          "http://127.0.0.1:8000"
        ]
      }
    }
  }
}
```

Notes:

- Use the `asset-gen.py` launcher: it puts the checkout root on
  `sys.path`, so it works from **any** working directory (no `PYTHONPATH`,
  no pinned `cwd`).
- With **no** `--project-root`, the server jails every relative
  `save_path` under its **launch directory** — for OpenCode that is the
  client's workspace (the project you are working in), so the agent's
  relative path lands in your project. Verify once with `server_info`
  (`project_root`); if it is not your project, launch the client from the
  project or add `--project-root <dir>`.
- This uses the **stdio** default (`mcp.run()`). No extra transport flags.
- HTTP is opt-in only: append `"--transport", "http", "--port", "8000"`
  to `command` to serve streamable-http (`mcp.run(transport="streamable-http")`).
- To pause the server without deleting the entry, set `"disabled": true`
  on the server object. There is **no `enabled` field** in OpenCode V2
  wiring — do not add one.
- `comfyui-url` defaults to `http://127.0.0.1:8188` and stays
  **localhost-only** unless the server is started with `--allow-remote`
  (non-loopback URLs are refused without that explicit opt-in).
- Asset writes never escape the approved roots (the project root plus any
  named `--workspace` root): an **absolute** `save_path` inside an
  approved root is honoured as given, one outside is refused with
  `POLICY_DENIED`, `..` traversal is always refused, and existing files
  need explicit `overwrite: true`. `--allow-any-path` removes the
  containment check entirely (power-user opt-in, default off).

## Foreign working directory

- `<python> <root>/asset-gen.py` works from any directory (the launcher
  puts the checkout root on `sys.path` itself). Add
  `--project-root <dir>` to pin the asset jail to a specific tree when the
  client's launch directory is not your project.
- Alternatively keep `-m src.mcp_server.server` with the client's `cwd`
  set to the project root; both entrypoints share the same `main()`.
