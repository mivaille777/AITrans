# AITrans LangGraph-Native 多 Agent 系统重构任务书

> **项目**：AITrans  
> **目标分支基线**：`WebReBuild`  
> **基线提交**：`4ffa8dbe86458c16bc23d3047c389dac4498d322`  
> **任务书版本**：LG-R1  
> **日期**：2026-09-19  
> **目标**：在最大限度复用现有多 Agent 业务代码的前提下，将多 Agent 执行编排迁移为 LangGraph-native Runtime，使后续新增 Agent 不再要求修改调度器、checkpoint、并发和恢复逻辑。

---

## 0. 文档用途与验收原则

本任务书不是概念设计文档，而是可以直接执行的开发计划。每一个阶段必须满足以下四个条件后，才能进入下一阶段：

1. **行为可验证**：必须有自动化测试或可重复的人工验证步骤。
2. **兼容可回滚**：在正式切换前必须保留旧路径回滚能力。
3. **不扩大业务改动面**：RAG、Artifact、Knowledge、Memory、FastAPI、Tauri 等非必要模块不得因为 LangGraph 重构而重写。
4. **以扩展能力为最终验收标准**：新增一个 Mock Agent 时，不修改调度 Runtime、checkpoint Runtime 和前端硬编码角色列表即可接入执行链。

本轮重构的核心思想：

> **保留 Domain，替换 Runtime。**

即保留 AITrans 已经成熟的 `ScopeContext / TaskSpec / Artifact / Evidence / Verification / ToolPolicy / MemoryPolicy`，将执行图、并行、恢复、Retry、Interrupt、Subgraph lifecycle 等执行语义收敛到 LangGraph。

---

# 1. 当前系统基线评估

## 1.1 当前主要调用链

当前生产链路可抽象为：

```text
Agent API / WebSocket
        │
        ▼
AgentRuntime
        │
        ▼
ReadingAgentGraph                     ← LangGraph Root
        │
        ▼
run_collaboration
        │
        ▼
MultiAgentRuntimeBridge
        │
        ▼
ResearchOrchestrationService
        │
        ├── ResearchTaskRouter
        ├── ValidatedSupervisorPlanner
        ├── AuthoritativeScopeResolver
        └── CoordinatorMemoryPort
        │
        ▼
ParallelTaskGraphExecutor             ← 自研 Workflow Runtime
        │
        ├── ThreadPoolExecutor
        ├── Future / FIRST_COMPLETED
        ├── ready frontier
        ├── retry
        ├── run lease
        ├── task checkpoint
        ├── shared budget
        └── concurrency / GPU semaphore
        │
        ├────────────┬────────────┬────────────┐
        ▼            ▼            ▼            ▼
Document         Research       Writer       Curator
LangGraph        LangGraph      LangGraph    LangGraph
```

当前形成了：

```text
LangGraph Root
    ↓
自研 Workflow Engine
    ↓
LangGraph Specialist
```

这套架构已经可用，但随着 Agent 数量增加，调度器、checkpoint、Role Enum、Planner、Dependency Injection、UI role mapping 都需要同步修改，可维护成本会快速上升。

---

## 1.2 当前关键技术栈

| 层 | 当前方案 | 重构结论 |
|---|---|---|
| Agent Runtime | `langgraph>=1.2,<1.3` | 强化使用 |
| LangGraph checkpoint | `langgraph-checkpoint-sqlite>=3,<4` | 保留 |
| API | FastAPI | 保留 |
| Schema / Contract | Pydantic 2 | 保留 |
| 本地持久化 | SQLite / WAL | 保留 |
| RAG | Qdrant | 保留 |
| Artifact | Versioned Artifact Store | 保留 |
| Memory | MemoryCoordinator / snapshot | 保留 |
| Tool | ProductAgentService / Tool Registry | 保留 |
| Frontend | React + Tauri | 保留 |
| Event | AgentEvent + Trace Store | 保留 |
| Multi-Agent Scheduler | `ParallelTaskGraphExecutor` | 迁移并退役 |
| Task checkpoint | `SQLiteTaskCheckpointStore` | 迁移并退役 |
| Legacy collaboration | `MultiAgentRuntimeBridge` / `MultiAgentWorkspaceService` | 兼容期后退役 |

---

## 1.3 当前最值得复用的代码

### 应基本原样保留

```text
backend/models/agent_tasks.py
backend/models/agent_artifacts.py

backend/agent_core/orchestration/
    artifact_store.py
    coordinator_memory.py
    evidence_service.py
    memory.py
    reducer.py
    roles.py                  # 第一阶段兼容保留
    scope_resolver.py
    validation.py

backend/agent_graph/
    document_analyst_graph.py
    research_synthesizer_graph.py
    academic_writer_graph.py
    knowledge_curator_graph.py

backend/services/
    product_agent_service.py
    agent_tool_registry.py
    agent_checkpoint_service.py
    agent_trace_store_service.py
    agent_conversation_service.py
    agent_evidence_gate_service.py
    agent_claim_evidence_verifier.py
    agent_literature_synthesis_service.py
```

### 中等修改

```text
backend/agent_graph/reading_agent_graph.py
backend/agent_graph/studio.py
backend/api/agent_dependencies.py

backend/agent_core/orchestration/
    planner.py
    router.py
    runtime_budget.py

backend/agent_core/runtime.py
backend/agent_core/state.py

apps/desktop/src/features/agent/
    components/TaskExecutionPanel.tsx
    components/MultiAgentTracePanel.tsx
    timeline/agent-timeline.ts
    runtime/agent-checkpoint-recovery.ts
```

### 最终退役

```text
backend/agent_core/orchestration/parallel_executor.py
backend/agent_core/orchestration/serial_executor.py
backend/agent_core/orchestration/task_state.py   # 视迁移后职责决定

backend/services/
    research_orchestration_service.py            # run() 最终退役或降级为薄 facade
    multi_agent_runtime_bridge.py
    multi_agent_workspace_service.py             # legacy only

backend/agent_core/multi_agent/
    legacy orchestration / planner / executor
```

---

# 2. 目标多 Agent 总体架构

## 2.1 最终目标

目标架构采用：

