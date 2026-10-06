# Agent Runtime Stage 9 实施报告

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-28  
基线：Stage 8 工作树  
HEAD：`824236e00cfb44d4353558572331e4154de688d4`  
LangGraph：`1.2.11`；Pydantic：`2.13.3`；pytest：`9.0.3`  
结果：**PASS**；native 默认开关仍关闭。

## 变更

- Provider 错误现在保留 HTTP status。已知安全操作中的网络瞬断、provider timeout 和 HTTP 5xx 可重试；认证、限流、scope/权限、预算、取消、验证错误和未知写入效果不自动重试。安全 Tool retry 仍由 `AgentToolRegistry.allows_safe_retry` 限定；Root 只对无业务写入的路由/规划节点配置有限 `RetryPolicy`，节点超时不超过剩余总预算。
- Root 原生 task retry 根据 checkpoint 重新开启目标与所有受影响 descendant，清理旧结果与引用并递增 attempt ID/ordinal；独立成功任务保留。重试前重新验证 authoritative Scope、计划、Memory policy/snapshot 和保留 Artifact 的身份、内容、scope、类型及撤销状态。重试使用新的 specialist checkpoint namespace。
- ProductAgentService 对需确认的写 Tool 使用 LangGraph `interrupt`。待审批 intent 绑定 run、task、step、tool 版本、参数指纹和目标指纹；确认只消费一次。AgentRunStore schema v6 持久化待消费决定，并在审批/拒绝时追加审计事件。重启后 checkpoint 仍停在 WAITING；未知副作用状态不进入自动重放。恢复与手动重试都会清除旧的 `confirmed_write_tools`。
- KnowledgeCurator 继续只生成草稿。写入仍走原 typed Tool、权限检查和业务 commit 边界；拒绝时取消且不执行写入。
- 取消通过共享 `AgentRunControl` 传到 active subgraph。四个 specialist 的 Artifact commit、Memory candidate 提交及最终编排投影都受取消栅栏保护；迟到的 specialist 结果不会形成成功事件或最终交付。Worker 总预算超时会设置取消信号。会话完成/释放流程保留。
- 新增 native retry/interrupt 与跨进程审批恢复测试；补充 native 并发取消晚到 Artifact 测试和 worker 超时取消测试。

## 改动文件

- `app/ai/client.py`、`app/ai/errors.py`、`app/ai/openai_compatible.py`
- `backend/agent_core/events.py`、`product_adapter.py`、`reliability.py`、`runtime.py`、`orchestration/graph_state.py`、`orchestration/specialist_adapter.py`
- `backend/agent_graph/factory.py`、`reading_agent_graph.py`、`academic_writer_graph.py`、`document_analyst_graph.py`、`knowledge_curator_graph.py`、`research_synthesizer_graph.py`
- `backend/models/agent_tools.py`、`backend/api/agent_runtime_jobs.py`
- `backend/services/agent_run_worker.py`、`agent_run_scheduler.py`、`agent_run_store.py`、`agent_tool_execution_service.py`、`multi_agent_runtime_bridge.py`、`product_agent_service.py`、`research_orchestration_service.py`
- `tests/multi_agent/test_native_retry_interrupt.py`、`tests/integration/test_native_write_recovery.py`、`tests/agent/test_agent_runtime_scheduler.py`
- `docs/development/Agent Runtime重构任务书.md`

## 验证

任务书 Stage 9 Gate 命令：**24 passed，2 warnings**。之后将 `tests/agent/test_agent_runtime_scheduler.py` 加入同一运行，覆盖全部 Stage 9 Gate 模块及 Worker deadline 回归：**40 passed，2 warnings**。警告为现有 FastAPI/httpx 与 Paramiko Blowfish 弃用提示。

```powershell
python -m pytest -q tests/multi_agent/test_native_retry_interrupt.py tests/integration/test_native_write_recovery.py tests/multi_agent/test_commit_idempotency.py tests/multi_agent/test_cancellation_fencing.py tests/multi_agent/test_run_lease.py tests/agent/test_agent_pause_resume.py tests/agent/test_agent_write_recovery.py tests/agent/test_multi_step_write_safety.py tests/integration/test_agent_write_crash_recovery.py tests/agent/test_agent_runtime_scheduler.py
```

Stage 9 相关 Python 文件 `compileall` 通过；Ruff 检查通过。Ruff 命令对 `backend/agent_core/product_adapter.py` 单独排除了 `S112`：该 `try/except/continue` 位于本阶段未更改的既有证据清洗逻辑，且在 Stage 8 基线 HEAD 中已存在。`git diff --check` 通过；Git 仅报告工作树已有的 LF/CRLF 转换提示。

## 边界与回滚

- 本阶段未开启 native 默认值、未启动 native beta，也未运行真实模型、Docker、性能或质量样本；稳定发布全量门禁仍按 Stage 11 执行。Stage 0/8 记录的六项 Canvas/grounded synthesis 基线失败仍未在本阶段全量重跑。
- 回滚与恢复继续遵循 run 创建时固定的 engine、graph version 和 state schema；旧 run 保持原 checkpoint 路径。AgentRunStore schema 以向前兼容迁移增加一次性 confirmation 字段；不得清理既有运行、checkpoint、Artifact、Memory 或 Knowledge 数据。
- Stage 10 尚未开始。
