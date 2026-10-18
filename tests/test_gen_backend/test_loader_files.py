"""loader_files tests (C2 v0.1.2 F2 slice): mocked transport, no live server.

Covers: allowlisted-loader parse (DualCLIPLoader + UnetLoaderGGUF +
CheckpointLoaderSimple-empty), unknown loader (no network), unreachable
mapping, server-404 mapping. Live read-only GET /object_info shape was
probed separately (PQM0 2026-10-18); these tests pin the adapter logic.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from gen_backend import ComfyClient, UnknownLoaderError
from gen_backend.client import _HttpStatusError
from gen_backend.errors import (
    COMFY_UNREACHABLE,
    UNKNOWN_LOADER,
    ComfyUnreachableError,
)


DUAL_CLIP_INFO = {
    "DualCLIPLoader": {
        "input": {
            "required": {
                "clip_name1": [["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"]],
                "clip_name2": [["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"]],
                "type": [["sdxl", "flux"]],
            }
        }
    }
}

UNET_GGUF_INFO = {
    "UnetLoaderGGUF": {
        "input": {"required": {"unet_name": [["flux1-schnell-Q4_K_S.gguf"]]}}
    }
}

CKPT_EMPTY_INFO = {
    "CheckpointLoaderSimple": {
        "input": {"required": {"ckpt_name": [[], {"tooltip": "The name of the checkpoint."}]}}
    }
}


class _ObjectInfoStub:
    """Stub transport serving canned /object_info payloads (records URLs)."""

    def __init__(self, payload=None, exc=None):
        self.payload = payload
        self.exc = exc
        self.urls = []

    def get_json(self, url, timeout):
        self.urls.append(url)
        if self.exc is not None:
            raise self.exc
        return 200, self.payload

    def post_json(self, url, body, timeout):
        raise AssertionError("unexpected POST " + url)

    def get_bytes(self, url, timeout):
        raise AssertionError("unexpected GET bytes " + url)


def _client(stub):
    return ComfyClient(transport=stub, sleep=lambda s: None, clock=lambda: 1000.0)


class LoaderFilesParseTest(unittest.TestCase):
    def test_dual_clip_parse_excludes_non_file_type(self):
        stub = _ObjectInfoStub(payload=DUAL_CLIP_INFO)
        result = _client(stub).loader_files("DualCLIPLoader")
        self.assertEqual(
            result,
            {
                "clip_name1": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
                "clip_name2": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
            },
        )
        self.assertTrue(stub.urls[0].endswith("/object_info/DualCLIPLoader"))

    def test_unet_gguf_parse(self):
        stub = _ObjectInfoStub(payload=UNET_GGUF_INFO)
        result = _client(stub).loader_files("UnetLoaderGGUF")
        self.assertEqual(result, {"unet_name": ["flux1-schnell-Q4_K_S.gguf"]})

    def test_ckpt_empty_list_preserved(self):
        stub = _ObjectInfoStub(payload=CKPT_EMPTY_INFO)
        result = _client(stub).loader_files("CheckpointLoaderSimple")
        self.assertEqual(result, {"ckpt_name": []})

    def test_vae_parse(self):
        stub = _ObjectInfoStub(
            payload={"VAELoader": {"input": {"required": {"vae_name": [["ae.safetensors"]]}}}}
        )
        self.assertEqual(
            _client(stub).loader_files("VAELoader"), {"vae_name": ["ae.safetensors"]}
        )


class LoaderFilesErrorTest(unittest.TestCase):
    def test_unknown_loader_no_network(self):
        stub = _ObjectInfoStub(payload={})
        with self.assertRaises(UnknownLoaderError) as ctx:
            _client(stub).loader_files("NopeLoader")
        self.assertEqual(ctx.exception.code, "UNKNOWN_LOADER")
        self.assertEqual(ctx.exception.code, UNKNOWN_LOADER)
        self.assertTrue(str(ctx.exception).startswith("UNKNOWN_LOADER:"))
        self.assertEqual(stub.urls, [])  # allowlist rejects before any GET

    def test_non_string_loader_unknown(self):
        stub = _ObjectInfoStub(payload={})
        with self.assertRaises(UnknownLoaderError):
            _client(stub).loader_files(None)
        self.assertEqual(stub.urls, [])

    def test_unreachable_propagates(self):
        stub = _ObjectInfoStub(exc=ComfyUnreachableError("ComfyUI unreachable at x"))
        with self.assertRaises(ComfyUnreachableError) as ctx:
            _client(stub).loader_files("VAELoader")
        self.assertEqual(ctx.exception.code, COMFY_UNREACHABLE)

    def test_server_404_maps_to_unknown_loader(self):
        stub = _ObjectInfoStub(exc=_HttpStatusError(404, {}))
        with self.assertRaises(UnknownLoaderError) as ctx:
            _client(stub).loader_files("UnetLoaderGGUF")
        self.assertEqual(ctx.exception.code, UNKNOWN_LOADER)

    def test_missing_key_maps_to_unknown_loader(self):
        stub = _ObjectInfoStub(payload={"something_else": {}})
        with self.assertRaises(UnknownLoaderError) as ctx:
            _client(stub).loader_files("VAELoader")
        self.assertEqual(ctx.exception.code, UNKNOWN_LOADER)


if __name__ == "__main__":
    unittest.main()
