"""Generate a sample gallery (new code, in-process FastMCP client)."""

import asyncio
import sys

sys.path.insert(0, ".")

from fastmcp import Client
from fastmcp.exceptions import ToolError

from src.mcp_server.config import ServerConfig
from src.mcp_server.server import create_server

SAMPLES = [
    {
        "prompt": "paper plane origami icon, flat style, teal and coral, minimal",
        "category": "icon",
        "save_path": "sample_icon_plane.png",
    },
    {
        "prompt": "cute fox face avatar, pixel art, 16-bit retro, orange fur",
        "category": "avatar",
        "style_preset": "pixel",
        "save_path": "sample_avatar_fox.png",
    },
    {
        "prompt": "art deco geometric tile pattern, gold and emerald green, elegant",
        "category": "pattern",
        "style_preset": "pattern",
        "seamless": True,
        "save_path": "sample_pattern_deco.png",
    },
    {
        "prompt": "small pastel watercolor dots on cream background, kids app texture",
        "category": "texture",
        "style_preset": "pattern",
        "seamless": True,
        "save_path": "sample_texture_dots.png",
    },
    {
        "prompt": "friendly robot mascot holding a paintbrush, 3D claymorphism, soft studio lighting",
        "category": "illustration",
        "style_preset": "clay",
        "save_path": "sample_mascot_robot.png",
    },
]


async def main():
    mcp = create_server(
        config=ServerConfig(project_root="assets/samples", comfyui_url="http://127.0.0.1:8000")
    )
    async with Client(mcp) as client:
        for s in SAMPLES:
            try:
                res = await client.call_tool("generate_app_asset", s)
                data = dict(res.data if getattr(res, "data", None) else res.structured_content)
                print("OK", s["save_path"], "seed", data.get("seed"))
            except ToolError as exc:
                print("FAIL", s["save_path"], str(exc)[:160])


asyncio.run(main())
