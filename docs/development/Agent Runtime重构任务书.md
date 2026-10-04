# Agent Runtime重构任务书

> 版本：AR-R2 · 2026-09-27 · 当前基线：`WebReBuild @ 75fad6ed75ea794d2f0489e001bf5be4b3cfac83`  
> 依据：[Agent Runtime 重构影响分析报告](agent-runtime-refactor-impact-analysis.md)、[LG00 基线记录](agent-runtime-lg00-baseline.md)、[LG01 实施记录](agent-runtime-lg01-report.md)。本文已接替原 LG-R1 方案；**后续实施以本文的顺序、文件和门禁为准**。

## 0. 任务目标与现状

目标是让一个权威 `AgentRuntime → RootAgentGraph` 负责 run、conversation、计划、专业 Agent 调度、checkpoint、恢复和最终交付。`AgentRegistry` 负责专业能力目录；`AgentToolRegistry → ProductAgentService` 继续负责 typed Tool 的权限和执行；Artifact、Evidence、Scope、Memory 仍使用现有业务服务。新增 Agent 的最终验收是：注册 spec 与图后即可被计划、执行、恢复和显示，不修改调度器、checkpoint 代码或前端角色常量。

当前调用链：`AgentWorkspace/useAgentRuntime → /api/agent/run|stream 或 /api/agent/runs → get_agent_runtime → AgentRuntime → RootAgentGraph(ReadingAgentGraph) → run_collaboration → MultiAgentRuntimeBridge → ResearchOrchestrationService → ParallelTaskGraphExecutor → 四个 specialist graph`。持久任务 Worker 也调用 `get_agent_runtime`；`AgentRunStore` 只管理队列、租约和任务生命周期。LangGraph Root 与 `SQLiteTaskCheckpointStore` 暂时都有执行状态，需按阶段收敛。

| 阶段 | 状态 | 本轮结论 |
| --- | --- | --- |
| Stage 0 基线与故障分流 | PASS；六项债务已在 Stage 11 解决 | 干净基线对照保留；Canvas 2 项与 grounded synthesis 4 项已由各自工作流修复，详见 [Stage 0 报告](agent-runtime-stage-00-report.md) |
| Stage 1 Agent Registry | 已实施；定向门禁通过 | 352 项相关测试通过，Mock Agent 可注册和发现，尚不能执行动态 `TaskSpec` |
| Stage 2 统一 Root Graph 工厂 | PASS | Studio/生产拓扑及条件边一致；临时图无 checkpoint；旧 checkpoint 与 native-off 夹具通过，详见 [Stage 2 报告](agent-runtime-stage-02-report.md) |
| Stage 3 Tool/Sandbox/MCP 准入 | PASS | Worker ToolPort 经 Agent 与 task allowlist、authoritative scope、typed ToolSpec 和 ProductAgentService；无 Docker/宿主回退，详见 [Stage 3 报告](agent-runtime-stage-03-report.md) |
| Stage 4 | PASS | Root canonical 编排 state、旧字段单向投影、raw checkpoint 版本选择与 queued run 版本 pin 已完成；定向 48 passed，Agent/multi-agent 全集复现 Stage 0 六项失败无新增，详见 [Stage 4 报告](agent-runtime-stage-04-report.md) |
| Stage 5 | PASS | native Root 显式 route/scope/memory/plan 节点，准备计划在 executor 前 checkpoint；9 项新节点测试通过，定向回归 43 passed；规划已迁入，执行未迁入，详见 [Stage 5 报告](agent-runtime-stage-05-report.md) |
| Stage 6 纯 frontier/reducer | PASS | 五类 fixture 覆盖独立任务、a→b、a→c/b→d 且 b 失败、结果重放与 hash 冲突；旧 executor 与纯函数合成一致，详见 [Stage 6 报告](agent-runtime-stage-06-report.md) |
| Stage 7 LangGraph Send | PASS | MA06 native 由 Send fan-out 执行注册子图，旧计划 JSON 形状兼容；动态 Mock、并行屏障、依赖失败传播、产物回收与 Studio 四图可见门禁通过，详见 [Stage 7 报告](agent-runtime-stage-07-report.md) |
| Stage 8 LangGraph checkpoint 恢复 | PASS | native 子图与 Root 共用 SQLite saver，跨进程崩溃恢复、取消恢复、temporary/legacy 隔离门禁通过；详见 [Stage 8 报告](agent-runtime-stage-08-report.md) |
| Stage 9 | PASS | 安全 retry、checkpoint 手动 task retry、单次写入确认/恢复、取消栅栏通过；详见 [Stage 9 报告](agent-runtime-stage-09-report.md) |
| Stage 10 | PASS | 统一语义 Trace、动态 Agent UI 与只读 Runtime Debug 完成，详见 [Stage 10 报告](agent-runtime-stage-10-report.md) |
| Stage 11 | IMPLEMENTED / GATE PENDING | Alpha 合成验收、DeepSeek 本机凭据/真实请求、六项 Stage 0 债务修复和旧 SQLite 只读导出已完成；Python 全量 890 passed。真实 Beta/RC、两条未终态 legacy run、连续 CI 与回滚演练仍待完成；native 默认关闭。详见 [Stage 11 报告](agent-runtime-stage-11-report.md) |

**全量门禁基线与后续**：Stage 0 的干净基线复测命令 `python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short` 在干净基线为 751 passed、6 failed、1 deselected；Stage 6 后为 808 passed、同样 6 failed、1 deselected；Stage 7 后为 816 passed、Stage 8 后为 820 passed，均为同样 6 failed、1 deselected。六项当时完全复现 Canvas 参数 2 项和 grounded synthesis 引文语义 4 项，没有新增 Runtime 失败。Docker 专项在 daemon 29.8.0 上干净基线与工作树均为 1 passed、3 deselected；此前超时为环境问题。Stage 11 已在 Canvas 与 grounded-synthesis 工作流分别修复六项，历史基线记录不改写；当前完整 Python 门禁为 890 passed、1 deselected。

**Stage 11 复测（2026-09-28）**：任务书指定的完整 Python 命令为 890 passed、1 deselected；带 Docker 标记的专项先前为 1 passed、888 deselected。桌面端 test/build、Electron 合约、Tauri clippy/test/build 在本阶段此前已通过。40 条确定性 Agent 回归轨迹为 40/40、p50 0ms、p95 16ms，但它使用 scripted 边界，不是 native Multi-Agent Beta 或真实模型性能证据。本机 DeepSeek 凭据和最小真实请求已验证；旧 SQLite 状态已只读导出并完整性校验，但两条未终态 legacy run 仍需在 Stable 前处置。其余分项和阻碍见 [Stage 11 报告](agent-runtime-stage-11-report.md)。

## 1. 每阶段都必须遵守的边界

