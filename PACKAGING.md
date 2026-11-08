# Packaging & distribution

`mcp-local-asset-gen` is a normal Python distribution (setuptools, `src` layout).
The runtime dependency pins live in two places and must stay identical:
`requirements.txt` (the documented install route) and the `dependencies` list of
`pyproject.toml` — a test compares them, so edit both together.

## Install

From a checkout (editable, so code edits apply without reinstalling):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # runtime + pytest
.venv/Scripts/python -m pip install --no-deps -e .
```

`--no-deps` is intentional: the pins are already installed above, and skipping
the resolver keeps the venv byte-stable. A plain `pip install -e .` works too
and is what CI runs.

Once published, the same thing without a checkout:

```bash
pip install mcp-local-asset-gen
```

ComfyUI and its FLUX weights are **not** pip dependencies — they are a separate
local service (see `src/gen_backend/setup_notes.md` and the setup guide).

## Versioning

There is exactly ONE version string: `SERVER_VERSION` in
`src/mcp_server/config.py`. `pyproject.toml` declares the version as dynamic
(`[tool.setuptools.dynamic] version = {attr = "mcp_server.config.SERVER_VERSION"}`),
so the wheel, `pip show`, the `asset-gen` CLI and the `server_info` tool all
report the same number and a release bump touches one line. Nothing in the
packaging metadata may hardcode a release literal.

## Console script

Installing exposes one command:

```bash
asset-gen --help            # stdio MCP server (default transport)
asset-gen --transport http --port 8000
asset-gen --project-root /path/to/project   # pin the asset jail
asset-gen --comfyui-url http://127.0.0.1:8000
```

The entry point is `asset-gen = "mcp_server.server:main"`; the repo-root
`asset-gen.py` launcher calls the same `main()` and additionally puts its own
checkout on `sys.path`, which is why MCP clients should invoke the launcher by
absolute path with no `cwd` pin (see `opencode.json`).

## Offline selftest

```bash
python asset-gen.py --selftest
```

Runs with **no ComfyUI, no GPU, no rembg model**: it builds the server with stub
backend/postprocess stages, asserts the five tools are registered, then performs
one generate, one refine, one `server_info` and one `check_model` against a
throwaway temp jail. It prints a JSON report `{ok, tools, checks, version}` and
exits 0 on success, 1 on failure — the fast "is this install sane?" gate used by
CI.

## What ships in the wheel

The three top-level packages (`mcp_server`, `gen_backend`, `postprocess`) plus
their non-Python package data, declared in `[tool.setuptools.package-data]`:

| Path | Why |
|---|---|
| `gen_backend/workflows/*.json` | the API-format ComfyUI workflows the backend injects into |
| `gen_backend/workflows/*.md` | the node-ID map (`workflow_params.md`) |
| `gen_backend/setup_notes.md` | ComfyUI + model placement notes |
| `postprocess/setup_notes.md` | rembg model cache notes |
| `mcp_server/*.md` | server README + OpenCode wiring notes |

A wheel without the workflow JSONs installs cleanly and then fails at the first
generation, so `tests/test_integration/test_packaging.py` builds a real wheel
and asserts these members (and the `asset-gen` entry point) are inside it.

## CI matrix

`.github/workflows/ci.yml` has two jobs:

- **test** — `ubuntu-latest` and `windows-latest` × Python 3.11 and 3.13:
  `pip install -r requirements-dev.txt`, `pip check`, `python -m pytest tests/ -q`.
  The suite is CPU-only (fake backend + canned fixtures, plus a real fake
  ComfyUI HTTP server), so it needs no GPU; Windows is kept because the path
  jail has NTFS-specific branches.
- **install** — Python 3.13 on Ubuntu: installs the runtime set, then
  `pip install --no-deps -e .`, runs `pip check`, `asset-gen --help` and
  `python asset-gen.py --selftest`, builds a wheel with `python -m build` and
  asserts the package data + entry point are inside it.

Locally, both documented pytest spellings work — `pytest tests/ -q` (console
script) and `python -m pytest tests/ -q` — because the repo-root `conftest.py`
puts the checkout root and `src/` on `sys.path` for both import styles
(`from src.mcp_server...` and the top-level `import postprocess` shim).
