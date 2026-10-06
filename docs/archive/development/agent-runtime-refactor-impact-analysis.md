# Agent Runtime 重构影响分析报告

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

> 扫描基线：`WebReBuild @ 75fad6ed75ea794d2f0489e001bf5be4b3cfac83`，2026-09-27。当时执行路线采用原 LG-R1 方案的 LG00 → LG01；该方案现已由 [Agent Runtime 任务书](<Agent Runtime重构任务书.md>) 接替。本文保留开发前的代码事实与边界。

## 结论

生产执行应继续只有一个 `AgentRuntime → RootAgentGraph`，并由它持有最终回答、会话、运行 ID 和 LangGraph checkpoint。LG00 锁定当前行为；LG01 在现有 `TaskRole` 之上引入 Agent Registry，把能力、产物和工具策略收拢到一个目录。此阶段不增加第二个执行图或第二套工具执行器。Root Graph、任务调度、checkpoint 的原生化属于后续 LG02–LG10。

当前最容易形成“双体系”的位置是 `MultiAgentRuntimeBridge` 的 legacy/typed 分支、`ParallelTaskGraphExecutor` 的任务 checkpoint，以及与 LangGraph Root Graph 并列的 Studio 工厂。它们目前是迁移兼容层，不应被误认为独立的最终回答入口。持久任务的 SQLite run store 和观测用的 trace store 也承担不同职责；后续调试 UI 应按 `run_id` 关联，而不是复制执行状态。

仓库还有 `backend/agent_core/multi_agent/agent_registry.py`，它管理旧 `BaseAgent` 实例，仍由 legacy `MultiAgentWorkspaceService` 使用；`app/agent/workflow.py`、`tool_runtime.py` 和 `desktop_tool_runtime.py` 是另一组独立的旧工具/图实现。本次源码搜索在非测试生产代码中未发现这组 `app/agent` 类的调用者，不能据此直接删除其兼容 API。LG01 新目录放在 `backend/agent_core/orchestration/agent_registry.py`，仅作为 typed 专业 Agent 元数据来源；LG10 按真实调用者审计再移除旧实现。

## 1. 当前调用链与所有权

```text
桌面端 AgentWorkspace / useAgentRuntime
  ├─ POST /api/agent/run 或 /run/trace；WS /api/agent/stream
  └─ POST /api/agent/runs（持久任务），WS /runs/{run_id}/stream
      └─ agent_runtime_jobs.execute_persisted_agent_run → _build_runtime
后端 Agent API / 持久任务 Worker
  → agent_dependencies.get_agent_runtime（共同工厂）
  → AgentRuntime.execute（预算、取消、事件、trace 记录）
  → RootAgentGraph(ReadingAgentGraph)
      resolve_context → run_collaboration → prepare_conversation
      → route_request → direct 或有限 ReAct → finalize_conversation
      └─ run_collaboration → migration bridge
          ├─ typed: ResearchOrchestrationService → TaskPlan → ParallelTaskGraphExecutor
          ├─ legacy: MultiAgentWorkspaceService
          └─ off/simple: 跳过协作
```

依据：`backend/api/agent.py`、`backend/api/agent_runtime_jobs.py`、`backend/api/agent_dependencies.py`、`backend/agent_core/runtime.py`、`backend/agent_graph/reading_agent_graph.py`、`backend/agent_core/orchestration/migration.py`。持久任务 Worker 调用同一个 `get_agent_runtime`，但另有 `AgentRunStore` 管理排队、租约、暂停和结果；这是任务生命周期存储，不是第二个 Agent 决策器。

### LangGraph 入口

