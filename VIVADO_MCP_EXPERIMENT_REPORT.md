# Vivado Agent MCP 实验报告

> 实验日期：2026-09-08  
> 项目：`vivado-agent-mcp`  
> Vivado：`D:\vivado\Vivado\2018.3\bin\vivado.bat`  
> 目标器件：`xc7a35tcpg236-1`  
> MCP transport：stdio

## 1. 结论摘要

本次实验验证了一个面向 AI Agent 的 Vivado MCP Server：它不仅能让客户端发现和调用 Vivado 能力，还能把有状态、长耗时的 FPGA 构建过程抽象成可观察、可轮询、带前置条件和恢复路径的工作流。

最终结果如下：

- Codex 成功接入 `vivado_agent` stdio MCP，并完成能力 discovery；
- connectivity smoke test 完整通过，真实启动并关闭了 Vivado；
- baseline 工程完成 synthesis、implementation、readiness gate 和 bitstream 全流程；
- readiness 结果为 `READY`，setup slack 为 `7.201 ns`，hold slack 为 `0.324 ns`；
- 真实生成的 `counter_top.bit` 当前仍存在，大小为 `2,192,119 bytes`；
- Agent 成功诊断真实 Verilog 语法错误，只修复一个缺失分号，重新综合后错误数由 2 降为 0；
- 缺少时钟约束的对照工程完成 route，但 readiness 为 `UNKNOWN`，bitstream 被 `BUILD_NOT_READY` 阻止，且没有启动 bitstream job；
- synthesis 前置条件和不存在 job id 两项异常保护均按预期生效；
- Project Resource、Job Resource Template 和两个 Prompts 均完成实际读取；
- 实验暴露并最小修复了两个真实项目 bug；
- 当前自动化测试为 `18/18 passed`，Ruff lint 与 format check 全部通过。

这说明项目已经形成“观察状态 → 选择动作 → 异步执行 → 查询证据 → 诊断恢复 → readiness 放行”的 Agent 闭环，而不是简单地把 Tcl 命令包装成远程调用。

## 2. 证据范围与可信度说明

本报告只使用两类真实证据：

1. 已完成实验时记录的 MCP 交互结果，包括 PID、job id、结构化返回、错误码、Resource 和 Prompt 读取结果；
2. 当前工作区保留的 Vivado 工程、run 日志、时序报告、DCP、`.bit` 和测试结果。

本次收尾没有重新启动 Vivado、没有重新运行 synthesis、implementation、route 或 bitstream，也没有修改三个实验工程的 Verilog/XDC baseline。磁盘 artifacts 用于交叉核对已有结果，而不是重新制造结果。

需要特别说明：MCP 的 `job_xxx` 是 Server 进程内的 Agent 句柄，当前目录中的 Vivado `.jobs/vrs_config_*.xml` 是 Vivado 自身的 run 元数据，二者不是同一种 job 记录。因此，本报告中的 MCP job id 来自已完成实验的交互记录；构建完成状态则同时由现存 Vivado run artifacts 佐证。

## 3. MCP 接入与 Discovery

### 3.1 接入配置

- Server 名称：`vivado_agent`
- transport：stdio
- Vivado executable：`D:\vivado\Vivado\2018.3\bin\vivado.bat`
- Server 入口：`python -m vivado_agent_mcp`

### 3.2 Discovery 结果

真实 discovery 返回：

- **10 Tools**
  - `start_vivado`
  - `stop_vivado`
  - `run_tcl`
  - `inspect_project`
  - `inspect_run`
  - `run_synthesis`
  - `run_implementation`
  - `generate_bitstream`
  - `diagnose_run`
  - `check_build_readiness`
- **Project Resource**：`vivado://project/current`
- **Job Resource Template**：`vivado://jobs/{job_id}`
- **2 Prompts**
  - `vivado_build_workflow`
  - `vivado_debug_workflow`

实验 probe 曾把 SDK 返回字段误写为 `resourceTemplates`；正确字段是 `resource_templates`。这是 probe 脚本错误，不是 MCP Server bug，修正字段后 discovery 正常。