1. **一条生产执行链**：即时 API 和持久任务 API 都调用 `get_agent_runtime`；每个 run 只有一个 Root Graph 拥有最终交付。迁移期可以按 run 的 `graph_version` 选择旧/新拓扑，不能在同一 run 中让两套调度器都执行 specialist。
2. **旧 run 可恢复**：已有 checkpoint 的 `run_id = thread_id` 规则、严格序列化和写入重放防护保持有效。新开关只决定新 run，不在 resume 时改引擎。
3. **Tool 权限只在服务端决定**：AgentSpec 的允许清单要经过 `validate_task_plan`，实际调用走 `AgentToolRegistry`、`ProductAgentService` 和业务确认；不把 sandbox manager、MCP client 或原始工具函数直接传给 Agent 节点。
4. **Scope/Evidence/Memory 不重造**：复用 `AuthoritativeScopeResolver`、`CoordinatorMemoryPort`、Artifact Store、Evidence 校验；graph checkpoint 中的新增编排字段仅放标识、版本、状态和引用。不要把 PDF、向量、数据库句柄或大产物放入新增编排字段。
5. **语义事件稳定**：公开事件仍是 `AgentEvent`；保持 `run_id`、`trace_id`、`task_id`、`attempt`、`sequence`。不要让前端消费 LangGraph 内部 event 名。
6. **MCP 现状**：当前没有生产 MCP 接入。只准备统一 Tool 适配边界；除非另有明确产品需求，不在 Runtime 迁移中接入真实 MCP server。
7. **暂不清理用户数据**：不得删除 `config/agent_checkpoints.sqlite3`、运行记录、Artifact/Memory/Knowledge 数据库或用户未提交文件。旧表停写后仍应保留只读迁移/回滚期。

## 2. 执行协议（供每个后续开发任务直接使用）

一次只做一个 Stage。开始时先读该 Stage 所列文件、`git status --short` 与上一阶段记录；不要假定旧任务书里的文件都已存在。按“契约/纯函数 → 生产接线 → 测试 → 文档”顺序修改。新增测试先写能失败的输入与预期，再做实现；测试不能只断言 mock 被调用。凡涉及新图版本、数据库或写入，使用临时 SQLite 与合成资料，不碰用户现有库。

每阶段结束必须在 `docs/development/agent-runtime-stage-NN-report.md` 记录：HEAD/依赖版本、改动文件、开关状态、执行命令与通过/失败数量、失败是否在干净基线复现、性能/质量样本、回滚方式、未满足门禁。**只有全部本阶段门禁通过才能标记 PASS。** 定向测试通过但全量有未分类失败时标记 `IMPLEMENTED / GATE PENDING`。不要自动删旧路径来消除失败。

通用检查命令（Windows PowerShell，从 `D:\AITrans` 运行；没有 Docker 时先排除 Docker 标记并单独记录）：

```powershell
python -m ruff check backend/agent_core backend/agent_graph backend/api backend/services tests/agent tests/multi_agent
python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration"
cd apps/desktop
npm run lint
npm run test
npm run build
```

根据 Stage 的改动范围运行相应子集；全量命令用于发布门禁，不能用定向通过替代全量结果。没有前端改动时可省略前端命令。性能与真实模型测试另记，不把“未运行”写成“通过”。

## 3. 新旧任务书映射与依赖

| 新阶段 | 主要工作 | 对应旧 LG | 为什么改顺序 |
| --- | --- | --- | --- |
| 0 | 基线、七项失败分流、开关 | LG00 | 先知道真实基线，再比较迁移结果 |
| 1 | Agent Registry | LG01 | 已完成配置收敛 |
| 2 | 统一 Root Graph 工厂与 Studio 拓扑 | LG09 前移 | 新节点只在一个 builder 中增加，避免生产/Studio 两套图 |
| 3 | Tool、Sandbox 与未来 MCP 准入契约 | 新增 | Native worker 上线前封住绕权入口 |
| 4 | Root Graph 编排状态 | LG02 | 状态可序列化、可迁移后再拆节点 |
| 5 | 路由、Scope、Memory、Plan 节点 | LG03 | 移除黑盒节点里的权威规划 |
| 6 | 纯 frontier 与 reducer | LG04 前半 | 先用纯函数证明 DAG 语义一致 |
| 7 | LangGraph Send + 四个 specialist 子图 | LG04 后半 + LG05 | 一个阶段接线并验证动态 Agent 可执行 |
| 8 | 原生 checkpoint 与持久 run 对齐 | LG06 | 实测恢复后才切新 run 的执行权 |
| 9 | Retry、Timeout、Interrupt、写入安全 | LG07 | 恢复边界稳定后再统一异常路径 |
| 10 | 语义 Trace、动态 UI、Runtime Debug | LG08 | 调试页面直接消费收敛后的运行数据 |
| 11 | 分批启用、性能质量门禁、旧代码移除 | LG10 | 用清理截止条件结束兼容期 |

Stage 2–9 的 native 开关默认 `false`；开发测试可显式开启。Stage 11 才考虑调整默认。不要新建与 `RootAgentGraph` 平行的最终回答服务。

## Stage 0 — 基线锁定与失败分流

**当前状态**：Stage 0 已 PASS。`agent-runtime-lg00-baseline.md` 与 `agent-runtime-stage-00-report.md` 记录了干净基线对照；六项确定性失败随后已在 Stage 11 的 Canvas 与 grounded-synthesis 工作流修复，Docker 专项已通过。`AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` 默认仍为 `false`。

**文件**：修改 `docs/development/agent-runtime-lg00-baseline.md`；必要时新增 `docs/development/agent-runtime-stage-00-report.md` 和只读复测记录。只在确认属于 Runtime 契约问题时修改对应代码；Docker 不可用属于环境门禁，不靠改业务代码掩盖。

**步骤**：

1. 记录当前 `git rev-parse HEAD`、`git status --short`、Python/LangGraph/checkpoint 版本和所有开关值。保留现有未提交文件。使用独立干净检出复测七项失败，记录每项在 HEAD 与工作树的结果、异常首因及是否依赖 Docker；不可直接在当前工作树重置文件。
2. 复核合成 TaskPlan、TaskResult、`task_planned → task_started → task_completed` envelope 和 `a 成功 / b 中断 / 恢复只重试 b` fixture；时间戳与随机 ID 要标准化，不能把私人内容写入 fixture。
3. 给 Canvas 2 项、引文 4 项建立独立问题记录；若干净 HEAD 也失败，作为已知基线债务并指定最终发布前的解决门禁。若只在工作树失败，先定位并修复回归。Docker 测试只在 daemon 可用时单独运行。
4. 保证原 `AITRANS_MULTI_AGENT_ENGINE=typed|legacy|off`、`AITRANS_MULTI_AGENT_ROLLOUT=simple|single|workflow` 行为不变；native flag 关闭时仍走现有桥。

**验证**：

```powershell
python -m pytest -q tests/multi_agent/test_lg00_baseline_fixture.py tests/multi_agent/test_migration_switch.py tests/multi_agent/test_subgraph_checkpoint.py tests/agent/test_agent_checkpoint_persistence.py
python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short
python -m pytest -q tests/agent/test_python_execute_agent_integration.py -m docker_integration
```

最后一条只在 Docker daemon 健康时执行。**Gate**：干净基线与工作树的失败差异为零，新增失败为零；每个已知失败都有可复现证据、责任边界与解决时点。未复测的失败保持 `PENDING`，不得称为既有问题。

## Stage 1 — Agent Registry 配置收敛

**当前状态**：代码已实施，定向测试通过；全量门禁承接 Stage 0 的七项分流。不要重复实现同一 Registry。

**文件**：`backend/agent_core/orchestration/agent_registry.py`、`roles.py`、`planner.py`、`validation.py`、`backend/api/agent_dependencies.py`、`tests/multi_agent/test_agent_registry.py`。旧 `backend/agent_core/multi_agent/agent_registry.py` 仍属于 legacy 分支。