> **Single-root + LangGraph-native + Registry-driven + Artifact-first + Evidence-grounded**

完整框架：

```text
┌───────────────────────────────────────────────────────┐
│                    Product Layer                      │
│        React / Tauri / FastAPI / WebSocket            │
└──────────────────────────┬────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────┐
│                  Agent Runtime Facade                  │
│        Run / Conversation / Cancellation / Trace       │
└──────────────────────────┬────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────┐
│              AITrans Root LangGraph                    │
│                                                       │
│ resolve_context                                       │
│      ↓                                                │
│ prepare_conversation                                  │
│      ↓                                                │
│ route                                                 │
│   ┌──┴────────────────────────────┐                   │
│   ▼                               ▼                   │
│ Direct / ReAct                Orchestrated            │
│                                   │                   │
│                             resolve_scope             │
│                                   ↓                   │
│                             load_memory               │
│                                   ↓                   │
│                             plan_tasks                │
│                                   ↓                   │
│                             validate_plan             │
│                                   ↓                   │
│                         dispatch_ready_tasks          │
│                              LangGraph Send           │
│                        ┌────────┼────────┐             │
│                        ▼        ▼        ▼             │
│                    Specialist Subgraphs               │
│                        └────────┼────────┘             │
│                              reducer                  │
│                                 ↓                     │
│                         advance_frontier              │
│                                 ↓                     │
│                        more Send / finish             │
│                                 ↓                     │
│                         verify_delivery               │
│                                 ↓                     │
│                    optional interrupt / commit        │
│                                 ↓                     │
│                         finalize_response             │
└──────────────────────────┬────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────┐
│                 Agent Registry Layer                  │
│                                                       │
│ document      → DocumentAnalystGraph                  │
│ research      → ResearchSynthesizerGraph              │
│ writer        → AcademicWriterGraph                   │
│ curator       → KnowledgeCuratorGraph                 │
│ future agents → dynamically registered                │
└──────────────────────────┬────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────┐
│                 Domain Contract Layer                 │
│ TaskSpec / ScopeContext / Artifact / Evidence         │
│ Verification / ToolPolicy / BudgetPolicy              │
└──────────────────────────┬────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────┐
│                  Capability Layer                     │
│ RAG / Qdrant / Memory / Knowledge / LLM Gateway       │
│ Language Service / Tool Runtime / future MCP / Skills │
└───────────────────────────────────────────────────────┘
```

---

## 2.2 Root Graph 目标拓扑

```text
START
  │
  ▼
resolve_context
  │
  ▼
prepare_conversation
  │
  ▼
route_request
  │
  ├────────── direct ──────────► direct_or_react
  │                                  │
  │                                  ▼
  │                           finalize_response
  │
  └────── orchestrated
             │
             ▼
        resolve_scope
             │
             ▼
        load_memory
             │
             ▼
        plan_tasks
             │
             ▼
        validate_plan
             │
             ▼
       dispatch_frontier
             │
          Send(...)
       ┌─────┼─────┐
       ▼     ▼     ▼
    worker worker worker
       └─────┼─────┘
             │
      reduce_task_results
             │
             ▼
       advance_frontier
         │          │
     more work    finished
         │          │
         └──────┐   ▼
                │ verify_delivery
                │   │
                └───┘
                    │
             approval_required?
               │          │
              yes         no
               │          │
          interrupt()     │
               │          │
        Command(resume)   │
               └────┬─────┘
                    ▼
          finalize_conversation
                    │
                   END
```

---

# 3. 架构原则

## P1. One Authoritative Root Graph

系统只能有一个根执行图拥有：

```text
run
conversation
checkpoint
final delivery
interrupt
resume
```

Multi-Agent 不再作为 Root Graph 中的黑盒 `run_collaboration` 服务执行。

---

## P2. LangGraph Owns Execution Semantics

交给 LangGraph：

```text
graph execution
branch
loop
parallel fan-out / fan-in
subgraph lifecycle
checkpoint
resume
retry
timeout
interrupt
stream lifecycle
```

不再自行维护：

```text
ThreadPoolExecutor
Future
FIRST_COMPLETED
task scheduler loop
task checkpoint tables
run lease scheduler state
```

---

## P3. AITrans Owns Domain Semantics

以下仍完全由 AITrans 决定：

```text
Scope
Task Contract
Artifact
Evidence
Verification
Tool Permission
Memory Policy
Budget Policy
Knowledge Write Policy
Product Authorization
```

LangGraph 只决定“什么时候运行某节点”，不决定“业务上是否允许运行”。

---

## P4. Agent Is Registered, Not Hard-coded

新增 Agent 必须通过 `AgentRegistry` 完成，不修改 Scheduler。

最终新增 Agent 的标准流程：

```text
1. 实现 Agent Graph
2. 定义/注册 Artifact
3. 注册 AgentSpec
4. Planner 可见 capability
5. 完成
```

---

## P5. Artifact-first Communication

Agent 之间通过：

```text
ArtifactRef
EvidenceRef
TaskResult
```

协作。

不得依赖自由文本对话作为正式事实传递链。

---

## P6. Deterministic When Possible, Agentic When Necessary

必须 deterministic：

```text
scope
permissions
tool allow-list
dependency validation
artifact validation
budget hard limits
commit authorization
```

允许 LLM：

```text
semantic planning
research synthesis
writing
interpretation
bounded replanning
```

---

## P7. State Stores Control Data and References

Graph State 不允许保存：

```text
PDF bytes
embedding vectors
Qdrant client
DB connection
LLM client
full large artifacts
```

只保存：

```text
refs
task state
plan
scope
result
control flags
```

---

## P8. UI Consumes Semantic Events

前端继续消费：

```text
task_planned
task_started
artifact_verified
rag_rerank_completed
...
```

不要直接依赖 LangGraph 内部 event 名。

LangGraph runtime event 必须映射为稳定的 `AgentEvent`。

---

# 4. Agent Registry 设计

## 4.1 新增 AgentSpec

建议新增：

```text
backend/agent_core/orchestration/agent_registry.py
```

目标接口：

