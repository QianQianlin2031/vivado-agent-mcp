# 从零构建 Vivado Agent MCP

这份教程不是“如何运行成品”，而是按设计依赖关系重新构建一遍项目。建议一边阅读，一边从空目录手写一个更小版本；不要先复制全部源码。

## 1. 先明确三层职责

第一层是 MCP。它解决 Agent 如何发现并调用能力：Tool 用于行动，Resource 用于读取上下文，Prompt 用于提供可复用工作流。

第二层是 Agent Service。它决定什么时候允许行动、如何组织多条 Tcl、失败后建议什么。它不应该知道 stdio、JSON-RPC 等传输细节。

第三层是 Vivado Adapter。它只负责启动进程、发送 Tcl、准确取回本次响应。

先分层再写代码的原因是：如果直接在 MCP Tool 中拼 Tcl，所有状态判断、协议错误和业务错误会混在一起，既难测试，也很难向面试官解释。

## 2. 创建最小 Python 包

目录从下面四个文件开始：

```text
vivado-agent-mcp/
├── pyproject.toml
├── README.md
├── src/vivado_agent_mcp/__init__.py
└── tests/
```

`pyproject.toml` 只需声明 Python 版本、`mcp` 依赖、命令行入口和测试工具。使用 `src` 布局可以避免测试时意外导入工作目录中的同名文件。

此时先完成一次可编辑安装：

```powershell
python -m pip install -e ".[dev]"
```

## 3. 定义 Agent 与 Tool 的合同

先不要碰 Vivado。创建 `models.py`，定义六个稳定字段：

- `ok`：调用是否成功；
- `state_changed`：外部状态是否发生变化；
- `summary`：给人看的单句结论；
- `evidence`：给 Agent 判断的结构化事实；
- `recommended_actions`：下一步 Tool 名、参数与理由；
- `error_code`：机器可分支处理的稳定错误码。

为什么 `summary` 和 `evidence` 都需要？因为自然语言适合解释，但不适合可靠分支；结构化数据适合分支，但人读起来费劲。两者服务不同消费者。

完成标准：构造一个结果，`to_dict()` 后可以被 JSON 序列化，并为它写第一个单元测试。

## 4. 为 Tcl 增加消息边界

交互式 Vivado 只有连续的 stdin/stdout，没有“这一行属于哪个 Tool”的天然边界。最危险的实现是发送命令后读取固定行数：日志长度变化就会串台。

`vivado/protocol.py` 采用四步协议：

1. 为每次调用生成随机 request id；
2. 把原始 Tcl 编码成 UTF-8 十六进制，避免它破坏外层包装；
3. 用 Tcl `catch` 得到 return code 和结果；
4. 输出带 request id 的状态标记和结束标记。

概念上相当于：

```text
command A ──► [hex decode + catch] ──► RC(A) ──► END(A)
command B 必须等 END(A) 后才可发送
```

这里还有两类输入：工程路径属于任意字符串，必须进行 Tcl quoting；run 名属于标识符，可以采用白名单校验。不要把两种输入都用字符串拼接裸放入 Tcl。

完成标准：测试成功返回、Tcl 错误、缺失标记、路径中包含 `$` 和 `[]`、恶意 run 名。

## 5. 管理唯一 Vivado 会话

`vivado/session.py` 启动：

```text
vivado -mode tcl -nojournal -nolog
```

一个 MCP Server 只拥有一个 Vivado 进程，因为工程和 run 都是有状态对象。会话层必须做到：

- 用异步锁串行发送命令；
- 一直读取到本次唯一 END marker；
- 超时时不取消底层 reader；
- 前一命令尚未结束时返回 `SESSION_BUSY`；
- 后台消耗 stderr，避免管道填满导致死锁；
- Server 退出时清理自己启动的进程。

“超时后保留 reader”是本项目最值得讲的细节之一。若超时时直接丢弃读取任务，Vivado 后续输出会留在管道中，下一次 Tool 可能把旧输出当作新结果。

## 6. 把 Vivado 输出变成状态

`tcl_commands.py` 不追求封装全部 Tcl，只提供少数带标签的查询，例如：

```text
VAMCP_PROJECT:top=counter_top
VAMCP_PROJECT:synthesis_status=Not started
VAMCP_RUN:progress=80%
```

`agent_context/state.py` 将这些行解析成 `ProjectState` 和 `RunSnapshot`。状态对象再产生下一步建议：

```text
无工程 ─► open_project
无顶层 ─► 设置 top
综合未完成 ─► run_synthesis
综合失败 ─► diagnose_run
实现未完成 ─► run_implementation
已布线 ─► check_build_readiness
```

注意：推荐逻辑属于 Agent Service，不属于底层 Tcl 会话。会话只知道命令是否完成，不知道业务上下一步应该做什么。

## 7. 把长任务改成 job

综合和实现可能运行很久，不能让一次 MCP Tool 一直阻塞。正确模型是：

