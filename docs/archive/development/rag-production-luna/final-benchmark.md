# S09–S16 功能验收与剩余事项

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../../start.ps1)；最新检索修复见 [语义排序报告](../../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-30。基准提交：`4b0d802c168a00cf12a967cfcdb24c1ba2ed1f4c`，分支 `electronrebuild`，本轮修改尚未提交。**用户已确认：以功能正常为主，效果验收暂缓。**

## 结论

本轮功能修复及已执行的功能检查通过。新增评测、坏例、Trace、缓存、故障注入和回归工具可以运行；Graph 在线检索、原文证据查看及重排接线正常。**完整任务书的生产验收尚未完成**：质量评测、人工事实标注、真实用户语料、大规模容量与同步调用硬取消仍有缺口。不能将工程通过解释为生产 Go。

规范及目标见 [整合执行计划](REMAINING-EXECUTION-PLAN.md)，部署、许可证与回滚见 [架构决定](architecture-decisions.md)。按调用依赖合并后续任务，复用现有存储、模型和服务；没有修改默认 Graph/Router 开关、默认重排池或安装新依赖。工作区原有 Agent 改动及删除文件保留。

## 按原任务 ID 核对

“功能通过”只描述本轮实现和实测，不替代原 Stage 的质量/生产门。未完成项明确列出，不将暂缓视为 PASS。

| ID | 本轮实现与功能证据 | 尚未完成或暂缓 |
|---|---|---|
| S09.1 | fusion/input/post/final 列表分开；手算测试证明完整 post 池与最终截断指标不同 | 无新增功能阻塞 |
| S09.2 | 8/12/20 池测试，final_top_k 保持原合同 | 真实质量配对与更大池推广暂缓 |
| S09.3 | 可选输入 token 限制、分批协作 deadline、RRF 回退和原因；真实 Qwen3 重排通过 | 池大小的质量/显存消融暂缓；不能中断已阻塞的同步推理 |
| S10.1 | 检查当前 scope/generation、持久化源 chunk、原文 span/hash；context 只允许实际纳入的引用；证据切片同步更新锚点 | 旧无 span 数据仍按兼容合同使用，需要重建才有完整版本化锚点 |
| S10.2 | atomic claim 的 OR-of-AND 原文引文检查，反向事实/否定句截断判不足 | 是逐字证据合同，不是语义真实性判定；未集成自动独立 claim 标注 |
| S10.3 | 知识专属问题无证据/检索故障直接拒答；Agent 返回证据状态；实际来源页可查看 | 有召回的事实支持度仍待独立语义核验；不宣称每个生成 claim 已验证；答案质量与错误拒答暂缓 |
| S11.1 | answerability、source gold、相关等级、证据集、scope 兼容旧 JSON；重切必须显式对齐 | 真实用户金标暂缓 |
| S11.2 | 文档/证据 Recall@1/5/10、Precision@K、Hit Rate、完整证据集及现有 MRR/nDCG；合法备选证据集可独立满足，分母/N 明确，0 相关等级不计入 gold | 真实各题型指标暂缓 |
| S11.3 | 独立 human/calibrated_judge 记录、一致性/争议接口；不信系统自报 supported | 盲标、judge 校准与复核尚未执行，独立答案 N=0 |
| S11.4 | 冻结预测 runner，32 条真实检索输出经独立原文 gold 对齐，输出四种产物；原文件 hash 与 QASPER 协议审核入口 | 本轮只跑合成功能输入；QASPER/真实用户/未知文档新质量运行暂缓，需先转换为明确标注合同 |
| S12.1 | 复用 Debug SQLite 保存不可覆盖坏例快照，默认原文脱敏、版本保留 | 脱敏快照不能直接重放原文，必须显式保留输入 |
| S12.2 | 15 个管线层及 scope/index/label 三类错误的首次失效检查 | 历史缺阶段/版本记录不自动补成已定位，人工根因确认仍保留 |
| S12.3 | 严格冻结 generation/config/model，Graph 库存在检查及实际 Alpha 图坏例回放 diff 通过；版本失配拒绝 | S00–S11 历史质量坏例未全部重放；缺失旧索引/原文的案例保留未定位；不虚报历史修复率 |
| S13.1 | 根 trace、parent、scope hash、generation、通道耗时/IDs、Graph seeds/paths/span；未知 token/cost=null | 不完整的历史事件无法还原；绝对阶段起止时间和完整 answer 树仍需补齐，不能宣称全部请求 100% 覆盖 |
| S13.2 | Companion/Agent 入口 trace 传递，初始化/路由失败及回退保留根 ID；生产 Lazy adapter 透传存活校验 | Studio 独立 Agent 图入口及 EvidenceService 缓存消费链未做本轮全链验证 |
| S13.3 | Studio 成功、失败、取消结果可脱敏持久化，重启可读，新 run 不覆盖旧 run | Companion 路由列表仍为进程内历史；其完整生成/验证快照未统一持久化 |
| S13.4 | Graph trace 及实际 source chunk 展示；修复 StrictMode 重挂载导致页面永远运行中的缺陷；实际页面点击通过 | 三个历史质量坏例仅看 Studio 定位、Trace 开销专项及人工逐句答案核验暂缓 |
| S14.1 | 固定 CI 功能集覆盖范围、过期/缺失源、拒答、图遍历、评测、缓存、持久化等；哈希跨 CRLF/LF 检出真实内容变化 | 历史质量坏例未全纳入，真实用户回归集暂缓 |
| S14.2 | 同数据指纹比较、硬门和 pass→fail 非零阻断；质量比较显式开关，缺值不能通过 | 分层质量/P95 门和生产报告联动未启用 |
| S14.3 | 在真实 GitHub CI 加入冻结功能集；本地 64 项通过，前端页面及合同通过 | 尚未推送，远端 CI 未运行；周期性 holdout/真实导入质量门暂缓 |
| S15.1 | 1000 次并发4混合请求，两轮通过；记录延迟/QPS/CPU/RSS/GPU及全部逐请求错误 | 小型 51 字符 fixture，不证明大库/长文档/多进程容量；RSS 是结束值，cold 模式只含首次初始化而非逐请求冷启动 |
| S15.2 | 有界 embedding LRU/TTL，key 含 scope/generation/model/query-version；重建后旧键不可复用 | 默认关闭；没有检索结果缓存；并发首次 miss 未实现 singleflight；未做质量调优 |
| S15.3 | 每通道协作 deadline、晚结果丢弃、降级原因；重建同时检索时旧证据被拒绝，全通道失败无引用 | 同步/native/GPU 已阻塞调用不能硬取消；后端正式异步/资源隔离尚未实施 |
| S15.4 | 本轮负载无迁移触发依据，保留 Qdrant Local/BM25 JSON/SQLite | 不能根据小型测试宣称本地存储达到生产容量门；服务端 Adapter 试验暂缓 |
| S16.1 | V/B/VB/VR/G/GV/GVB/GVBR 共32真实模型调用通过，逐题/输入/配置/模型/索引记录固定 | rewrite/池/遍历本轮为定向功能测试及既有 S08 记录，不是同条件真实质量消融；holdout 未使用 |
| S16.2 | 本报告区分合成/QASPER/真实用户/未知文档，许可证与回滚可查 | 文档家族 bootstrap、收益/退化与成本结论暂缓，样本不支持这些推断 |
| S16.3 | 默认策略保持，实际 Debug 人工查看、1000 请求复验通过 | 正式生产 Go 暂缓；缺完整质量/容量门，不推广默认策略 |

## 自动及实际功能验证

- 最终 RAG/权限/Companion 回归：`python -m pytest tests/rag tests/agent/test_knowledge_access_contract.py tests/test_rag_debug_companion_trace.py -q`：**603 passed, 3 skipped**，47.42s。三个 skip 是仓库既有 opt-in Docling/Qwen3 模型集成测试；没有新增跳过。
- 随后针对失败/取消持久化、评测坏例导出、跨换行冻结门的补充定向复验：**16 passed**；备选证据集完整性及评测/坏例定向复验另有 **29 passed**。冻结 CI 集再验：`python scripts/check_rag_regression.py --suite ci`：**64 passed**。
- 前端既有整套 **109 文件 / 466 tests passed**；新增 StrictMode 与 Graph 回源后，Trace 定向 **14 passed**，`npm run typecheck:test` 通过。最初多余参数曾使测试脚本末尾类型检查命令失败，改用正确独立命令后通过。
- 修改涉及的45个 Python 文件，相对 HEAD 的 Ruff 诊断差分：**0 新增问题**；历史 lint 不顺手修改。最终 `git diff --check` 通过；前端定向Lint退出0，保留历史React effect提示。
- 真实模型和存储：8组 × 4题 = **32/32 功能通过**，每组3条正例有证据、1条禁止范围负例无证据；启用图的正例均有原文 Graph hit。输入只有一段短文，不能据此推断质量收益。
- 页面复验：最初开发模式 StrictMode 的 mounted 标记不恢复，后端完成后页面仍“运行中”；修复一处 effect 并新增回归后，实际页面成功显示 Graph seeds/paths、completed 与 `chain.txt` 原文。冷启动页面总时间约15.8s，不以此宣称延迟门通过。
- 当前冻结 Graph 案例回放成功，输出 before/after/diff，未将新 generation 冒充旧版本。历史丢失版本拒绝回放。

## S16 同输入功能表

dataset：合成 `chain.txt`，3条正例 + 1条范围负例/方案；独立 source gold 由原始引文和字符位置构造，而非答案自报。机器 RTX 4060 Laptop 8GB，Python 3.11.7 / Torch 2.13.0+cu130。模型 revision、有效配置、generation 及代码指纹见本机 `data/benchmarks/rag-final/verification.json` 和对应 manifest。

下表只证明测量链路工作；正例检索只有一个 chunk，所有排序指标无区分力。**各方案质量结论均暂缓**。方案顺序运行，V 首次加载 embedding、VR 首次加载 reranker，缓存条件不相同；N=4 的 P95 只记录观察值，不能比较生产性能。context token 是本地估算，正例171、负例126，不是模型账单。

| 方案 | Recall@5 | Recall@10 | MRR | nDCG@10 | 完整证据覆盖 | Faithfulness | Citation Accuracy | 观察P95 ms（含首次加载） | Context token/题 |
|---|---:|---:|---:|---:|---:|---|---|---:|---|
| V | 1 | 1 | 1 | 1 | 1 | 暂缓 N=0 | 暂缓 N=0 | 10697.291 | 171/126 |
| B | 1 | 1 | 1 | 1 | 1 | 暂缓 N=0 | 暂缓 N=0 | 0.329 | 171/126 |
| VB | 1 | 1 | 1 | 1 | 1 | 暂缓 N=0 | 暂缓 N=0 | 1.393 | 171/126 |
| VR | 1 | 1 | 1 | 1 | 1 | 暂缓 N=0 | 暂缓 N=0 | 1441.805 | 171/126 |
| G | 1 | 1 | 1 | 1 | 1 | 暂缓 N=0 | 暂缓 N=0 | 31.069 | 171/126 |
| GV | 1 | 1 | 1 | 1 | 1 | 暂缓 N=0 | 暂缓 N=0 | 32.653 | 171/126 |
| GVB | 1 | 1 | 1 | 1 | 1 | 暂缓 N=0 | 暂缓 N=0 | 32.256 | 171/126 |
| GVBR | 1 | 1 | 1 | 1 | 1 | 暂缓 N=0 | 暂缓 N=0 | 90.792 | 171/126 |

QASPER 已知论文、真实用户原文件、未知文档的新效果表：**全部暂缓**。历史分数仍见 S03–S05，不混入本表。181题 holdout 未执行；没有 bootstrap 区间和真实 Graph 净收益结论。

## 1000 请求混合负载

最终复验 `load-v2.json`：真实 embedding/Qdrant/BM25/Graph，小型单文档、并发4、warmup单独计；混合故障与一次并发重建，reranker在该负载中关闭。

| 请求 | 未预期错误 | P50/P95/P99 ms | QPS | CPU sec | RSS结束 | GPU已分配峰值 |
|---:|---:|---|---:|---:|---:|---:|
| 1000 | 0 | 68.609 / 139.766 / 191.850 | 60.482 | 24.406 | 1,987,121,152 B | 1,236,775,424 B |

**有12次预期拒绝**：9次注入全通道失败、3次重建导致版本过期，均无引用，不计为“未预期错误”。49次故障注入中的其余40次按可用通道降级，原因可见。944次 embedding 缓存命中。发布 generation 从 `91160e77…` 切到 `4391bd16…`。第一轮为 P95=150.678ms、QPS=54.521、同样12次预期拒绝，保留旧产物不覆盖。

这一结果通过本轮功能负载检查；**不是生产 P95、错误率或容量承诺**，没有测大库、多进程、长文档持续导入和1000次答案生成。

## 产物和复跑

代码/测试/合成 fixture 与冻结 manifest 可入库；原文件、模型缓存、SQLite、逐题和截图保留在忽略目录 `data/benchmarks/rag-final/`。本轮没有提交或推送，也没有运行远端 CI。

| 本机产物 | 内容 |
|---|---|
| `final-v2/{manifest.json,per_case.jsonl}` | 32条检索/图/重排/上下文功能结果及延迟 |
| `evaluation/{manifest.json,metrics.json,per_case.jsonl,bad_cases.jsonl}` | 独立 source gold 显式对齐、32条冻结预测指标，答案验收 deferred |
| `evaluation-input/{cases.json,predictions.json,chunks.jsonl}` | 上述评测输入，合成标签来源明确 |
| `load-v2.json`、`load.json` | 两轮1000混合请求全量记录 |
| `replay/{case.json,config.json,diff.json}` | 明确保留输入的当前 generation Graph 回放 |
| `verification.json` | 代码/产物 SHA、基准提交、机器记录；本轮非已提交 release |
| `debug-studio-acceptance.jpg`、`debug-studio-source.jpg` | 实际页面及来源查看证据 |

在 `conda activate aitrans` 后，使用以下入口。已完成产物不可覆盖，复跑指定新输出目录；负载输出需指定新文件以保留历史。

```powershell
python scripts/check_rag_regression.py --suite ci
python scripts/run_rag_final_benchmark.py --manifest docs/development/rag-production-luna/regression-manifest.json --output data/benchmarks/rag-final/new-final
python scripts/load_test_rag.py --scenario mixed --queries 1000 --output data/benchmarks/rag-final/new-load.json
python scripts/eval_rag_production.py --dataset data/benchmarks/rag-final/evaluation-input/cases.json --predictions data/benchmarks/rag-final/evaluation-input/predictions.json --catalogue data/benchmarks/rag-final/evaluation-input/chunks.jsonl --output data/benchmarks/rag-final/new-evaluation
python scripts/replay_rag_bad_case.py --case-json data/benchmarks/rag-final/replay/case.json --runtime-root data/benchmarks/rag-final/runtime --config data/benchmarks/rag-final/replay/config.json --output data/benchmarks/rag-final/new-replay.json
```

重建后旧 replay case 的 generation 失配会拒绝，这是预期保护；恢复对应旧索引/原文才能重放，不能改 case 中的旧 generation 来冒充原实验。

## 必要修改文件与原因

路径以仓库根为基准；每项均服务于本轮任务。未列出的 Agent/文档/依赖文件是原有工作区变更，本轮未处理。

| 文件 | 必须修改的原因 |
|---|---|
| `backend/rag/config.py` | 增加向后兼容、默认关闭的输入/截止时间/缓存设置 |
| `backend/rag/retrieval_service.py` | 版本缓存、通道晚结果拒绝、根Trace及引用前源存活检查 |
| `backend/rag/rerankers/qwen3.py` | 输入截断、分批 deadline 及真实失败回退依据 |
| `backend/rag/evidence_builder.py` | 证据原文哈希/位置保护和 provenance 透传 |
| `backend/rag/evidence_selection.py` | 修复证据切片仍保留父 span/hash 的错误 |
| `backend/rag/context_builder.py` | 移除被预算截掉证据的引用授权及不完整引用组 |
| `backend/rag/citation_service.py` | 引用前校验版本化 excerpt/hash |
| `backend/rag/evidence_verifier.py` | 检查每个 atomic claim 的完整逐字证据集合 |
| `backend/rag/evaluation_dataset.py` | source gold/answerability/证据集合与独立测量输入合同 |
| `backend/rag/evaluation.py` | 修复 pre/post 测量，新增文档/证据/完整性及独立答案指标 |
| `backend/rag/evaluation_protocol.py` | 独立标注与 judge 校准记录协议 |
| `backend/rag/observability.py` | 图事件、根关联、scope/generation/路径及未知成本记录 |
| `backend/rag/cache.py` | 可选有界、按版本隔离的 embedding 缓存 |
| `backend/rag/bad_cases/models.py` | 坏例阶段/版本/修复状态合同 |
| `backend/rag/bad_cases/store.py` | 复用快照存储、默认脱敏 |
| `backend/rag/bad_cases/triage.py` | 逐层首次证据丢失定位 |
| `backend/services/rag_debug_service.py` | 配置切换保留Graph、正确重排列表/耗时、Graph阶段及终态快照 |
| `backend/services/rag_debug_store_service.py` | 在现有SQLite增加不可覆盖快照表 |
| `backend/services/companion_chat_service.py` | 知识专属无证据拒答、引用前验证及回退Trace |
| `backend/agent_tools/knowledge.py` | Agent检索/读取消费点存活校验、证据状态和Trace |
| `backend/api/agent_dependencies.py` | 生产Lazy adapter必须透传新增存活检查，避免被适配器隔断 |
| `backend/agent_core/events.py` | 允许新增rag_graph_completed事件 |
| `backend/models/agent_tools.py` | 接纳图事件及向后兼容的证据状态字段 |
| `backend/models/rag_debug.py` | Graph阶段类型合同 |
| `apps/desktop/src/api/rag-debug.ts` | Graph配置类型兼容 |
| `apps/desktop/src/features/settings/RagDebugStudioTrace.tsx` | 图阶段/来源查看及实际发现的StrictMode挂载缺陷 |
| `apps/desktop/src/features/settings/RagDebugStudioTrace.test.tsx` | StrictMode与Graph source选择回归 |
| `.github/workflows/ci.yml` | 接入冻结功能回归阻断 |
| `scripts/eval_rag_production.py` | 对齐source gold、审核来源版本，输出完整评测产物 |
| `scripts/replay_rag_bad_case.py` | 固定generation/config/model及Graph回放 |
| `scripts/check_rag_regression.py` | 冻结测试/同数据报告及硬门阻断，处理Git换行差异 |
| `scripts/load_test_rag.py` | 记录完整混合负载及资源/异常，不隐藏失败 |
| `scripts/run_rag_final_benchmark.py` | 复用真实运行时执行8组功能矩阵及故障操作 |
| `tests/rag/test_context_builder.py` | 预算外引用不进入allowlist回归 |
| `tests/rag/test_evidence_builder.py` | 正确span与篡改excerpt回归 |
| `tests/rag/test_qwen3_reranker_provider.py` | max_length/分批deadline回归 |
| `tests/rag/test_rag_evaluation.py` | 完整post池指标和独立supported真值回归 |
| `tests/rag/test_rag_observability.py` | 根关联及新图事件合同 |
| `tests/test_rag_debug_companion_trace.py` | Graph跳过阶段与Companion Trace合同 |
| `tests/rag/test_evidence_verifier.py` | 完整证据、反向事实、截断、缺要求回归 |
| `tests/rag/test_production_metrics.py` | 独立手算、分母、grade0与自报支持无效 |
| `tests/rag/test_production_eval_runner.py` | 重切/hash/原文件/不可覆盖/正确空答案导出回归 |
| `tests/rag/test_bad_case_workflow.py` | 18种失效层、脱敏不可覆盖、冻结版本拒绝 |
| `tests/rag/test_graph_trace.py` | 图根关联与成功/失败/取消重启持久化 |
| `tests/rag/test_rag_cache.py` | TTL/LRU/scope/generation/model缓存隔离 |
| `tests/rag/test_regression_gate.py` | 退化阻断和CRLF/LF等价但内容改变失效 |
| `tests/rag/test_load_harness.py` | 负载错误如实计数和有效边界 |
| `tests/rag/test_rerank_pool.py` | 8/12/20池范围与最终返回上限 |
| `tests/rag/regression/test_grounding_regressions.py` | 发布后过期、缺失源、知识拒答、deadline及Lazy adapter回归 |
| `tests/rag/regression/fixtures/{chain.txt,graph-extraction.json}` | 冻结合成原文及先前真实provider抽取结果，供可复跑功能矩阵 |
| `docs/development/rag-production-luna/regression-manifest.json` | 固定功能输入/配置/测试哈希，声明效果暂缓 |
| `docs/development/rag-production-luna/REMAINING-EXECUTION-PLAN.md` | 明确最小修改规范、目标和整合执行顺序 |
| `docs/development/rag-production-luna/{STATUS.md,OPEN-ISSUES.md}` | 更新真实验收状态和保留缺口 |
| `docs/development/rag-production-luna/{final-benchmark.md,architecture-decisions.md}` | 验收证据、每个修改的必要性与回滚依据 |

