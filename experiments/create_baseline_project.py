"""Create the isolated baseline Vivado project through vivado-agent-mcp."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
CREATE_TCL = ROOT / "experiments" / "projects" / "baseline_counter" / "create_project.tcl"


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
            started = await session.call_tool("start_vivado", {})
            try:
                command = f'source "{CREATE_TCL.as_posix()}"'
                created = await session.call_tool("run_tcl", {"command": command})
                inspected = await session.call_tool("inspect_project", {})
                print(
                    json.dumps(
                        {
                            "start_vivado": started.structured_content,
                            "create_project": created.structured_content,
                            "inspect_project": inspected.structured_content,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            finally:
                await session.call_tool("stop_vivado", {})


if __name__ == "__main__":
    asyncio.run(main())
