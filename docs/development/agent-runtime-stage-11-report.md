# Agent Runtime Stage 11 实施报告

日期：2026-09-28  
基线：Stage 10 工作树  
HEAD：`824236e00cfb44d4353558572331e4154de688d4`  
环境：Python 3.11.15、pytest 9.0.3、Pydantic 2.13.3、LangGraph 1.2.11、Node 24.11.1、npm 11.6.2、Rust 1.97.1  
结果：**IMPLEMENTED / GATE PENDING**；`AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT` 默认仍为 `false`，legacy 路径保留。

## 本阶段完成

- 用原生开关显式为合成 FAST 和 SINGLE run 选择 native。FAST 的 run 状态为 idle；SINGLE 成功完成、绑定 Scope 并产出 1 个 Artifact 引用。两条轨迹均为 `reading-agent-ma06-v1`，事件 ID 完整、序号连续，没有调用旧 executor。报告：`test-results/agent-runtime-alpha-smoke.json`。这是本地合成验收，不是 native Beta 的真实模型样本；跨进程恢复另由专项测试覆盖。
- 有界执行线程把 `BaseException` 传回调用方；已知 provider/网络瞬断按安全策略重试，硬 worker deadline 不再触发可能与尚未结束线程重叠的自动重试。Runtime snapshot API 仅在 adapter 提供可调用的 checkpoint 投影时请求它；其他 adapter 使用兼容 state projection。修复文献综合回归脚本的直接执行导入路径，并按 Rust 格式规范整理 Tauri 主文件。
- Canvas/companion-chat 工作流修复 Stage 0 的 2 项失败：接收 `filesystem_workspace_files`，只允许有界相对路径与文件大小元数据，并传入最终聊天提示词；提示词明确文件内容未经读取。Grounded-synthesis/evidence-verifier 工作流修复另外 4 项：严格 claim 指标只计 claim 自身的引文；段落层的部分放行规则保留并单独标识。六项原有失败均在对应工作流解决，历史 Stage 0 对照记录保留。
- 本机 `config/user.toml` 的 provider/model 路由已核对为 DeepSeek。API 凭据存放在当前用户的 Windows Credential Manager 目标 `AITranslator/ai/deepseek`，未写进配置文件或仓库。由于本机 Python 的 pywin32 DLL 无法加载，后端默认读取改用 Windows `CredReadW`；Electron/Tauri 使用的目标名不变。后端读取验证与一次最小真实 `deepseek-v4-flash` 请求成功；Electron 凭据状态与脱敏预览均显示已配置。当前 Electron 管理的后端通过 `/api/settings/llm/models` 实时返回 DeepSeek 可用、2 个模型。
- 对旧数据选择“只读导出并保留兼容读取”：`data/exports/stage11-legacy-20260928T110554Z/` 保存 `config/`、`data/`、`runtime/` 顶层共 17 个 SQLite 快照，采用 SQLite backup API 纳入已提交 WAL 内容。`manifest.json` 记录各文件大小和 SHA-256；独立复核的哈希与 SQLite `quick_check` 均通过。该导出只覆盖 SQLite，跨数据库不是原子快照，且不包含 Windows 凭据或非 SQLite 资源。
- 只读审计发现 legacy task checkpoint 共 7 条：5 条 `partial`、2 条 `running`，均无有效 lease。五条 `partial` 的 Root 快照已完成；两条 `running` 的 Root 快照尚有待执行分支，且均无对应的 AgentRun 生命周期记录。当前决定保留原状态和 legacy 恢复路径，不自动重放、取消、终结或删除。Stable 前必须逐条处理这两条非终态 run；这次导出满足旧 checkpoint 的可见导出条件，但不满足“没有非终态 legacy run”的条件。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| `python -m pytest -q tests/agent tests/multi_agent tests/integration tests/api -m "not docker_integration" --tb=short` | **890 passed、1 deselected、2 warnings**。Stage 0 六项已修复；全量无失败。 |
| Canvas 与 grounded-synthesis 定向套件 | **24 passed、1 warning**。 |
| `python -m pytest -q tests/test_ai_secrets.py` | **6 passed**。Windows 凭据真实读取与最小真实模型请求另外通过。 |
| Stage 15 离线质量协议真实 DeepSeek judge | 固定 12 条样本，`deepseek-v4-flash`、temperature 0；**8 pass、3 fail、1 review**，协议与样本对齐检查通过。数据集 SHA-256：`feb79eab851b2ea66f16e68bc5e61c086856690ffff7bad5f0a5fede2e6c4808`。报告：`test-results/agent-quality-live-stage11.json`；1 条仍待独立人工复核。这是离线候选答案评估，不是 native Beta 的真实运行质量或性能证据。 |
| `scripts/run_agent_regression_benchmark.py` | **40/40** 确定性轨迹通过；p50 **0 ms**、p95 **16 ms**。这是 Stage 14 scripted-boundary 回归，不是 30 个 native lane 的真实 Beta 样本。报告：`test-results/agent-regression-native.json`。 |
| `scripts/run_agent_literature_synthesis_regression.py` | **8/8** 通过；报告：`test-results/agent-literature-native.json`。 |
| Stage 15 qualitative fixture replay | schema/alignment 通过；属于 fixture replay。报告：`test-results/agent-quality-protocol-stage11.json`。 |
| Ruff critical checks、`compileall`、`git diff --check` | 通过；Git 提示工作树文件可能发生 LF/CRLF 转换。 |
| 桌面端 `npm run lint` / `npm run test` / test typecheck / `npm run build` | 本阶段此前均通过；lint 有 warnings；**100 files、423 tests passed**，PDF.js offline guard 通过。当前 Python/文档改动后未重复运行桌面端。 |
| `npm run test:electron-contracts` / `npm run electron:compile` | 本阶段此前 **7 files、23 tests passed**，编译通过。 |
| Tauri `cargo fmt --check` / `cargo clippy --locked --no-default-features --all-targets -- -D warnings` / `cargo test --locked --no-default-features` / `cargo build --locked --no-default-features` | 本阶段此前全部通过；Rust 单测 **1 passed**。 |
| Docker 标记专项 | 本阶段此前 **1 passed、888 deselected**。 |
| 旧 SQLite 导出 | **17/17** 文件的大小、SHA-256、`quick_check` 经独立复核。 |