## 4. Connectivity Smoke Test

真实调用链：

```text
start_vivado
  → inspect_project
  → run_tcl
  → stop_vivado
```

结果：

- Vivado 真实进程 PID：`51904`
- Tcl 输出：`HELLO_VIVADO_MCP`
- 会话能正常启动、读取工程、执行 Tcl 并关闭

该测试验证了 stdio MCP client、Server、Vivado Tcl 子进程和请求/响应协议的完整连通性。

## 5. Agent Build Workflow

baseline 工程位于：

```text
experiments/projects/baseline_counter/
```

工程目标器件为 `xc7a35tcpg236-1`。真实完整构建过程如下：

| 阶段 | MCP job id | 结果 |
|---|---|---|
| Synthesis | `job_63e0ef17665a` | `completed` |
| Implementation | `job_383a2852e9dc` | `completed` |
| Readiness | — | `READY` |
| Bitstream | `job_ff2b10663601` | `write_bitstream Complete!` / `100%` |

readiness 关键证据：

| 指标 | 结果 |
|---|---:|
| Setup slack | `7.201 ns` |
| Hold slack | `0.324 ns` |
| Verdict | `READY` |

现存 Vivado artifacts 进一步确认：

- synthesis 日志包含 `synth_design completed successfully`；
- implementation 日志包含 `route_design completed successfully`；
- routed timing summary 包含 `All user specified timing constraints are met.`；
- implementation 日志包含 `write_bitstream completed successfully`。

## 6. Async Jobs

综合、实现和 bitstream 都采用异步 job 模型：启动操作快速返回稳定的 `job_id`，Agent 随后使用 `inspect_run(job_id=...)` 轮询真实 Vivado run 状态，而不是让一次 MCP 调用同步阻塞到构建结束。

这一模型有三个关键行为：

- **可观察**：job 保存 kind、run name、原始 status、归一化 state 和 progress；
- **幂等**：同一 active run 不会被重复启动，而是返回已有 active job；
- **状态以 Vivado 为准**：registry 只保存 Agent 句柄映射，轮询时仍读取 Vivado 的真实 run status。

MVP 的 job registry 位于内存中。Server 重启后 `job_id` 映射不会恢复，但 Vivado 原生 run 仍可通过 `run_name` 查询。这是当前明确的设计取舍，而不是把内存状态当作构建真相。

## 7. State 与 `recommended_actions`

所有 Tool 使用统一结构返回：

```json
{
  "ok": true,
  "state_changed": false,
  "summary": "...",
  "evidence": {},
  "recommended_actions": [],
  "error_code": null
}
```

其中：

- `ok` 表示本次 Tool 调用本身是否成功；
- `evidence` 保存可供 Agent 判断的结构化事实；
- `recommended_actions` 根据当前工程状态给出下一步工具及原因；
- `error_code` 为可稳定分支处理的机器可读错误码。

典型状态推进为：

```text
synthesis 未完成
  → run_synthesis
  → implementation 未完成
  → run_implementation
  → route 完成
  → check_build_readiness
  → READY
  → generate_bitstream
```

当 implementation status 已为 `write_bitstream Complete!` 时，工程已经超过 route 阶段，不应再推荐 `run_implementation`。该边界在本次实验中暴露并已修复，当前完成 bitstream 后返回空的重复构建建议。

## 8. Agent Debug & Recovery

### 8.1 故障注入

故障工程：

```text
experiments/projects/synthesis_error_counter/
```

故障 synthesis job：`job_da8d56239018`

`diagnose_run` 返回的关键根因：

```text
[Synth 8-2715] syntax error near 'end'
counter_top.v:16
```

根因是故障副本缺少一个分号。修复严格限制为补回该分号，没有修改 baseline，也没有进行无关重构。

### 8.2 恢复结果

- 修复后 synthesis job：`job_e1daaea2d8a2`
- 结果：`completed`
- error count：`2 → 0`

