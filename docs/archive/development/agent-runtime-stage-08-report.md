# Agent Runtime Stage 8 实施报告

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-28  
基线：Stage 7 工作树  
HEAD：`824236e00cfb44d4353558572331e4154de688d4`  
LangGraph：`1.2.11`  
结果：**PASS**；native 默认开关仍关闭。

## 变更

- Root 和 specialist per-invocation 子图复用 `AgentCheckpointService` 的 SQLite saver。子图 checkpoint namespace 加入由 `task_id` 派生的稳定标识，使同一 Agent 的并行任务各自读取对应进度；temporary 图使用独立的无 checkpoint 编译路径。
- Root 和持久 specialist 调用使用同步 durability，使每个已完成 superstep 在后续步骤开始前持久化。恢复仍以 run store 中固定的 `engine/graph_version/state_schema_version` 选图，`run_id` 用作 LangGraph `thread_id`；不支持的图版本会明确拒绝。
- 冻结 Memory 的正文只在运行时 context 中提供给 specialist；child checkpoint 保存编排输入、结果和引用，不写入该正文。恢复时从原有 Memory port 按 snapshot 引用重新加载，并校验 snapshot 身份。
- 保留严格 `JsonPlusSerializer`，增加显式应用 DTO / enum allowlist，覆盖 checkpoint 中实际使用的 Task、Scope、Evidence、Artifact 值类型；没有开放任意模块反序列化。SQLite WAL 和 `busy_timeout` 配置保留。
- native runtime 不构造或使用 `SQLiteTaskCheckpointStore`；compat/legacy runtime 仍保留原存储路径。`AgentRunStore` 继续管理队列、运行状态、租约、heartbeat 和请求/结果记录。temporary run 使用临时图与 Artifact Store，不进入持久 checkpoint 路径。即时 API 与持久 Worker 继续通过同一 runtime factory。
- 增加真正跨进程的 document-3 中断/恢复测试，以及 specialist namespace、temporary 路径和 native/compat task store 选择测试。

## 验证

任务书列出的 Stage 8 Gate 命令：**45 passed，2 warnings**。覆盖真实子进程退出后只重跑中断的 document-3、document-1/2 不重跑且 research 等待文档任务完成、取消后恢复、同一 saver 下子图隔离、temporary/Artifact 隔离、旧 run/checkpoint 兼容、未知写入不自动重放和 AgentRunStore 生命周期。

补充命令 `python -m pytest -q tests/agent/test_native_checkpoint_store_selection.py`：**2 passed**。该测试确认 native 不创建旧 task checkpoint store，compat 仍创建。

Agent/multi-agent 全量命令 `python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short`：**820 passed, 6 failed, 1 deselected**。六个失败与 Stage 0/7 的已知失败相同：2 项 Canvas 请求参数契约、4 项 grounded synthesis 引文语义；未出现新的失败。测试输出包含 FastAPI/httpx 与 Paramiko Blowfish 两条依赖弃用警告。

Stage 8 涉及文件的 Ruff 检查：**All checks passed**。对更大 backend/tests 目录执行的额外 Ruff 检查报告 157 项目录级诊断；这些不是 Stage 8 Gate，本阶段没有批量改写无关文件。`git diff --check` 通过；Git 仅提示现存工作树文件的 LF/CRLF 转换警告。

Electron 复核时存在主窗口标题为 `desktop` 的进程，后端 `http://127.0.0.1:8766/health` 返回 `{"status":"ok","service":"aitrans-backend"}`。用户已恢复窗口，但桌面自动化接口仍返回 `apps: []`，所以本报告**不把肉眼 UI 手工验收记为通过**。

## 边界与回滚

- 本阶段未启用 native 默认开关，未运行真实模型或 Docker 专项，也未采集性能/质量样本。
- 回滚继续按 run 创建时固定的版本路由；compat/legacy run 仍由原 task checkpoint 路径恢复。不得通过环境变量把运行中的旧 run 改为 native，也不删除 checkpoint、运行记录、Artifact 或 Memory 数据。
- Stage 8 的代码 Gate 已通过。桌面窗口的视觉手工验收仍待可读取窗口画面后确认；Stage 9–11 尚未开始。
