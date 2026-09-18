# Agent 演示任务

请使用 `vivado_build_workflow` 完成指定 Vivado 工程的构建。

约束：

1. 启动后先读取工程状态；
2. 只依据 Tool 返回的 evidence 判断阶段是否完成；
3. 综合、实现和 bitstream 启动后保留 job id，并通过 `inspect_run` 轮询；
4. 失败时先执行 `diagnose_run`，不直接重复运行；
5. `check_build_readiness` 为 `BLOCKED` 或 `UNKNOWN` 时不得生成 bitstream；
6. 最终给出阶段、状态、关键证据和未解决问题。