当前保留的故障工程 synthesis 日志也显示修复后的 `synth_design completed successfully`。这验证了 Agent 能根据有界日志证据定位根因、执行最小修改并重新进入正常 workflow。

## 9. Readiness Gate 对照实验

### 9.1 Baseline

baseline 保留 100 MHz `create_clock` 约束：

```tcl
create_clock -add -name sys_clk -period 10.000 -waveform {0 5.000} [get_ports clk]
```

结果：

```text
route complete
  → setup/hold 均有有效非负 slack
  → READY
  → bitstream allowed
```

### 9.2 `gate_unknown_counter`

对照工程只删除 `create_clock`，其余设计与物理管脚约束保持相同。真实结果：

- synthesis 正常完成；
- implementation / `route_design` 正常完成；
- timing readiness 为 `UNKNOWN`；
- `generate_bitstream` 返回 `BUILD_NOT_READY`；
- 没有启动 bitstream job。

现存对照工程日志包含 `route_design completed successfully`，同时提示应使用 `create_clock/create_generated_clock` 指定时钟，和 readiness 为 `UNKNOWN` 的结果一致。

这个对照证明“route 成功”不等于“可安全生成 bitstream”。Gate 检查的是证据是否足够以及时序是否满足，而不是仅检查流程有没有走到 route。

## 10. Exception Guard

已真实验证两项异常保护：

| 场景 | 返回错误码 | 行为 |
|---|---|---|
| synthesis 未完成时直接启动 implementation | `SYNTHESIS_NOT_COMPLETE` | 拒绝启动 implementation，并建议先运行 synthesis |
| 查询不存在的 `job_id` | `JOB_NOT_FOUND` | 返回稳定错误，不向 Vivado 发起无意义构建 |

此外，`generate_bitstream` 会先调用 readiness gate。只要 verdict 不是 `READY`，就返回 `BUILD_NOT_READY`，不会调用 bitstream launch。

## 11. Resources 与 Prompts

本实验不仅完成了 capability discovery，还实际读取了：

- `vivado://project/current`：已打开 baseline 的当前工程快照；
- `vivado://jobs/{job_id}`：已完成 bitstream job 的状态；
- `vivado_build_workflow`：完整构建调用顺序；
- `vivado_debug_workflow`：失败诊断和最小修复顺序。

职责边界清晰：

- Tool 执行动作或显式查询；
- Resource 读取上下文，不隐式触发构建；
- Prompt 只提供可复用的 Agent 工作流，不执行代码。

## 12. 实验发现并修复的两个真实项目 Bug

### Bug 1：`deque` 切片覆盖原始 Vivado 退出错误

原问题：Vivado 在响应 marker 前异常退出时，会收集最近 stderr。代码对 `deque` 直接执行 `[-10:]`，但 `deque` 不支持切片，导致错误处理路径再次抛出异常，反而覆盖最有价值的 Vivado stderr。

最小修复：

```python
stderr = "\n".join(list(self._stderr_tail)[-10:])
```

影响：Vivado 异常退出时，现在能够保留并返回最近十行 stderr，而不是暴露二次 Python 异常。

### Bug 2：bitstream 完成后错误推荐 implementation

原问题：状态推荐逻辑只把 `route_design Complete` 识别为已实现，没有把 `write_bitstream Complete!` 视为已经完成 route 之后的更高阶段，因此错误推荐 `run_implementation`。

最小修复：同时识别 route 和 bitstream 完成状态；若 bitstream 已完成，返回空的重复构建建议。

对应回归测试：`test_completed_bitstream_has_no_redundant_build_action`。

## 13. Codex Windows Sandbox 环境限制

已确认的环境限制是：Codex Windows workspace sandbox 会阻止启动工作区外 `D:\vivado` 下的 Vivado 子进程。这不是 MCP Server、stdio transport 或 Vivado 本身的功能故障。

验证边界如下：

- 在 Codex workspace sandbox 中：工作区外 Vivado 子进程启动受阻；
- 在正常 Windows 权限下使用标准 stdio MCP client：Server 与 Vivado 可正常启动并完成实验。

