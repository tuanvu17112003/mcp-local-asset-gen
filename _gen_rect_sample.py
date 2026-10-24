"""Generate a 1024x512 seamless texture sample (new code, in-process)."""

import asyncio
import sys

sys.path.insert(0, ".")

from fastmcp import Client

from src.mcp_server.config import ServerConfig
from src.mcp_server.server import create_server


async def main():
    mcp = create_server(
        config=ServerConfig(project_root="assets/samples", comfyui_url="http://127.0.0.1:8000")
    )
    async with Client(mcp) as client:
        res = await client.call_tool(
            "generate_app_asset",
            {
                "prompt": "seamless wooden plank texture, warm oak, subtle grain, top-down, even lighting",
                "category": "texture",
                "style_preset": "pattern",
                "seamless": True,
                "include_image": True,
                "width": 1024,
                "height": 512,
                "save_path": "sample_texture_wood_1024x512.png",
            },
        )
        data = dict(res.data if getattr(res, "data", None) else res.structured_content)
        print("OK", data.get("asset_path"), "seed", data.get("seed"))


asyncio.run(main())
