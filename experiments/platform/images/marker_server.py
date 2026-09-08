"""Return one random marker through native MCP image content."""

import argparse
import asyncio
import base64
import io
import json
import secrets
from pathlib import Path

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from PIL import Image, ImageDraw, ImageFont


def render_marker(row: int, column: int) -> bytes:
    """Draw a labeled four-by-four grid with one red marker."""
    image = Image.new("RGB", (640, 640), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=25)
    origin, cell = 110, 120
    draw.text((320, 30), "Locate the red marker", fill="black", font=font, anchor="mm")
    for index in range(4):
        center = origin + index * cell + cell // 2
        draw.text((center, 80), f"C{index + 1}", fill="black", font=font, anchor="mm")
        draw.text((65, center), f"R{index + 1}", fill="black", font=font, anchor="mm")
    for index in range(5):
        offset = origin + index * cell
        draw.line((origin, offset, origin + 4 * cell, offset), fill="#555555", width=3)
        draw.line((offset, origin, offset, origin + 4 * cell), fill="#555555", width=3)
    x = origin + (column - 1) * cell + cell // 2
    y = origin + (row - 1) * cell + cell // 2
    draw.ellipse((x - 28, y - 28, x + 28, y + 28), fill="#db1f35")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def serve(evidence: Path) -> None:
    server = Server("p01-marker")
    observed = False

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="observe",
                description="Return an image of one red marker in a labeled four-by-four grid.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.ImageContent]:
        nonlocal observed
        if name != "observe" or arguments:
            raise ValueError("Call observe without arguments.")
        if observed:
            raise ValueError("This trial permits one observation.")
        observed = True
        row, column = secrets.randbelow(4) + 1, secrets.randbelow(4) + 1
        png = render_marker(row, column)
        content = types.ImageContent(
            type="image", data=base64.b64encode(png).decode("ascii"), mimeType="image/png"
        )
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "marker.png").write_bytes(png)
        (evidence / "witness.json").write_text(json.dumps({"row": row, "column": column}) + "\n")
        (evidence / "server-content.json").write_text(content.model_dump_json() + "\n")
        return [content]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    asyncio.run(serve(parser.parse_args().evidence))
