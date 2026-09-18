from vivado_agent_mcp.models import RecommendedAction, ToolResult


def test_result_contract_is_json_serializable() -> None:
    result = ToolResult.success(
        "ready",
        evidence={"stage": "synthesis"},
        recommended_actions=[
            RecommendedAction(tool="inspect_run", arguments={"job_id": "job_1"}, reason="poll")
        ],
    )

    assert result.to_dict() == {
        "ok": True,
        "state_changed": False,
        "summary": "ready",
        "evidence": {"stage": "synthesis"},
        "recommended_actions": [
            {"tool": "inspect_run", "reason": "poll", "arguments": {"job_id": "job_1"}}
        ],
        "error_code": None,
    }