```python
AgentSpec(
    agent_id="document",
    version="1",
    display_name="Document Analyst",
    description="...",
    capabilities={...},
    accepted_input_kinds={...},
    output_kinds={...},
    allowed_tools={...},
    graph_factory=...,
    resource_class="cpu",
    retry_policy=...,
    timeout_policy=...,
)
```

必要字段：

| 字段 | 用途 |
|---|---|
| `agent_id` | 稳定唯一 ID |
| `version` | Agent contract/version |
| `display_name` | UI 名称 |
| `description` | Planner capability 描述 |
| `capabilities` | Planner 选择能力 |
| `accepted_input_kinds` | 可消费 Artifact/Input |
| `output_kinds` | 可产生 Artifact |
| `allowed_tools` | Tool policy |
| `graph_factory` | 创建/获取 subgraph |
| `resource_class` | cpu/gpu/io |
| `retry_policy` | 默认 retry |
| `timeout_policy` | 默认 timeout |

---

## 4.2 第一阶段兼容 TaskRole

不要立即删除：

```python
TaskRole.DOCUMENT
TaskRole.RESEARCH
TaskRole.WRITER
TaskRole.CURATOR
```

LG01-LG05 期间：

```text
TaskRole
  ↓ adapter
agent_id
```

后续再将：

```text
TaskSpec.role: TaskRole
```

演化为：

```text
TaskSpec.agent_id: str
```

这样可以避免一次性修改大量 Pydantic schema 和已有测试。

---

## 4.3 Agent Catalog

后续新增只读 API：

```text
GET /agent/catalog
```

返回：

```text
agent_id
display_name
description
capabilities
icon_key
version
```

前端不再硬编码：

```typescript
const roleLabels = {...}
```

---

# 5. Root Graph State 设计

## 5.1 第一阶段状态结构

为了最大限度兼容现有 `AgentState`，建议建立：

```text
backend/agent_core/orchestration/graph_state.py
```

概念状态：

```python
class OrchestrationGraphState(TypedDict, total=False):
    agent_state: dict

    route: dict

    scope: dict
    memory_snapshot_ref: str
    memory_snapshot: dict

    task_plan: dict

    task_results: Annotated[
        list[TaskResult],
        reduce_task_results
    ]

    dispatched_task_ids: Annotated[
        list[str],
        merge_unique_ids
    ]

    retry_task_ids: list[str]

    final_artifact_refs: list[ArtifactRef]

    orchestration_status: str
    delivery: dict
```

---

## 5.2 State 分层

### Checkpoint State

必须持久化：

```text
AgentState JSON
route
ScopeContext
ValidatedTaskPlan
TaskResult
ArtifactRef
memory_snapshot_ref
dispatched task IDs
retry request
delivery state
```

### Runtime Context

不得持久化：

```text
event_sink
AgentRunControl
AgentRegistry
ArtifactStore
EvidenceService
MemoryPort
ToolRuntime
ResourceManager
BudgetManager
LLM providers
```

继续使用：

```python
Runtime[...]
```

注入。

---

# 6. Specialist Subgraph 设计

现有四个 Specialist Graph 尽量原样保留。

## 6.1 Document Analyst

现有：

```text
plan_coverage
  ↓
retrieve_evidence
  ↓
analyze_document
  ↓
verify_artifact
```

保留：

```text
DocumentAnalysisArtifact
evidence refs
coverage verification
scope verification
```

只需要增加标准 Worker 输入/输出 adapter。

---

## 6.2 Research Synthesizer

现有：

```text
load_document_artifacts
  ↓
load_authorized_memory
  ↓
synthesize_comparison
  ↓
verify_comparison
```

保留。

必须继续保证：

```text
Memory ≠ Evidence
```

Memory 只能提供 hypothesis/context，不能直接升级为文献事实。

---

## 6.3 Academic Writer

保留：

```text
Outline
ManuscriptSection
Revision
```

保持：

```text
用户实验数据 = user_supplied
不得自动编造结果
正式 literature review 保留 review gate
```

---

## 6.4 Knowledge Curator

继续只生成：

```text
KnowledgeDraftArtifact
```

不得直接 commit。

后续 commit 流程：

```text
Curator
  ↓
KnowledgeDraftArtifact
  ↓
verification
  ↓
interrupt()
  ↓
user approval
  ↓
existing Knowledge Service commit
```

---

# 7. Task DAG 与 LangGraph Send 设计

## 7.1 保留 DAG Contract

继续使用：

```text
ValidatedTaskPlan
TaskSpec.depends_on
```

Planner 仍然负责生成 logical DAG。

例如：

```text
document-1 ─┐
document-2 ─┼── research-1 ── writer-1
document-3 ─┘
```

---

## 7.2 抽取纯函数 frontier

从 `parallel_executor.py` 抽出：

```text
backend/agent_core/orchestration/frontier.py
```

包含：

```text
get_ready_tasks()
get_blocked_tasks()
get_descendants()
is_plan_complete()
dependency_results_for()
```

这些属于业务图算法，可保留。

---

## 7.3 用 Send 替换线程池

目标：

```python
def dispatch_frontier(state):
    ready = get_ready_tasks(...)

    return [
        Send(
            registry.node_name(task.role),
            build_worker_state(task, state),
        )
        for task in ready
    ]
```

删除生产路径中的：

```text
ThreadPoolExecutor
Future
wait(FIRST_COMPLETED)
```

---

## 7.4 Reducer

直接复用：

```text
backend/agent_core/orchestration/reducer.py
reduce_task_results()
```

作为 LangGraph reducer。

同时新增：

```text
merge_unique_ids()
merge_artifact_refs()
```

必须具备：

```text
deterministic
idempotent
conflict detection
stable ordering
```

---

# 8. Agent 状态生命周期

## 8.1 Task 状态

继续使用：

```text
PENDING
READY
RUNNING
WAITING_CONFIRMATION
SUCCEEDED
PARTIAL
FAILED
CANCELLED
BLOCKED
SKIPPED
```

但不再使用独立 task checkpoint table 作为 authoritative state。

Graph State + Checkpoint 为真相源。

---

## 8.2 Dependency failure

规则：

```text
dependency SUCCEEDED/PARTIAL
    → 下游是否运行由 acceptance policy 判断

required dependency FAILED/CANCELLED
    → dependent BLOCKED

optional dependency FAILED
    → dependent 允许继续，但必须带 warning
```

