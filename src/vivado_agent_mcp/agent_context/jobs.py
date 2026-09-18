# 给 Vivado 的长时间异步任务建立一个“任务登记表”，
# 为每个任务分配稳定的 job_id，并记录它当前是运行中、完成还是失败。
# 像综合、实现、生成 bitstream 这种任务可能要跑很久，Agent 不能一直阻塞等待，
# 所以需要先启动任务，再通过一个 job_id 后续查询状态。
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class JobRecord:
    job_id: str
    kind: str  # 任务类型，例如 synthesis、implementation；
    run_name: str  # Vivado 里的真实 run
    state: str  # MCP 自己归一化后的状态，比如 active / completed / failed
    status: str  # Vivado 返回的原始状态
    progress: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobRegistry:
    """Track jobs for one MCP server lifetime; Vivado remains the source of truth."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def create(self, *, kind: str, run_name: str, status: str = "queued") -> JobRecord:
        existing = self.find_active(run_name)
        if existing is not None:
            return existing
        now = _now()
        record = JobRecord(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            kind=kind,
            run_name=run_name,
            state=_state_from_status(status),
            status=status,
            progress=None,
            created_at=now,
            updated_at=now,
        )
        self._jobs[record.job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def find_active(self, run_name: str) -> JobRecord | None:
        return next(
            (
                job
                for job in self._jobs.values()
                if job.run_name == run_name and job.state == "active"
            ),
            None,
        )

    def update(
        self,
        job: JobRecord,
        *,
        status: str,
        progress: str | None = None,
        state: str | None = None,
    ) -> JobRecord:
        job.status = status
        job.progress = progress
        job.state = state or _state_from_status(status)
        job.updated_at = _now()
        return job

    def all(self) -> list[JobRecord]:
        return list(self._jobs.values())


def _state_from_status(status: str) -> str:
    normalized = status.lower()
    if any(word in normalized for word in ("error", "failed", "cancel")):
        return "failed"
    if any(word in normalized for word in ("complete", "finished")):
        return "completed"
    return "active"


def _now() -> str:
    return datetime.now(UTC).isoformat()


""" 
Agent
   ↑
jobs.py
长任务如何登记、查询状态
   ↑
state.py
Vivado 当前工程 / run 是什么状态
   ↑
models.py
Tool 统一返回什么格式
   ↑
protocol.py
Tcl 消息怎么包装
   ↑
session.py
Vivado 进程怎么真正运行
   ↑
Vivado

create()：创建/复用一个 Job，并生成稳定 job_id
update()：同步最新的 Vivado 状态和进度
_state_from_status()：把 Vivado 各种状态统一成 active / completed / failed

 """