- `backend/agent_graph/root_agent_graph.py` 的 `RootAgentGraph` 继承 `ReadingAgentGraph`；后者用 `StateGraph` 编译持久图和临时图，持久图使用 `run_id` 作为 `thread_id`。
- `langgraph.json` 暴露 `root_agent` 和兼容名 `reading_agent`，都指向 `backend/agent_graph/studio.py`。Studio 工厂目前只建相同拓扑，没有注入生产协作桥及持久 checkpointer；因此“同一拓扑”尚不等于“同一生产构造”。LG09 再统一工厂。
- `run_collaboration` 仍是 Root Graph 的单个节点，内部任务调度与任务 checkpoint 在 `ParallelTaskGraphExecutor`/`SQLiteTaskCheckpointStore`。LG02–LG06 应逐步将任务状态、并发和恢复交还 LangGraph；LG01 不应在这里插入新执行路径。

## 2. Tool 注册与执行

`backend/api/dependencies.py:get_agent_tool_registry` 构造进程级 `AgentToolRegistry`；`backend/services/agent_tool_registry.py` 汇集 reading、translation、writing、research、knowledge、evidence、sandbox 等 typed definitions。`ProductAgentService` 负责受控执行，Root Graph 的直接路径和 ReAct 路径都复用该业务边界。`/api/agent/tools` 提供目录，`/api/agent/tools/{tool_name}/execute` 提供显式执行。

专业任务的允许工具由 `backend/agent_core/orchestration/roles.py:RoleRegistry` 校验，而 `backend/agent_core/orchestration/planner.py` 还单独维护 `_TOOLS_BY_ROLE` 与 `_OUTPUT_BY_ROLE`。这是 LG01 应消除的重复配置：Registry 必须提供规划默认工具、输出类型和允许清单；`validate_task_plan` 保留服务端的最终工具授权检查。Agent Registry 是专业执行者目录，不替代 `AgentToolRegistry` 的 typed 解析、权限和执行。

## 3. MCP 接入位置

在 `backend/`、`app/`、桌面端源码和依赖声明中未发现已接线的 MCP client、server 或 MCP tool。文档中的 future MCP 是设计预留，不是当前生产能力。将来接入时，应把 MCP capability 适配为 `TypedAgentToolDefinition`，经 `AgentToolRegistry`、`ProductAgentService` 的同一 scope、确认、超时、trace 边界执行；Agent Registry 只引用允许的工具名。不可把 MCP 工具直接挂到专家图中绕过该边界。

## 4. Sandbox 调用路径

`get_agent_tool_registry` 在 `AITRANS_SANDBOX_ENABLED` 且 `get_sandbox_manager()` 可用时注册 `python_execute` 与 `command_execute`。定义分别位于 `backend/agent_tools/sandbox.py`、`backend/agent_tools/command.py`；调用 `SandboxManager` / `SandboxCommandExecutor`，底层 `DockerSandboxRuntime` 与受限命令运行时位于 `backend/sandbox/`。调试数据由 `SandboxDebugService` 记录，审批经 `SandboxApprovalService`，桌面端已有独立的 Sandbox Debug Studio。LG01 的 Agent 允许工具必须沿用此注册与执行路径，不能把 sandbox manager 直接交给新增 Agent。

## 5. Trace 数据流

`ReadingAgentGraph` 产生语义事件 → `AgentRuntime._emit` 加 `run_id`、`trace_id`、`task_id`、序号 → WebSocket/同步 trace 响应，同时调用 `AgentTraceStoreService.append_event`；结束时保存摘要。观测 SQLite 只存受限/脱敏元数据，LangGraph checkpoint 则包含实际任务状态。持久任务同时向 `AgentRunStore` 保存生命周期事件，通过 `/api/agent/runs/{run_id}/events` 回放。`/api/agent/observability/recent` 和 `/summary` 提供历史摘要；`/api/agent/runs/{run_id}/snapshot` 提供运行快照。调试视图应优先复用这些既有 API 与事件契约，不读取 checkpoint 的原始内容，也不另建 trace 库。

多 Agent 的 `task_planned`、`task_started`、完成/失败、artifact 事件经协作桥映射为 `AgentEvent`。迁移期应保持稳定的 `run_id / trace_id / task_id / attempt / sequence`，并明确对齐 WebSocket、持久 run store 与观测 store，避免同一事件出现不同名字或序号。

## 6. 前端 Runtime Debug 决策