不得由 LLM 自己判断依赖是否有效。

---

## 8.3 Partial

`PARTIAL` 不是异常。

必须允许：

```text
partial artifact
+
explicit unmet_requirements
+
warnings
+
coverage
```

后续节点根据 acceptance criteria 判断是否可继续。

---

# 9. Memory 设计

## 9.1 Memory 分层

必须区分：

```text
Conversation State
Run State
Memory Snapshot
Long-term Memory
Evidence
```

禁止混用。

---

## 9.2 当前 CoordinatorMemoryPort 继续保留

当前：

```text
CoordinatorMemoryPort
MemoryCoordinator
```

应继续负责：

```text
load_snapshot
role projections
submit_candidates
revocation handling
scope filtering
```

---

## 9.3 Graph 中的 Memory 流

```text
resolve_scope
    ↓
load_memory_snapshot
    ↓
memory_snapshot_ref
    ↓
Specialist receives bounded projection
    ↓
Artifact output
    ↓
memory_candidate_node
    ↓
MemoryCoordinator.submit_candidates()
```

专家不得：

```text
直接写长期记忆
直接修改 user profile
直接将自身结论变成长期事实
```

---

## 9.4 Checkpoint 与 Memory 的边界

Checkpoint 保存：

```text
memory_snapshot_ref
snapshot revision/hash
```

长期 Memory 继续由 Memory Store 管理。

Resume 时必须检查：

```text
snapshot 是否仍有效
scope 是否变化
source 是否被撤销/删除
```

无效则：

```text
阻止旧 memory 自动重新进入模型
```

保留现有：

```text
memory_snapshot_invalidated
```

语义。

---

# 10. Checkpoint 设计

## 10.1 Authoritative Checkpoint

最终唯一执行状态 checkpoint：

```text
LangGraph SqliteSaver
```

继续保留：

```text
thread_id = run_id
WAL
busy_timeout
strict JsonPlusSerializer
```

---

## 10.2 Temporary Run

继续保留双 graph：

```text
persistent graph
  → checkpointer

temporary graph
  → compile without checkpointer
```

temporary run：

```text
不可跨进程 resume
不可写 persistent task state
```

---

## 10.3 Specialist Checkpoint

Specialist 作为 parent graph subgraph。

优先使用：

```text
per-invocation subgraph persistence
```

不要给每个 Specialist 单独建立 SQLite DB。

目标恢复粒度：

```text
Root node-level
+
Specialist subgraph node-level
```

而不是当前：

```text
Root node-level
+
Specialist whole-task retry
```

---

## 10.4 旧 TaskCheckpointStore 迁移

### Shadow 阶段

```text
LangGraph state
    +
SQLiteTaskCheckpointStore
```

两边同时记录。

### Authoritative 阶段

```text
LangGraph = authoritative
TaskCheckpointStore = compare only
```

### Removal 阶段

删除：

```text
multi_agent_task_runs
multi_agent_task_checkpoints
```

相关 runtime 代码。

---

# 11. Retry / Timeout / Recovery

## 11.1 Retry 分层

| 错误 | 处理 |
|---|---|
| HTTP transient | LangGraph RetryPolicy |
| Provider 5xx | RetryPolicy |
| Node timeout | TimeoutPolicy + Retry |
| malformed structured output | Node 内 repair |
| Artifact verify failed | 返回 FAILED/PARTIAL |
| scope violation | fail，不 retry |
| permission denied | fail，不 retry |
| budget exhausted | blocked/fail，不 retry |
| user cancellation | cancel，不 retry |
| manual retry | recovery branch |

---

## 11.2 Manual Retry

当前 UI 的：

```text
重试失败任务
```

继续保留。

新流程：

```text
failed task
   ↓
recovery_gate
   ↓
interrupt()
   ↓
user chooses retry
   ↓
Command(resume={task_id})
   ↓
mark target + descendants pending
   ↓
dispatch_frontier
```

已经成功的 sibling 不重复运行。

---

## 11.3 Write Replay Safety

现有安全策略必须保留：

```text
恢复 checkpoint 后清空 confirmed_write_tools
write node 不允许自动重放
```

所有持久写入必须：

```text
重新确认
```

---

# 12. Budget 与 Resource 设计

## 12.1 BudgetManager

保留 AITrans 产品预算：

```text
max_model_calls
max_tool_calls
max_retrievals
token budget
elapsed time
```

但建议从当前：

```text
SharedRunBudget + ContextVar
```

逐步迁移到：

```text
Runtime Context → BudgetManager
```

---

## 12.2 Graph 并发

普通 Agent 并发交给 LangGraph execution。

最终删除：

```text
_GLOBAL_EXPERT_SLOTS
ThreadPoolExecutor(max_workers=...)
```

---

## 12.3 GPU ResourceManager

GPU 资源限制仍属于 AITrans。

保留概念：

```text
gpu = 1
ocr = bounded
embedding = bounded
vision = bounded
```

但从 Scheduler 中拆出：

```text
ResourceManager
```

Graph node 在执行 GPU 操作前：

```text
ResourceManager.acquire(resource_class)
```

---

# 13. Event / Trace / UI 设计

## 13.1 AgentEvent 继续作为公开事件协议

继续保留：

```text
AgentEventType
AgentTraceStoreService
WebSocket event delivery
```

---

## 13.2 Event 来源

未来：

```text
LangGraph lifecycle
      +
AITrans semantic event
      ↓
AgentEvent normalization
      ↓
Trace Store
      ↓
WebSocket
      ↓
Frontend
```

---

## 13.3 前端不要依赖 LangGraph 内部 event

前端继续消费：

```text
task_planned
task_ready
task_started
task_progress
task_completed
artifact_verified
artifact_rejected
workflow_resumed
...
```

---

## 13.4 Task UI 动态 Agent 化

当前：

```typescript
const roleLabels = {
  document,
  research,
  writer,
  curator
}
```

迁移：

```text
GET /agent/catalog
```

UI 使用：

```text
task.agent_id
catalog[agent_id]
```

后续新增 Agent 不修改 `TaskExecutionPanel.tsx` 的角色映射。

