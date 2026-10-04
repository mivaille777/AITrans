# LG01 Agent Registry 实施记录

> 2026-09-27；基于 [重构影响分析](agent-runtime-refactor-impact-analysis.md) 和 [LG00 基线](agent-runtime-lg00-baseline.md)。

## 已实施

- 新增 `backend/agent_core/orchestration/agent_registry.py`：不可变 `AgentSpec` 包含稳定 ID、版本、能力、输入/输出 Artifact 类型、允许与默认工具、graph factory，以及资源类别、`retry_policy`、`timeout_policy`。`AgentRegistry` 支持确定性列举、注册、查询和服务端工具校验；默认注册 Document、Research、Writer、Curator 四个专业 Agent。
- `RoleRegistry` 成为 `TaskRole → agent_id` 兼容适配器。其旧公开 API 保留，允许工具清单已迁入 Agent Registry。旧 `backend/agent_core/multi_agent/agent_registry.py` 仍用于 legacy 协作分支，两者未互相调用。
- `ValidatedSupervisorPlanner` 从 Agent Registry 读取默认工具和输出类型，移除 `_TOOLS_BY_ROLE`、`_OUTPUT_BY_ROLE`。Writer 的 outline/revision 选择也由对应 `AgentSpec` 管理。Planner 暴露 `available_agents()` 和 `resolve_agent()` 供后续能力规划使用。
- 生产 `get_agent_runtime` 把现有四个 specialist graph 注册到同一 Registry，并将该 Registry 传给 Planner。执行仍由现有 `ParallelTaskGraphExecutor` 负责，最终回答仍由 Root Graph 交付。
- LG00 新增默认关闭的 `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` 解析契约；LG01 未启用 native 执行分支。现有 engine/rollout 开关保留。

## 验收结果

| 项目 | 结果 |
| --- | --- |
| 四种既有专业 Agent 的计划和工具权限 | 通过；单任务计划使用注册的默认工具与输出类型 |
| Mock Agent 动态注册 | 通过；Planner 能列出/解析 `mock_data`，无需改 Scheduler |
| 越权 Tool 请求 | 通过；Registry 拒绝未授权工具，`validate_task_plan` 的原有校验仍生效 |
| 旧迁移开关与默认行为 | 通过；native 开关默认关闭，typed/single 保持原值 |
| LG00 snapshot fixture | 通过；TaskPlan、TaskResult、事件 envelope 与基线一致 |
| 任务书要求的核心兼容套件 | 90 passed，1 warning，10.26s |
| `tests/multi_agent` 与定向 Agent API/Graph/Trace 测试 | 352 passed，2 warnings，19.69s（最终改动后） |
| Python lint（改动文件） | Ruff 通过 |

全量 `tests/agent tests/multi_agent` 运行结果是 **758 passed、7 failed、2 warnings**。七项失败分别属于 Canvas 请求参数（2）、grounded synthesis 引文覆盖率断言（4）和 Docker daemon 超时（1）；涉及的服务代码不在本次改动文件中。它们未在干净 `HEAD` 上另行复测，因此不能据此宣称全仓质量门禁通过，也不能仅凭本次运行将其正式定性为既有失败。Docker 集成测试依赖可用 daemon。LG01 的定向功能门禁通过，全仓门禁仍需单独处理这七项。

## 边界与下一阶段

`TaskSpec.role` 仍是 `TaskRole` 枚举，Mock Agent 本阶段只能注册并被 Planner 发现，不能生成可执行的 `TaskSpec`。这是任务书 LG01–LG05 的兼容安排；LG02 应把 `agent_id` 与计划/结果纳入 Root State，后续再做真正动态调度。LG01 没有修改 RAG、Sandbox、Trace、前端页面或 checkpoint 存储。Runtime Debug 页面按影响分析在 LG08 建设。