**核验步骤**：

1. `AgentSpec` 应给四个已有专业 Agent 稳定 ID、版本、capabilities、输入/输出 Artifact kind、默认/允许 Tool、graph factory、资源/重试/超时元数据。`RoleRegistry` 只做 `TaskRole → agent_id` 适配。
2. `ValidatedSupervisorPlanner` 只从新 Registry 取默认工具和输出类型；全文搜索确认没有 `_TOOLS_BY_ROLE`、`_OUTPUT_BY_ROLE` 的第二份生产映射。Provider 生成的计划仍由 `validate_task_plan` 在服务端校验 Scope 与 Tool。
3. 注册 `mock_data` 并验证 Planner 能发现能力；此阶段 `TaskSpec.role` 仍是枚举，Mock Agent 实际执行留到 Stage 7。`get_agent_runtime` 对四个已有图只构造一次 Registry。

**验证**：

```powershell
python -m pytest -q tests/multi_agent/test_agent_registry.py tests/multi_agent/test_supervisor_planner.py tests/multi_agent/test_plan_validation.py tests/multi_agent/test_migration_switch.py tests/agent/test_agent_lazy_dependencies.py
rg -n "_TOOLS_BY_ROLE|_OUTPUT_BY_ROLE" backend/agent_core/orchestration
```

`rg` 无匹配为预期。**Gate**：四个 Agent 的旧计划、工具权限与 Writer 产物选择语义不变；Mock 可注册/发现、越权 Tool 被拒；新增失败为零。已记录的定向结果为 352 passed（多 Agent 与相关 API/Graph/Trace 套件），全仓 PASS 仍取决于 Stage 0 分流。

## Stage 2 — 统一 Root Graph 构造与 Studio 拓扑（旧 LG09 前移）

**当前状态**：Stage 2 已 PASS。`factory.py` 是生产 `ReadingAgentGraph` 与 Studio 图共用的拓扑入口；12 个旧节点名、普通边、条件边及 durable/temporary 编译规则保持一致。Stage 2 定向套件 25 passed，native-off fixture 与 migration switch 12 passed。实施证据见 [Stage 2 报告](agent-runtime-stage-02-report.md)。

**目标**：后续新增节点只改一处 builder，Studio 与生产的节点/边一致；生产依赖依然由服务端注入。

**新增**：`backend/agent_graph/factory.py`、`tests/agent/test_root_graph_factory_parity.py`。

**修改**：`backend/agent_graph/reading_agent_graph.py`、`root_agent_graph.py`、`studio.py`、`backend/api/agent_dependencies.py`、`langgraph.json`（仅当 factory 路径改变）、`tests/agent/test_langsmith_studio_support.py`。

**代码任务**：

1. 从 `ReadingAgentGraph.__init__` 抽出一个 `build_root_graph(...)` builder，节点名、边、conditional route、持久/temporary compile 规则在同一函数定义；`RootAgentGraph` 仍是唯一生产类，`ReadingAgentGraph` 保留兼容 API。
2. `get_agent_runtime` 传生产 adapter、context provider、collaboration adapter、checkpointer；`studio.make_root_graph` 传 Studio 可构造的依赖，但调用同一 builder。保留 `langgraph.json` 的 `root_agent` 与 `reading_agent` 兼容别名。构图时不得连接 LLM、Qdrant、Docker 或读取凭据。
3. 写图签名测试：比较 Studio/生产的 node 名与边，包含条件边；比较临时图无 checkpointer、持久图有 checkpointer。不要只比较类名。测试两个工厂都不触发工具/模型调用。
4. 暂不增加新编排节点，暂不改变旧 checkpoint 节点名。为未来新增节点留 `factory` 入口；后续各阶段改这里，不再在 `studio.py` 复制拓扑。

**验证**：

```powershell
python -m pytest -q tests/agent/test_root_graph_factory_parity.py tests/agent/test_langsmith_studio_support.py tests/agent/test_root_agent_graph.py tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_lazy_dependencies.py
```

**Gate**：两个工厂签名一致，旧 `run_id` checkpoint 仍可恢复，`ReadingAgentGraph` 兼容调用通过；native flag 关闭时结果与 Stage 0 fixture 一致。回滚只需让 `get_agent_runtime` 与 Studio 恢复旧工厂接线，不迁移用户数据库。

## Stage 3 — Tool、Sandbox 与 MCP 准入契约

**当前状态**：Stage 3 已 PASS。新增 worker-only `ToolRuntimePort` 契约和 `ProductAgentToolRuntimePort` adapter；所有 worker Tool 通过服务端 task/Agent allowlist、authoritative scope、typed ToolSpec 与 `ProductAgentService`。服务器可注入 `TypedAgentToolDefinition`；请求体没有 Tool 注册字段。Sandbox Tool 仅由显式启用且健康的 manager 提供。指定验证 44 passed，Agent API 兼容测试 14 passed。详见 [Stage 3 报告](agent-runtime-stage-03-report.md)。

**目标**：任何新 specialist worker 都只能通过既有 typed Tool 边界调用外部能力。

**修改**：`backend/services/agent_tool_registry.py`、`product_agent_service.py`、`backend/agent_core/orchestration/validation.py`、`agent_registry.py`、`backend/api/dependencies.py`。按需要新增 `backend/agent_core/orchestration/tool_port.py`（只放接口，不执行 Tool）和 `tests/agent/test_native_tool_boundary.py`。

**代码任务**：

1. 定义 worker 的 ToolPort：输入 `run_id/task_id/agent_id/tool_name/typed arguments/scope_ref`，实现委托现有 `AgentToolRegistry` 和 `ProductAgentService`。先由 Registry 验证 Agent allowlist，再由 Tool spec 验证参数和业务确认；禁止 worker 自己调用 `definition.execute`、`SandboxManager` 或未来 MCP client。
2. 建立仅由服务端配置注入的外部 Tool definition 扩展点；检查重名、空名和 schema，禁止请求 payload 注册 Tool。真实 MCP 客户端暂不开发；未来 MCP capability 必须先适配为 `TypedAgentToolDefinition` 再走同一 ToolPort。
3. 保持 `AITRANS_SANDBOX_ENABLED` 控制 `python_execute/command_execute` 的注册。复用 `backend/agent_tools/sandbox.py`、`command.py`、`backend/sandbox/manager.py`、Sandbox approval/debug service；无 Docker 时工具不可用，不能回退到宿主机执行。
4. Trace 只存安全参数摘要：Python 代码 hash/长度、命令 argv hash/数量，不存原文；写工具继续要求一次性确认且不自动重试。保留 `/api/agent/tools` 和显式 execute 端点的旧响应。

**验证**：新增 `test_native_tool_boundary.py` 覆盖允许工具成功、未授权工具拒绝且 executor 未调用、伪造 scope 拒绝、重名外部定义拒绝、沙箱关闭时工具缺席、写入确认缺失拒绝、trace 不含代码/命令原文。随后运行：

```powershell
python -m pytest -q tests/agent/test_native_tool_boundary.py tests/agent/test_typed_tool_registry.py tests/agent/test_agent_tool_execution.py tests/agent/test_python_execute_tool.py tests/agent/test_command_execute_tool.py tests/agent/test_multi_step_write_safety.py
```