本项目不应通过复制 Vivado、绕过安全策略或修改 Server 业务逻辑来“修复”该环境限制。正确做法是记录限制，并在允许启动 Vivado 的正常 Windows 执行环境中运行真实 E2E。

## 14. Tests 与静态质量检查

2026-09-08 最终收尾结果：

```text
pytest:             18 passed in 7.14s
ruff check:         All checks passed!
ruff format --check: 29 files already formatted
```

测试覆盖的主要边界包括：

- MCP capability discovery 和 Tool schema；
- 统一 JSON 结果契约；
- Tcl 请求唯一 marker、hex payload、解析和转义；
- job 创建幂等性与完成状态；
- synthesis 异步 job 和 poll action；
- 无效 project path 不启动 Vivado；
- synthesis 未完成时的 implementation guard；
- timing 不满足时的 bitstream guard；
- 状态推进、失败诊断建议和 bitstream 完成后的推荐行为。

收尾时 Ruff format check 首次发现 19 个 Python 文件只有机械格式差异，已执行格式化；随后完整重跑 tests、lint 和 format check，全部通过。没有修改业务逻辑，也没有修改 baseline Verilog/XDC。

## 15. Bitstream 交付核对

当前真实文件：

```text
experiments/projects/baseline_counter/vivado/
  baseline_counter.runs/impl_1/counter_top.bit
```

核对结果：

- 存在：是
- 大小：`2,192,119 bytes`
- 当前文件时间：`2026-09-08 17:53:51`
- 对应 run 日志：`write_bitstream completed successfully`
- MCP job：`job_ff2b10663601`
- MCP 状态：`write_bitstream Complete!` / `100%`

## 16. 当前限制

当前版本有意保留以下边界：

- 一个 MCP Server 管理一个 Vivado Tcl 会话，不支持多个工程并发会话；
- MCP job registry 是内存映射，Server 重启后 job id 不持久化；
- 未覆盖 GUI 自动化、波形查看、IP Catalog、设备下载和远程 attach；
- `run_tcl` 是必要的逃生舱，但无法替代带前置条件和结构化证据的专用 Tool；
- 真实 Vivado E2E 依赖本机 license、器件支持包和允许启动外部子进程的权限；
- 本次实验验证了构建到 `.bit`，未验证把 bitstream 下载到实体 FPGA 板卡；
- 当前测试为离线单元/契约测试，真实 Vivado artifacts 来自本次独立 E2E 实验，不在默认 pytest 中重复执行。

## 17. 3～5 分钟 Demo 脚本

### 0:00～0:40：问题与架构

展示 README 架构图，说明传统脚本无法根据状态动态恢复，而直接暴露任意 Tcl 又缺少安全边界。项目增加 Agent Service 层，提供结构化 evidence、job 和 readiness gate。

### 0:40～1:20：Discovery 与 Connectivity

展示 discovery 结果：10 Tools、Project Resource、Job Resource Template、2 Prompts。随后展示已有 smoke test 记录：

```text
start_vivado → inspect_project → run_tcl → stop_vivado
HELLO_VIVADO_MCP
```

强调这是标准 stdio MCP 到真实 Vivado Tcl 进程的完整链路。

### 1:20～2:15：异步完整构建

展示三个 job id 和状态推进：

```text
job_63e0ef17665a  synthesis       completed
job_383a2852e9dc  implementation  completed
READY: setup 7.201 ns, hold 0.324 ns
job_ff2b10663601  bitstream       100%
```

打开 `counter_top.bit` 的文件属性，展示真实大小 `2,192,119 bytes`。说明长任务不阻塞 Agent，而是启动后用 job id 轮询。

### 2:15～3:10：Debug & Recovery

展示故障诊断证据：

```text
[Synth 8-2715] syntax error near 'end'
counter_top.v:16
```

说明 Agent 只补一个缺失分号；重新综合 job 完成，错误数 `2 → 0`。重点不是“自动改很多代码”，而是“根据真实证据做最小恢复”。

