# fake_comfyui stand-in spec (GPU-less CI)

Base: `http://127.0.0.1:8188`. In-memory fake; no GPU, no models, no installs.

## Routes + canned behaviors

| Method + route | Canned behavior |
|---|---|
| `POST /prompt` `{"prompt": {...}, "client_id"?}` | Validate numeric node IDs + known `class_type`s. Known `workflow_id` marker → `{"prompt_id": "prompt-abc123", "number": 1, "node_errors": {}}`. Unknown loader file (e.g. missing `flux1-schnell-fp8.safetensors`) → `MODEL_NOT_FOUND` error payload. Unknown workflow → `UNKNOWN_WORKFLOW`. |
| `GET /history/{prompt_id}` | Success → `fixtures/c2/history_success.json` entry (outputs: node `8`/`9` images `[{filename, subfolder, type}]` + `status.status_str="success"` + `meta`). Failure → `fixtures/c2/history_error.json` entry (`outputs: {}`, `status.status_str="error"`, `messages=[[node_id, message, details, extra]]`). Unknown id → `{}` (treated as not_found). |
| `GET /view?filename=&subfolder=&type=` | Success id → bytes of `fixtures/c2/tiny.png`. Unknown file → 404. |
| `GET /queue` | `{"queue_running": [...], "queue_pending": [...]}`; canned empty unless a submit is in-flight. Checked first while queued/running. |
| `POST /interrupt` | Cancels the running job; subsequent `GET /history/{id}` stays `{}` (cancelled, never resolves). |

## Rules the fake enforces

- Poll model: `GET /history/{id}` every 1 s, up to 300 s, then `JOB_TIMEOUT`.
- `fetch_result` reads `outputs.<node>.images[0]` → `GET /view` bytes; asserts PNG magic.
- img2img uploads are read-only fixtures; the fake never writes to source files.
