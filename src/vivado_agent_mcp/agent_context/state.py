# 它把 Vivado 返回的“带标签的 Tcl 文本输出”解析成结构化的工程状态，
# 并进一步告诉 Agent：当前工程处于什么阶段、下一步应该做什么。
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..models import RecommendedAction


@dataclass(slots=True)
class ProjectState:
    open: bool = False
    name: str | None = None
    directory: str | None = None
    part: str | None = None
    top: str | None = None
    source_count: int = 0
    constraint_count: int = 0
    synthesis_status: str | None = None
    implementation_status: str | None = None
    parse_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def recommended_actions(self) -> list[RecommendedAction]:
        if not self.open:
            return [
                RecommendedAction(
                    tool="run_tcl",
                    arguments={"command": "open_project <path-to-project.xpr>"},
                    reason="No Vivado project is open.",
                )
            ]
        if not self.top:
            return [
                RecommendedAction(
                    tool="run_tcl",
                    arguments={"command": "set_property top <module> [current_fileset]"},
                    reason="The project has no top module.",
                )
            ]
        if self.source_count == 0:
            return [
                RecommendedAction(
                    tool="run_tcl",
                    arguments={"command": "add_files <source-file>"},
                    reason="The project contains no design sources.",
                )
            ]
        synth = (self.synthesis_status or "").lower()
        impl = (self.implementation_status or "").lower()
        if any(word in synth for word in ("error", "failed")):
            return [
                RecommendedAction(
                    tool="diagnose_run",
                    arguments={"run_name": "synth_1"},
                    reason="Synthesis did not complete successfully.",
                )
            ]
        if "complete" not in synth:
            return [
                RecommendedAction(
                    tool="run_synthesis",
                    arguments={},
                    reason="Synthesis has not completed.",
                )
            ]
        if any(word in impl for word in ("error", "failed")):
            return [
                RecommendedAction(
                    tool="diagnose_run",
                    arguments={"run_name": "impl_1"},
                    reason="Implementation did not complete successfully.",
                )
            ]
        route_complete = "route_design complete" in impl
        bitstream_complete = "write_bitstream complete" in impl
        if not route_complete and not bitstream_complete:
            return [
                RecommendedAction(
                    tool="run_implementation",
                    arguments={},
                    reason="Implementation has not reached routed design.",
                )
            ]
        if bitstream_complete:
            return []
        return [
            RecommendedAction(
                tool="check_build_readiness",
                arguments={},
                reason="The routed design is ready for timing and diagnostic gates.",
            )
        ]


@dataclass(slots=True)
# 记录某一个 Vivado run 的状态
class RunSnapshot:
    run_name: str
    status: str
    progress: str | None = None
    directory: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_tagged_output(output: str, prefix: str) -> dict[str, str]:
    """Parse `PREFIX:key=value` lines while preserving values containing '='."""

    values: dict[str, str] = {}
    marker = f"{prefix}:"
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith(marker):
            continue
        pair = stripped[len(marker) :]
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        values[key] = value
    return values


def parse_project_state(output: str) -> ProjectState:
    values = parse_tagged_output(output, "VAMCP_PROJECT")
    if values.get("open") == "0":
        return ProjectState(open=False)

    warnings: list[str] = []
    source_count = _parse_int(values.get("source_count"), "source_count", warnings)
    constraint_count = _parse_int(values.get("constraint_count"), "constraint_count", warnings)
    return ProjectState(
        open=values.get("open") == "1",
        name=_none_if_empty(values.get("name")),
        directory=_none_if_empty(values.get("directory")),
        part=_none_if_empty(values.get("part")),
        top=_none_if_empty(values.get("top")),
        source_count=source_count,
        constraint_count=constraint_count,
        synthesis_status=_none_if_empty(values.get("synthesis_status")),
        implementation_status=_none_if_empty(values.get("implementation_status")),
        parse_warnings=warnings,
    )


def parse_run_snapshot(output: str, run_name: str) -> RunSnapshot:
    values = parse_tagged_output(output, "VAMCP_RUN")
    return RunSnapshot(
        run_name=run_name,
        status=values.get("status", "unknown"),
        progress=_none_if_empty(values.get("progress")),
        directory=_none_if_empty(values.get("directory")),
    )


def _none_if_empty(value: str | None) -> str | None:
    return value if value not in (None, "") else None


def _parse_int(value: str | None, label: str, warnings: list[str]) -> int:
    try:
        return int(value or 0)
    except ValueError:
        warnings.append(f"Could not parse {label}: {value!r}")
        return 0


""" 
把底层 Vivado 输出转成 Agent 可以直接理解和决策的结构化上下文。

parse_project_state()：Vivado 文本 → ProjectState
recommended_actions()：ProjectState → Agent 下一步动作

 """
