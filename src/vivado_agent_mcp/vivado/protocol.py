# 消息应该怎么包装、怎么解析

import re
import uuid
from dataclasses import dataclass

_SAFE_TCL_NAME = re.compile(r"^[A-Za-z0-9_.:/-]+$")


class TclProtocolError(RuntimeError):
    """Raised when a response violates the MCP-to-Vivado framing protocol."""


@dataclass(frozen=True, slots=True)
class TclRequest:
    request_id: str
    # 这次调用的唯一编号
    command: str
    # 真正想执行的 Tcl 命令
    payload: str
    # 包装以后真正发给 Vivado 的内容
    end_marker: str


@dataclass(frozen=True, slots=True)
class TclResponse:
    request_id: str
    return_code: int
    output: str
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.return_code == 0


def validate_tcl_name(value: str, *, label: str = "name") -> str:

    if not value or not _SAFE_TCL_NAME.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def tcl_quote(value: str) -> str:
    # 对用户输入进行 Tcl 转义

    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def create_request(command: str, request_id: str | None = None) -> TclRequest:

    if not command.strip():
        raise ValueError("Tcl command must not be empty")

    request_id = request_id or uuid.uuid4().hex
    if not re.fullmatch(r"[a-fA-F0-9]+", request_id):
        raise ValueError("request_id must contain hexadecimal characters only")

    command_hex = command.encode("utf-8").hex()
    # 防止原 Tcl 命令中的特殊字符破坏外层包装脚本。
    end_marker = f"<<<VAMCP:{request_id}:END>>>"
    payload = "\n".join(
        [
            f"set __vamcp_cmd [encoding convertfrom utf-8 [binary format H* {command_hex}]]",
            "set __vamcp_rc [catch {uplevel #0 $__vamcp_cmd} __vamcp_out]",
            'if {$__vamcp_out ne ""} {puts $__vamcp_out}',
            f'puts "<<<VAMCP:{request_id}:RC=$__vamcp_rc>>>"',
            f'puts "{end_marker}"',
            "flush stdout",
            "",
        ]
    )
    return TclRequest(request_id, command, payload, end_marker)


def parse_response(request: TclRequest, raw_output: str) -> TclResponse:

    status_pattern = re.compile(
        rf"^<<<VAMCP:{re.escape(request.request_id)}:RC=(\d+)>>>$", re.MULTILINE
    )
    matches = list(status_pattern.finditer(raw_output))
    if len(matches) != 1:
        raise TclProtocolError(
            f"Expected one status marker for request {request.request_id}, found {len(matches)}"
        )

    status_match = matches[0]
    body = raw_output[: status_match.start()].strip()
    body = _strip_vivado_prompt_echo(body, request.payload)
    return_code = int(status_match.group(1))
    return TclResponse(
        request_id=request.request_id,
        return_code=return_code,
        output=body,
        error_message=body if return_code else None,
    )


def _strip_vivado_prompt_echo(output: str, payload: str) -> str:
    """Remove common interactive prompt/echo noise without hiding tool output."""

    lines = output.splitlines()
    payload_lines = {line.strip() for line in payload.splitlines() if line.strip()}
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        without_prompt = stripped.removeprefix("Vivado%").strip()
        if without_prompt in payload_lines:
            continue
        if stripped == "Vivado%":
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


""" 
 原始命令
report_timing_summary
        │
        ↓
   create_request()
        │
        ├─ 生成唯一 request_id
        ├─ Hex 编码命令
        ├─ catch 捕获异常
        ├─ 加 RC 状态标记
        └─ 加 END 结束标记
        ↓
      Vivado
        ↓
   Tcl执行 + stdout
        ↓
   parse_response()
        │
        ├─ 找 RC
        ├─ 清理 Vivado%
        ├─ 提取真正输出
        └─ 判断成功/失败
        ↓
   TclResponse
"""
