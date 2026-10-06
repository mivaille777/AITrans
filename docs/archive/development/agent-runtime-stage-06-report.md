# Agent Runtime Stage 6 报告

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

## 状态

**PASS**：Stage 6 定向门禁通过，旧线程池 specialist executor 仍是兼容执行路径；没有将 `Send` 接入生产执行。

- HEAD：`824236e00cfb44d4353558572331e4154de688d4`（本阶段未提交）
- Python：3.11.15
- LangGraph：1.2.11；langgraph-checkpoint-sqlite：3.1.1；Pydantic：2.13.3
- Native 开关：`AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` 默认仍为 `false`。Stage 6 未修改引擎选择；true/false 都保留 typed specialist bridge。

## 实施

- 新增 `backend/agent_core/orchestration/frontier.py`：纯函数 `ready_tasks` 和 `dependency_results`。前沿按 task ID 稳定排序，只检查声明的依赖。依赖投影只含 TaskResult 与去重后的 ArtifactRef/EvidenceRef，不包含 executor 原始 output。
- `ParallelTaskGraphExecutor` 复用上述纯函数生成 frontier 和依赖视图。ThreadPoolExecutor、预算、lease、checkpoint、事件与结果 merge 路径保持原状。
- `DependencyProjection` 用 `dependency_unavailable` 与失败 task ID 表达原因；按旧契约，required 后继变为 BLOCKED，optional 后继变为 SKIPPED。未开始 attempt 的 pure state helper 也保留这一状态选择。
- `reducer.py` 增加 ArtifactRef、EvidenceRef、event ID 和语义指纹 reducer。相同 identity 的相同内容幂等；Artifact/Evidence identity 或 event ID 对应不同内容时明确抛冲突错误。事件指纹只保存 hash，不将原始事件 payload 放入 Root checkpoint。
- Root state 增加 `evidence_refs` 和 `event_fingerprints` 两个可选 reducer channel；checkpoint projection/import 兼容新旧字段；`state_schema_version` 递增到 5。旧字段投影契约没有扩张。
- 新增五类 fixture，并用旧 scheduler 与 pure synthesis 对前三类的任务状态、结果 hash 和 output 做逐项比较；重放与冲突 fixture 验证 executor 原本调用的 `reduce_task_results` 合并语义。

## Fixture 输入 / 输出 / 差异

| Fixture | 输入 | 旧 executor 输出 | Pure/reducer 输出 | 差异 |
| --- | --- | --- | --- | --- |
| `independent-a-b` | `a`, `b` 无依赖 | `a,b=SUCCEEDED`；分别产出本 task output | 相同 | 无 |
| `a-before-b` | `a→b` | `a` 先完成，之后 `b` 成功 | 相同 | 无 |
| `failed-b-only-blocks-d` | `a→c`, `b→d`；`b` 抛异常 | `a,c=SUCCEEDED`; `b=FAILED`; `d=BLOCKED`；保留 `a,c` outputs | 相同 | 无；`b` 失败不阻断 `c` |
| `same-result-replay` | 同 task/attempt/version 与同 hash 重放 | reducer 留一条 canonical TaskResult | 留一条相同 hash 的结果 | 无 |
| `conflicting-result-replay` | 同 task/attempt/version、不同 content hash | `TaskResultConflictError` | 同一明确冲突 | 无 |

另有 optional descendant 场景与旧 executor 比较：依赖失败时结果仍为 SKIPPED、`error_code=dependency_unavailable`、`unmet_requirements` 保持旧值。

## 验证

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q tests/multi_agent/test_frontier.py tests/multi_agent/test_result_reducer.py tests/multi_agent/test_parallel_scheduler.py tests/multi_agent/test_task_state.py tests/multi_agent/test_plan_validation.py` | **33 passed** |
| `python -m pytest -q tests/multi_agent/test_langgraph_orchestration_state.py tests/multi_agent/test_migration_switch.py` | **23 passed**；true/false native flag 均继续选择 typed specialist bridge |
| `python -m ruff check`（本阶段变更的 Python 源码与测试文件） | **All checks passed** |
| `python -m compileall -q`（本阶段变更的 Python 源码与测试文件） | **通过** |
| `python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short` | **808 passed, 6 failed, 1 deselected**；六项与 Stage 0 干净基线完全相同，没有新失败 |
| `python -m ruff check backend/agent_core backend/agent_graph backend/api backend/services tests/agent tests/multi_agent` | **失败：157 条诊断**，主要位于本阶段未改的旧模块。本次没有在干净基线上复跑该命令，因此不将它们标注为已验证的基线问题；本阶段变更文件的 lint 单独通过 |

全量的 6 项已知失败仍为 Canvas `_build_request()` 参数不匹配 2 项，以及 grounded-synthesis citation/claim 语义 4 项；与 Stage 0 / Stage 5 报告一致。未运行 Docker、真实模型质量或性能样本；它们不属于 Stage 6 的验证范围，Stage 11 release gate 仍要求处理/记录。

## 回滚与剩余门禁

- Stage 6 的旧 scheduler 仍在；需要回滚 frontier 时，可将 `ParallelTaskGraphExecutor.execute` 的 frontier 列表与依赖字典恢复为旧内联逻辑，不需要迁移任务数据。
- `schema_version=5` 与新增 Root 引用/指纹字段只追加信息。回滚执行逻辑时应继续保留能读取 schema 5 的兼容代码，或先确保所有 schema 5 checkpoint 可由回滚版本读取；不得降写版本或删除 checkpoint/数据库。
- Stage 6 Gate：**PASS**。全量 Agent/multi-agent CI、六项既有失败、全仓 Ruff、Docker/真实模型/性能与 Stage 8 桌面验收仍按对应阶段继续追踪。
