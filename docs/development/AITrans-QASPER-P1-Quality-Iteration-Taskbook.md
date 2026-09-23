# AITrans QASPER P1 质量迭代开发任务书

> 状态：待实施；基线提交 `e2ac8838658133a4f83086b3cf486f488840bbf8`；制定日期：2026-09-24。
> 范围：改进已实现的单论文 QASPER RAG 链路。P2 的 ScholarQABench、跨论文 KG/PPR 和引用图另立任务。

## 1. 目标与当前证据

目标是让系统在**找到了正确论文证据以后**，把更少、更准确的证据交给回答器，生成简短且有依据的答案。所有改进必须在真实 QASPER 数据上与同题基线比较；单元测试和模拟 provider 只用于定位实现错误，不能替代真实冒烟。

公开数据源为 [QASPER v0.3](https://qasper-dataset.s3.us-west-2.amazonaws.com/qasper-train-dev-v0.3.tgz)。本仓库的 `validation` 对应官方 `dev`：281 篇论文、1005 题。原始 JSON SHA256 为 `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93`。准备记录见 `data/benchmarks/qasper/manifests/qasper-validation-prepared.json`。QASPER 的官方脚本分别计算 Answer F1 与 Evidence F1；Yes/No 和 Unanswerable 是明确的答案形式，Evidence F1 按证据段落文本集合计算：[官方 evaluator](https://github.com/allenai/qasper-led-baseline/blob/main/scripts/evaluator.py)。

2026-09-24 真实冒烟基线：`data/benchmarks/qasper/results/real-smoke-final-e2ac883/`，seed 42，20 题、18 篇论文、312 个 chunk，20/20 运行成功，0 个运行错误；采用本地 Qwen3-Embedding-0.6B、Qwen3-Reranker-0.6B、Qdrant/BM25 和已配置的 DeepSeek。

| 指标 | 20 题基线 | 解释 |
| --- | ---: | --- |
| Recall@10 | 0.9688 | 仅 16 道有可映射 Gold 的题参与 |
| Gold Evidence Recall@10 | 1.0000 | Gold 已进入前十候选 |
| Evidence Precision@10 | 0.0788 | 返回的无关段落较多 |
| 官方 Evidence F1 | 0.0681 | 20 题官方口径 |
| 官方 Answer F1 | 0.0735 | 当前用户可见长回答的官方口径 |
| 平均回答上下文 | 3937.6 tokens | 约 20 个候选块进入当前链路 |
| Unsupported Claim Rate | 0.4750 | 95/200 个被核验 claim 标记为 unsupported |
| 检索延迟 p95 | 1686 ms | GPU 暖缓存运行 |
| 回答生成延迟 p95 | 2330 ms | DeepSeek，包含网络波动 |

这 20 题只用于冒烟和故障发现，不作为效果晋级依据。已跑过的 5 题证据选择对比中，`rerank_top_k` 的 Evidence F1 高于当前抽取式 `evidence_selection`；不得预设抽取式方案一定胜出。

### 论文仓库的代码对照（2026-09-24 核对）

| 官方实现与实际代码 | 可迁移的机制 | AITrans 中的落点及验证 |
| --- | --- | --- |
| [QASPER evaluator](https://github.com/allenai/qasper-led-baseline/blob/main/scripts/evaluator.py)：答案先规范化再算 token F1；证据按段落文本集合算 F1；多标注取最高分，且单列 `Yes`、`No`、`Unanswerable`。 | 保持官方评分语义，明确答案类型与证据文本。 | Q1-0 锁定官方 all/text-only 两种口径；Q1-2 用真实布尔题、不可回答题核验 answer contract，严禁改评分器追分。 |
| [PaperQA2 `Docs.aget_evidence`](https://github.com/Future-House/paper-qa/blob/main/src/paperqa/docs.py)：先检索 `evidence_k` 个文本，再逐段生成与问题相关的证据上下文，过滤非正相关评分并去重；[配置](https://github.com/Future-House/paper-qa/blob/main/src/paperqa/settings.py)另设 `answer_max_sources`。 | 候选召回、证据筛选、回答来源数量是独立控制量。 | Q1-1 保留 Top20 检索池，独立记录入选证据和回溯 offset；对 Top5/8/10 与抽取器做同题消融。PaperQA2 的长答案默认值不直接套用于 QASPER。 |
| [SciRAG `initial_critic`/`gap_critic`](https://github.com/yale-nlp/SciRAG/blob/main/shortans/scifact/pipe.py)：判断现有回答是否足够；不足时解析补充查询，沿查询树递归检索，并以 `max_depth` 限制深度。 | 缺口驱动的追加检索、可解释的停止条件、轮次预算。 | Q1-3 将 EvidenceRequirement 缺口、每轮新增证据、停止原因写进 trace；用真实问题证明至少一次追加检索和一次正确停止。其论文级引用图扩展属 P2；不复制依赖自由文本标记的脆弱解析。 |
| [RAPTOR `tree_retriever.py`](https://github.com/parthsarthi03/raptor/blob/master/raptor/tree_retriever.py)：同时提供全树节点排序后的 token 预算选取，以及自上而下逐层选取；[入口](https://github.com/parthsarthi03/raptor/blob/master/raptor/RetrievalAugmentation.py)暴露 `collapse_tree`、`top_k`、`max_tokens`。 | 树摘要与叶子证据是不同检索路径，需同时约束上下文预算。 | Q1-4 用已实现的 R0–R3 比较 flat、mixed、collapsed、hybrid；分别记录树缓存、摘要命中、叶子展开、预算和真实 Answer/Evidence F1。摘要命中不能代替可引用的原文证据。 |

这些代码是设计参照，不是 AITrans 已达到相同效果的证据。外部仓库中的语料规模、答案长度及检索作用域与 QASPER 不同；每项机制是否启用都由下文同题真实数据消融决定。

## 2. 实验约束

1. **同题配对。** 每一组 baseline/candidate 必须具有完全相同的 question ID 集合、原始数据 SHA、qrels 版本和 known-paper 过滤条件。当前 `sample_qasper_dataset` 对不同 limit 分别随机抽样，所以 seed 42 的 20 题不能被当作 100 题的子集。比较工具须拒绝只取交集的静默比较。
2. **不泄漏 Gold。** Gold 答案、答案类型、证据段落和错误标签仅用于离线采样核对、评估与分析；运行时检索、选证和回答策略都不得读取它们。
3. **明确三层对象。** 记录 retrieval candidate pool、送入回答器的 selected evidence、官方评估的 predicted evidence。前 20 个候选的召回率不能冒充最终引用证据的精确率；证据不得默认扩张回全部候选。
4. **固定可复现配置。** 每个 run 保存 git SHA、数据/题目清单 SHA、模型与路由、prompt/policy 版本、索引 fingerprint、是否缓存命中、硬件、provider 调用次数、token/延迟和错误。Query-time 策略变化复用索引；改变 chunking、embedding 或实际向量化方法时必须更新 fingerprint 并重建。
5. **保持数据隔离。** 仅在 `data/benchmarks/qasper/` 下写 Qdrant、BM25、manifest 与运行产物；每题必须以其 `document_id` 限定论文。不得将 API key、完整私有配置或用户 Knowledge 数据写进报告。
6. **保留两种评估口径。** 官方 all-evidence 与 text-evidence-only 同时输出；`FLOAT SELECTED` 图表证据不得当成普通文本段落。多标注答案继续按官方 evaluator 规则计算。
7. **区分质量和可靠性。** 运行状态 `complete`、0 error 只是功能门槛；Answer/Evidence F1、错误类别、人工审查和成本是独立质量门槛。禁止靠一律弃答或直接裁剪评测字符串提高单个指标。

### 固定样本

- 固定清单位于 `backend/rag/benchmarks/qasper/sample_ids/`，由 `scripts/freeze_qasper_p1_sample_ids.py` 生成；每个 ID 文件及其生成规则的 SHA 都记录在同目录 manifest。Smoke20 保持现有 seed 42 的样本，Dev100 使用 seed 42 的独立抽样，Holdout905 是 Dev100 的补集。
- Smoke：固定 ID 文件中的 20 题，用于冒烟和故障发现。
- Dev：固定 ID 文件中的 100 题，作为调参与策略选择集。
- Holdout：validation 中不属于 Dev100 的 905 题；仅在方案冻结后评估。完整 1005 题可做规模与稳定性检查，但它包含 Dev100，**不是独立测试集**。
- 另设少量真实 challenge cases，覆盖 boolean、unanswerable、多段落、多 section、证据缺失和二次检索。该清单在实验开始前冻结；允许用 Gold 做离线分层，但运行时不可使用 Gold。

## 3. 全阶段冒烟规范

在项目根目录使用安装了 PyTorch、sentence-transformers、Qdrant client 的 `aitrans` Python 环境运行。每个阶段先做单元/fixture 集成检查，再做**真实数据端到端冒烟**。GPU/LLM 测试保持 opt-in，不放进普通 CI。

每次真实冒烟至少核对：

1. 原始数据 SHA 与样本 ID 清单一致；manifest 指向当前提交及本次 policy 版本。
2. `status == complete`、`error_count == 0`、预测/trace/qrels 数量相同，`errors.jsonl` 为空。
3. 每个最终 chunk 都来自该问题的论文；dense、BM25、rerank 阶段均有实际记录；需要结构化/多轮的变体还需有对应 trace。
4. 回答模式下全部题目有真实 provider 调用或明确的策略弃答；记录失败和重试次数，不把 retrieval-only 的 Answer F1 当作生成效果。
5. selected evidence 的源 chunk、精确 offset、paragraph ID 与输出文本可回溯；无跨论文证据、无失效引用。
6. 同一指标的分母、无 Gold 题数、异常题 ID、p50/p95、上下文 token、provider 调用次数均进入报告。
7. 检索质量冒烟只判断是否退化或出现异常；效果晋级由同题 Dev100/holdout 对比决定。

每阶段交付 `results/<run-id>/` 原始产物、摘要 JSON/Markdown、失败题清单及本地可复跑命令。原始数据与完整回答仍留在已忽略的 benchmark 目录；提交可公开的摘要、代码和测试。每完成一个阶段，**仅暂存本阶段文件，提交并推送到 `WebReBuild`**；已有的其他未提交工作不得混入提交。

## 4. Q1-0：测量契约与 100 题基线

### 实施

- 固定 Smoke20、Dev100、Holdout905 的 question ID 文件和 SHA；保存分层计数。为所有 benchmark/ablation CLI 增加 `--question-ids-file`，按文件精确执行指定题目，并拒绝不存在、重复或跨 split 的 ID。新建严格比较入口（建议 `scripts/compare_qasper_runs.py`）：校验两次运行题目集合完全相同、source/qrels 一致、paper scope 正确，再调用已有 `paired_bootstrap`，输出 Answer F1、Evidence F1、Recall@10、MRR 的候选减基线 delta 与 95% CI。当前 bootstrap 函数只取交集，不能直接作为协议校验器。
- 新建运行审计入口（建议 `scripts/check_qasper_run.py`），自动执行第 3 节不变量，返回非零退出码并列出问题 ID。增强 manifest 以保存 answer provider、prompt/policy、采样清单和成本字段。
- 把 20 题基线结果冻结为参考，不更改官方 evaluator 的算法；100 题基线必须用当前产品回答链路真实生成答案。人工复核 20 个代表性答案，归类“证据过宽、正确但过长、错误 Yes/No、错误弃答、无支持 claim、映射错误”。

### 现有可运行命令

```powershell
python scripts/prepare_qasper.py prepare --split validation
python scripts/run_qasper_benchmark.py --mode smoke --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-smoke20-seed42.txt --run-id p1q0-smoke-current
python scripts/run_qasper_benchmark.py --mode dev --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt --run-id p1q0-dev-current
python scripts/evaluate_qasper.py --run-directory data/benchmarks/qasper/results/p1q0-dev-current
```

Q1-0 实现后统一增加以下审计命令；入口应将错误写到标准错误并返回非零退出码，比较报告默认保存在 candidate 的 `comparison/` 下：

```powershell
python scripts/check_qasper_run.py --run-directory data/benchmarks/qasper/results/p1q0-dev-current --output data/benchmarks/qasper/results/p1q0-dev-current/audit.json
python scripts/compare_qasper_runs.py --baseline data/benchmarks/qasper/results/p1q0-dev-current --candidate data/benchmarks/qasper/results/p1q0-dev-current --resamples 5000 --seed 42
```

### 验收

- 两档真实运行均 0 error、known-paper 越界 0、manifest 与题目清单一致；Dev100 有 100 条预测、trace 与 qrels。
- 比较入口对错样本、错 source SHA、缺题、重复题一律失败；同题自比较所有 delta 为 0。
- 输出按答案类型、有/无可映射 Gold、Local/Cross-section/Global 分组的基线，以及至少 20 题人工故障清单。未完成这一步不得挑选后续“优胜”策略。

## 5. Q1-1：证据收窄与精确映射

### 实施

- 在现有 `backend/rag/benchmarks/qasper/runner.py` 路径中把候选召回上限与最终 evidence 上限解耦。保留 Top20 候选用于检索分析，分别比较 `rerank_top5`、`rerank_top8`、`rerank_top10`、现有 query-conditioned excerpt selection；原样保留 current20 控制组。CLI 增加可复现的 `--quality-profile` 或等价的版本化配置文件，明确记录参数。
- 最终 `predicted_evidence` 必须来自送给回答器的**选中证据**；对 excerpt 使用原文精确 offset 找到覆盖的 paragraph，去重并验证文本逐字来自源 chunk。若找不到有效摘录，显式记录 `no_valid_excerpt` 并采取受控回退或弃答，不悄悄输出全部候选。
- 把多段落完整覆盖、Evidence Precision/F1、平均上下文 token 和 answer grounding 一起看。真实 5 题初测显示当前 extractor 可能损失 recall，因此先和简单 rerank Top-K 公平比较，再决定是否改 extractor 评分。

### 必要检查

- 单元/fixture：重复证据去重、跨 paragraph 的 offset、空摘录、图表标记、多标注 Gold、同论文过滤、索引复用、受控回退。
- 现有 CLI 可先跑真实 retrieval-only 三路对照：

```powershell
python scripts/run_qasper_evidence_selection_ablation.py --mode smoke --seed 42 --retrieval-only --suite-id p1q1-smoke-retrieval
python scripts/run_qasper_evidence_selection_ablation.py --mode dev --seed 42 --retrieval-only --suite-id p1q1-dev-retrieval
```

- 实施新 profile 后，对 current20 与入围的至少两个策略分别跑相同 Smoke20 的**真实回答**，再跑 Dev100。运行审计必须核实 selected evidence 真正进入 `GroundedContextBuilder`，不能只改 evaluator 输出。

### 验收

- 真实 Smoke20 全部 complete、0 跨论文/offset/引用错误；selected evidence 数量与 token 上限符合 profile，检索 Top20 trace 完整。
- 在 Dev100 上入围策略的官方 Evidence F1 与 Evidence Precision 优于同题 current20；同时 Gold Evidence Recall@5 的绝对下降不超过 0.03。若 trade-off 超限，保留对照结果并修复选证策略，不晋级。
- 记录 Answer F1、Unsupported Claim Rate、p95 与每题 LLM 调用次数；LLM extractor 若无明确质量收益或调用成本过高，不作为默认策略。

## 6. Q1-2：直接答案、布尔题与弃答协议

### 实施

- 新增版本化 answer contract，要求模型先给直接、简短的答案，再以独立字段给引用/补充说明。用户可见的最终答案与提交官方评分的 answer 字段必须语义一致；保留原始模型输出和核验后的最终输出供审计。禁止根据 Gold 类型或参考答案在评估后裁剪/重写。
- 布尔题需明确 `Yes`/`No`，无足够证据时明确 `Unanswerable`；不能把“未在检索结果看到”直接当成论文不可回答。类型判断只可依赖问题及检索证据，不能读取 Gold。
- 用同一份 Q1-1 选中证据比较旧/新 answer contract，确保答案格式变化不被证据变化混淆。统计错误弃答率、漏弃答率、各答案类型 Answer F1、引用有效率与 token。

### 必要检查

- 单元/fixture：结构化输出校验、解析失败安全回退、Yes/No 歧义、引用分离、空证据仍先检索、原始/最终答案留存。
- 真实 Smoke20 必须同时包含当前固定样本和冻结的 boolean/unanswerable challenge cases，运行实际 DeepSeek 回答，逐题核对输出与 citation。
- 同题 Dev100 运行旧/新 contract，调用严格比较入口；人工审阅至少 20 个分歧题，尤其查看 F1 提高是否只是格式缩短，而核心事实仍错误。

### 验收

- Smoke20 0 运行错误、0 无效引用、无 Gold 泄漏；boolean 输出可规范解析，弃答可规范解析。
- Dev100 的官方 Answer F1 上升，官方 Evidence F1 不因 answer contract 变化而下降；布尔/不可回答题的人工事实判断不得退化。只提高 token F1 而引入事实错误不能晋级。

## 7. Q1-3：依据核验与有条件二次检索

### 实施

- 在已选证据上核验回答 claim。对无支持 claim 优先重写为可证实的简短答案；仍无证据时明确弃答并保留 reason code。记录核验前后文本、claim 数、支持比例、回退、引用失效与额外 LLM 调用。
- 改善 EvidenceRequirement / Evidence Gate 的触发条件：当必须的信息缺失时允许限额二次检索；当已有完整证据时停止。最多三轮，保留每轮 query、novel chunk、Gold sufficiency 的离线标签和耗时。Gold 只在运行结束后评分。
- 在固定 Smoke20 之外冻结一组真实 challenge cases，确保至少有一次**实际**二次检索及一次正确停止。如果真实样本没有触发，不得仅用 mock 测试宣称该路径通过。

### 必要检查

- 单元/fixture：无依据 claim、假引用、空证据、重复检索、三轮上限、premature stop 与 unnecessary retrieval。
- 现有真实对照可先运行：

```powershell
python scripts/run_qasper_adaptive_retrieval_ablation.py --mode smoke --seed 42 --retrieval-only --suite-id p1q3-smoke-adaptive
python scripts/run_qasper_adaptive_retrieval_ablation.py --mode dev --seed 42 --retrieval-only --suite-id p1q3-dev-adaptive
```

- 新核验策略实施后，对 current 与 candidate 进行 Smoke20、challenge cases、Dev100 的真实回答；人工抽查至少 20 条被改写或弃答的 case。

### 验收

- 真实二次检索、正确停止、回退与弃答路径均有成功 trace；0 跨论文、0 无效引用、0 超出轮次上限。
- Dev100 的 Unsupported Claim Rate 相比 Q1-0 基线下降，目标 ≤0.25；人工复核不得发现因核验而新增的错误事实或明显错误弃答。报告 Gold sufficiency、Premature Stop Rate、Unnecessary Retrieval Rate 与 p95/调用成本，不以低支持率换取一律弃答。

## 8. Q1-4：RAPTOR 树检索的质量消融

### 实施

- 复核已实现的 R0（当前 flat/structural）、R1（leaf 与 summary 混合）、R2（summary 命中后展开叶子）、R3（hybrid 加 summary 后 rerank）。确保四路检索相同论文、相同固定问题清单、相同叶子索引与回答模型；摘要树 fingerprint 要包含叶子、embedding、聚类、summary provider/prompt 等影响树结构的配置。
- 分开比较已实现的 extractive summary 和 LLM summary；前者作为低成本对照，后者只在真实数据上证明额外收益后考虑启用。Q1-4 四路回答都固定同一 Q1-1 选证策略与 Q1-2 answer contract，避免把树检索收益与其他策略变化混在一起。Query-time 参数实验复用树缓存，建树与回答成本分别计量。摘要节点只能帮助检索；官方 predicted evidence 必须映射回原文叶子/paragraph，不能直接拿生成摘要当 Gold 段落。
- 按 Local、Cross-section、Global、Unanswerable 及 Overall 报告 Recall@10、Gold Evidence Recall、官方 Evidence/Answer F1、上下文 token、树构建/缓存命中、检索和端到端 p95、每题 provider 成本。检查 Global 收益是否伴随 Local 退化。

### 必要检查

- 单元/fixture：摘要节点到叶子/paragraph 映射、同论文约束、空树回退、树 fingerprint 变更失效、同配置缓存复用、token 预算、重复叶子去重。
- 先运行真实 Smoke20 和 Dev100 的四路 retrieval-only 对照：

```powershell
python scripts/run_qasper_raptor_ablation.py --mode smoke --seed 42 --retrieval-only --summary-provider extractive --suite-id p1q4-smoke-retrieval
python scripts/run_qasper_raptor_ablation.py --mode dev --seed 42 --retrieval-only --summary-provider extractive --suite-id p1q4-dev-retrieval
```

- 随后用相同固定问题与真实 DeepSeek，对 R0 和最多两个入围策略跑 Smoke20、Dev100 完整回答。若比较 LLM summary，另跑相同问题清单的 `--summary-provider llm`；确认缓存首次构建与再次复用都可审计。不得把 retrieval-only 的回答分数当成生成收益。

### 验收

- Smoke20 四路 complete、0 跨论文/失效叶子引用；R1–R3 的树摘要命中与展开 trace 完整，第二次同配置运行命中树缓存。
- Dev100 只有在官方 Answer F1 或 Evidence F1 有同题收益、另一项无明确退化，且 Global/Cross-section 的提升足以覆盖成本时，才允许 RAPTOR 变体进入 Q1-5 候选。否则保留 R0 为默认，并保存负面消融结果；实现存在不等于应默认启用。

## 9. Q1-5：同题统计验证、完整规模复跑与晋级决定

### 实施

- 冻结 Q1-1 至 Q1-4 产生的一个候选配置；若 Q1-4 未达到入围门槛则继续使用 R0。严格对齐 Dev100 的 baseline/candidate 后，用既有 `paired_bootstrap` 做至少 5000 次同题重采样，seed 42，报告四项核心 delta 与 95% CI；生成模型有波动时，同配置额外重复运行，报告方差。
- 在冻结后对完整 validation 1005 题真实运行 baseline 与 candidate；**单独报告 Holdout905** 的官方 Answer/Evidence F1、retrieval、groundedness、成本/延迟及分层结果，并对 Holdout905 单独做严格配对 bootstrap。1005 总体值可展示，但不能代替独立 Holdout905 判断。
- 建立逐题差异表：新解决、旧正确新错误、引用不实、Gold 缺失、无答案、float evidence、长尾延迟。产物保存全部 run ID、manifest、指标、CI、人工审查清单与决策。

### 必要检查

- Smoke20：完整端到端复跑，0 error，准确记录当前 git SHA、profile、模型和数据哈希。
- Dev100：相同 question IDs、相同索引 fingerprint（仅 Query-time 变化时）、模型路由和 qrels；严格配对比较。
- Full1005：两组都完整、0 越界/失效引用；报告 Holdout905 与 Dev100 分开统计。真实 GPU/LLM 运行可分批恢复，但不得把未完成 run 标为 complete。

### 晋级门槛

同时满足以下条件才把候选标为 P1 质量改进，并考虑开始 P2：

1. Holdout905 官方 Answer F1 和 Evidence F1 均高于同题基线；至少主要收益指标的 paired 95% CI 下界大于 0，其余核心指标不能出现明确负向 CI。
2. Gold Evidence Recall@10 绝对下降不超过 0.02；Unsupported Claim Rate 比基线下降且最终目标 ≤0.25；人工抽查无严重跨论文引用或系统性错误弃答。
3. 0 运行错误、0 论文作用域违规、0 无效源 offset；所有策略的 `errors.jsonl`、manifest、trace、官方指标与比较结果一致。
4. 候选的端到端 p95 和每题 provider 调用成本均已报告；默认策略的 p95 不超过同环境基线 2 倍。若超过，必须有明确的质量收益和单独的成本决策，不能静默晋级。
5. 若任一条件未满足，保留完整失败报告，回到对应阶段修复并重新用冻结样本复跑；不启动 P2 以掩盖单论文链路问题。

## 10. 预计文件与交付

| 位置 | 任务 |
| --- | --- |
| `backend/rag/benchmarks/qasper/runner.py`、`index.py` | 候选/最终证据分离，answer contract 接线，trace 与缓存一致性 |
| `backend/rag/evidence_selection.py` | 摘录与评分改进，精确 offset/paragraph 映射 |
| `backend/rag/raptor/`、`scripts/run_qasper_raptor_ablation.py` | R0–R3 树检索消融、树缓存 fingerprint 与原文证据映射 |
| `backend/rag/benchmarks/qasper/evaluator.py`、`statistics.py` | 分层、严格配对前置校验、质量与成本统计 |
| `scripts/run_qasper_benchmark.py`、各 ablation CLI | 版本化质量 profile 与固定题目清单入口 |
| 计划新增 `scripts/check_qasper_run.py`、`scripts/compare_qasper_runs.py` | 实际运行审计与严格同题比较 |
| `tests/rag/benchmarks/` | 每阶段确定性单元/fixture 集成覆盖 |
| `data/benchmarks/qasper/` | 真实数据索引、predictions、traces、metrics、comparison、人工审查原始记录；保留忽略规则 |

每阶段提交信息建议 `feat(qasper-p1-quality): <阶段目标>` 或 `fix(qasper-p1-quality): <实际缺陷>`，推送 `WebReBuild` 后在阶段报告写入提交 SHA、真实 run ID 和验收结论。

## 11. 边界

本任务书不把 P2 的跨论文 KG/PPR、Citation Graph 或 ScholarQABench 加进 QASPER 主结论。QASPER 本身是针对给定研究论文的问答；跨论文多跳能力需要第二个具备相应 Gold 的基准单独验证。关于 QASPER 的任务定义见[原始论文](https://aclanthology.org/2021.naacl-main.365/)。本方案以 AITrans 现有链路和官方 QASPER evaluator 为准，不照搬外部实现。