---

# 14. LangGraph Studio 设计

## 14.1 当前问题

当前：

```text
langgraph.json
  → studio.py
  → ReadingAgentGraph(adapter)
```

未完整使用生产：

```text
scope
memory
multi-agent runtime
specialists
```

Studio 中的 `run_collaboration` 并不等价于生产行为。

---

## 14.2 目标

新增统一 builder：

```text
backend/agent_graph/factory.py
```

建议：

```python
build_agent_graph(dependencies, *, persistent=True)
```

FastAPI：

```text
build_agent_graph(prod deps)
```

Studio：

```text
build_agent_graph(studio deps)
```

两者：

```text
Topology 必须相同
```

只允许 dependency provider 不同。

---

# 15. 开发阶段总览

| 阶段 | 名称 | 主要目标 |
|---|---|---|
| LG00 | Baseline Lock | 固化现状、测试和回滚基线 |
| LG01 | Agent Registry | 建立可扩展 Agent 注册模型 |
| LG02 | Graph State | 将 TaskPlan / TaskResult 进入 Root State |
| LG03 | Root Orchestration Nodes | 将 Scope/Memory/Plan 拆成 LangGraph nodes |
| LG04 | Send + Reducer | 用 LangGraph 替换线程池调度 |
| LG05 | Specialist Subgraphs | 四个专家正式成为 Root 子图 |
| LG06 | Checkpoint Native | LangGraph 接管 task durable execution |
| LG07 | Retry / Interrupt / HITL | 统一恢复、手动 retry 和写入确认 |
| LG08 | Event / UI Dynamic Agent | UI 与 Registry/Graph 对齐 |
| LG09 | Studio / Production Unification | Studio 与生产统一图工厂 |
| LG10 | Legacy Removal | 删除旧 Orchestrator 与兼容层 |

---

# 16. LG00 — Baseline Lock

## 目标

建立重构前可重复验证基线。

## 开发任务

- [ ] 记录 `WebReBuild` baseline commit。
- [ ] 锁定当前 LangGraph / checkpoint 实际安装版本。
- [ ] 保存现有测试结果。
- [ ] 保存典型 multi-agent event fixture。
- [ ] 保存典型 TaskPlan / TaskResult snapshot。
- [ ] 保存 checkpoint/resume fixture。
- [ ] 建立 `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` feature flag。
- [ ] 保留原 `AITRANS_MULTI_AGENT_ENGINE / ROLLOUT` 兼容开关。

## 涉及文件

```text
pyproject.toml
backend/agent_core/orchestration/migration.py
backend/api/agent_dependencies.py
tests/multi_agent/*
tests/agent/test_agent_checkpoint_persistence.py
```

## 必须通过的现有测试

至少：

```text
test_parallel_scheduler.py
test_subgraph_checkpoint.py
test_result_reducer.py
test_plan_validation.py
test_supervisor_planner.py
test_root_orchestration_integration.py
test_temporary_workflow.py
test_task_events.py
test_memory_port_integration.py
test_memory_revocation_resume.py
test_cancellation_fencing.py
test_run_lease.py
test_commit_idempotency.py
```

## 验收门槛

- [ ] old runtime 全部通过。
- [ ] feature flag 关闭时行为完全不变。
- [ ] 建立重构前 deterministic report。

---

# 17. LG01 — Agent Registry

## 目标

新增 Agent 不再直接修改 Scheduler。

## 新增文件

```text
backend/agent_core/orchestration/agent_registry.py
tests/multi_agent/test_agent_registry.py
```

## 修改文件

```text
backend/agent_core/orchestration/roles.py
backend/agent_core/orchestration/planner.py
backend/api/agent_dependencies.py
```

## 开发任务

- [ ] 定义 `AgentSpec`。
- [ ] 定义 `AgentRegistry`。
- [ ] 注册现有四个 Agent。
- [ ] TaskRole → agent_id compatibility adapter。
- [ ] 将 `_TOOLS_BY_ROLE` 信息迁入 Registry。
- [ ] 将 `_OUTPUT_BY_ROLE` 信息迁入 Registry。
- [ ] Planner 改为读取 Registry。
- [ ] 添加 Mock Agent 测试。

## 验证

### Test A：现有 Planner 不变

同样输入产生语义等价 TaskPlan。

### Test B：Mock Agent

运行时注册：

```text
mock_data
```

Planner/Registry 能解析，且无需改 Scheduler。

### Test C：Tool Policy

注册 Agent 请求未授权 Tool：

```text
validate_task_plan → reject
```

## Gate

```text
LG01 PASS =
现有四 Agent 行为不变
+
Mock Agent 可注册
+
Planner 不再依赖硬编码 _TOOLS_BY_ROLE/_OUTPUT_BY_ROLE
```

---

# 18. LG02 — Orchestration Graph State

## 目标

TaskPlan / TaskResult 正式成为 LangGraph state，而不是黑盒 service 的局部状态。

## 新增文件

```text
backend/agent_core/orchestration/graph_state.py
backend/agent_core/orchestration/frontier.py
tests/multi_agent/test_langgraph_orchestration_state.py
```

## 修改文件

```text
backend/agent_graph/reading_agent_graph.py
backend/agent_core/state.py
backend/agent_core/orchestration/reducer.py
```

## 开发任务

- [ ] 建立 `OrchestrationGraphState`。
- [ ] 复用 `reduce_task_results`。
- [ ] 新增 unique ID reducer。
- [ ] 新增 ArtifactRef reducer。
- [ ] 把 scope / memory ref / plan / result 纳入 root checkpoint state。
- [ ] 继续同步旧 `AgentState.orchestration_*` 字段，保证 API 兼容。
- [ ] `browser_context` 中的 orchestration payload 标记 deprecated，但暂不删除。

## 验证

- [ ] checkpoint 中可读取 task plan。
- [ ] checkpoint 中可读取 task results。
- [ ] reducer 并行合并无覆盖。
- [ ] hash conflict 仍抛出 `TaskResultConflictError`。
- [ ] old frontend snapshot API 不变。

---

# 19. LG03 — Root Orchestration Nodes

## 目标

将 `ResearchOrchestrationService.run()` 拆进 Root LangGraph。