**Gate**：普通、Sandbox 和合成外部 Tool 都经过同一准入；无绕权调用路径；未引入真实 MCP 服务或第二个 Tool registry。此 Stage 只建立契约，不改变用户可见的工具列表默认值。

## Stage 4 — Root Graph 编排状态与版本契约

**当前状态**：Stage 4 已 PASS。Root checkpoint 持有 canonical Scope/Plan/TaskResult/ArtifactRef 与状态；legacy snapshot 从 canonical state 单向投影。MA01/MA03 raw checkpoint 先选图再迁移；新队列固定 engine/graph/schema。Store schema v5 为旧 run 加 engine 兼容列。实施与验证记录见 [Stage 4 报告](agent-runtime-stage-04-report.md)。

**目标**：TaskPlan、TaskResult、scope 和 artifact 引用进入 Root LangGraph checkpoint；只保留一份可写的编排状态。

**新增**：`backend/agent_core/orchestration/graph_state.py`、`tests/multi_agent/test_langgraph_orchestration_state.py`。

**修改**：`backend/agent_graph/reading_agent_graph.py`、`backend/agent_graph/factory.py`、`backend/agent_core/state.py`、`backend/agent_core/runtime.py`、`backend/agent_core/orchestration/reducer.py`、`backend/api/agent_dependencies.py`、`backend/api/agent_runtime_jobs.py`、`backend/services/agent_run_store.py`、`backend/models/agent_tasks.py`（只在序列化契约确需扩充时）、`backend/api/agent.py` 的 snapshot 投影、`tests/multi_agent/test_orchestration_state_compatibility.py`。

**代码任务**：

1. 在 `graph_state.py` 定义 Root 编排字段：`scope`（只含 ScopeContext 的 ID/版本/允许列表）、`memory_snapshot_ref`、`task_plan`、`task_results`、`task_status_by_id`、`frontier_task_ids`、`artifact_refs`、`orchestration_status`。Runtime Context 只放 event sink、control、服务实例；严禁序列化它们。
2. 给 `task_results` 配 LangGraph reducer，复用 `reduce_task_results`：同 `task_id + attempt_id + result_version + content_hash` 重放幂等，不同 hash 抛 `TaskResultConflictError`。为 artifact refs 和事件 ID 分别添加稳定去重 reducer；不同版本的 artifact 不能互相覆盖。
3. 新增单向 `project_orchestration_state`：从 Root canonical state 派生旧 `AgentState.orchestration_scope/plan/results` 和 `/api/agent/runs/{run_id}/snapshot` 响应。旧字段在兼容期仍可读，但新节点不再把它们当作另一份可写状态。`browser_context` 中旧 orchestration payload 仅用于旧 checkpoint 读取。
4. 明确新 `graph_version` 与 `state_schema_version`，在 `migrate_agent_state_payload` 添加仅针对已知旧版本的读取适配；未知/未来版本拒绝。**在状态迁移前**由 `get_agent_runtime`/持久任务 `_build_runtime` 读取 run store/checkpoint 的**原始** `graph_version` 并选择对应 builder；现有 `migrate_agent_state_payload` 会把旧版本值改写为当前版本，不能把改写后的字段用于选图。持久 run 在入队时就写入 `engine/graph_version/state_schema_version`（为旧表增加兼容列），不能等第一个 checkpoint 才记录；即时 run 从 checkpoint 元数据选择。Stage 5 增加新节点前必须让旧 run 固定旧拓扑，且新 run 的所选版本在创建时固定；Stage 8 再把这一机制用于 native 恢复和完整跨进程门禁。
5. 使用测试专用 SQLite checkpointer 做保存/加载往返；Root checkpoint 仅保存编排控制数据和引用，不保存 Artifact 内容或服务对象。现有 `AgentState` 已有用户输入，不能把这条新增字段限制误写成“整个 checkpoint 不含内容”。

**验证**：新测试至少覆盖字段往返、两路并行结果无覆盖、重复结果幂等、冲突抛错、Artifact 不同版本、旧 state 迁移、未知版本拒绝、snapshot 旧字段不变，以及“原始旧版本先选旧拓扑、已入队未执行的新 run 固定版本、环境开关变化不改版本、迁移后版本值不影响拓扑选择”。然后运行：

```powershell
python -m pytest -q tests/multi_agent/test_langgraph_orchestration_state.py tests/multi_agent/test_result_reducer.py tests/multi_agent/test_orchestration_state_compatibility.py tests/agent/test_agent_state_contract.py tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_api_runtime.py tests/agent/test_root_graph_factory_parity.py
```

**Gate**：checkpoint 读回计划与结果，API snapshot 契约兼容；旧 run 由原始版本选择旧拓扑，新 run 的版本选择不随环境开关变化；没有双向同步或两份 authoritative task 状态。native flag 关闭仍使用旧执行链。

## Stage 5 — Root 内显式路由、Scope、Memory、Plan 节点

**目标**：让 Root Graph 在 specialist 执行前持有权威计划；`run_collaboration` 不再在 native 路径中隐式重做 route/scope/memory/plan。

**新增**：`tests/multi_agent/test_root_planning_nodes.py`；若现有 service 抽取逻辑不清晰，可新增 `backend/agent_core/orchestration/planning_service.py`（只做规划，不调度或写入）。

**修改**：`backend/agent_graph/factory.py`、`reading_agent_graph.py`、`backend/services/research_orchestration_service.py`、`multi_agent_runtime_bridge.py`、`backend/api/agent_dependencies.py`、`backend/agent_core/orchestration/migration.py`。

**代码任务**：

1. 保持现有顺序中 `prepare_conversation` 在专业工作之前取得会话所有权。其后加入 `route_orchestration`，FAST 直接去原来的 `knowledge_access`；SINGLE/WORKFLOW 依次走 `resolve_scope → load_memory_snapshot → plan_tasks → validate_plan`。
2. 节点调用既有 `ResearchTaskRouter`、`AuthoritativeScopeResolver`、`CoordinatorMemoryPort`、`ValidatedSupervisorPlanner`、`validate_task_plan`；每个节点只返回自己的 state delta。`missing_information` 在计划前生成明确受阻结果，禁止启动 specialist。Scope 解析失败或 memory snapshot 已撤销时立即中止。
3. 将 `ResearchOrchestrationService.run` 拆为可接受已解析 route/scope/memory/plan 的薄 `execute_prepared(...)` 与旧兼容入口。native flag 为 true 时由 Root 节点规划，旧 executor 暂执行**同一份**已准备计划；不得再调用 `run()` 重复规划。flag false 仍走旧路径。
4. 计划一经 `validate_plan` 通过立即进入 Root checkpoint；record `plan_revision`、`scope_ref` 与 memory policy revision。resume 前重新核对撤销/权限，不把旧 snapshot 直接当有效来源。
5. Factory/Studio 同步新增这些节点；当前 old run 的旧 graph topology 继续可用，不把未完成旧 run 直接恢复到新节点名。

**验证**：新测试注入计数型 resolver/planner，证明 native 路径各只调用一次；FAST 0 个 specialist、SINGLE 1 task、WORKFLOW 合法 DAG、缺来源 0 tool call、Scope/Memory 失败不产生 Artifact。再运行：