需要 Runtime Debug 页面，但放在 LG08 事件/UI 阶段实现。现有 `RagDebugStudioTrace.tsx` 面向检索阶段、chunk、QASPER 和 RAG 评估；`SandboxDebugStudio.tsx` 面向隔离执行；`AgentTimeline.tsx` 与 `AgentObservabilityPanel` 面向运行中活动与聚合指标。Agent Runtime 的 plan、Graph node、专家任务、checkpoint/resume、工具权限、预算与失败原因横跨 RAG 和 Sandbox，适合在 Settings 增加独立 **Runtime Debug** 入口，同时复用现有组件、API 类型和 `run_id` 关联跳转。RAG Debug Studio 可提供关联的 Agent run 链接；不建议把 Runtime 控制面塞进检索专用的六个 tab。

首版页面读取现有 run 列表、单次事件、snapshot 与安全配置，展示 route、节点/任务时间线、工具、artifact 引用、失败/恢复和关联的 RAG/Sandbox ID。只有 API 确实提供的数据才显示；隐藏 prompt、原文、checkpoint payload、密钥。LG00/LG01 不需要修改前端页面。

## 7. 影响与收敛约束

| 风险 | 当前证据 | 本阶段处理 | 后续处理 |
| --- | --- | --- | --- |
| 两套专业角色配置漂移 | `RoleRegistry` 与 Planner `_TOOLS_BY_ROLE/_OUTPUT_BY_ROLE` | LG01 单一 Agent Registry，保留 `TaskRole` adapter | LG02+ 把 `agent_id` 放入任务状态 |
| 新旧协作分支长期并存 | `migration.py` 的 `typed/legacy/off` 与 rollout | LG00 冻结开关、默认行为和回滚基线；不开启新引擎 | LG10 移除 legacy |
| 同名 Registry 意义不同 | legacy `multi_agent/agent_registry.py` 持有 `BaseAgent`，typed Registry 持有 `AgentSpec` | 包路径明确区分，生产 typed 规划只读新目录 | LG10 移除旧目录及未用 `app/agent` 图前复核调用者 |
| 双 checkpoint 所有权 | LangGraph checkpoint 与 `SQLiteTaskCheckpointStore` | LG00 固化恢复样例 | LG06 原生 checkpoint 接管任务 |
| Studio 与生产构造差异 | `studio.py` 的轻量工厂 | 报告记录 | LG09 统一图工厂 |
| Tool/MCP/Sandbox 绕权 | 专业角色工具允许清单独立于 typed tool catalog | LG01 保留 `validate_task_plan` 的服务端校验 | MCP 进入同一 ToolRegistry |
| Debug 状态分散 | RAG、Sandbox、Agent Timeline、Observability 分开 | 确定页面边界 | LG08 独立 Runtime Debug，按 run ID 关联 |

## 8. Stage 0 → Stage 1 实施与验收

**LG00 Baseline Lock**：记录 commit、实际依赖版本、确定性测试结果；保存典型 TaskPlan/TaskResult、语义事件和 checkpoint/resume 基线；引入默认关闭的 `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` flag，同时保持 `AITRANS_MULTI_AGENT_ENGINE`、`AITRANS_MULTI_AGENT_ROLLOUT` 原义。flag 关闭时不能改变生产路径。

**LG01 Agent Registry**：定义不可变 `AgentSpec` 和可注入 `AgentRegistry`，注册 document/research/writer/curator 四种现有专业 Agent；建立 `TaskRole → agent_id` 兼容适配；Planner 从 Registry 取得默认工具及产物种类，验证仍由允许工具清单执行。Mock Agent 能注册并查询能力，不改 scheduler；当前 `TaskSpec.role` 是枚举，mock agent 的实际调度要等 LG02+ schema/图状态演进。

后续阶段与验收以 [Agent Runtime重构任务书](<Agent Runtime重构任务书.md>) 为准。LG00 完成前不启用 native 执行，LG01 完成后也只切换配置来源，不切换调度。报告中的现状判断来自静态代码扫描；测试结果在 LG00 记录中另列。