### 3:10～4:00：Readiness Gate 对照

并排展示：

| baseline | 无 `create_clock` 对照 |
|---|---|
| `READY` | `UNKNOWN` |
| bitstream allowed | `BUILD_NOT_READY` |
| bitstream job 启动 | 没有 bitstream job |

强调 route 成功并不足以放行 bitstream，Agent 必须有有效时序证据。

### 4:00～4:40：可靠性收尾

快速展示两个 guard、两个真实 bug 修复和 `18 passed`。最后用一句话收束：项目把 Vivado 从“命令行工具”提升为 Agent 可发现、可观察、可恢复、带安全门的工程能力。

## 18. GitHub README 亮点文案

可在 README 顶部加入以下摘要：

> Vivado Agent MCP 是一个面向 AI Agent 的 Vivado 自动化 Server，通过标准 MCP stdio 暴露 10 个 Tools、2 个 Resources 和 2 个 Prompts。它将 synthesis、implementation 和 bitstream 建模为可轮询的异步 job，以结构化 evidence 和 `recommended_actions` 驱动工作流，并使用 synthesis 前置条件与 timing/readiness gate 阻止无效构建。真实 Vivado 2018.3 实验已完成从工程检查到 `.bit` 的完整闭环，同时验证了语法错误诊断、最小修复与失败恢复。

建议在 README 增加一组可快速扫描的实验数字：

- `10 Tools · 2 Resources · 2 Prompts`
- `18/18 tests passed`
- `Synthesis → Implementation → READY → Bitstream`
- `Setup 7.201 ns · Hold 0.324 ns`
- `2,192,119-byte real bitstream`
- `2 → 0 synthesis errors after evidence-guided minimal fix`

## 19. 简历亮点

### 一句话版本

设计并实现面向 AI Agent 的 Vivado MCP Server，将有状态 FPGA 构建抽象为可发现、可轮询、可诊断和带 readiness gate 的自动化工作流，并在 Vivado 2018.3 上完成真实 bitstream E2E 验证。

### 项目经历版本

- 基于 MCP stdio 设计 10 个 Agent 语义化 Tools、2 个 Resources 和 2 个 Prompts，统一返回结构化 evidence、稳定错误码与下一步建议；
- 将 synthesis、implementation、bitstream 改造成幂等异步 job + polling 模型，解决 EDA 长任务阻塞和状态不可观察问题；
- 实现 synthesis 前置条件与 setup/hold/readiness 安全门，在缺少时钟约束时以 `BUILD_NOT_READY` 阻止 bitstream 启动；
- 基于真实 Vivado 日志完成语法错误定位与单分号最小修复，使 synthesis error count 从 2 降至 0；
- 修复异常路径 `deque` 切片导致 stderr 丢失、bitstream 完成后状态推荐错误两个真实缺陷，最终 `18/18` 测试及静态检查全部通过；
- 在 Artix-7 `xc7a35tcpg236-1` 上完成真实全流程构建，达到 setup `7.201 ns`、hold `0.324 ns`，生成 `2,192,119 bytes` bitstream。

## 20. 最终验收清单

- [x] MCP stdio 接入成功
- [x] 10 Tools / Project Resource / Job Resource Template / 2 Prompts discovery
- [x] Resources / Prompts 实际读取
- [x] Connectivity smoke test
- [x] Baseline synthesis / implementation / route / readiness / bitstream
- [x] Async job polling
- [x] Debug、最小修复与 recovery
- [x] Readiness Gate 正反对照
- [x] `SYNTHESIS_NOT_COMPLETE` / `JOB_NOT_FOUND` / `BUILD_NOT_READY`
- [x] 两个真实项目 bug 最小修复
- [x] Codex Windows sandbox 限制记录
- [x] `.bit` 当前存在且大小核对一致
- [x] `18/18` tests passed
- [x] Ruff lint / format 全部通过
- [x] 未重跑已完成 Vivado 实验
- [x] 未修改 baseline

