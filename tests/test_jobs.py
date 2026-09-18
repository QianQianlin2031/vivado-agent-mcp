from vivado_agent_mcp.agent_context.jobs import JobRegistry


def test_active_job_creation_is_idempotent() -> None:
    registry = JobRegistry()
    first = registry.create(kind="synthesis", run_name="synth_1")
    second = registry.create(kind="synthesis", run_name="synth_1")

    assert first.job_id == second.job_id

    registry.update(first, status="synth_design Complete!")
    third = registry.create(kind="synthesis", run_name="synth_1")
    assert third.job_id != first.job_id


def test_completed_job_is_not_active() -> None:
    registry = JobRegistry()
    completed = registry.create(
        kind="bitstream", run_name="impl_1", status="write_bitstream Complete!"
    )

    assert completed.state == "completed"
    assert registry.find_active("impl_1") is None
