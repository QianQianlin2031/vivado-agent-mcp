from vivado_agent_mcp.agent_context.state import parse_project_state, parse_run_snapshot


def test_project_state_recommends_next_stage() -> None:
    state = parse_project_state(
        "\n".join(
            [
                "VAMCP_PROJECT:open=1",
                "VAMCP_PROJECT:name=counter",
                "VAMCP_PROJECT:directory=C:/work/counter",
                "VAMCP_PROJECT:part=xc7a35tcpg236-1",
                "VAMCP_PROJECT:top=counter_top",
                "VAMCP_PROJECT:source_count=3",
                "VAMCP_PROJECT:constraint_count=1",
                "VAMCP_PROJECT:synthesis_status=Not started",
                "VAMCP_PROJECT:implementation_status=Not started",
            ]
        )
    )

    assert state.open
    assert state.source_count == 3
    assert state.recommended_actions()[0].tool == "run_synthesis"


def test_failed_run_recommends_diagnosis() -> None:
    state = parse_project_state(
        "\n".join(
            [
                "VAMCP_PROJECT:open=1",
                "VAMCP_PROJECT:top=top",
                "VAMCP_PROJECT:source_count=1",
                "VAMCP_PROJECT:constraint_count=0",
                "VAMCP_PROJECT:synthesis_status=ERROR",
            ]
        )
    )
    assert state.recommended_actions()[0].tool == "diagnose_run"


def test_run_snapshot_preserves_status() -> None:
    snapshot = parse_run_snapshot(
        "VAMCP_RUN:status=route_design Complete!\nVAMCP_RUN:progress=100%", "impl_1"
    )
    assert snapshot.run_name == "impl_1"
    assert snapshot.progress == "100%"


def test_completed_bitstream_has_no_redundant_build_action() -> None:
    state = parse_project_state(
        "\n".join(
            [
                "VAMCP_PROJECT:open=1",
                "VAMCP_PROJECT:top=top",
                "VAMCP_PROJECT:source_count=1",
                "VAMCP_PROJECT:constraint_count=1",
                "VAMCP_PROJECT:synthesis_status=synth_design Complete!",
                "VAMCP_PROJECT:implementation_status=write_bitstream Complete!",
            ]
        )
    )

    assert state.recommended_actions() == []
