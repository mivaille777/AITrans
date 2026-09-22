# Knowledge Auto Routing 基线

本文件记录 Knowledge Auto Routing & Agentic RAG 任务在 K0 阶段的实际基线。

## 版本与范围

- 分支：`WebReBuild`
- 基线提交：`ff448bd820594e1b1140e9c87beff9c395a2940d`
- 远端：`mivaille777/AITrans`
- 任务书：`AITrans_Knowledge_Auto_Routing_Agentic_RAG_开发任务书.md`

任务书中的需求是本次开发的验收依据；本文件只记录当前代码事实，不改变业务行为。

## 已确认的现状

1. Reading 请求可以携带冻结的 `source_text`、文档元数据和上下文窗口。
2. Markdown/PDF selection actions 已在基线提交中恢复。
3. Agent Runtime、Runtime Event/Timeline 和 Agent Tool Catalog 已可用。
4. `backend/api/agent.py` 会把选中的 Research Workspace 转换为可信知识范围。
5. 空 Research Workspace 使用 `__workspace_empty_scope__:<kind>:<workspace_id>` sentinel，避免空列表退化成全局搜索。
6. Chat/Companion 仍以 `knowledge_enabled: boolean` 表达知识访问意图。

## K2.1 回归夹具

夹具定义于 `tests/agent/fixtures/knowledge_auto_routing_cases.json`：

```text
Reading document = doc-A
Active Research Workspace = workspace-X
workspace-X documents = []
```

用户请求为“基于当前 Reading Context 分析这篇论文的方法”。在 K0 基线中，API 层仍将已选 Workspace 视为权威范围，因此会得到空 Workspace sentinel；这正是后续 K2.1 要修复的 Reading/Research Scope 耦合。

显式 Research 任务必须继续得到空 Workspace sentinel，不能因为修复 Reading 路径而放宽权限。

## 基线验证

```powershell
python -m pytest -q tests/agent/test_research_workspace_stage16.py tests/agent/test_agent_context_isolation.py
```

结果：`14 passed`。

