"""Query the real Vivado version and a small set of installed FPGA parts over MCP."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    parameters = StdioServerParameters(
        command=str(ROOT / ".venv" / "Scripts" / "python.exe"),
        args=["-m", "vivado_agent_mcp"],
        env=os.environ.copy(),
        cwd=str(ROOT),
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await session.call_tool("start_vivado", {})
            try:
                version = await session.call_tool(
                    "run_tcl", {"command": 'puts "VIVADO_VERSION=[version -short]"'}
                )
                parts = await session.call_tool(
                    "run_tcl",
                    {
                        "command": (
                            "set ps [lrange [get_parts -quiet] 0 29]; "
                            'puts "INSTALLED_PARTS=[join $ps ,]"'
                        )
                    },
                )
                selected_part = await session.call_tool(
                    "run_tcl",
                    {"command": ('puts "SELECTED_PART=[get_parts -quiet xc7a35tcpg236-1]"')},
                )
                print(
                    json.dumps(
                        {
                            "version": version.structured_content,
                            "parts": parts.structured_content,
                            "selected_part": selected_part.structured_content,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            finally:
                await session.call_tool("stop_vivado", {})


if __name__ == "__main__":
    asyncio.run(main())
