# asset-gen MCP server (C1)

FastMCP entrypoint: `src/mcp_server/server.py`. Imports cleanly without
`fastmcp` and without the sibling stages installed; only live serving
needs `fastmcp`.

## Run

Stdio (default):

```sh
python -m src.mcp_server.server --project-root .
```

Streamable-http opt-in:

```sh
python -m src.mcp_server.server --project-root . --transport http --port 8000
```

Python note: 3.10 imports and runs stub/canned paths, but live
diffusion/postprocess model paths need **Python >= 3.11** (a warning is
logged below that floor; nothing crashes at import).

## Tests

```sh
pytest tests/test_mcp_server/ -q
```