## 新增/修改节点

在 `ReadingAgentGraph` 中加入：

```text
resolve_scope
load_memory_snapshot
plan_tasks
validate_plan
prepare_orchestrated_execution
```

## 复用现有方法

```text
ResearchOrchestrationService._scope_request
AuthoritativeScopeResolver.resolve
CoordinatorMemoryPort.load_snapshot
ResearchTaskRouter.route
ValidatedSupervisorPlanner.plan
validate_task_plan
```

第一阶段允许继续由薄 service 方法提供逻辑，避免重写。

## 修改文件

```text
backend/agent_graph/reading_agent_graph.py
backend/services/research_orchestration_service.py
backend/services/multi_agent_runtime_bridge.py
backend/api/agent_dependencies.py
```

## 验证

- [ ] FAST 不进入 orchestration nodes。
- [ ] SINGLE 进入 plan，但只产生 1 task。
- [ ] WORKFLOW 产生 DAG。
- [ ] missing_information 不执行 Specialist。
- [ ] scope failure 中止执行。
- [ ] invalid memory snapshot 中止执行。
- [ ] TaskPlan 进入 LangGraph checkpoint。

## Gate

`run_collaboration` 内部不得再负责 route/scope/memory/plan 的 authoritative 执行。

---

# 20. LG04 — Send + Reducer

## 目标

替换 `ParallelTaskGraphExecutor` 的核心调度循环。

## 新增节点

```text
dispatch_frontier
specialist_worker
advance_frontier
finalize_task_graph
```

或者采用 role-specific dispatch node。

## 开发任务

- [ ] 抽取 `frontier.py`。
- [ ] 实现 ready task 计算。
- [ ] 实现 dependency result projection。
- [ ] 用 `Send` 动态 fan-out。
- [ ] worker 返回 `TaskResult`。
- [ ] reducer 合并结果。
- [ ] `advance_frontier` 计算下一层。
- [ ] required failure → BLOCKED descendant。
- [ ] optional failure → warning + continue。
- [ ] sibling failure 不阻塞无依赖 sibling。
- [ ] 并发上限通过 LangGraph config 控制。
- [ ] 旧 ParallelExecutor 保留 shadow path。

## 修改文件

```text
backend/agent_graph/reading_agent_graph.py
backend/agent_core/orchestration/frontier.py
backend/agent_core/orchestration/reducer.py
backend/api/agent_dependencies.py
```

## 对照验证

### Case 1

```text
a
b
```

必须并发进入 worker。

### Case 2

```text
a → b
```

b 不得在 a 完成前启动。

### Case 3

```text
a → c
b → d
```

b failed：

```text
a = SUCCEEDED
b = FAILED
c = SUCCEEDED
d = BLOCKED
```

必须与当前 `test_parallel_scheduler.py` 行为一致。

### Case 4

同一个 TaskResult 重复 replay：

```text
idempotent
```

不同 hash：

```text
conflict
```

## Gate

生产 feature flag 打开时，不再调用：

```text
ThreadPoolExecutor
FIRST_COMPLETED
```

---

# 21. LG05 — Specialist Subgraphs

## 目标

四个现有 Graph 正式成为 Root Graph 可见 subgraph。

## 开发任务

- [ ] Document Graph adapter。
- [ ] Research Graph adapter。
- [ ] Writer Graph adapter。
- [ ] Curator Graph adapter。
- [ ] Registry 的 graph_factory 指向真实 subgraph。
- [ ] Worker state 使用统一 schema。
- [ ] dependency_results 由 parent state 提供。
- [ ] memory projection 由 parent scope/memory snapshot 提供。
- [ ] ArtifactStore 继续独立。
- [ ] 不给每个 Specialist 建立独立 SQLite checkpointer。

## 涉及文件

```text
backend/agent_graph/document_analyst_graph.py
backend/agent_graph/research_synthesizer_graph.py
backend/agent_graph/academic_writer_graph.py
backend/agent_graph/knowledge_curator_graph.py
backend/agent_core/orchestration/agent_registry.py
```

## 验证

- [ ] 四个现有 Specialist 原测试全部通过。
- [ ] Root Graph 可以看到 specialist subgraph。
- [ ] Artifact hash / scope / verification contract 不变化。
- [ ] Specialist 可以独立单 Agent 执行。
- [ ] 多个同类型 Document Agent instance 可并行。

---

# 22. LG06 — LangGraph-native Checkpoint

## 目标

LangGraph checkpoint 成为唯一 authoritative execution checkpoint。

## 开发任务

- [ ] 验证 root + subgraph checkpoint 恢复。
- [ ] 验证并行 sibling pending writes。
- [ ] 验证 process interruption。
- [ ] 验证成功 task 不重复执行。
- [ ] 将旧 TaskCheckpointStore 设为 shadow compare。
- [ ] 对比 LangGraph state 与 TaskCheckpointStore 状态一致性。
- [ ] 加入 graph/state schema version。
- [ ] 明确旧 checkpoint legacy resume 策略。

## 旧 checkpoint 策略

不强行迁移旧 graph position。

```text
new run
    → LangGraph-native

old active run
    → legacy runtime resume
```

旧 run 结束后再删除旧 runtime。

## 验证场景

```text
document-1 success
document-2 success
document-3 crash
research pending
```

进程重启后：

```text
document-1 不重跑
document-2 不重跑
document-3 恢复/重试
research 等待
```

## Gate

- [ ] 新 run 不依赖 `SQLiteTaskCheckpointStore` 才能恢复。
- [ ] temporary run 不写 persistent checkpoint。
- [ ] pending write 不自动 replay。

---

# 23. LG07 — Retry / Timeout / Interrupt / HITL

## 目标

统一所有 execution recovery 行为。

## 开发任务

- [ ] 为 transient LLM node 配 RetryPolicy。
- [ ] 为长耗时 node 配 TimeoutPolicy。
- [ ] scope/permission/budget failure 标记 non-retryable。
- [ ] manual task retry 改为 recovery branch。
- [ ] Curator save 使用 interrupt。
- [ ] 未来 destructive write 统一 interrupt。
- [ ] resume 后必须重新确认 write permission。
- [ ] cancellation 传播到 active subgraph。
- [ ] cancellation 后 late artifact 禁止成为 authoritative output。

