"""MCP surface: 10 tools, 2 resources, and 2 workflow prompts."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import MCPServer

from .models import ToolResultDict
from .service import VivadoAgentService

_active_service: VivadoAgentService | None = None


@asynccontextmanager
async def lifespan(_: MCPServer) -> AsyncIterator[None]:
    """Own the Vivado session for exactly the MCP server lifetime."""

    global _active_service
    _active_service = VivadoAgentService()
    try:
        yield
    finally:
        await _active_service.close()
        _active_service = None


mcp = MCPServer("vivado-agent-mcp", lifespan=lifespan)


def get_service() -> VivadoAgentService:
    """Return the lifecycle service, with a lazy instance for direct tests."""

    global _active_service
    if _active_service is None:
        _active_service = VivadoAgentService()
    return _active_service


@mcp.tool()
async def start_vivado(vivado_path: str = "", project_path: str = "") -> ToolResultDict:
    """Start one headless Vivado Tcl session and optionally open an existing .xpr project."""

    result = await get_service().start_vivado(vivado_path=vivado_path, project_path=project_path)
    return result.to_dict()


@mcp.tool()
async def stop_vivado() -> ToolResultDict:
    """Stop the Vivado process owned by this MCP server."""

    return (await get_service().stop_vivado()).to_dict()


@mcp.tool()
async def run_tcl(command: str, timeout_seconds: float = 30) -> ToolResultDict:
    """Use raw Tcl as an escape hatch, then refresh project context before further actions."""

    return (await get_service().run_tcl(command, timeout_seconds=timeout_seconds)).to_dict()


@mcp.tool()
async def inspect_project() -> ToolResultDict:
    """Read current project, sources, part, top module, and build-run states."""

    return (await get_service().inspect_project()).to_dict()


@mcp.tool()
async def inspect_run(job_id: str = "", run_name: str = "") -> ToolResultDict:
    """Inspect an asynchronous job by MCP job ID or a native Vivado run name."""

    return (await get_service().inspect_run(job_id=job_id, run_name=run_name)).to_dict()


@mcp.tool()
async def run_synthesis(jobs: int = 4) -> ToolResultDict:
    """Launch synthesis idempotently and return a job ID instead of blocking."""

    return (await get_service().run_synthesis(jobs=jobs)).to_dict()


@mcp.tool()
async def run_implementation(jobs: int = 4) -> ToolResultDict:
    """Launch implementation only after project and synthesis prerequisites pass."""

    return (await get_service().run_implementation(jobs=jobs)).to_dict()


@mcp.tool()
async def generate_bitstream(jobs: int = 4) -> ToolResultDict:
    """Launch bitstream generation only when timing and diagnostic gates pass."""

    return (await get_service().generate_bitstream(jobs=jobs)).to_dict()


@mcp.tool()
async def diagnose_run(run_name: str, max_issues: int = 20) -> ToolResultDict:
    """Extract bounded errors and critical warnings from a Vivado run log."""

    return (await get_service().diagnose_run(run_name=run_name, max_issues=max_issues)).to_dict()


@mcp.tool()
async def check_build_readiness() -> ToolResultDict:
    """Gate bitstream generation on routed state, timing slack, and blocking diagnostics."""

    return (await get_service().check_build_readiness()).to_dict()


@mcp.resource("vivado://project/current")
async def current_project_resource() -> str:
    """Current project context for read-only Agent grounding."""

    result = await get_service().inspect_project()
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


@mcp.resource("vivado://jobs/{job_id}")
def job_resource(job_id: str) -> str:
    """Last known state for one MCP-managed asynchronous job."""

    result = get_service().job_snapshot(job_id)
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


@mcp.prompt()
def vivado_build_workflow(project_path: str = "") -> str:
    """Guide an Agent through an evidence-driven Vivado build."""

    project_hint = project_path or "<path-to-project.xpr>"
    return f"""You are operating Vivado through the vivado-agent-mcp server.

Goal: build {project_hint} safely and report evidence, not guesses.

Workflow rules:
1. Call start_vivado with project_path, then inspect_project.
2. Follow recommended_actions returned by each tool; do not invent run state.
3. Launch synthesis and implementation with their dedicated tools. They are asynchronous:
   retain each job_id and poll inspect_run until completed or failed.
4. On failure, call diagnose_run and explain the smallest evidence-backed fix.
5. Call check_build_readiness before generate_bitstream. Never bypass a BLOCKED or UNKNOWN verdict.
6. Use run_tcl only when no dedicated tool expresses the required operation,
   then inspect_project again.
7. Finish with a concise table of stage, status, and supporting evidence.
"""


@mcp.prompt()
def vivado_debug_workflow(run_name: str = "synth_1") -> str:
    """Guide an Agent through bounded, evidence-first run diagnosis."""

    return f"""Diagnose Vivado run {run_name} through vivado-agent-mcp.

1. Call inspect_project and inspect_run(run_name={run_name!r}).
2. If the run failed, call diagnose_run(run_name={run_name!r}).
3. Group reported issues by likely root cause; do not treat every repeated log line as a new cause.
4. Propose the smallest reversible fix. Use run_tcl only if needed.
5. Re-run only the failed stage, poll it by job_id, and compare new evidence with the old evidence.
6. Stop after success or after one unresolved blocker, clearly stating what human input is required.
"""


def run() -> None:
    """Run the MCP server over stdio for local Agent clients."""

    mcp.run(transport="stdio")
