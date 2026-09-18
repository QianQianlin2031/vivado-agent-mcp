"""Create both isolated experiment variants through the MCP server."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("synthesis_error_counter", "gate_unknown_counter")


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
            results: dict[str, object] = {}
            try:
                for index, variant in enumerate(VARIANTS):
                    if index:
                        await session.call_tool("run_tcl", {"command": "close_project"})
                    script = ROOT / "experiments" / "projects" / variant / "create_project.tcl"
                    created = await session.call_tool(
                        "run_tcl", {"command": f'source "{script.as_posix()}"'}
                    )
                    inspected = await session.call_tool("inspect_project", {})
                    results[variant] = {
                        "create": created.structured_content,
                        "inspect": inspected.structured_content,
                    }
                print(json.dumps(results, indent=2, ensure_ascii=False))
            finally:
                await session.call_tool("stop_vivado", {})


if __name__ == "__main__":
    asyncio.run(main())
