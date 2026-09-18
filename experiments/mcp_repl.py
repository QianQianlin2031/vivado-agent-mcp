"""Persistent black-box MCP client; workflow decisions stay with the calling Agent."""

from __future__ import annotations

import asyncio
import json
import os
import sys
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
            initialized = await session.initialize()
            print(
                json.dumps(
                    {"ready": True, "server": initialized.server_info.name},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line:
                    return
                if line.strip() == "quit":
                    return
                try:
                    request = json.loads(line)
                    result = await session.call_tool(request["tool"], request.get("arguments", {}))
                    response = {
                        "tool": request["tool"],
                        "result": result.structured_content,
                    }
                except Exception as exc:
                    response = {"client_error": type(exc).__name__, "message": str(exc)}
                print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