```powershell
python -m pytest -q tests/multi_agent/test_root_planning_nodes.py tests/multi_agent/test_orchestration_routing.py tests/multi_agent/test_root_orchestration_integration.py tests/multi_agent/test_memory_revocation_resume.py tests/multi_agent/test_plan_validation.py tests/agent/test_agent_conversation_integration.py tests/agent/test_root_graph_factory_parity.py
```

**Gate**：native 路径计划只产生一次，Root checkpoint 在执行前可读到计划；旧路径开关关闭时保持 Stage 0 结果。此时 executor 仍是旧的，报告必须写明“规划已迁入，执行未迁入”。

## Stage 6 — 纯 frontier、依赖和 reducer

**目标**：先用可复现纯函数替换旧线程池内的 DAG 判定逻辑，再接 LangGraph `Send`。

**新增**：`backend/agent_core/orchestration/frontier.py`、`tests/multi_agent/test_frontier.py`、`tests/multi_agent/fixtures/native-frontier-cases.json`。

**修改**：`backend/agent_core/orchestration/reducer.py`、`task_state.py`、`parallel_executor.py`（仅提取/复用逻辑，旧行为不变）；为持久化新增 EvidenceRef 与 event fingerprint reducer，增加 `graph_state.py`、`reading_agent_graph.py` 和 `backend/agent_core/state.py` 的 Root 通道/兼容投影，结构版本递增到 5。新增 Root 通道仅保存引用和语义事件指纹，不保存事件原始 payload。

**代码任务**：

1. 抽取 `ready_tasks(plan, results, statuses)`，返回稳定排序的 ready task ID；每个 task 只在依赖完成后进入 frontier，不因无关 sibling 失败被阻断。
2. 抽取 `dependency_results(task, results)`；只投影声明的上游结果及 ArtifactRef，不传播其它任务的原始输出。`required` 上游失败将 descendant 标记 `BLOCKED`；可选失败产生 reason/warning，依任务契约决定继续。周期、未知依赖和重复 ID 仍由 `ValidatedTaskPlan`/验证器拒绝。
3. 把任务状态转移、attempt 递增、required/optional failure 语义写成无 IO 函数；不在 reducer 中访问数据库、LLM、Tool 或全局变量。
4. `reduce_task_results` 保留 hash 冲突规则；增加 ArtifactRef、EvidenceRef 和事件 ID 的去重/冲突规则，顺序稳定，适合并行 fan-in。Fixture 至少含独立 a/b、a→b、a→c 与 b→d 且 b 失败、重复回放、冲突 hash。
5. 将旧 `ParallelTaskGraphExecutor` 的合成结果与新纯函数逐项比对，测试中不以 sleep 判断并发。

**验证**：

```powershell
python -m pytest -q tests/multi_agent/test_frontier.py tests/multi_agent/test_result_reducer.py tests/multi_agent/test_parallel_scheduler.py tests/multi_agent/test_task_state.py tests/multi_agent/test_plan_validation.py
```

**Gate**：五类 fixture 的任务状态和结果与旧 executor 一致；相同结果重放幂等、不同 hash 明确失败；生产 flag 两种值都未改变执行路径。本阶段报告附输入、输出和差异表。

## Stage 7 — LangGraph Send 与动态 specialist 子图

**目标**：native 路径由 Root Graph 的 `Send + reducer` 执行专业任务；四个现有图和 `mock_data` 均通过 Registry 装配。

**新增**：`backend/agent_core/orchestration/specialist_adapter.py`、`backend/agent_core/orchestration/resource_manager.py`（若需要将旧全局并发配额抽出）、`tests/multi_agent/test_native_send_dispatch.py`、`tests/multi_agent/test_dynamic_mock_agent_execution.py`。

**修改**：`backend/agent_graph/factory.py`、`reading_agent_graph.py`、四个 `backend/agent_graph/*_graph.py` 专业图、`backend/agent_core/orchestration/agent_registry.py`、`backend/models/agent_tasks.py`、`backend/agent_core/orchestration/planner.py`、`validation.py`、`backend/api/agent_dependencies.py`。

**代码任务**：

1. 新增 `dispatch_frontier → specialist node(s) → advance_frontier → finalize_task_graph`。Factory 按已注册 `agent_id` 生成稳定 node 名并挂载对应 `graph_factory` 的真实 compiled subgraph；`Send` 只给 ready tasks 发单任务输入。不要在 worker 再维护 `ThreadPoolExecutor/Future/FIRST_COMPLETED` 循环。
2. 建立统一 child 输入/输出 adapter：输入为 TaskSpec、已验证 ScopeContext、该任务依赖结果、按角色投影的 memory 和运行预算；输出为 `TaskResult` 与 ArtifactRef。Artifact 内容仍在现有 store，Root state 只收引用。四个专业图内部的验证、Evidence 和 Artifact hash 逻辑保留，不为每个图新建 SQLite checkpointer。
3. 扩展 `TaskSpec` 为向后兼容的 `agent_id` 契约：旧 JSON 有 `role` 时派生对应 `agent_id`；新 Agent 可用 `agent_id` 且不必伪装为四种 `TaskRole`。校验 `role/agent_id` 一致性、未知 Agent、Tool allowlist、输入/输出 kind 和 Scope。flag false 的旧 executor 仅接受四种 legacy role；不能让 Mock 任务落到它。
4. 使用 `AgentSpec.resource_class` 与现有 `ParallelExecutionPolicy` 语义实现并发/预算：普通 specialist 同时最多 2 个，GPU 资源同一时间最多 1 个；模型/Tool/检索硬预算仍是共享的，超预算要返回明确 blocked/failure。数值变化必须另做基准，不因迁移偷偷放宽。
5. 同类型 Document task 以不同 `task_id` 并行，结果按 ID 合并；依赖 Research 在其 Document 全部完成后才启动。`mock_data` 在测试里注册一个最小 compiled subgraph，无需改 scheduler、checkpoint runtime 或前端角色常量即可执行（前端显示在 Stage 10 验收）。
6. native flag true 的新 run 只走 `Send`，不调用 `ParallelTaskGraphExecutor.execute`；flag false 仍走旧 executor。禁止同一 run 并行执行两个引擎作为 shadow 对照；影子对照只比无副作用的计划/状态或离线 fixture。

**验证**：新测试用 barrier/event 证明两个独立 worker 同时进入，不靠耗时阈值；a→b 严格等待；`a→c, b→d` 中 b 失败得到 `a/c=SUCCEEDED,b=FAILED,d=BLOCKED`；Mock 图被调用一次；Tool 越权与 Scope 越界在图启动前拒绝。随后运行：

```powershell
python -m pytest -q tests/multi_agent/test_native_send_dispatch.py tests/multi_agent/test_dynamic_mock_agent_execution.py tests/multi_agent/test_parallel_scheduler.py tests/multi_agent/test_document_analyst.py tests/multi_agent/test_research_synthesizer.py tests/multi_agent/test_academic_writer.py tests/multi_agent/test_knowledge_curator.py tests/multi_agent/test_artifact_verification.py tests/multi_agent/test_evidence_scope.py tests/agent/test_root_graph_factory_parity.py
```

**Gate**：native run 完全不调用旧线程池调度；四图的 Artifact/Evidence/Scope 契约通过；Mock Agent 可被计划与执行；Studio 可见四个真实子图。此阶段尚不能宣称生产级恢复，默认开关保持关闭。

## Stage 8 — LangGraph checkpoint 接管专业任务恢复

