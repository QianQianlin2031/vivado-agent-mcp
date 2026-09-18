# Vivado Agent MCP

一个面向 AI Agent 的 Vivado 自动化 MCP Server。它不追求把所有 Vivado Tcl 命令逐个包装成工具，而是提供少量、状态明确、可恢复的能力，让 Agent 完成“观察 → 决策 → 执行 → 验证”的闭环。

## 这个项目解决什么问题

普通脚本只会按固定顺序执行；直接把任意 Tcl 暴露给大模型又缺少边界。本项目在两者之间增加一层 Agent 运行时：

```text
AI Agent
   │  MCP: Tools / Resources / Prompts
   ▼
Vivado Agent Service
   │  状态检查、前置条件、job id、统一结果
   ▼
单个 Vivado Tcl Session
   │  唯一请求标记、串行执行、超时隔离
   ▼
Vivado Project / Runs / Logs
```

核心目标：

- 让 Agent 在行动前先读取工程状态，而不是猜测；
- 综合、实现和 bitstream 都异步启动，并返回可查询的 job id；
- 每个 Tool 返回同一种 JSON 结构；
- 在综合未完成、时序失败或日志存在阻断问题时拒绝危险的下一步；
- 保留 `run_tcl` 作为逃生舱，但优先使用有语义的专用 Tool。

## MCP 能力

### 10 个 Tools

| Tool | 用途 |
|---|---|
| `start_vivado` | 启动唯一的无头 Tcl 会话，可选打开 `.xpr` |
| `stop_vivado` | 关闭本 Server 拥有的 Vivado 进程 |
| `run_tcl` | 执行无法由专用 Tool 表达的 Tcl |
| `inspect_project` | 读取器件、顶层、文件数和 run 状态 |
| `inspect_run` | 用 job id 或 Vivado run 名查询进度 |
| `run_synthesis` | 幂等启动综合并返回 job id |
| `run_implementation` | 检查综合前置条件后启动实现 |
| `generate_bitstream` | 通过 readiness gate 后启动 bitstream |
| `diagnose_run` | 从 `runme.log` 提取有界错误证据 |
| `check_build_readiness` | 检查 routed 状态、setup/hold slack 和阻断日志 |

### 2 个 Resources

- `vivado://project/current`：当前工程快照；
- `vivado://jobs/{job_id}`：某个异步任务的最近状态。

### 2 个 Prompts

- `vivado_build_workflow`：完整构建工作流；
- `vivado_debug_workflow`：失败诊断与最小修复工作流。

## Agent 友好的统一返回值

每个 Tool 都返回：

```json
{
  "ok": true,
  "state_changed": false,
  "summary": "Project demo is open.",
  "evidence": {"project": {}},
  "recommended_actions": [
    {
      "tool": "run_synthesis",
      "reason": "Synthesis has not completed.",
      "arguments": {}
    }
  ],
  "error_code": null
}
```

`ok` 表示 Tool 自身是否成功执行；业务结论放在 `evidence` 中。例如 readiness 检查成功，但 `evidence.verdict` 仍可能是 `BLOCKED`。

## 安装

要求：Python 3.10+、支持 Tcl 模式的 Vivado。项目测试不要求安装 Vivado。

```powershell
cd C:\path\to\vivado-agent-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

指定 Vivado 可执行文件：

```powershell
$env:VIVADO_PATH = "C:\Xilinx\Vivado\2024.2\bin\vivado.bat"
```

如果没有指定，程序依次检查参数、`VIVADO_PATH`、系统 `PATH` 和常见 Xilinx 安装目录。

## 运行与接入 Agent

本地启动 stdio MCP Server：

```powershell
python -m vivado_agent_mcp
```

Codex/兼容客户端的配置思路见 [examples/codex-config.toml](examples/codex-config.toml)。把路径改成自己的绝对路径：

```toml
[mcp_servers.vivado_agent]
command = "C:\\path\\to\\vivado-agent-mcp\\.venv\\Scripts\\python.exe"
args = ["-m", "vivado_agent_mcp"]
env = { VIVADO_PATH = "C:\\Xilinx\\Vivado\\2024.2\\bin\\vivado.bat" }
```

连接后可对 Agent 说：

> 使用 vivado_build_workflow 构建 D:\fpga\demo\demo.xpr。每个阶段都展示 evidence；遇到失败先诊断，不要绕过 readiness gate。

## 测试

```powershell
python -m pytest -q
python -m ruff check .
```

默认测试使用假 Vivado 会话，覆盖协议封装、状态解析、job 幂等性、工作流前置条件和 bitstream 安全门。当前测试结果为 `18/18 passed`。

## 真实 Vivado 实验

项目已在 Vivado 2018.3 和 Artix-7 `xc7a35tcpg236-1` 上完成真实端到端验证：

- MCP discovery：10 Tools、2 Resources、2 Prompts；
- connectivity：`start_vivado → inspect_project → run_tcl → stop_vivado`；
- 完整构建：synthesis、implementation、readiness gate、bitstream 全部完成；
- timing：setup slack `7.201 ns`，hold slack `0.324 ns`；
- bitstream：真实文件大小 `2,192,119 bytes`；
- debug recovery：根据 `[Synth 8-2715]` 证据补回一个分号，错误数从 2 降为 0；
- safety gate：缺少 `create_clock` 时 readiness 为 `UNKNOWN`，bitstream 被 `BUILD_NOT_READY` 阻止。

完整过程、job id、异常保护、两个真实 bug 修复和 Demo 脚本见
[VIVADO_MCP_EXPERIMENT_REPORT.md](VIVADO_MCP_EXPERIMENT_REPORT.md)。

### 实验目录说明

`experiments/projects/` 中只应提交可复现输入：RTL、XDC 和 `create_project.tcl`。Vivado 生成的 `.xpr`、`.runs`、缓存、报告、DCP 和 bitstream 由 `.gitignore` 排除，避免把机器相关文件和大体积构建产物提交到 GitHub。

需要复现实验工程时，在安装了 Vivado 的 Windows 环境中执行对应的 `create_project.tcl`，再通过 MCP 工作流启动构建。默认测试不会启动 Vivado。

## 项目边界

第一版刻意不做 GUI 自动化、波形查看、IP Catalog、设备下载、远程 attach、自动安装和几十个同质化 Tcl wrapper。这些功能会放大代码量，却削弱“Agent 如何通过 MCP 可靠控制有状态工具”这一主线。

与参考项目相比，本项目的主要差异不是少几个 Tool，而是重新定义了抽象层：

- 从“Vivado 命令集合”改为“Agent 决策接口”；
- 从同步长调用改为 job id + 轮询；
- 从自由调用改为前置条件与 readiness gate；
- 从自然语言输出改为稳定的结构化证据和下一步建议；
- 核心逻辑可在无 Vivado 环境中测试。

## 代码导航

```text
src/vivado_agent_mcp/
├── server.py           # MCP Tools / Resources / Prompts
├── service.py          # Agent 工作流、前置条件和错误恢复
├── models.py           # 统一 JSON 返回契约
├── tcl_commands.py     # 有标签、可解析的 Tcl 查询
├── config.py           # Vivado 路径发现
├── agent_context/
│   ├── state.py        # 工程状态解析与下一步推荐
│   └── jobs.py         # 异步 job id 注册表
└── vivado/
    ├── protocol.py     # 请求编码、唯一标记和响应解析
    └── session.py      # 单 Vivado 进程与串行命令通道
```

想真正掌握项目，请继续阅读 [docs/FROM_ZERO.md](docs/FROM_ZERO.md)。

