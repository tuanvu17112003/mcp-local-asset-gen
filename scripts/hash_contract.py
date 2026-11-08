"""Contract content hash (the scheme the freezes describe).

SHA256 over the contract file's LF bytes with every ``sha256:<64hex>``
field normalized out (the self-hash field is excluded, so the recorded
value stays stable when it is written into the file).

    python .workflow/artifacts/mcp-agent-output-path/hash_contract.py

Prints ``<HASH> <path>`` per contract file.
"""

import hashlib
import pathlib
import re
import sys

HASH_FIELD = re.compile(r"sha256:[0-9a-fA-F]{64}")
PLACEHOLDER = "sha256:<64hex>"


def content_hash(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = HASH_FIELD.sub(PLACEHOLDER, text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parents[1]
    targets = sorted((root / "docs" / "contracts" / "mcp-local-asset-gen").glob("*/contract.md"))
    if len(sys.argv) > 1:
        targets = [pathlib.Path(arg) for arg in sys.argv[1:]]
    for target in targets:
        print(content_hash(target), str(target))