**目标**：新 native run 的 task frontier、结果和子图进度由同一个 LangGraph checkpointer 恢复；`AgentRunStore` 继续管理队列/租约，不与 checkpoint 争夺任务状态。

**修改**：`backend/agent_graph/factory.py`、`reading_agent_graph.py`、`backend/agent_core/runtime.py`、`state.py`、`backend/services/agent_checkpoint_service.py`、`agent_run_store.py`、`agent_run_worker.py`、`backend/api/agent_runtime_jobs.py`、`backend/api/agent_dependencies.py`、`backend/agent_core/orchestration/migration.py`、`parallel_executor.py`、`agent_registry.py`、`specialist_adapter.py` 和四个 specialist graph。新增 `tests/integration/test_native_agent_crash_recovery.py`、`tests/multi_agent/test_native_subgraph_checkpoint.py` 与 `tests/agent/test_native_checkpoint_store_selection.py`。

**代码任务**：

1. 新 run 创建时一次性固定 `graph_version/state_schema_version/engine`，连同 `run_id` 存入持久 run 记录；`run_id` 始终是 LangGraph `thread_id`。恢复先读版本，再选兼容拓扑；不得因环境变量变化把旧 run 恢复到新 graph。未知版本明确拒绝，不静默从头运行。
2. native Root 与子图共用 `AgentCheckpointService` 的 SQLite saver。验证安装版本的 per-invocation subgraph 持久化；如实际语义不同，先调整图构造与测试，不能给每个 specialist 建独立数据库。保留严格 `JsonPlusSerializer` 与 WAL/busy_timeout。
3. native run 不再写 `SQLiteTaskCheckpointStore` 作为恢复依据；可以在测试/诊断中只读比较旧 fixture，但禁止生产双写任务状态。旧 run 的原 checkpoint/TaskCheckpointStore 仍可走旧 engine 恢复，直到其终态。
4. `AgentRunStore` 的 `queued/running/paused/waiting/completed`、worker lease、heartbeat 和请求/结果记录继续保留；它不是专业 task checkpoint，不得在本次清理中删除。`agent_runtime_jobs._build_runtime` 与即时 API 仍调用同一工厂。
5. 对 crash 进行真实进程边界测试：`document-1/2` 成功、`document-3` 执行中断、research 未开始；新进程恢复只执行 `document-3`，Research 等待其完成。验证并行 sibling pending writes、相同结果 replay、取消后恢复、temporary run 不写持久 checkpoint 或持久 Artifact。
6. 写 Tool 在副作用结果未知时必须停在 `write_checkpoint_requires_manual_recovery`/等价安全状态；恢复不能自动重放。API snapshot 的旧字段继续由 Stage 4 投影。

**验证**：

```powershell
python -m pytest -q tests/integration/test_native_agent_crash_recovery.py tests/multi_agent/test_native_subgraph_checkpoint.py tests/multi_agent/test_subgraph_checkpoint.py tests/multi_agent/test_temporary_workflow.py tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_write_recovery.py tests/agent/test_agent_run_store.py tests/agent/test_agent_runtime_scheduler.py tests/integration/test_agent_crash_recovery.py tests/integration/test_agent_runtime_concurrency.py tests/integration/test_agent_write_crash_recovery.py
```

**Gate**：新 native run 不依赖旧 TaskCheckpointStore 就能跨进程恢复；成功任务不重跑、未知写入不重放、临时 run 无持久 task/Artifact；旧 run 仍按原版本恢复。只有此 Gate 通过，Stage 11 才能让真实新 run 采用 native。回滚按 run 版本路由，不能通过改环境变量强制改正在运行的 run。

**结果**：Stage 8 Gate 通过，定向测试 45 passed；`tests/agent/test_native_checkpoint_store_selection.py` 另有 2 passed。详见 [Stage 8 报告](agent-runtime-stage-08-report.md)。

## Stage 9 — Retry、Timeout、Interrupt 与确认写入

**目标**：将执行层的重试、暂停和人工确认归于 Root/子图，同时保留原业务写入权限。当前安装的 LangGraph 1.2.11 有 `RetryPolicy` 与 `TimeoutPolicy`；使用前以本仓测试验证它们在子图与同步节点上的实际行为。

**修改**：`backend/agent_graph/factory.py`、`reading_agent_graph.py`、`knowledge_curator_graph.py`（只涉及草稿输出，不增加直接写入）、`backend/agent_core/reliability.py`、`runtime.py`、`backend/services/product_agent_service.py`、`agent_tool_execution_service.py`、`agent_run_store.py`、`backend/api/agent_runtime_jobs.py`。新增 `tests/multi_agent/test_native_retry_interrupt.py` 和 `tests/integration/test_native_write_recovery.py`。

**代码任务**：

1. 建立错误分类表：provider 5xx/网络瞬断/安全的只读超时可重试；Scope、权限、预算耗尽、Artifact 验证失败、用户取消、写入效果未知不得自动重试。只给符合 `AgentToolRegistry.allows_safe_retry` 的动作安装 `RetryPolicy`；节点超时与 `AgentRunControl` 总预算要取更严格者，避免双重无限重试。
2. 手动 task retry 在 Root 恢复分支重开目标和受影响 descendant，保留成功且独立的 sibling；attempt ID/ordinal 递增。retry 前再次校验 Scope 版本、来源是否撤销、Artifact 引用和 Memory policy。
3. `KnowledgeCuratorGraph` 目前只生成 draft，不能把它改成自动保存。真正写入沿用 ProductAgentService/既有 commit 边界：在调用前 `interrupt` 等待用户确认，确认只授权一次具体工具/参数/目标；拒绝后标记取消/失败。使用现有 `AgentRunStore` 一次性确认记录，resume 后清空旧 `confirmed_write_tools`。
4. 在 checkpoint 等待确认时跨进程重启，仍保持 WAITING；审批与拒绝都要有可追溯事件。若副作用已开始但结果未知，保持人工恢复阻断，不能凭 checkpoint 直接重放。
5. 取消传播到 active subgraph，fencing 晚到的模型/Tool/Artifact 结果；取消后不得提交 final successful delivery、Knowledge 写入或 Memory candidate。保留现有会话所有权释放逻辑。

**验证**：新测试覆盖 transient 恰好重试到上限、业务错误 0 retry、手动 retry 只重跑目标+descendant、审批后只写一次、拒绝 0 写入、进程重启仍 WAITING、未知写入被挡、取消后的 late result 不可见。运行：

```powershell
python -m pytest -q tests/multi_agent/test_native_retry_interrupt.py tests/integration/test_native_write_recovery.py tests/multi_agent/test_commit_idempotency.py tests/multi_agent/test_cancellation_fencing.py tests/multi_agent/test_run_lease.py tests/agent/test_agent_pause_resume.py tests/agent/test_agent_write_recovery.py tests/agent/test_multi_step_write_safety.py tests/integration/test_agent_write_crash_recovery.py
```

**Gate**：自动 retry 只发生在安全动作，确认不跨 run/attempt 泄漏，取消/未知写入无重复副作用。人工确认和 pending write 测试未通过时不能启动 native beta。

**结果**：Stage 9 Gate 通过。任务书列出的验收组 24 passed、2 warnings；另加 `tests/agent/test_agent_runtime_scheduler.py`（包含 worker 总预算超时取消回归）后，合并运行 40 passed。详见 [Stage 9 报告](agent-runtime-stage-09-report.md)。native 默认开关仍关闭。

