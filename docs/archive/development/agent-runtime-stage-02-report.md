# Agent Runtime Stage 2 实施报告

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-28  
任务书：`Agent Runtime重构任务书.md` · Stage 2 统一 Root Graph 构造与 Studio 拓扑  
工作树 HEAD：`824236e00cfb44d4353558572331e4154de688d4`（本阶段未提交）

## 结果

**PASS。** 生产 `RootAgentGraph` 与 LangSmith Studio 的 `make_root_graph` 共用 `ReadingAgentGraph` 调用的 `build_root_graph`。图签名测试比较了全部节点、普通边、条件边及条件分支标签；没有新增或改名 checkpoint 节点。持久图继续使用注入的 checkpointer，临时图仍不带 checkpointer。

Studio 现在以延迟依赖包装产品 Agent 与 conversation service。构图不会调用服务 getter；测试将这些 getter 替换为立即失败的函数后，Studio 与生产图均可构建。Studio 兼容别名 `make_graph` 与 `langgraph.json` 中的 `reading_agent`、`root_agent` 路径未改变。生产 `get_agent_runtime` 继续注入生产 adapter、context provider、collaboration adapter 和 checkpointer。

## 基线与开关

- Python 3.11.15
- LangGraph 1.2.11；langgraph-checkpoint 4.2.0；langgraph-checkpoint-sqlite 3.1.1；pytest 9.0.3
- `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT`、`AITRANS_MULTI_AGENT_ENGINE`、`AITRANS_MULTI_AGENT_ROLLOUT`、`AITRANS_SANDBOX_ENABLED` 在当前 shell 均未设置；应用默认保持 native 关闭、engine `typed`、rollout `single`。本阶段未修改开关或用户数据。
- 图构造验收使用合成 service 和内存 checkpointer；未发起真实模型、Qdrant 或 Docker 操作。

## 修改文件

- 新增 `backend/agent_graph/factory.py`：集中定义 Root 节点注册、普通边、条件边以及持久/临时 compile 规则。
- `backend/agent_graph/reading_agent_graph.py`：保留节点处理器和兼容 API，改为调用共享 builder。
- `backend/agent_graph/studio.py`：延迟解析运行时依赖，仍以 RootAgentGraph 暴露 Studio topology。
- 新增 `tests/agent/test_root_graph_factory_parity.py`：校验生产/Studio 签名、checkpointer 规则及构图不解析依赖。
- 更新本任务书 Stage 2 状态。

## 验证

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q tests/agent/test_root_graph_factory_parity.py tests/agent/test_langsmith_studio_support.py tests/agent/test_root_agent_graph.py tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_lazy_dependencies.py` | **25 passed**，1 个 Paramiko Blowfish 弃用警告 |
| `python -m pytest -q tests/multi_agent/test_lg00_baseline_fixture.py tests/multi_agent/test_migration_switch.py` | **12 passed** |
| `python -m ruff check backend/agent_graph/factory.py backend/agent_graph/reading_agent_graph.py backend/agent_graph/root_agent_graph.py backend/agent_graph/studio.py tests/agent/test_root_graph_factory_parity.py` | **通过** |

Stage 2 定向门禁没有失败。全量 suite 未在本阶段重跑；Stage 0 记录的 6 项基线失败状态不变，也不属于本次图构造修改范围。性能基准和真实模型样本未运行，因为本阶段验收针对纯图拓扑且明确禁止构图时触发模型或外部运行服务。

## Gate 与回滚

- Studio 与生产图节点、普通边、条件边一致；条件边标签也纳入签名比较。
- 持久图带注入的 checkpointer，temporary 图无 checkpointer。
- ReadingAgentGraph/RootAgentGraph 兼容路径、旧 checkpoint 恢复测试通过；native-off fixture 与 migration switch 测试通过。
- 未增加编排节点，未改变旧 checkpoint 节点名，未迁移或写入用户数据库。
- 回滚可恢复 `ReadingAgentGraph.__init__` 中原内联拓扑及 Studio 原来的 eager service 接线；本阶段没有改变 checkpoint schema。

## 后续

Stage 2 Gate 全部通过，可开始 Stage 3。Electron Stage 8 的桌面手工验收是独立事项；其 Sandbox 执行项当前因服务返回 `sandbox_disabled` 尚待用户启用安全开关后复验。
