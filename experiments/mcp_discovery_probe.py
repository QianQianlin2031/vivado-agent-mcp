"""Black-box stdio discovery probe used by the experiment report."""

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
            initialize_result = await session.initialize()
            tools = await session.list_tools()
            resources = await session.list_resources()
            templates = await session.list_resource_templates()
            prompts = await session.list_prompts()
            not_running = await session.call_tool("inspect_project", {})

            print(
                json.dumps(
                    {
                        "server": initialize_result.server_info.model_dump(mode="json"),
                        "tools": [tool.name for tool in tools.tools],
                        "resources": [str(resource.uri) for resource in resources.resources],
                        "resource_templates": [
                            str(template.uri_template) for template in templates.resource_templates
                        ],
                        "prompts": [prompt.name for prompt in prompts.prompts],
                        "inspect_project_without_vivado": not_running.structured_content,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