## Stage 10 — 统一语义 Trace、动态 Agent UI 与 Runtime Debug

**目标**：前端显示真实 Agent/任务进度；Settings 增加独立 Runtime Debug 页面，复用既有观测与运行记录，不复制 RAG 或 Sandbox 调试库。

**后端新增**：`backend/api/agent_catalog.py`（或在 `agent.py` 加只读路由）、`backend/api/agent_runtime_debug.py`、`backend/models/agent_runtime_debug.py`、`tests/api/test_agent_runtime_debug_api.py`。只读接口建议为 `GET /api/agent/catalog`、`GET /api/agent/runtime/debug/runs`、`GET /api/agent/runtime/debug/runs/{run_id}`；最终路径以路由冲突检查为准，记录到 API 契约。

**后端修改**：`backend/agent_core/events.py`、`backend/models/agent_tools.py`、`backend/services/agent_trace_store_service.py`、`agent_run_store.py`、`backend/api/agent.py`、`agent_observability.py`、`agent_runtime_jobs.py`、`backend/services/multi_agent_runtime_bridge.py`（兼容期事件映射）。

**前端新增**：`apps/desktop/src/features/settings/RuntimeDebugStudio.tsx`、`RuntimeDebugStudio.test.tsx`、`apps/desktop/src/api/agent-runtime-debug.ts` 及 API test。

**前端修改**：`apps/desktop/src/features/settings/SettingsWorkspace.tsx`、`RagDebugStudioTrace.tsx`（仅关联 run 链接）、`apps/desktop/src/features/agent/components/TaskExecutionPanel.tsx`、`AgentTimeline.tsx`、`apps/desktop/src/features/agent/timeline/agent-timeline.ts`、`apps/desktop/src/features/agent/state/agent-workspace-state.ts`、`apps/desktop/src/api/agent.ts`、`agent-runtime.ts`。按需复用 `SandboxDebugStudio.tsx` 的链接组件。

**代码任务**：

1. `AgentEvent` 扩展可选 `agent_id/agent_version/node_name/subgraph_path`，不改旧 event type。节点事件映射成 `task_planned/started/completed/failed`、artifact、budget、pause/resume 等语义事件；同一 run 的同步响应、WebSocket、`AgentTraceStoreService`、`AgentRunStore` 使用一致的 event ID/sequence。跨 store 合并时按稳定 ID 去重，不按时间戳猜顺序。
2. Catalog 从 AgentRegistry 返回安全的 ID、显示名、描述、capabilities、版本和图标 key；不返回 graph_factory、Tool 执行函数、prompt 或凭据。Task 面板从 Catalog 取名称/图标，移除 `roleLabels` 四角色常量；Catalog 暂不可用时显示 `agent_id` 文本，不假装其它角色正在运行。
3. Runtime Debug API 从既有 run store、trace store 与安全 snapshot **投影**构造 DTO：route/计划、任务依赖、尝试、节点耗时、工具名、ArtifactRef、失败/恢复原因、关联 RAG/Sandbox ID。不要把 `/api/agent/runs/{run_id}/snapshot` 中的原始 Artifact 内容直接透传给新页面；在服务端剔除 prompt、原文、完整工具参数、checkpoint payload、路径和密钥。不存在或未持久化的字段显示“未记录”，不得补零或猜测。
4. Settings 新增 **Runtime Debug** 独立入口；列表按 run 选择，详情有任务 DAG/时间线、错误与重试、工具及产物引用、关联调试入口。`RAG Debug Studio` 仍保留原六个检索 tab，只在有可信 `run_id` 时提供“查看 Runtime”链接；Sandbox Debug 保持独立。页面默认只读，重试/确认按钮若提供必须调用 Stage 9 的既有 API，不能直接改数据库。
5. React 组件区分 Agent、Tool 和共享 Language capability；显示真正运行中的 Agent instance。同一 `agent_id` 的两个 Document task 按 `task_id` 分开。等待确认、部分失败、取消、恢复都有单独状态。

**验证**：API test 注入含“private text”、“API key”、“raw Python code”的事件与 Artifact，断言 DTO/JSON 均不出现；事件序号单调且多 store 无重复。前端 test 用 Mock Agent Catalog 验证无需改角色映射即可显示名称、状态、依赖、尝试和结果；无 run ID 不显示关联跳转。运行：

```powershell
python -m pytest -q tests/api/test_agent_runtime_debug_api.py tests/agent/test_agent_trace_event_contract.py tests/agent/test_agent_observability.py tests/multi_agent/test_task_events.py tests/agent/test_agent_api_runtime.py
cd apps/desktop
npm run lint
npm run test
npm run build
```

**Gate**：Runtime Debug 用现有存储、服务端脱敏、无第二套 trace DB；RAG/Sandbox 页面仍可用；Mock Agent 在真实 Task 面板和 Runtime Debug 中可见。前端不得依赖 LangGraph 私有事件名。

**结果**：Stage 10 Gate 通过。后端验收组 **168 passed、2 warnings**；desktop 全量测试 **423 passed**，测试类型检查通过；lint 退出码 0（37 条现有告警）；生产构建及 PDF.js 离线资源检查通过。`git diff --check` 通过。native 默认开关仍关闭；Stage 11 未开始。详见 [Stage 10 报告](agent-runtime-stage-10-report.md)。

## Stage 11 — 分批切换、质量门禁与旧路径退役

**目标**：native 成为新 run 的唯一默认执行路径，并结束维护两套专业任务调度器的兼容期。

**修改候选**：`backend/agent_core/orchestration/migration.py`、`parallel_executor.py`、`serial_executor.py`、`roles.py`、`backend/services/multi_agent_runtime_bridge.py`、`multi_agent_workspace_service.py`、`research_orchestration_service.py`、`backend/api/agent_dependencies.py`、`backend/agent_graph/factory.py`、`backend/agent_core/state.py`、`backend/models/agent_tasks.py`、`langgraph.json`、`docs/architecture.md`、`docs/agent-production-runtime.md`、`docs/repository-structure.md`、`.github/workflows/ci.yml`。**按消费者审计结果逐文件处理；此列表不是批量删除授权。**

**切换步骤**：

1. **Alpha**：开发环境显式 `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT=true`；先跑 FAST 与 SINGLE。收集 `run_id`、graph version、成功/失败、Scope、Artifact、恢复、事件完整性。不碰默认值。
2. **Beta**：只让新 SINGLE run 采用 native；旧 run 按版本继续旧引擎。真实模型/检索按固定数据集、相同版本和预算比较 baseline/native；记录样本量、p50/p95、Tool/模型调用、任务重跑数、Artifact 验证、失败原因。
3. **RC**：WORKFLOW 也转 native；跑至少两个 Document 并行、研究 fan-in、Writer/Curator、取消、写入确认、跨进程恢复。避免对同一输入同时执行两套产生副作用的任务作为在线 shadow。
4. **Stable**：Stage 0 的确定性债务已解决或经正式隔离且本阶段所有 Runtime 门禁绿灯后，才调默认值。记录最后一个 legacy run、旧 checkpoint 数、回滚策略与备份验证。
5. **Cleanup**：审计 `rg` 调用者与 CI；停止新写 `multi_agent_task_runs/multi_agent_task_checkpoints`，移除 `ParallelTaskGraphExecutor`、旧协作桥和关键词 planner 的生产接线。旧表及旧 run checkpoint 保留只读恢复/导出窗口，不能直接删用户数据。旧 `backend/agent_core/multi_agent/agent_registry.py` 与 `app/agent/*` 只有确认无生产消费者、测试用途已替代后才移除；若有消费者，记录单独迁移任务。
6. `AgentRunStore`、`AgentRunWorker`、run lease/heartbeat **继续保留**：它们管理持久任务生命周期，不是待删除的第二个 specialist scheduler。`TaskRole` 兼容字段仅在新旧 JSON/DB 已有读取适配并通过迁移测试后退役。