1. `run_synthesis` 检查工程前置条件；
2. Tcl 调用 `launch_runs`，立即返回；
3. Service 创建 `job_xxx`；
4. Agent 通过 `inspect_run(job_id=...)` 轮询；
5. Registry 根据 Vivado 的真实 status 更新完成或失败状态。

Registry 只是句柄映射，Vivado 才是状态真相。Server 重启后内存 job 会丢失，但仍可通过 `run_name` 查询原生 run；这是 MVP 的有意取舍。后续如需恢复，可把 job 映射持久化为 SQLite，而不必改 MCP 接口。

幂等性也在这里实现：同一个 active run 再次启动时返回已有 job，而不是创建重复工作。

## 8. 组合安全工作流

`service.py` 是项目主角。它把原子 Tcl 操作组合成 Agent 可以信赖的语义：

- `run_implementation` 在综合未完成时返回 `SYNTHESIS_NOT_COMPLETE`；
- `diagnose_run` 只返回有限数量的重要日志，防止上下文爆炸；
- `check_build_readiness` 同时检查 routed 状态、setup/hold slack、ERROR 和 CRITICAL WARNING；
- `generate_bitstream` 只有收到 `READY` 才会调用 `launch_runs -to_step write_bitstream`。

这里必须区分“Tool 执行成功”和“设计满足条件”。readiness 得出 `BLOCKED` 时，检查本身是成功的，所以 `ok=true`，结论放在 `evidence.verdict`；随后 `generate_bitstream` 因业务条件不满足返回 `ok=false` 和 `BUILD_NOT_READY`。

## 9. 最后才暴露 MCP

在 `server.py` 创建 `MCPServer`，再把 Service 的方法薄薄地包装为 10 个 Tool。包装层不应重复业务判断：

```python
@mcp.tool()
async def run_synthesis(jobs: int = 4) -> dict:
    return (await get_service().run_synthesis(jobs=jobs)).to_dict()
```

Resource 与 Tool 的区别：Resource 表达可读取的上下文，不应触发构建；Tool 表达行动或一次显式查询。Prompt 则不执行任何代码，只把推荐的多步调用顺序交给 Agent。

Server 使用 lifespan 创建 Service，并在退出时关闭 Vivado。这使进程所有权清晰：MCP Server 只清理自己启动的 Vivado。

## 10. 测试策略

测试分三层：

1. 纯函数：协议、转义、标签解析、状态建议；
2. Fake Session：输入预设 Tcl 输出，验证工作流是否启动/拒绝正确阶段；
3. MCP 合同：启动 in-memory/stdio client，检查 10/2/2 能力可发现并能返回 schema。

目前仓库完成前两层和 MCP 注册检查。真正运行 Vivado 的端到端测试需要本机 license、器件支持包和一个很小的示例工程，因此不应混入默认单元测试。

建议手工演示顺序：

```text
start_vivado(project_path)
inspect_project
run_synthesis -> job_id
inspect_run(job_id) ...
run_implementation -> job_id
inspect_run(job_id) ...
check_build_readiness
generate_bitstream -> job_id
inspect_run(job_id) ...
```

故障演示可以故意删除一个 HDL 模块，展示 `diagnose_run` 如何把日志证据交给 Agent，而不是让模型猜错误。

## 11. 自己新增一个 Tool 的练习

建议新增 `report_utilization`，但先不要参考原项目：

1. 写一个只输出 `VAMCP_UTIL:key=value` 的 Tcl 查询；
2. 写纯解析函数和测试；
3. 在 Service 中定义返回 `ToolResult` 的方法；
4. 再用 `@mcp.tool()` 暴露；
5. 判断它是否需要 recommended action；
6. 更新 README 的能力表。

如果能独立完成这个练习，你已经理解了本项目的完整纵向链路。

## 12. 简历与面试怎么讲

不要描述成“用 Python 调 Vivado”。更准确的主线是：

> 设计并实现面向 AI Agent 的 Vivado MCP Server，将有状态 EDA 工具抽象为可发现、可观测、可恢复的 Tool/Resource/Prompt；通过唯一消息标记与单会话并发控制避免 Tcl 响应串台，通过异步 job、结构化证据、前置条件和 bitstream readiness gate 构建可靠的 Agent 执行闭环。

可量化指标必须以真实测试结果填写，不要预先编造。适合记录：

- MCP 暴露能力数量：10 Tools、2 Resources、2 Prompts；
- 单元测试数量与覆盖率；
- 在示例 FPGA 工程上的综合/实现成功率；
- 自动提取日志问题数量与上下文压缩比例；
- 重复启动同一 run 时避免的重复任务数；
- 从启动到定位故障的平均 Tool 调用轮数。

面试时重点准备回答：为什么不能并发读一个 Tcl stdout、为什么超时后不能立刻开始下一命令、为什么 job registry 不是状态真相、为什么 Resource 不应该启动综合、为什么 bitstream gate 需要单独的业务 verdict。