## 修改文件

```text
backend/agent_graph/reading_agent_graph.py
backend/agent_core/reliability.py
backend/agent_core/runtime.py
backend/services/product_agent_service.py
backend/agent_graph/knowledge_curator_graph.py
```

## 验证

- [ ] retryable transient error 自动 retry。
- [ ] business validation fail 不 retry。
- [ ] manual retry 只重跑 target + descendants。
- [ ] successful siblings 不重跑。
- [ ] user cancel 后不出现最终 successful delivery。
- [ ] interrupt 跨进程可恢复。
- [ ] write replay safety 保持。

---

# 24. LG08 — Event 与动态 Agent UI

## 目标

后端 Registry 与前端 Agent Timeline 对齐，去除固定四角色假设。

## Backend

新增：

```text
GET /agent/catalog
```

Agent event 增加可选：

```text
agent_id
agent_version
node_name
subgraph_path
```

但保持现有 event type 兼容。

## Frontend 修改

```text
apps/desktop/src/features/agent/components/TaskExecutionPanel.tsx
apps/desktop/src/features/agent/components/MultiAgentTracePanel.tsx
apps/desktop/src/features/agent/timeline/agent-timeline.ts
apps/desktop/src/features/agent/state/agent-workspace-state.ts
apps/desktop/src/api/agent.ts
```

## 开发任务

- [ ] 删除固定 `roleLabels`。
- [ ] catalog 驱动角色名称/图标。
- [ ] Task DAG 仍根据 TaskPlan 动态显示。
- [ ] timeline 显示实际 Agent instance。
- [ ] tool call 仍显示为 capability，不伪装成 Agent。
- [ ] language service 仍标记“共享能力/非独立 Agent”。
- [ ] retry UI 对接 LangGraph recovery API。
- [ ] waiting confirmation 显示为真实 interrupt 状态。

## 验证

动态注册 Mock Agent：

```text
mock_data
```

不修改前端代码，UI 能显示：

```text
名称
状态
依赖
事件
结果
```

---

# 25. LG09 — Studio / Production Unification

## 目标

LangGraph Studio 与生产使用同一 topology。

## 新增

```text
backend/agent_graph/factory.py
```

## 修改

```text
backend/agent_graph/studio.py
backend/api/agent_dependencies.py
langgraph.json
```

## 开发任务

- [ ] 统一 `build_agent_graph()`。
- [ ] Production 注入真实 services。
- [ ] Studio 注入 studio-compatible providers。
- [ ] 图节点 topology 完全相同。
- [ ] Studio 能看到：
  - route
  - scope
  - plan
  - dispatch
  - document subgraphs
  - research
  - writer
  - curator
  - interrupt
  - finalization

## Gate

Studio 中不得再只有：

```text
run_collaboration
```

黑盒。

---

# 26. LG10 — Legacy Runtime Removal

## 前提

LG00–LG09 全部通过。

## 删除/降级

```text
ParallelTaskGraphExecutor
SQLiteTaskCheckpointStore
MultiAgentRuntimeBridge
legacy MultiAgentWorkspaceService production path
legacy orchestration executor
legacy keyword planner
```

`ResearchOrchestrationService`：

```text
run()
```

删除或变成 compatibility facade。

## 清理

- [ ] 删除双 task state。
- [ ] 删除 run lease scheduler state。
- [ ] 删除旧 task checkpoint tables 新写入。
- [ ] 保留旧 DB 只读 migration/cleanup 工具一段时间。
- [ ] 删除旧 feature flags。
- [ ] 更新 architecture docs。
- [ ] 更新 README / developer docs。

---

# 27. 建议最终目录

```text
backend/
├ agent_core/
│  ├ runtime.py
│  ├ state.py
│  ├ reliability.py
│  │
│  └ orchestration/
│     ├ agent_registry.py
│     ├ graph_state.py
│     ├ frontier.py
│     ├ planner.py
│     ├ router.py
│     ├ validation.py
│     ├ reducer.py
│     ├ roles.py                  # compatibility until TaskSpec v2
│     ├ scope_resolver.py
│     ├ coordinator_memory.py
│     ├ evidence_service.py
│     ├ artifact_store.py
│     ├ runtime_budget.py
│     └ resource_manager.py
│
├ agent_graph/
│  ├ factory.py
│  ├ reading_agent_graph.py       # authoritative Root Graph
│  ├ document_analyst_graph.py
│  ├ research_synthesizer_graph.py
│  ├ academic_writer_graph.py
│  ├ knowledge_curator_graph.py
│  └ studio.py
│
├ models/
│  ├ agent_tasks.py
│  ├ agent_artifacts.py
│  └ agent_orchestration.py
│
└ services/
   ├ product_agent_service.py
   ├ agent_checkpoint_service.py
   ├ agent_trace_store_service.py
   ├ agent_conversation_service.py
   └ ...
```

---

# 28. 完整验证矩阵

## Routing

- [ ] 普通聊天 → direct。
- [ ] 简单翻译 → direct language capability。
- [ ] 单文档分析 → one specialist。
- [ ] 多文档比较 → workflow。
- [ ] compare + write → document → research → writer。
- [ ] curate → appropriate upstream → curator。
- [ ] missing source → blocked before execution。

## Scope

- [ ] Agent 无法访问 scope 外 document。
- [ ] Agent 无法访问 scope 外 note。
- [ ] Planner 不能扩大 scope。
- [ ] Resume 时 scope revision 不一致必须检测。
- [ ] deleted source 不得重新进入恢复后的任务。

## Parallel

- [ ] independent workers 并行。
- [ ] dependency task 等待。
- [ ] sibling failure 隔离。
- [ ] fan-in reducer 无覆盖。
- [ ] max concurrency 生效。

## Artifact

- [ ] type 正确。
- [ ] hash 正确。
- [ ] lineage 正确。
- [ ] evidence refs 正确。
- [ ] version 正确。
- [ ] out-of-scope artifact 被拒绝。

## Memory

- [ ] frozen snapshot。
- [ ] role projection。
- [ ] revoked snapshot。
- [ ] temporary run 不提交 long-term candidates。
- [ ] memory 不充当 evidence。