**退出兼容期的硬条件**：没有非终态 legacy run；旧 checkpoint 可只读恢复或已提供用户可见导出；两次连续 CI 通过；全部确定性/写入安全门禁通过；Alpha/Beta/RC 报告有真实观测；回滚演练成功。条件未满足时记录阻碍，不能删除兼容代码；兼容期最多跨两个正式发布版本，超出须明确列出未终态 run 和解决计划，不能无限期保留双体系。

**验证命令**：

```powershell
python -m pytest -q tests/agent tests/multi_agent tests/integration tests/api -m "not docker_integration"
python scripts/run_agent_regression_benchmark.py --report test-results/agent-regression-native.json
python scripts/run_agent_literature_synthesis_regression.py --report test-results/agent-literature-native.json
cd apps/desktop
npm run lint
npm run test
npm run build
```

有 Docker 的 CI 单独运行 `docker_integration`；桌面 shell 按 `.github/workflows/ci.yml` 的 `tauri_shell` job 跑 cargo fmt/clippy/test/build。真实模型质量评估使用 `scripts/run_agent_quality_evaluation.py` 的 CI 参数，固定模型、数据集、配置、seed 和报告路径；未配模型不能标记质量 PASS。

**量化 Gate**：Scope 越界、重复写入、取消后成功交付均为 0；确定性回归用例通过率不低于 baseline；同数据集的 Artifact 验证通过率不下降；各 lane 至少 30 个可复现样本，native p95 不超过 baseline 的 1.20 倍（固定硬件/模型/语料并报告方差）。若真实模型方差或外部服务使对比无效，标记 PENDING 并补测，不能填假数据。最终 full Python/desktop/Tauri CI 全绿后标记 COMPLETE。

## 4. 跨阶段最小验收矩阵

| 风险 | 必须有的合成场景 | 首次引入阶段 | 最终验收证据 |
| --- | --- | --- | --- |
| 路由 | 普通聊天/翻译 FAST，单文档 SINGLE，多文档 WORKFLOW，缺来源拒绝 | 5 | Root 计划与事件快照 |
| Scope | 跨 workspace 文档、撤销 note、伪造 scope_ref 均拒绝 | 3、5 | 服务调用次数为 0、无 Artifact |
| Tool | Agent allowlist、typed schema、Sandbox disabled、外部定义重名、写确认 | 3 | executor 未调用与安全 trace |
| 并行 | a/b 同时进入，a→b 等待，b 失败只阻断 d | 6、7 | barrier 测试和确定性结果 |
| Artifact | kind、hash、版本、lineage、EvidenceRef、越界来源 | 4、7 | 无冲突覆盖、验证报告 |
| Memory | 冻结 snapshot、撤销拒绝、temporary 不写长期记忆 | 5、8 | 恢复前后 scope/memory revision |
| 恢复 | 两项成功一项中断，重启仅恢复中断任务 | 8 | 新进程 SQLite 测试 |
| 写入/取消 | 未知副作用阻断、一次确认一次写、取消晚到结果拒绝 | 8、9 | 持久 store + 图双侧断言 |
| 动态 Agent | `mock_data` 注册→计划→执行→恢复→UI | 1、7、8、10 | 不改 scheduler/checkpointer/角色映射 |
| Trace | 即时/持久流同 ID/序号，调试响应无原文 | 10 | API 与 React 测试 |
| 回滚 | 旧 run 按旧版本恢复，新 run 可退回旧 engine | 8、11 | 双版本 fixture 与演练记录 |

## 5. 最终完成定义

以下全部成立才可宣布 Agent Runtime 重构完成：

- [ ] 生产只有一个 Root Graph 拥有每个 run 的最终交付；即时与持久入口使用同一构造工厂。
- [ ] Native Root 中可见 route、Scope、Memory、Plan、dispatch、四个 specialist 子图、recovery、finalize；Studio 节点/边一致。
- [ ] `Send + reducer` 替代生产 `ParallelTaskGraphExecutor`，新 native run 只依赖 LangGraph checkpoint 恢复专业任务。
- [ ] `AgentRunStore` 继续负责排队/租约，checkpoint 只负责图执行状态，两者按 run ID/graph version 对齐。
- [ ] Tool、Sandbox、未来 MCP 统一走 typed Tool 权限/确认/trace 边界；没有直接外部执行后门。
- [ ] Artifact/Evidence/Scope/Memory 的原有验证和撤销语义保持；失败、取消、未知写入效果不产生越权或重复副作用。
- [ ] Mock Agent 可被计划、执行、跨进程恢复、在 UI 展示；无 scheduler、checkpoint runtime、前端 role map 源码改动。
- [ ] Runtime Debug 独立入口可按 run ID 看安全的任务/事件数据，并能关联 RAG/Sandbox；不新增运行真相库。
- [ ] Stage 0 的七项失败已归因并按最终门禁处理；full CI、质量与性能记录齐全。
- [ ] 没有非终态旧 run；旧执行器与桥的生产接线已移除，用户历史数据保留安全读取路径。

每个后续开发任务的交付说明只需引用“Stage N”、本阶段报告和本任务书对应小节；若实际代码与文档不符，先更新文件清单与测试门禁，再写代码。

## 6. 给 GPT-6 Luna 的单阶段执行模板

后续每次只下发一个 Stage，可直接复制以下指令并替换编号；不要把 Stage 2–11 一次性交给同一个短任务，也不要把上阶段未通过的 Gate 默认为通过。

```text
请在 D:\AITrans 完成《docs/development/Agent Runtime重构任务书.md》的 Stage N，仅限该阶段。
先阅读该 Stage、影响分析报告、上一阶段报告和 AGENTS.md（如有），检查当前 Git 状态并保留已有修改。
逐项实现本阶段列出的文件和代码任务；需要调整文件清单时先说明依据。保持 native 开关默认关闭，不让新旧调度器在同一 run 中同时执行。
按本阶段“验证”逐条运行测试；记录真实命令、通过/失败/跳过数量，不能把未运行写成通过。新增或修改测试必须覆盖任务书所列边界场景。
把结果写入 docs/development/agent-runtime-stage-NN-report.md：修改文件、接口/状态迁移、测试结果、已知失败与干净基线比较、回滚办法、Gate 的 PASS 或 IMPLEMENTED / GATE PENDING。
完成后只汇报本阶段，不自行进入下一阶段；若 Gate 未通过，先修复本阶段可修复的问题并明确剩余阻碍。
```

进入下一阶段前，先复核上一阶段报告、对应代码和本书的依赖顺序；若代码现状与报告冲突，以代码与可复现测试为准并更正文档。
