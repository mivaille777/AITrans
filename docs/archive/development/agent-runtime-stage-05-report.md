# Agent Runtime Stage 5 实施报告

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-28  
任务书：`Agent Runtime重构任务书.md` · Stage 5 Root 内显式路由、Scope、Memory、Plan 节点  
工作树 HEAD：`824236e00cfb44d4353558572331e4154de688d4`（本阶段未提交）

## 结果

**PASS。规划已迁入，执行未迁入。** 新 native Root 在会话所有权之后完成 `route_orchestration → resolve_scope → load_memory_snapshot → plan_tasks → validate_plan`。FAST 仍进入原有 knowledge/Agent 路径；缺少来源信息时 Root 写出明确 blocked response 并直接完成会话，不调用 specialist。Scope 解析或内存权限/快照撤销失败会在 plan/executor 前终止。

`run_collaboration` 的 native 分支只接收 Root 已准备的 route、Scope、Memory snapshot 和 validated plan，并调用 `execute_prepared()`。它不调用 legacy `run()`，也不再 route 或计划。兼容 `run()` 保留旧 route/scope/plan 流程，然后把相同的准备结果交给共同 executor 方法。Stage 6 之前实际 specialist executor 仍为现有 executor。

Validated plan、`plan_revision`、`scope_ref` 和 memory policy revision 在执行前写入 Root checkpoint。调用侧只把 Memory snapshot body 放在 LangGraph invocation context；Root checkpoint 保存 snapshot ID。因为标准节点写入直到 superstep 边界才提交，验证节点在调 executor 前显式 checkpoint validated delta；记录型 checkpointer 测试在 executor 入口确认 plan 与 Scope 已落盘。

新建运行使用 `reading-agent-ma05-v1` / state schema `4`。`reading-agent-ma04-v1` 无论 engine 值为何仍编译兼容拓扑；MA05/compat 也保留原拓扑。持久 worker 按队列记录的 engine 和 graph version 重建 Root。Studio 通过同一 factory 选择当前 topology。

Memory policy revision 绑定在 Scope，由 memory repository 当前 `read_enabled` / `write_enabled` 标志稳定计算。恢复时重新解析 Scope、核对 policy revision、验证原计划、重新载入冻结 snapshot；Scope/policy 改变或已撤销 snapshot 会在 executor 前拒绝。关闭 memory read 时不会启动计划或执行。

## 验证

| 命令 | 结果 |
| --- | --- |
| Stage 5 任务书指定的七个测试文件 | **43 passed**，1 个 Paramiko deprecation warning |
| `tests/multi_agent/test_root_planning_nodes.py` | **9 passed**。覆盖 FAST 0 specialist、SINGLE 1 task、WORKFLOW 3 task DAG、missing-information block、Scope/Memory 失败、memory revocation/policy change resume，以及 executor 前 checkpoint |
| `python -m pytest -q tests/agent tests/multi_agent -m "not docker_integration" --tb=short` | **793 passed, 6 failed, 1 deselected**；6 项与 Stage 0 干净基线完全相同：2 项 Canvas `filesystem_workspace_files` 参数契约、4 项 grounded-synthesis 引文/claim 语义；无新失败 |
| Stage 5 修改文件定向 Ruff 检查 | **通过** |
| Stage 5 Python compileall | **通过** |

本阶段未启动 Docker、未调用真实模型，也没有性能 benchmark。Stage 8 桌面手工验收仍未完成：用户已恢复 Electron 窗口，但桌面控制接口重新枚举后仍只返回浏览器、`apps: []`，不能读取 `desktop` 窗口。

## Gate 与回滚

- native router、scope resolver 和 planner 在单次 run 中各执行一次；native bridge 只执行 Root checkpoint 中同一份 plan。
- FAST、SINGLE、WORKFLOW、缺来源、Scope/Memory error 与 resume revocation/policy-change 验收通过。
- 当前旧 run 的 graph version 固定旧 topology；队列 engine 固定值不会因 worker 进程的环境变量改变而被替换。
- compat 默认保持 Stage 0 行为；完整测试复测没有引入基线外失败。
- 回滚时保留 MA04/MA05 图版本识别、run store engine 列及既有 checkpoint；不要恢复一个不能读取 Stage 5 checkpoints 的 builder。

## 后续

Stage 5 gate 通过，可进入 Stage 6 纯 frontier、依赖与 reducer 提取。
