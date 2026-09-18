"""Exercise both MCP resources and both prompts against the completed baseline."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
BASELINE_XPR = (
    ROOT / "experiments" / "projects" / "baseline_counter" / "vivado" / "baseline_counter.xpr"
)


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
            await session.call_tool("start_vivado", {"project_path": str(BASELINE_XPR)})
            try:
                project = await session.read_resource("vivado://project/current")
                completed_bitstream = await session.call_tool("generate_bitstream", {"jobs": 4})
                job_id = completed_bitstream.structured_content["evidence"]["job"]["job_id"]
                job = await session.read_resource(f"vivado://jobs/{job_id}")
                build_prompt = await session.get_prompt(
                    "vivado_build_workflow",
                    {"project_path": str(BASELINE_XPR)},
                )
                debug_prompt = await session.get_prompt(
                    "vivado_debug_workflow", {"run_name": "synth_1"}
                )
                print(
                    json.dumps(
                        {
                            "project_resource": [
                                content.model_dump(mode="json") for content in project.contents
                            ],
                            "job_resource": [
                                content.model_dump(mode="json") for content in job.contents
                            ],
                            "build_prompt": build_prompt.model_dump(mode="json"),
                            "debug_prompt": debug_prompt.model_dump(mode="json"),
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            finally:
                await session.call_tool("stop_vivado", {})


if __name__ == "__main__":
    asyncio.run(main())
