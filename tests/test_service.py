from __future__ import annotations

import asyncio

from vivado_agent_mcp.service import VivadoAgentService
from vivado_agent_mcp.vivado.protocol import TclResponse


class FakeSession:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.commands: list[str] = []
        self.is_alive = True
        self.pid = 42

    async def start(self) -> bool:
        return False

    async def stop(self) -> bool:
        self.is_alive = False
        return True

    async def execute(self, command: str, *, timeout_seconds: float = 30) -> TclResponse:
        self.commands.append(command)
        output = self.responses.pop(0)
        return TclResponse("fake", 0, output)


class StartTrackingSession(FakeSession):
    def __init__(self) -> None:
        super().__init__([])
        self.start_calls = 0

    async def start(self) -> bool:
        self.start_calls += 1
        return True


PROJECT_NOT_STARTED = "\n".join(
    [
        "VAMCP_PROJECT:open=1",
        "VAMCP_PROJECT:name=demo",
        "VAMCP_PROJECT:top=top",
        "VAMCP_PROJECT:source_count=2",
        "VAMCP_PROJECT:constraint_count=1",
        "VAMCP_PROJECT:synthesis_status=Not started",
        "VAMCP_PROJECT:implementation_status=Not started",
    ]
)


def test_synthesis_returns_job_and_poll_action() -> None:
    session = FakeSession(
        [
            PROJECT_NOT_STARTED,
            "\n".join(
                [
                    "VAMCP_LAUNCH:previous_status=Not started",
                    "VAMCP_LAUNCH:started=1",
                    "VAMCP_LAUNCH:run_name=synth_1",
                ]
            ),
        ]
    )
    service = VivadoAgentService(session)

    result = asyncio.run(service.run_synthesis(jobs=2))

    assert result.ok and result.state_changed
    assert result.evidence["job"]["job_id"].startswith("job_")
    assert result.recommended_actions[0].tool == "inspect_run"


def test_invalid_project_path_does_not_start_vivado() -> None:
    session = StartTrackingSession()
    service = VivadoAgentService(session)

    result = asyncio.run(service.start_vivado(project_path="missing.xpr"))

    assert not result.ok
    assert result.error_code == "INVALID_PROJECT_PATH"
    assert session.start_calls == 0


def test_implementation_is_guarded_by_synthesis() -> None:
    service = VivadoAgentService(FakeSession([PROJECT_NOT_STARTED]))

    result = asyncio.run(service.run_implementation())

    assert not result.ok
    assert result.error_code == "SYNTHESIS_NOT_COMPLETE"
    assert result.recommended_actions[0].tool == "run_synthesis"


def test_bitstream_is_refused_when_timing_is_negative() -> None:
    routed_project = PROJECT_NOT_STARTED.replace(
        "VAMCP_PROJECT:implementation_status=Not started",
        "VAMCP_PROJECT:implementation_status=route_design Complete!",
    )
    timing = "\n".join(
        [
            "VAMCP_READY:implementation_status=route_design Complete!",
            "VAMCP_READY:setup_slack=-0.120",
            "VAMCP_READY:hold_slack=0.080",
        ]
    )
    diagnostics = "\n".join(
        [
            "VAMCP_DIAG:errors=0",
            "VAMCP_DIAG:critical_warnings=0",
            "VAMCP_DIAG:emitted=0",
        ]
    )
    service = VivadoAgentService(FakeSession([routed_project, timing, diagnostics]))

    result = asyncio.run(service.generate_bitstream())

    assert not result.ok
    assert result.error_code == "BUILD_NOT_READY"
    assert result.evidence["verdict"] == "BLOCKED"
