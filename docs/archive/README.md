# 历史文档归档

2026-10-06 整理，共归档 89 份 Markdown。这里的阶段报告保留当时的失败、未验收项目和质量限制，不能当作当前系统配置或启动说明。

当前系统使用根目录 [start.ps1](../../start.ps1)。最近实施记录保留在 [docs/development](../development/)，运行与维护指南仍在 docs 下。Electron parity 和 RAG 回归 JSON 仍在原位置供测试/脚本读取；没有移动有效测试或资料库。已移除的旧启动脚本可从 Git 历史恢复。

本轮移除 7 个重复/废弃的系统启动脚本，只保留根目录 `start.ps1`；保留有效 Python 和桌面功能测试，更新两项依赖旧启动文件的契约测试及发布静态扫描入口。`scripts/start_langsmith_studio.ps1` 是专项开发工具，安装、构建、验证脚本也继续保留。

验证记录：统一入口的真实 FAISS/CUDA 预检通过；PowerShell 7 与 Windows PowerShell 5.1 的后端预检通过；从其他工作目录调用及退出时恢复调用者环境通过；在隔离数据目录通过此脚本实际启动 FastAPI，`/health` 返回 `ok` / `aitrans-backend`，随后仅停止该烟测进程树。桌面编译、66 项运行时契约测试及测试类型检查通过。404 个 Python 测试文件均保留，2,381 项测试正常收集；这不是全量 Python 测试执行结果。归档文件的本地 Markdown 链接均可解析，资料库 manifest、BM25 与 SQLite 的哈希未变。

`npm run desktop:build` 也已通过，包括 React/TypeScript/Vite 构建、Electron 编译与 PDF.js 离线资源检查。没有把这次源码/预检验证当作打包发布或桌面 GUI 人工验收。原始归档映射、哈希与烟测日志在忽略目录 `test-results/startup-cleanup/`。旧 `docs/archive/legacy/` 空目录保留，其中已无启动脚本。

