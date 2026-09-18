"""Direct stdio smoke test used before repeating the Codex connectivity demo."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


async def main() -> None:
    parameters = StdioServerParameters(
        command=str(PYTHON),
        args=["-m", "vivado_agent_mcp"],
        env=os.environ.copy(),
        cwd=str(PROJECT_ROOT),
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            results: dict[str, object] = {}
            try:
                results["start_vivado"] = (
                    await session.call_tool("start_vivado", {})
                ).structured_content
                results["inspect_project"] = (
                    await session.call_tool("inspect_project", {})
                ).structured_content
                results["run_tcl"] = (
                    await session.call_tool("run_tcl", {"command": 'puts "HELLO_VIVADO_MCP"'})
                ).structured_content
            finally:
                results["stop_vivado"] = (
                    await session.call_tool("stop_vivado", {})
                ).structured_content
            print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