## 尚未满足的发布门禁

- **Beta 仍缺真实 native 对照**：凭据和真实模型调用已就绪，但尚无固定硬件、模型、语料、预算下 baseline/native 每 lane 至少 30 个可复现运行样本，不能判断 native p95 是否 ≤ baseline 的 1.20 倍。上述 12 条离线 judge 样本不替代此门禁。现有 MA10 CLI 只从记录好的 observations 生成报告；MA10 deterministic contract matrix 使用 `no-model` 并明确将配置 LLM 标为未验证，因此都不能直接作为 native Beta 证据。下一步需提供真正调用生产 AgentRuntime 的 live runner、30 条无副作用固定样本、质量标注与调用/延迟采集，再按同版本和预算运行 baseline/native。
- **RC 观测与回滚演练未完成**：尚无真实 WORKFLOW native 发布观测；取消、写入确认、跨进程恢复、fan-out/fan-in 有确定性测试，但不能替代 RC 与回滚演练。
- **两条非终态 legacy run**：已经导出并保留，只能在核对业务意图后恢复、归档或正式终结。未达“没有非终态 legacy run”的退出兼容期硬条件；旧执行代码和 checkpoint 写入兼容逻辑继续保留。
- **连续 CI 与 Stable 未达标**：本机完整 Python 门禁已绿，但尚无两次连续完整 CI 的证据。桌面/Tauri 本阶段此前通过，但这次修改后未再次跑全平台 CI。native 默认维持关闭。
- **Cleanup 未做**：生产代码仍有旧 executor、bridge/workspace、research orchestration 与 Studio 消费者。`AgentRunStore`、`AgentRunWorker`、lease/heartbeat 属于持久任务生命周期，按任务书继续保留。未满足退出兼容期条件，不移除兼容代码或用户数据。

## 回滚与数据边界

新 run 的 native 仍需显式开启；已有 run 继续按创建时固定的 engine 和 graph version 路由。未修改、重试或删除旧数据库记录；本地导出与 Windows 凭据不纳入 Git。此工作树未提交或推送。满足真实 Beta/RC、非终态 legacy run 处置、连续 CI 和回滚演练后，再评估 Stable 与 Cleanup。
