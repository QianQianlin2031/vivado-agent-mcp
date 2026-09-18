"""Agent workflows composed from small, deterministic Vivado Tcl operations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from . import tcl_commands
from .agent_context.jobs import JobRecord, JobRegistry
from .agent_context.state import (
    ProjectState,
    parse_project_state,
    parse_run_snapshot,
    parse_tagged_output,
)
from .config import discover_vivado
from .models import RecommendedAction, ToolResult
from .vivado.protocol import TclResponse, tcl_quote
from .vivado.session import (
    VivadoCommandTimeout,
    VivadoNotRunningError,
    VivadoSession,
    VivadoSessionBusy,
    VivadoSessionError,
)


class SessionLike(Protocol):
    @property
    def is_alive(self) -> bool: ...

    @property
    def pid(self) -> int | None: ...

    async def start(self) -> bool: ...

    async def stop(self) -> bool: ...

    async def execute(self, command: str, *, timeout_seconds: float = 30) -> TclResponse: ...


class VivadoAgentService:
    """The domain layer used by MCP tools and directly by unit tests."""

    def __init__(self, session: SessionLike | None = None) -> None:
        self._session = session
        self.jobs = JobRegistry()

    @property
    def session_alive(self) -> bool:
        return self._session is not None and self._session.is_alive

    async def start_vivado(self, *, vivado_path: str = "", project_path: str = "") -> ToolResult:
        try:
            project: Path | None = None
            if project_path:
                project, valid_project = await asyncio.to_thread(
                    _resolve_project_path, project_path
                )
                if not valid_project:
                    return ToolResult.failure(
                        f"Project file is not a readable .xpr: {project}",
                        error_code="INVALID_PROJECT_PATH",
                    )

            if self._session is None:
                executable = discover_vivado(vivado_path or None)
                if executable is None:
                    return ToolResult.failure(
                        "Vivado executable was not found.",
                        error_code="VIVADO_NOT_FOUND",
                        evidence={"discovery_hint": "Set VIVADO_PATH or pass vivado_path."},
                    )
                self._session = VivadoSession(executable)

            started = await self._session.start()
            project_opened = False
            if project is not None:
                response = await self._session.execute(
                    f"open_project {tcl_quote(str(project))}", timeout_seconds=60
                )
                if not response.ok:
                    if started:
                        await self._session.stop()
                    return self._tcl_failure(
                        response, "Vivado started but the project could not open"
                    )
                project_opened = True

            return ToolResult.success(
                "Vivado Tcl session is ready.",
                state_changed=started or project_opened,
                evidence={
                    "started_now": started,
                    "project_opened": project_opened,
                    "pid": self._session.pid,
                },
                recommended_actions=[
                    RecommendedAction(
                        tool="inspect_project",
                        arguments={},
                        reason="Establish current project state before changing it.",
                    )
                ],
            )
        except Exception as exc:
            return self._exception_result(exc)

    async def stop_vivado(self) -> ToolResult:
        if self._session is None:
            return ToolResult.success("Vivado is already stopped.")
        try:
            stopped = await self._session.stop()
            return ToolResult.success(
                "Vivado Tcl session stopped." if stopped else "Vivado is already stopped.",
                state_changed=stopped,
            )
        except Exception as exc:
            return self._exception_result(exc)

    async def run_tcl(self, command: str, *, timeout_seconds: float = 30) -> ToolResult:
        if not command.strip():
            return ToolResult.failure("Tcl command is empty.", error_code="INVALID_ARGUMENT")
        try:
            response = await self._execute(command, timeout_seconds=timeout_seconds)
            if not response.ok:
                return self._tcl_failure(response, "Tcl command failed")
            return ToolResult.success(
                "Tcl command completed.",
                state_changed=True,
                evidence={"output": response.output, "return_code": response.return_code},
                recommended_actions=[
                    RecommendedAction(
                        tool="inspect_project",
                        arguments={},
                        reason="Refresh Agent context after an arbitrary Tcl command.",
                    )
                ],
            )
        except Exception as exc:
            return self._exception_result(exc)

    async def inspect_project(self) -> ToolResult:
        try:
            state = await self._inspect_project_state()
            summary = (
                f"Project {state.name or '(unnamed)'} is open."
                if state.open
                else "No Vivado project is open."
            )
            return ToolResult.success(
                summary,
                evidence={"project": state.to_dict()},
                recommended_actions=state.recommended_actions(),
            )
        except Exception as exc:
            return self._exception_result(exc)

    async def run_synthesis(self, *, jobs: int = 4) -> ToolResult:
        return await self._launch_guarded(
            kind="synthesis", run_name="synth_1", jobs=jobs, require_synthesis=False
        )

    async def run_implementation(self, *, jobs: int = 4) -> ToolResult:
        return await self._launch_guarded(
            kind="implementation", run_name="impl_1", jobs=jobs, require_synthesis=True
        )

    async def inspect_run(self, *, job_id: str = "", run_name: str = "") -> ToolResult:
        record: JobRecord | None = None
        if job_id:
            record = self.jobs.get(job_id)
            if record is None:
                return ToolResult.failure(f"Unknown job id: {job_id}", error_code="JOB_NOT_FOUND")
            run_name = record.run_name
        if not run_name:
            return ToolResult.failure("Provide job_id or run_name.", error_code="INVALID_ARGUMENT")

        try:
            response = await self._execute(tcl_commands.inspect_run(run_name))
            if not response.ok:
                return self._tcl_failure(response, f"Could not inspect run {run_name}")
            snapshot = parse_run_snapshot(response.output, run_name)
            if record is not None:
                self.jobs.update(record, status=snapshot.status, progress=snapshot.progress)
            actions = self._run_actions(snapshot.status, run_name)
            return ToolResult.success(
                f"Run {run_name}: {snapshot.status}.",
                evidence={
                    "run": snapshot.to_dict(),
                    "job": record.to_dict() if record else None,
                },
                recommended_actions=actions,
            )
        except Exception as exc:
            return self._exception_result(exc)

    async def diagnose_run(self, *, run_name: str, max_issues: int = 20) -> ToolResult:
        try:
            response = await self._execute(
                tcl_commands.diagnose_run(run_name, max_issues), timeout_seconds=60
            )
            if not response.ok:
                return self._tcl_failure(response, f"Could not diagnose run {run_name}")
            evidence = self._parse_diagnostics(response.output)
            issue_count = evidence["error_count"] + evidence["critical_warning_count"]
            summary = (
                f"Found {issue_count} important issue(s) in {run_name}."
                if issue_count
                else f"No errors or critical warnings found in {run_name}."
            )
            actions = []
            if issue_count:
                actions.append(
                    RecommendedAction(
                        tool="run_tcl",
                        arguments={"command": "# Apply the smallest fix supported by the evidence"},
                        reason="Resolve the reported root cause before relaunching the run.",
                    )
                )
            return ToolResult.success(summary, evidence=evidence, recommended_actions=actions)
        except Exception as exc:
            return self._exception_result(exc)

    async def check_build_readiness(self) -> ToolResult:
        try:
            state = await self._inspect_project_state()
            impl_status = (state.implementation_status or "").lower()
            is_routed = "route_design complete" in impl_status
            bitstream_done = "write_bitstream complete" in impl_status
            if not is_routed and not bitstream_done:
                return ToolResult.success(
                    "Build readiness is BLOCKED: implementation is not routed.",
                    evidence={"verdict": "BLOCKED", "project": state.to_dict()},
                    recommended_actions=state.recommended_actions(),
                )

            timing_response = await self._execute(
                tcl_commands.READINESS_TIMING, timeout_seconds=120
            )
            if not timing_response.ok:
                return self._tcl_failure(timing_response, "Timing readiness query failed")
            timing = parse_tagged_output(timing_response.output, "VAMCP_READY")

            diag_response = await self._execute(
                tcl_commands.diagnose_run("impl_1", 20), timeout_seconds=60
            )
            if not diag_response.ok:
                return self._tcl_failure(diag_response, "Implementation diagnostics failed")
            diagnostics = self._parse_diagnostics(diag_response.output)

            verdict, reasons = self._readiness_verdict(timing, diagnostics)
            actions: list[RecommendedAction] = []
            if verdict == "READY":
                actions.append(
                    RecommendedAction(
                        tool="generate_bitstream",
                        arguments={},
                        reason="Implementation passed timing and diagnostic gates.",
                    )
                )
            else:
                actions.append(
                    RecommendedAction(
                        tool="diagnose_run",
                        arguments={"run_name": "impl_1"},
                        reason="Inspect the evidence that blocked bitstream generation.",
                    )
                )
            return ToolResult.success(
                f"Build readiness is {verdict}: {'; '.join(reasons)}",
                evidence={
                    "verdict": verdict,
                    "reasons": reasons,
                    "timing": timing,
                    "diagnostics": diagnostics,
                },
                recommended_actions=actions,
            )
        except Exception as exc:
            return self._exception_result(exc)

    async def generate_bitstream(self, *, jobs: int = 4) -> ToolResult:
        readiness = await self.check_build_readiness()
        if not readiness.ok:
            return readiness
        if readiness.evidence.get("verdict") != "READY":
            return ToolResult.failure(
                "Bitstream launch refused because the build did not pass readiness gates.",
                error_code="BUILD_NOT_READY",
                evidence=readiness.evidence,
                recommended_actions=readiness.recommended_actions,
            )
        try:
            response = await self._execute(tcl_commands.launch_bitstream(jobs))
            if not response.ok:
                return self._tcl_failure(response, "Bitstream launch failed")
            launch = parse_tagged_output(response.output, "VAMCP_LAUNCH")
            started = launch.get("started") == "1"
            completed = launch.get("completed") == "1"
            status = "queued" if started else launch.get("previous_status", "running")
            job = self.jobs.create(kind="bitstream", run_name="impl_1", status=status)
            if completed:
                self.jobs.update(job, status=status, progress="100%", state="completed")
            if completed:
                summary = "Bitstream generation was already complete."
            elif started:
                summary = "Bitstream generation is running."
            else:
                summary = "Bitstream generation was already running."
            return ToolResult.success(
                summary,
                state_changed=started,
                evidence={"job": job.to_dict(), "launch": launch},
                recommended_actions=[
                    RecommendedAction(
                        tool="inspect_run",
                        arguments={"job_id": job.job_id},
                        reason="Poll the asynchronous bitstream run.",
                    )
                ],
            )
        except Exception as exc:
            return self._exception_result(exc)

    def job_snapshot(self, job_id: str) -> ToolResult:
        job = self.jobs.get(job_id)
        if job is None:
            return ToolResult.failure(f"Unknown job id: {job_id}", error_code="JOB_NOT_FOUND")
        return ToolResult.success(f"Job {job_id}: {job.status}.", evidence={"job": job.to_dict()})

    async def close(self) -> None:
        if self._session is not None:
            await self._session.stop()

    async def _launch_guarded(
        self, *, kind: str, run_name: str, jobs: int, require_synthesis: bool
    ) -> ToolResult:
        try:
            state = await self._inspect_project_state()
            if not state.open or not state.top or state.source_count == 0:
                return ToolResult.failure(
                    f"{kind.capitalize()} launch refused because project "
                    "prerequisites are missing.",
                    error_code="PROJECT_NOT_READY",
                    evidence={"project": state.to_dict()},
                    recommended_actions=state.recommended_actions(),
                )
            synth_status = (state.synthesis_status or "").lower()
            if require_synthesis and "complete" not in synth_status:
                return ToolResult.failure(
                    "Implementation launch refused because synthesis is incomplete.",
                    error_code="SYNTHESIS_NOT_COMPLETE",
                    evidence={"synthesis_status": state.synthesis_status},
                    recommended_actions=[
                        RecommendedAction(
                            tool="run_synthesis",
                            arguments={},
                            reason="Implementation depends on a completed synthesis run.",
                        )
                    ],
                )

            response = await self._execute(tcl_commands.launch_run(run_name, jobs))
            if not response.ok:
                return self._tcl_failure(response, f"Could not launch {run_name}")
            launch = parse_tagged_output(response.output, "VAMCP_LAUNCH")
            started = launch.get("started") == "1"
            status = "queued" if started else launch.get("previous_status", "running")
            job = self.jobs.create(kind=kind, run_name=run_name, status=status)
            summary = (
                f"{kind.capitalize()} is running."
                if started
                else f"{kind.capitalize()} was already running."
            )
            return ToolResult.success(
                summary,
                state_changed=started,
                evidence={"job": job.to_dict(), "launch": launch},
                recommended_actions=[
                    RecommendedAction(
                        tool="inspect_run",
                        arguments={"job_id": job.job_id},
                        reason=f"Poll the asynchronous {kind} run.",
                    )
                ],
            )
        except Exception as exc:
            return self._exception_result(exc)

    async def _inspect_project_state(self) -> ProjectState:
        response = await self._execute(tcl_commands.PROJECT_INFO)
        if not response.ok:
            raise VivadoSessionError(response.error_message or "Project query failed")
        return parse_project_state(response.output)

    async def _execute(self, command: str, *, timeout_seconds: float = 30) -> TclResponse:
        if self._session is None:
            raise VivadoNotRunningError("Vivado is not running; call start_vivado first")
        return await self._session.execute(command, timeout_seconds=timeout_seconds)

    @staticmethod
    def _parse_diagnostics(output: str) -> dict[str, object]:
        values = parse_tagged_output(output, "VAMCP_DIAG")
        issues = [
            line.strip().split("=", 1)[1]
            for line in output.splitlines()
            if line.strip().startswith("VAMCP_DIAG:issue=")
        ]
        return {
            "error_count": int(values.get("errors", "0")),
            "critical_warning_count": int(values.get("critical_warnings", "0")),
            "log_path": values.get("log"),
            "issues": issues,
            "issues_truncated": int(values.get("emitted", "0"))
            < (int(values.get("errors", "0")) + int(values.get("critical_warnings", "0"))),
        }

    @staticmethod
    def _readiness_verdict(
        timing: dict[str, str], diagnostics: dict[str, object]
    ) -> tuple[str, list[str]]:
        setup = _float_or_none(timing.get("setup_slack"))
        hold = _float_or_none(timing.get("hold_slack"))
        errors = int(diagnostics["error_count"])
        critical = int(diagnostics["critical_warning_count"])
        reasons: list[str] = []
        if setup is None or hold is None:
            reasons.append("timing slack is unavailable")
        if setup is not None and setup < 0:
            reasons.append(f"setup slack is negative ({setup})")
        if hold is not None and hold < 0:
            reasons.append(f"hold slack is negative ({hold})")
        if errors:
            reasons.append(f"implementation log contains {errors} error(s)")
        if critical:
            reasons.append(f"implementation log contains {critical} critical warning(s)")
        if not reasons:
            return "READY", ["timing is non-negative and no blocking diagnostics were found"]
        if setup is None or hold is None:
            return "UNKNOWN", reasons
        return "BLOCKED", reasons

    @staticmethod
    def _run_actions(status: str, run_name: str) -> list[RecommendedAction]:
        normalized = status.lower()
        if any(word in normalized for word in ("error", "failed")):
            return [
                RecommendedAction(
                    tool="diagnose_run",
                    arguments={"run_name": run_name},
                    reason="The run status indicates failure.",
                )
            ]
        if "complete" in normalized:
            return [
                RecommendedAction(
                    tool="inspect_project",
                    arguments={},
                    reason="Refresh project state after run completion.",
                )
            ]
        return []

    @staticmethod
    def _tcl_failure(response: TclResponse, summary: str) -> ToolResult:
        return ToolResult.failure(
            summary,
            error_code="TCL_ERROR",
            evidence={
                "return_code": response.return_code,
                "output": response.output,
                "error_message": response.error_message,
            },
        )

    @staticmethod
    def _exception_result(exc: Exception) -> ToolResult:
        if isinstance(exc, VivadoNotRunningError):
            code = "VIVADO_NOT_RUNNING"
        elif isinstance(exc, VivadoSessionBusy):
            code = "SESSION_BUSY"
        elif isinstance(exc, VivadoCommandTimeout):
            code = "COMMAND_TIMEOUT"
        elif isinstance(exc, (ValueError, TypeError)):
            code = "INVALID_ARGUMENT"
        else:
            code = "VIVADO_SESSION_ERROR"
        return ToolResult.failure(str(exc), error_code=code)


def _float_or_none(value: str | None) -> float | None:
    if value in (None, "", "NA"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _resolve_project_path(project_path: str) -> tuple[Path, bool]:
    project = Path(project_path).expanduser().resolve()
    return project, project.is_file() and project.suffix.lower() == ".xpr"