## Checkpoint

- [ ] root interruption resume。
- [ ] subgraph interruption resume。
- [ ] completed sibling 不重放。
- [ ] temporary 不持久。
- [ ] unknown graph version reject。
- [ ] write pending replay reject。

## Retry

- [ ] transient error。
- [ ] timeout。
- [ ] max retry。
- [ ] manual retry。
- [ ] descendant reset。
- [ ] successful sibling reuse。

## Cancellation

- [ ] root cancel。
- [ ] active specialist cancel。
- [ ] pending task cancel。
- [ ] late future/output fence。
- [ ] cancelled run 不产生 final successful delivery。

## HITL

- [ ] knowledge commit interrupt。
- [ ] resume approve。
- [ ] resume reject。
- [ ] process restart 后继续等待。
- [ ] confirmation 不跨 run 泄漏。

## Dynamic Agent

- [ ] register Mock Agent。
- [ ] Planner sees capabilities。
- [ ] Graph dispatch works。
- [ ] checkpoint works。
- [ ] timeline works。
- [ ] no scheduler source modification。

---

# 29. 回滚策略

任何阶段发生严重问题时：

```text
langgraph-native
      ↓
old typed workflow
      ↓
single
      ↓
simple
      ↓
legacy/off
```

LG00-LG09 保留旧 Runtime。

禁止在新 runtime 通过全部 checkpoint/retry/cancel/write safety gate 前删除旧路径。

---

# 30. 发布策略

## Alpha

仅开发开关：

```text
AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT=1
```

默认关闭。

---

## Beta

仅：

```text
SINGLE
```

迁移到新 Runtime。

复杂 workflow 保持 old executor。

---

## RC

```text
SINGLE + WORKFLOW
```

进入 LangGraph-native。

TaskCheckpointStore 仍 shadow。

---

## Stable

LangGraph-native authoritative。

---

## Cleanup

移除：

```text
old executor
task checkpoint store
migration bridge
legacy runtime flags
```

---

# 31. 性能与质量指标

迁移不能只以“测试通过”为依据。

至少比较：

| 指标 | Baseline | New Runtime |
|---|---|---|
| 单 Specialist latency | 记录 | 不显著恶化 |
| 多 Document fan-out latency | 记录 | 不劣于旧 parallel executor |
| crash resume 重复任务数 | 记录 | ≤ baseline |
| Artifact verification pass rate | 记录 | 不下降 |
| scope violation | 0 | 必须 0 |
| duplicate write | 0 | 必须 0 |
| cancel 后 late delivery | 0 | 必须 0 |
| task event 完整率 | 记录 | 不下降 |
| 新增 Agent 修改 Runtime 文件数 | 多 | **目标 0** |

---

# 32. 最终 Done Definition

整个项目只有在满足以下条件时，才能宣布“LangGraph-native Multi-Agent 重构完成”：

- [ ] Multi-Agent 是 Root Graph 的 first-class branch。
- [ ] `run_collaboration` 不再承载黑盒 workflow。
- [ ] `ParallelTaskGraphExecutor` 不再是生产调度器。
- [ ] `SQLiteTaskCheckpointStore` 不再是 authoritative state。
- [ ] 四个 Specialist 是真正 subgraphs。
- [ ] `Send + Reducer` 驱动动态 fan-out/fan-in。
- [ ] LangGraph checkpoint 驱动 resume。
- [ ] Retry / Timeout / Interrupt 使用统一执行语义。
- [ ] Artifact / Evidence / Scope contract 完全保留。
- [ ] Memory snapshot/revocation contract 完全保留。
- [ ] Frontend 不硬编码四个 Agent。
- [ ] Studio 与 Production 使用同一 graph builder。
- [ ] 新增 Mock Agent 不修改 Scheduler。
- [ ] 新增 Mock Agent 不修改 checkpoint runtime。
- [ ] 新增 Mock Agent 不修改 TaskExecutionPanel role map。
- [ ] 旧运行可安全回滚/恢复。
- [ ] 所有 deterministic gate 通过。

---

# 33. 推荐实际实施顺序

不要同时开发所有阶段。

建议严格按：

```text
LG00
 ↓
LG01 Agent Registry
 ↓
LG02 Graph State
 ↓
LG03 Root orchestration nodes
 ↓
LG04 Send + Reducer
 ↓
LG05 Specialist Subgraphs
 ↓
LG06 Checkpoint
 ↓
LG07 Retry / HITL
 ↓
LG08 UI / Events
 ↓
LG09 Studio
 ↓
LG10 Cleanup
```

其中最大的技术风险集中在：

```text
LG04
LG06
LG07
```

因此每个阶段都必须独立提交并可以单独回滚。

---

# 34. 第一批建议提交

建议开发提交粒度：

```text
feat(agent): add extensible agent registry
feat(agent): add langgraph orchestration state
refactor(agent): move scope and planning into root graph
refactor(agent): replace task threadpool with langgraph send
refactor(agent): mount specialist graphs as subgraphs
feat(agent): add native graph checkpoint recovery
feat(agent): unify task retry and human interrupts
refactor(agent-ui): drive task agents from runtime catalog
refactor(agent): unify studio and production graph factory
refactor(agent): remove legacy multi-agent executor
```

不要将整个迁移压成一个 commit。

---

# 35. 最终架构目标一句话

> **AITrans 的多 Agent 系统最终应成为：由一个权威 LangGraph Root Graph 驱动、通过 Agent Registry 动态扩展、以 Artifact/Evidence 为 Agent 间数据契约、以 Scope/Verification 为安全边界、以 LangGraph Checkpoint/Retry/Interrupt 为执行基础设施的可恢复多 Agent Runtime。**

其扩展目标是：

```text
新增 Agent
   ↓
实现 Graph
   ↓
定义 Artifact
   ↓
注册 AgentSpec
   ↓
Planner 使用 capability
   ↓
完成
```

而不再是：

```text
新增 Agent
→ 改 Scheduler
→ 改 Executor
→ 改 Checkpoint
→ 改 Planner
→ 改 Runtime
→ 改 UI
```

这条差异即为本轮重构最核心的工程价值。
