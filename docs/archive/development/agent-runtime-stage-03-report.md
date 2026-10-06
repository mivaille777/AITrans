# Agent Runtime Stage 3 实施报告

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-28  
任务书：`Agent Runtime重构任务书.md` · Stage 3 Tool、Sandbox 与 MCP 准入契约  
工作树 HEAD：`824236e00cfb44d4353558572331e4154de688d4`（本阶段未提交）

## 结果

**PASS。** 新 worker Tool 调用通过 `ToolRuntimePort` 契约进入 `ProductAgentToolRuntimePort`。Adapter 先解析服务端 TaskSpec 和 ScopeContext，校验 task/Agent/tool allowlist 与 scope 引用，再验证服务器注册的 ToolSpec 参数；执行委托现有 `AgentToolRegistry` 和 `ProductAgentService.run`，不直接访问 executor 或 SandboxManager。

外部 capability 只能由 `get_server_agent_tool_definitions()` 返回的服务端配置注入 `AgentToolRegistry`。注册时检查 definition 类型、名称、输入/结果 Pydantic 模型、可 JSON 序列化 schema、schema 字段和重名；请求模型没有 Tool 注册字段。当前服务端扩展 provider 默认返回空 tuple，没有启用真实 MCP。

写入审批由服务端 `write_confirmation_provider` 提供，并按 run/task/tool 消费一次；ToolPort 不接受 worker 自带的确认字段。没有审批时 ProductAgentService 返回确认状态，adapter 拒绝执行。写入 Tool 仍由 typed definition 的 `retry_policy="never"` 和现有执行服务保护。Python/command trace 继续记录摘要，不存代码或 argv 原文。

## 基线与开关

- Python 3.11.15
- LangGraph 1.2.11；langgraph-checkpoint 4.2.0；langgraph-checkpoint-sqlite 3.1.1；pytest 9.0.3
- 当前 shell 的 `AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT`、`AITRANS_MULTI_AGENT_ENGINE`、`AITRANS_MULTI_AGENT_ROLLOUT`、`AITRANS_SANDBOX_ENABLED` 均未设置；默认 native 仍关闭、engine 为 `typed`、rollout 为 `single`。
- 未启动 Docker 或真实模型。Sandbox 准入由 fake manager 验证；manager 缺失时 Python/command definitions 均不可见。现有 `get_sandbox_manager` 仍要求显式启用开关与健康 runtime，无宿主机执行 fallback。

## 修改文件

- `backend/agent_core/orchestration/ports.py`：将 `ToolRuntimePort` 定义为 worker 所需的 run/task/agent/tool/typed arguments/scope_ref 接口。
- `backend/agent_core/orchestration/agent_registry.py`：添加单 Tool allowlist 授权入口。
- `backend/agent_core/orchestration/validation.py`、`planner.py`：在已有 Agent allowlist 后确认任务工具存在于服务端 Tool Registry；`get_agent_runtime` 注入 ProductAgentService 持有的 registry。
- `backend/agent_tools/base.py`：让 JSON Schema integer/number/boolean/object 参数保留类型并校验类型/范围。
- `backend/services/agent_tool_registry.py`：增加服务端外部 typed definition 注入及名称/schema/重名检查。
- `backend/services/product_agent_service.py`：暴露同一 server-owned Tool Registry 给规划校验。
- 新增 `backend/services/product_agent_tool_port.py`：核对服务端 TaskSpec/ScopeContext、Agent/task allowlist 与 typed ToolSpec，然后委托 ProductAgentService；执行事件附带 run/task/agent 身份。
- `backend/api/dependencies.py`、`backend/api/agent_dependencies.py`：接入服务端 definition provider 与 ToolPort 构造入口、规划 Tool Registry。
- 新增 `tests/agent/test_native_tool_boundary.py`：允许/拒绝、scope、外部 Tool、Sandbox、写确认、typed 参数、服务端注册及 trace 摘要测试。

## 验证

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q tests/agent/test_native_tool_boundary.py tests/agent/test_typed_tool_registry.py tests/agent/test_agent_tool_execution.py tests/agent/test_python_execute_tool.py tests/agent/test_command_execute_tool.py tests/agent/test_multi_step_write_safety.py` | **44 passed**，1 个 Paramiko Blowfish 弃用警告 |
| `python -m pytest -q tests/multi_agent/test_plan_validation.py tests/multi_agent/test_agent_registry.py` | **14 passed** |
| `python -m pytest -q tests/agent/test_agent_api_runtime.py` | **14 passed**，2 个 Starlette/httpx 与 Paramiko 弃用警告 |
| `python -m ruff check backend/agent_tools/base.py backend/services/agent_tool_registry.py backend/services/product_agent_service.py backend/services/product_agent_tool_port.py backend/api/dependencies.py backend/api/agent_dependencies.py backend/agent_core/orchestration/agent_registry.py backend/agent_core/orchestration/validation.py backend/agent_core/orchestration/planner.py backend/agent_core/orchestration/ports.py tests/agent/test_native_tool_boundary.py` | **通过** |

红测先因缺少 worker ToolPort 在收集时失败，加入实现后通过。新增用例通过 fake SandboxManager 调用既有 `python_execute` typed definition；没有触碰 Docker 或宿主命令。全量 suite 未在本阶段运行，Stage 0 记录的 6 项全量基线失败状态未复核且没有在此宣称通过。

## Gate 与回滚

- Task/Agent allowlist 拒绝时 executor 未调用；伪造或不匹配 scope 在调用前拒绝。
- 外部 synthetic Tool 和已注册 Sandbox Tool 均使用相同 ProductAgentService typed execution boundary；无第二份 Tool Registry。
- Sandbox manager 不可用时 Python/command Tool 缺席；没有宿主机执行回退。
- 写入缺确认时 executor 未调用；server confirmation provider 测试确认 grant 仅消费一次；写入不自动重试。
- Python 代码和 command argv 的 trace summary 不含原文；Tool catalog/API runtime 回归通过。
- 回滚时移除 ProductAgentToolRuntimePort/ToolRuntimePort 接线、外部 definition provider 与 planner Tool Registry 注入，并恢复 Tool 参数旧字符串校验；不涉及用户数据库和 checkpoint schema。

## 后续

Stage 3 Gate 全部通过，可开始 Stage 4。Stage 4 将编入 Root canonical state 与版本选择；应继续保持 native 默认关闭和旧 run 拓扑兼容。
