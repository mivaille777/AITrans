# Agent Runtime Stage 4 实施报告

日期：2026-09-28  
任务书：`Agent Runtime重构任务书.md` · Stage 4 Root Graph 编排状态与版本契约  
工作树 HEAD：`824236e00cfb44d4353558572331e4154de688d4`（本阶段未提交）

## 结果

**PASS。** Root Graph 新增 checkpoint-safe 编排 channels：版本、受限 ScopeContext、memory snapshot 引用、ValidatedTaskPlan、TaskResult、任务状态、frontier ID、ArtifactRef、事件 ID 和 orchestration status。Scope 和计划在进入 state 前分别按 `ScopeContext`/`ValidatedTaskPlan` 验证；ArtifactRef 只保存 id/version/kind/hash，不含 Artifact body。Runtime Context 仍由 LangGraph `context_schema` 承载，不属于 checkpoint state。

`task_results` reducer 委托既有 `reduce_task_results`，以 task/attempt/result version 幂等合并、以不同 hash 报冲突。ArtifactRef 按 `(artifact_id, version)` 合并，同一版本冲突时拒绝，不覆盖其它版本。事件 ID 和 frontier 使用稳定排序去重。旧 `AgentState.orchestration_*` 字段只由 Root canonical channels 单向投影；只在兼容 bridge 边界读取 legacy checkpoint/bridge 输出。

新版本为 `reading-agent-ma04-v1` / state schema `3`。已知 `reading-agent-v1`、`reading-agent-ma03-v1` 仍可恢复，未知图版本与未来 state schema 会被拒绝。恢复先从未迁移的 Root channel 或原始 `agent_state` 读取版本，再选 builder，之后才迁移 AgentState。持久 run 在入队写入 `engine/graph_version/state_schema_version`；Store schema 升为 5，为旧库添加 engine 列并保留旧行未填写的版本值。checkpoint 更新不会覆盖已固定的 run 版本；worker 与 checkpoint 版本不一致时失败关闭。

`/api/agent/runs/{run_id}/snapshot` 从 canonical channels 构造 scope/plan/results，再投影到原响应字段；旧 checkpoint 无 canonical channels 时从兼容 AgentState 提供相同字段。

## 基线与环境

- Python 3.11.15
- LangGraph 1.2.11；langgraph-checkpoint 4.2.0；langgraph-checkpoint-sqlite 3.1.1；Pydantic 2.13.3
- `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` 默认仍为 `false`；Stage 4 只固定 engine 元数据，没有切换执行路径。没有启动 Docker 或真实模型。
- HEAD 为 `824236e00cfb44d4353558572331e4154de688d4`；未提交现有 Stage 0–3 与用户文件。

## 修改文件

- 新增 `backend/agent_core/orchestration/graph_state.py`：Root state schema、Scope/Plan 安全解析、TaskResult/ArtifactRef/event/frontier/status reducer、legacy projection、原始 checkpoint 版本读取。
- `backend/agent_core/state.py`：当前 Agent graph/state schema 升至 MA04/schema 3；保留 MA01/MA03 已知迁移入口并拒绝未知版本。
- `backend/agent_graph/factory.py`、`reading_agent_graph.py`：builder 接受固定 graph version；Root state 初始化、legacy adapter 边界导入、checkpoint 读回投影、原始版本恢复选择及 pin 冲突检查。
- `backend/agent_core/runtime.py`、`backend/api/agent_runtime_jobs.py`：恢复前准备版本；worker 对入队的 graph/schema 版本 pin，并提供 canonical orchestration snapshot。
- `backend/models/agent_run.py`、`backend/services/agent_run_scheduler.py`、`agent_run_store.py`：run contract 增加 engine；入队固定选择；retry 保留版本；DB schema v5 增加兼容列；checkpoint 元数据不能改写已 pin 的版本。
- `backend/api/agent.py`：snapshot response 从 canonical state 投影为旧 API 字段。
- 新增 `tests/multi_agent/test_langgraph_orchestration_state.py`；更新 checkpoint legacy 选择、run schema pin、worker scheduler 测试。

## 验证

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q tests/multi_agent/test_langgraph_orchestration_state.py tests/multi_agent/test_result_reducer.py tests/multi_agent/test_orchestration_state_compatibility.py tests/agent/test_agent_state_contract.py tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_api_runtime.py tests/agent/test_root_graph_factory_parity.py --tb=short` | **48 passed**，2 个 Starlette/httpx 与 Paramiko 弃用警告 |
| 同上 Stage 4 套件，并加 `tests/agent/test_agent_runtime_scheduler.py tests/agent/test_agent_run_store.py tests/agent/test_agent_pause_resume.py` | **73 passed**，2 个弃用警告 |
| `python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short` | **784 passed, 6 failed, 1 deselected**；六项与 Stage 0 基线一致：Canvas 2 项、grounded synthesis 引文语义 4 项；没有新增失败 |
| `python -m ruff check` 对所有已修改与新增的 backend/tests Python 文件 | **通过** |
| `python -m ruff check backend/agent_core backend/agent_graph backend/api backend/services tests/agent tests/multi_agent` | **157 项 lint findings**；全目录 lint 尚未建立干净 HEAD 对照。定向改动文件扫描为通过，不把全目录扫描记为通过 |

Reducer 质量样本覆盖并行 `a/b` 合并、同内容重放、hash 冲突、同 Artifact 不同版本和 SQLite checkpointer 保存/读回。没有运行性能 benchmark 或真实模型质量测试；没有 Docker 依赖。

## Gate 与回滚

- TaskResult/ArtifactRef reducers 可重放且顺序稳定；不同结果 hash、同一 Artifact 版本内容冲突会明确失败。
- SQLite checkpoint 往返保留计划、scope、结果和 refs；新增 state contract 不包含 service/runtime object 或 Artifact body。AgentState 原有用户输入字段仍属于 checkpoint，报告不把整个 checkpoint 描述为不含内容。
- 旧 checkpoint 的 raw 版本先决定 builder，再迁移状态；旧 API snapshot 字段通过单向投影保持兼容。
- 入队版本不随 native 环境开关变化；retry 保留 engine/graph/schema；checkpoint 不能覆盖已 pin 版本。native 默认关闭，compat 执行路径保持现状。
- Store schema 变更只添加列，不删除或重写用户 run/checkpoint 数据。回滚需保留 v5 DB 与 MA04 checkpoint；不要直接换成不识别 MA04 的旧二进制。应先恢复版本识别兼容代码或继续使用 Stage 4 builder，再评估后续回滚。
- Stage 0 已分类的六项测试债务与全目录 lint findings 未在本阶段修复；Stage 11 全量质量门禁仍保留。

## 后续

Stage 4 专项 gate 已通过，可进入 Stage 5。Stage 5 应在新增路由/Scope/Memory/Plan 节点前使用版本分支保留 MA04 已排队 run 的旧拓扑，并继续让 native flag 默认关闭。
