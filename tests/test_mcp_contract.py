import asyncio

from vivado_agent_mcp.server import mcp


def test_mcp_capabilities_are_discoverable() -> None:
    tools = {tool.name for tool in asyncio.run(mcp.list_tools())}
    resources = {str(resource.uri) for resource in asyncio.run(mcp.list_resources())}
    templates = {
        str(resource.uri_template) for resource in asyncio.run(mcp.list_resource_templates())
    }
    prompts = {prompt.name for prompt in asyncio.run(mcp.list_prompts())}

    assert tools == {
        "start_vivado",
        "stop_vivado",
        "run_tcl",
        "inspect_project",
        "inspect_run",
        "run_synthesis",
        "run_implementation",
        "generate_bitstream",
        "diagnose_run",
        "check_build_readiness",
    }
    assert resources == {"vivado://project/current"}
    assert templates == {"vivado://jobs/{job_id}"}
    assert prompts == {"vivado_build_workflow", "vivado_debug_workflow"}


def test_tool_schemas_expose_agent_inputs() -> None:
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    schemas = {name: tool.input_schema for name, tool in tools.items()}

    assert set(schemas["start_vivado"]["properties"]) == {"vivado_path", "project_path"}
    assert set(schemas["inspect_run"]["properties"]) == {"job_id", "run_name"}
    assert schemas["run_synthesis"]["properties"]["jobs"]["default"] == 4
    assert set(tools["inspect_project"].output_schema["properties"]) == {
        "ok",
        "state_changed",
        "summary",
        "evidence",
        "recommended_actions",
        "error_code",
    }


def test_tool_call_returns_structured_content() -> None:
    result = asyncio.run(mcp.call_tool("inspect_project", {}))

    assert result.structured_content is not None
    assert result.structured_content["ok"] is False
    assert result.structured_content["error_code"] == "VIVADO_NOT_RUNNING"
