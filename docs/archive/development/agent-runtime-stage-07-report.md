# Agent Runtime Stage 7 实施报告

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-28  
基线：Stage 6 工作树  
结果：**PASS**；native 开关仍默认关闭，Stage 8 恢复门禁尚未执行。

## 变更

- MA06/native Root 增加 `dispatch_frontier → Send specialist → advance_frontier → finalize_task_graph`。ready task 以稳定 `agent_id` 映射到 Registry 所持 compiled subgraph；fan-out payload 只有该 TaskSpec、已校验 ScopeContext 和声明依赖的 TaskResult 引用。
- Root reducer 合并每个 TaskResult、状态、ArtifactRef 和 EvidenceRef。依赖失败在 Root 归约：required 后代为 `BLOCKED`，optional 后代为 `SKIPPED`；共享模型预算耗尽也写入明确终态。native 路径将已完成结果交回 prepared bridge，服务从 Artifact Store 校验 hash、scope、producer 与 kind 后读取可投影内容，不调用旧 DAG executor。
- `AgentResourceManager` 复用既有 `ParallelExecutionPolicy` 与共享调用预算，普通专家最多 2 个并发，GPU 专家最多 1 个并发，进程级额度对多个 run 仍共享。
- `TaskSpec.role` 兼容旧 JSON 并派生 `agent_id`；只有 `agent_id` 的新 Agent 不必伪装为 legacy role。legacy role 的 JSON 序列化仍省略冗余 `agent_id`，Stage 0 plan fixture 保持逐字段一致。没有 Send 的兼容执行路径在进入旧 executor 前拒绝 dynamic Agent。
- Studio 在 native 配置下注册四个现有 compiled specialist 子图；默认 compat 拓扑与生产 Root 保持 Stage 2 parity。现有四张 specialist graph 已公开 `compiled_graph`，因此其图内部实现无需改写。

## 验证

任务书列出的 Stage 7 命令：**38 passed**。覆盖独立 task 屏障并行、依赖顺序、`a/c=SUCCEEDED,b=FAILED,d=BLOCKED`、Mock Agent 单次执行、Tool/Scope 前置拒绝、旧 executor 不调用、artifact 回收及 Studio 四图可见。

本阶段涉及的后端和测试文件 Ruff：**All checks passed**。

Agent/multi-agent 全量命令 `python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short`：**816 passed, 6 failed, 1 deselected**。六个失败与 Stage 0 完全相同：Canvas 两项契约、grounded synthesis 四项引文语义；新增的旧计划 JSON fixture 差异已修复，没有新增失败。

Electron 合同套件：**7 files / 23 tests passed**；`npm run typecheck:test` exit 0。复核时现有 Electron 主窗口进程标题为 `desktop` 且响应正常，Vite renderer `http://127.0.0.1:5173` 返回 200，后端 `http://127.0.0.1:8766/health` 返回 `{"status":"ok","service":"aitrans-backend"}`。

## 边界与后续

本阶段没有启用默认 native 开关、没有为同一 run 启动两套调度器，也没有执行真实模型或 Docker 测试。Stage 7 不承诺跨进程恢复；该能力由 Stage 8 统一验证。

桌面控制接口在用户恢复窗口后仍返回 `apps: []`，因此本轮只以窗口进程、renderer 与 backend health 完成启动/健康检查，**没有把肉眼 UI 手工验收记为通过**。沙箱状态保持原值；本报告不要求开启 `sandbox_disabled`。
