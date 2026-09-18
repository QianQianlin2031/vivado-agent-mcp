# 统一规定 MCP 工具执行完以后，要以什么格式把结果返回给 Agent。

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, TypedDict, cast


# 当前工具执行完以后，建议 Agent 下一步调用什么工具。
class RecommendedActionDict(TypedDict):
    tool: str
    reason: str
    arguments: dict[str, Any]


class ToolResultDict(TypedDict):
    ok: bool
    state_changed: bool
    summary: str
    evidence: dict[str, Any]
    recommended_actions: list[RecommendedActionDict]
    error_code: str | None


@dataclass(frozen=True, slots=True)
class RecommendedAction:
    """A machine-actionable suggestion for the Agent's next tool call."""

    tool: str
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    """The common envelope used by every public MCP tool."""

    ok: bool
    state_changed: bool
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recommended_actions: list[RecommendedAction] = field(default_factory=list)
    error_code: str | None = None

    def to_dict(self) -> ToolResultDict:
        """Return a JSON-serializable representation with stable field names."""

        return cast(ToolResultDict, asdict(self))

    # ToolResult转成普通 Python dict，方便后面序列化成 JSON，通过 MCP 返回给客户端。

    @classmethod
    def success(
        cls,
        summary: str,
        *,
        state_changed: bool = False,
        evidence: dict[str, Any] | None = None,
        recommended_actions: list[RecommendedAction] | None = None,
    ) -> ToolResult:
        return cls(
            ok=True,
            state_changed=state_changed,
            summary=summary,
            evidence=evidence or {},
            recommended_actions=recommended_actions or [],
        )

    @classmethod
    def failure(
        cls,
        summary: str,
        *,
        error_code: str,
        evidence: dict[str, Any] | None = None,
        recommended_actions: list[RecommendedAction] | None = None,
    ) -> ToolResult:
        return cls(
            ok=False,
            state_changed=False,
            summary=summary,
            evidence=evidence or {},
            recommended_actions=recommended_actions or [],
            error_code=error_code,
        )


""" 
summary                给人看结论
evidence               给 Agent 看事实
recommended_actions    告诉 Agent 下一步能做什么

ok                     判断调用是否成功
state_changed          判断环境是否变化
error_code             进行稳定的错误分支

Vivado / Python 工具
        ↓
执行结果
        ↓
models.py 统一包装
        ↓
ToolResult
        ↓
MCP Client
        ↓
Agent
        ↓
Agent 根据结果决定下一步
"""
