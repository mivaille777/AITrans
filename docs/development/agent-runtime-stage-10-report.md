# Agent Runtime Stage 10 实施报告

日期：2026-09-28  
基线：Stage 9 工作树  
HEAD：`824236e00cfb44d4353558572331e4154de688d4`  
结果：**PASS**；native 默认开关仍关闭。

## 实施内容

- `AgentEvent` 和 trace DTO 增加可选 Agent ID、版本、节点名及子图路径。Trace Store schema v2 和 AgentRunStore schema v7 持久化稳定 event ID、canonical sequence 与任务/Agent 元数据；跨存储投影按 event ID 去重，不根据时间戳排序。兼容桥会从已校验任务的 role/actor 保留 Agent ID，supervisor 事件不会被标成 Agent。
- 新增只读 Agent Catalog 与 Runtime Debug API。Catalog 仅返回注册表中的身份、描述、能力、版本和图标 key。Debug API 将既有 run store、trace store 和安全 checkpoint snapshot 投影为 DTO；原文、prompt、完整工具参数、原始 Artifact 内容、checkpoint payload、路径与密钥不会返回。未持久化的数据保留为缺失值。
- Agent Task 面板从 Catalog 显示名称和图标，同一 Agent 的多个任务按 `task_id` 独立显示；Catalog 缺失时回退到 `agent_id`。Tool、共享 Language capability、等待确认、部分失败、取消与恢复状态分别显示。
- Settings 增加独立只读 Runtime Debug Studio，呈现 run、任务依赖与尝试、事件时间线、工具名、Artifact 引用和可信关联 ID。RAG Debug Studio 仍保留六个检索 tab，仅在收到可信 Agent `run_id` 时显示 Runtime 链接；Sandbox Debug 仍是独立入口。
- 新增 API 隐私与事件契约测试、Catalog/UI/API 前端测试，并补充兼容桥身份透传及 supervisor 不误标为 Agent 的回归测试。

## 主要文件

- 后端：`backend/agent_core/events.py`、`backend/agent_core/runtime.py`、`backend/models/agent_tools.py`、`backend/models/agent_runtime_debug.py`、`backend/api/agent_catalog.py`、`backend/api/agent_runtime_debug.py`、`backend/api/agent.py`、`backend/main.py`、`backend/services/agent_trace_store_service.py`、`backend/services/agent_run_store.py`、`backend/services/multi_agent_runtime_bridge.py`。
- 桌面端：`apps/desktop/src/api/agent-runtime-debug.ts`、`apps/desktop/src/api/agent.ts`、`apps/desktop/src/features/agent/AgentWorkspace.tsx`、`apps/desktop/src/features/agent/components/TaskExecutionPanel.tsx`、`apps/desktop/src/features/settings/RuntimeDebugStudio.tsx`、`apps/desktop/src/features/settings/SettingsWorkspace.tsx`、`apps/desktop/src/features/settings/RagDebugStudioTrace.tsx`。
- 测试：`tests/api/test_agent_runtime_debug_api.py`、`tests/agent/test_agent_trace_event_contract.py`、`tests/multi_agent/test_task_events.py`，以及对应 desktop API、Task 面板、Runtime Debug Studio 和 RAG 链接测试。

## 验证

任务书指定的后端命令通过：**168 passed，2 warnings**。两条告警为 Paramiko Blowfish 与 Starlette/httpx 的弃用提示。

```powershell
python -m pytest -q tests/api/test_agent_runtime_debug_api.py tests/agent/test_agent_trace_event_contract.py tests/agent/test_agent_observability.py tests/multi_agent/test_task_events.py tests/agent/test_agent_api_runtime.py
```

desktop 门禁通过：`npm run test` 为 **100 test files / 423 tests passed**，并完成 `tsc --noEmit -p tsconfig.test.json`；Vitest 输出一条既有 jsdom 跨 Document 导航提示，但进程退出码为 0。`npm run lint` 退出码为 **0**，报告 37 条 lint warning；主要来自已有知识、阅读、RAG、credential 和测试代码。`npm run build` 退出码为 **0**，Vite 构建、PDF.js 离线资源 guard 和 bundle report 均完成。

```powershell
cd apps/desktop
npm run lint
npm run test
npm run build
```

`git diff --check` 通过。Git 提示若干既有工作树文件下次写入时可能发生 LF/CRLF 转换；没有 whitespace error。

## 边界

- Runtime Debug 默认只读；本阶段没有新增直接修改数据库的调试操作，也没有创建第二套 trace 数据库。
- 未开启 native 默认值，未启动 native beta，未运行真实模型、性能样本或 Stage 11 发布质量门禁。
- Stage 11 未开始；任务书中的六项 Stage 0 Canvas/grounded synthesis 基线失败仍保留为发布门禁。