| 原位置 | 归档位置 |
| --- | --- |
| AITrans-RAG-Production-Improvement-Plan-GPT6-Luna.md | [AITrans-RAG-Production-Improvement-Plan-GPT6-Luna.md](<development/AITrans-RAG-Production-Improvement-Plan-GPT6-Luna.md>) |
| docs/development/Agent Runtime重构任务书.md | [Agent Runtime重构任务书.md](<development/Agent Runtime重构任务书.md>) |
| docs/development/agent-runtime-lg00-baseline.md | [agent-runtime-lg00-baseline.md](<development/agent-runtime-lg00-baseline.md>) |
| docs/development/agent-runtime-lg01-report.md | [agent-runtime-lg01-report.md](<development/agent-runtime-lg01-report.md>) |
| docs/development/agent-runtime-refactor-impact-analysis.md | [agent-runtime-refactor-impact-analysis.md](<development/agent-runtime-refactor-impact-analysis.md>) |
| docs/development/agent-runtime-stage-00-report.md | [agent-runtime-stage-00-report.md](<development/agent-runtime-stage-00-report.md>) |
| docs/development/agent-runtime-stage-02-report.md | [agent-runtime-stage-02-report.md](<development/agent-runtime-stage-02-report.md>) |
| docs/development/agent-runtime-stage-03-report.md | [agent-runtime-stage-03-report.md](<development/agent-runtime-stage-03-report.md>) |
| docs/development/agent-runtime-stage-04-report.md | [agent-runtime-stage-04-report.md](<development/agent-runtime-stage-04-report.md>) |
| docs/development/agent-runtime-stage-05-report.md | [agent-runtime-stage-05-report.md](<development/agent-runtime-stage-05-report.md>) |
| docs/development/agent-runtime-stage-06-report.md | [agent-runtime-stage-06-report.md](<development/agent-runtime-stage-06-report.md>) |
| docs/development/agent-runtime-stage-07-report.md | [agent-runtime-stage-07-report.md](<development/agent-runtime-stage-07-report.md>) |
| docs/development/agent-runtime-stage-08-report.md | [agent-runtime-stage-08-report.md](<development/agent-runtime-stage-08-report.md>) |
| docs/development/agent-runtime-stage-09-report.md | [agent-runtime-stage-09-report.md](<development/agent-runtime-stage-09-report.md>) |
| docs/development/agent-runtime-stage-10-report.md | [agent-runtime-stage-10-report.md](<development/agent-runtime-stage-10-report.md>) |
| docs/development/agent-runtime-stage-11-report.md | [agent-runtime-stage-11-report.md](<development/agent-runtime-stage-11-report.md>) |
| docs/development/agent-runtime-v1-validation.md | [agent-runtime-v1-validation.md](<development/agent-runtime-v1-validation.md>) |
| docs/development/knowledge-auto-routing-baseline.md | [knowledge-auto-routing-baseline.md](<development/knowledge-auto-routing-baseline.md>) |
| docs/development/qasper-p1-q1-0-baseline-report.md | [qasper-p1-q1-0-baseline-report.md](<development/qasper-p1-q1-0-baseline-report.md>) |
| docs/development/qasper-p1-q1-1-evidence-selection-report.md | [qasper-p1-q1-1-evidence-selection-report.md](<development/qasper-p1-q1-1-evidence-selection-report.md>) |
| docs/development/qasper-p1-q1-2-answer-contract-report.md | [qasper-p1-q1-2-answer-contract-report.md](<development/qasper-p1-q1-2-answer-contract-report.md>) |
| docs/development/qasper-p1-q1-3-adaptive-grounding-report.md | [qasper-p1-q1-3-adaptive-grounding-report.md](<development/qasper-p1-q1-3-adaptive-grounding-report.md>) |
| docs/development/qasper-p1-q1-3-contextual-remediation-report.md | [qasper-p1-q1-3-contextual-remediation-report.md](<development/qasper-p1-q1-3-contextual-remediation-report.md>) |
| docs/development/qasper-p1-q1-4-raptor-ablation-report.md | [qasper-p1-q1-4-raptor-ablation-report.md](<development/qasper-p1-q1-4-raptor-ablation-report.md>) |
| docs/development/qasper-p1-q1-5-gate-review.md | [qasper-p1-q1-5-gate-review.md](<development/qasper-p1-q1-5-gate-review.md>) |
| docs/development/RAG-improvement-baseline.md | [RAG-improvement-baseline.md](<development/RAG-improvement-baseline.md>) |
| docs/development/rag-improvement-stage-0-report.md | [rag-improvement-stage-0-report.md](<development/rag-improvement-stage-0-report.md>) |
| docs/development/rag-improvement-stage-1-report.md | [rag-improvement-stage-1-report.md](<development/rag-improvement-stage-1-report.md>) |
| docs/development/rag-improvement-stage-2-report.md | [rag-improvement-stage-2-report.md](<development/rag-improvement-stage-2-report.md>) |
| docs/development/rag-production-luna/architecture-decisions.md | [architecture-decisions.md](<development/rag-production-luna/architecture-decisions.md>) |
| docs/development/rag-production-luna/final-benchmark.md | [final-benchmark.md](<development/rag-production-luna/final-benchmark.md>) |
| docs/development/rag-production-luna/FUNCTION-CALLING-20261003.md | [FUNCTION-CALLING-20261003.md](<development/rag-production-luna/FUNCTION-CALLING-20261003.md>) |
| docs/development/rag-production-luna/METADATA-RISK-20261003.md | [METADATA-RISK-20261003.md](<development/rag-production-luna/METADATA-RISK-20261003.md>) |
| docs/development/rag-production-luna/OPEN-ISSUES-REMEDIATION.md | [OPEN-ISSUES-REMEDIATION.md](<development/rag-production-luna/OPEN-ISSUES-REMEDIATION.md>) |
| docs/development/rag-production-luna/OPEN-ISSUES.md | [OPEN-ISSUES.md](<development/rag-production-luna/OPEN-ISSUES.md>) |
| docs/development/rag-production-luna/PDF-RAG-VALIDATION.md | [PDF-RAG-VALIDATION.md](<development/rag-production-luna/PDF-RAG-VALIDATION.md>) |
| docs/development/rag-production-luna/QUALITY-ACCEPTANCE.md | [QUALITY-ACCEPTANCE.md](<development/rag-production-luna/QUALITY-ACCEPTANCE.md>) |
| docs/development/rag-production-luna/QUALITY-CAPACITY-20261003.md | [QUALITY-CAPACITY-20261003.md](<development/rag-production-luna/QUALITY-CAPACITY-20261003.md>) |
| docs/development/rag-production-luna/RAG-ARCHITECTURE-CURRENT.md | [RAG-ARCHITECTURE-CURRENT.md](<development/rag-production-luna/RAG-ARCHITECTURE-CURRENT.md>) |
| docs/development/rag-production-luna/RAG-ENABLEMENT-AND-CHAT-VALIDATION.md | [RAG-ENABLEMENT-AND-CHAT-VALIDATION.md](<development/rag-production-luna/RAG-ENABLEMENT-AND-CHAT-VALIDATION.md>) |
| docs/development/rag-production-luna/REMAINING-EXECUTION-PLAN.md | [REMAINING-EXECUTION-PLAN.md](<development/rag-production-luna/REMAINING-EXECUTION-PLAN.md>) |
| docs/development/rag-production-luna/RISK-CLOSURE-20261003.md | [RISK-CLOSURE-20261003.md](<development/rag-production-luna/RISK-CLOSURE-20261003.md>) |
| docs/development/rag-production-luna/RISK-REMEDIATION-20261003.md | [RISK-REMEDIATION-20261003.md](<development/rag-production-luna/RISK-REMEDIATION-20261003.md>) |
| docs/development/rag-production-luna/S00-S04-REMEDIATION.md | [S00-S04-REMEDIATION.md](<development/rag-production-luna/S00-S04-REMEDIATION.md>) |
| docs/development/rag-production-luna/S00.1.md | [S00.1.md](<development/rag-production-luna/S00.1.md>) |
| docs/development/rag-production-luna/S00.2.md | [S00.2.md](<development/rag-production-luna/S00.2.md>) |
| docs/development/rag-production-luna/S00.3.md | [S00.3.md](<development/rag-production-luna/S00.3.md>) |
| docs/development/rag-production-luna/S00.md | [S00.md](<development/rag-production-luna/S00.md>) |
| docs/development/rag-production-luna/S01.1.md | [S01.1.md](<development/rag-production-luna/S01.1.md>) |
| docs/development/rag-production-luna/S01.2.md | [S01.2.md](<development/rag-production-luna/S01.2.md>) |
| docs/development/rag-production-luna/S01.3.md | [S01.3.md](<development/rag-production-luna/S01.3.md>) |
| docs/development/rag-production-luna/S01.4.md | [S01.4.md](<development/rag-production-luna/S01.4.md>) |
| docs/development/rag-production-luna/S01.5.md | [S01.5.md](<development/rag-production-luna/S01.5.md>) |
| docs/development/rag-production-luna/S01.md | [S01.md](<development/rag-production-luna/S01.md>) |
| docs/development/rag-production-luna/S02.1.md | [S02.1.md](<development/rag-production-luna/S02.1.md>) |
| docs/development/rag-production-luna/S02.2.md | [S02.2.md](<development/rag-production-luna/S02.2.md>) |
| docs/development/rag-production-luna/S02.3.md | [S02.3.md](<development/rag-production-luna/S02.3.md>) |
| docs/development/rag-production-luna/S02.md | [S02.md](<development/rag-production-luna/S02.md>) |
| docs/development/rag-production-luna/S03.1.md | [S03.1.md](<development/rag-production-luna/S03.1.md>) |
| docs/development/rag-production-luna/S03.2.md | [S03.2.md](<development/rag-production-luna/S03.2.md>) |
| docs/development/rag-production-luna/S03.3.md | [S03.3.md](<development/rag-production-luna/S03.3.md>) |
| docs/development/rag-production-luna/S04.1.md | [S04.1.md](<development/rag-production-luna/S04.1.md>) |
| docs/development/rag-production-luna/S04.2.md | [S04.2.md](<development/rag-production-luna/S04.2.md>) |
| docs/development/rag-production-luna/S04.md | [S04.md](<development/rag-production-luna/S04.md>) |
| docs/development/rag-production-luna/S05.1.md | [S05.1.md](<development/rag-production-luna/S05.1.md>) |
| docs/development/rag-production-luna/S05.2.md | [S05.2.md](<development/rag-production-luna/S05.2.md>) |
| docs/development/rag-production-luna/S05.3.md | [S05.3.md](<development/rag-production-luna/S05.3.md>) |
| docs/development/rag-production-luna/S05.md | [S05.md](<development/rag-production-luna/S05.md>) |
| docs/development/rag-production-luna/S06.md | [S06.md](<development/rag-production-luna/S06.md>) |
| docs/development/rag-production-luna/S07.md | [S07.md](<development/rag-production-luna/S07.md>) |
| docs/development/rag-production-luna/S08.md | [S08.md](<development/rag-production-luna/S08.md>) |
| docs/development/rag-production-luna/STATUS.md | [STATUS.md](<development/rag-production-luna/STATUS.md>) |
| docs/electron-migration/baseline.md | [baseline.md](<electron-migration/baseline.md>) |
| docs/electron-migration/dependency-health.md | [dependency-health.md](<electron-migration/dependency-health.md>) |
| docs/electron-migration/manual-acceptance.md | [manual-acceptance.md](<electron-migration/manual-acceptance.md>) |
| docs/electron-migration/stage10-closure.md | [stage10-closure.md](<electron-migration/stage10-closure.md>) |
| docs/electron-migration/stage11-closure.md | [stage11-closure.md](<electron-migration/stage11-closure.md>) |
| docs/electron-migration/stage12-closure.md | [stage12-closure.md](<electron-migration/stage12-closure.md>) |
| docs/electron-migration/stage12-manual-acceptance.md | [stage12-manual-acceptance.md](<electron-migration/stage12-manual-acceptance.md>) |
| docs/electron-migration/stage13-closure.md | [stage13-closure.md](<electron-migration/stage13-closure.md>) |
| docs/electron-migration/stage14-closure.md | [stage14-closure.md](<electron-migration/stage14-closure.md>) |
| docs/electron-migration/stage8-closure.md | [stage8-closure.md](<electron-migration/stage8-closure.md>) |
| docs/electron-migration/stage9-closure.md | [stage9-closure.md](<electron-migration/stage9-closure.md>) |
| docs/agent-production-runtime.md | [agent-production-runtime.md](<agent-production-runtime.md>) |
| docs/development/AITrans-QASPER-P1-Quality-Iteration-Taskbook.md | [AITrans-QASPER-P1-Quality-Iteration-Taskbook.md](<development/AITrans-QASPER-P1-Quality-Iteration-Taskbook.md>) |
| docs/development/memory-system-taskbook.md | [memory-system-taskbook.md](<development/memory-system-taskbook.md>) |
| docs/development/multi-agent-system-design.md | [multi-agent-system-design.md](<development/multi-agent-system-design.md>) |
| docs/pdf-offline-baseline.md | [pdf-offline-baseline.md](<pdf-offline-baseline.md>) |
| docs/pdf-offline-release-validation.md | [pdf-offline-release-validation.md](<pdf-offline-release-validation.md>) |
