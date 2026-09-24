# QASPER P1 Q1-3：自适应检索与依据核验阶段报告

> 状态（2026-09-24 更新）：Q1-3 真实回答复测和人工审查已完成，但质量门未通过，不晋级到 Q1-4。原代码检查点 `ece05455bcb0b27736d7c23cc813ce39b861bf22` 已推送；本报告记录额度恢复后的完整对照、失败门槛和当前实现边界。

## 本阶段改动

- 将 Q1-1 `p1q1-evidence-selection-v2` 与 requirement-aware 二次检索组合。Gate 只检查最终供回答器使用的 Top5 选证；原先按完整 Top20 候选判断覆盖会高估证据充分性。
- 在多轮 trace 中保留累积 Top5 上下文、gate chunk IDs、候选池大小、停止原因和最终选证结果；离线 Gold sufficiency 评估按 cumulative context 处理，避免错误合并轮次上下文。
- 自适应检索实验 CLI 支持固定质量 profile、选证 variant 与可选 answer contract；suite manifest 保存 profile hash、answer contract 和分 variant 指标。变体限于 `one_shot` 与 `requirement_aware`。
- Grounded answerer 保存修复稿 claim 数；评估器分别报告初稿、修复稿与最终放行答案的 Unsupported Claim Rate、claim 数和修复成功数，避免安全弃答后的零 claim 分母掩盖初稿失败。
- 所有新检索行为保持在 QASPER benchmark opt-in 路径中；没有将 requirement-aware 默认启用到线上 RAG。

## 可复现数据与配置

- 数据集：公开 QASPER v0.3 validation；source SHA256 `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93`。
- Smoke28：`backend/rag/benchmarks/qasper/sample_ids/validation-p1q2-smoke28-seed42.txt`，含固定 Smoke20 和 8 道布尔/不可回答挑战题；样本 hash `32d4c96711952faba2b9d84f3591c8a55ed91902348ad5e02af055dc41434bb0`。
- Dev100：`backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt`；样本 hash `6dd1fb858c30efc9a42292bdd9fcfe55043f8dcfbc67dcf4cd500eb678bea369`。
- 两组均固定 Q1-1 `p1q1-evidence-selection-v2`，profile SHA256 `23234a32c85878ad5b7baca32ff87d939914d7cfb1ac6a520eccb42ba1b75fc2`。以下说明只适用于额度恢复前的初始检索/partial answer runs：当时未启用 Q1-2 contract，以观察已有 grounded verification/repair 路径。
- 初始检索 runs 的 manifest `git_sha` 为 `dd41453d36f8e4f4a663d54cca25927e39040b29`。额度恢复后的完整问答 runs 使用当前工作树中的 answer recovery 代码和 Q1-2 contract v1；manifest 记录的 Git HEAD 为 `418204a6ac27a512764657e30d52ed6280549054`，当前工作树实验改动将在本阶段审计提交中保存。

## Smoke28 与 Dev100 检索结果

四个检索 run 的 `check_qasper_run.py --retrieval-only` 审计均为 `ok=true`、issues 为空、0 运行错误和 0 无效 selected evidence offset。Smoke28 覆盖 24 篇论文，Dev100 覆盖 86 篇论文。one-shot 与 requirement-aware 使用相同题目、Q1-1 profile 和索引。

| 数据 / 变体 | Gold Evidence Recall@5 | Selected Evidence F1@5 | Official Evidence F1 | 上下文 token 均值 | RAG p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Smoke28 one-shot | 0.8333 | 0.2031 | 0.15236 | 913.3 | 1228 ms |
| Smoke28 requirement-aware | 0.8333 | 0.2031 | 0.15236 | 916.5 | 1924 ms |
| Dev100 one-shot | 0.8002 | 0.1839 | 0.14524 | 999.5 | 1534 ms |
| Dev100 requirement-aware | 0.8002 | 0.1839 | 0.14524 | 999.5 | 1560 ms |

Requirement-aware Smoke28 有 2/28 题触发二次检索；Dev100 有 3/100 题触发。所有第二轮都没有增加 novel chunk，因此 Gold context coverage 和选证指标均未提升。Smoke28 gate 的 TP/FP/FN/TN 为 17/3/0/2，precision 0.85、recall 1.00；Dev100 为 63/18/2/2，precision 0.7778、recall 0.9692。Dev100 有 18 个 premature-stop false positive。当前词面 EvidenceRequirement gate 误停较多，不能作为质量改进晋级。

结论：该组合在检索质量上与 one-shot 打平；Smoke28 p95 明显增加，Dev100 也无质量收益。当前启用 requirement-aware 只会增加复杂度和延迟，应保留为实验变体。

## 真实回答和修复诊断

真实答案运行位于：

- `data/benchmarks/qasper/results/p1q3-smoke28-answer-v1-ar-one-shot`
- `data/benchmarks/qasper/results/p1q3-smoke28-answer-v1-ar-requirement-aware`

one-shot 完成了 28/28 的检索，但只有 16/28 道题生成答案，12 道因 DeepSeek HTTP 402 失败。Requirement-aware 的 28 道答案请求全部收到 HTTP 402。该运行未形成可比较的 Smoke28 答案结果，也没有 Dev100 答案结果。

两个 answer run 的完整审计均失败并返回 exit code 2：manifest 为 `partial`，存在生成错误和缺少 provider record 的题目；虽然全部题目检索完成，不能将它们当作已通过的端到端冒烟结果。

对已生成的 16 个 one-shot 输出进行离线重评后：初稿共评估 108 条 claim，其中 51 条无支持，Initial Unsupported Claim Rate 为 0.4722；14 次 claim repair 仅 1 次成功；13 个最终输出弃答，其中 9 个对应 Gold 可回答问题（9/24，37.5%）。例如 Smoke28 ID `1f085b9b` 的 Gold 为 `No`，本次最终答案为 `Unanswerable`。Q1-0 官方 Smoke20 基线为 79/187 = 0.4225，Dev100 为 346/789 = 0.4385；Smoke28 部分输出既非同一题集，也缺少 12 道答案，不能计算 paired delta 或据此判断改进。

最终指标中的 Unsupported Claim Rate 是 0/8，但这只覆盖 8 条最终保留的 claim；被弃答的初稿不计入该分母。不能把它解释为实现已达成 `≤0.25` 的改进。当前部分运行只有 16 个成功答案，未达到至少 20 条变更/弃答人工复核数量要求。新加的修复稿 claim 数遥测也未包含在已经生成的回答记录中，必须随下一次回答运行一并验证。

## 验证和提交

- 回归：`python -m pytest tests/rag/test_evidence_requirements.py tests/rag/benchmarks/test_qasper_runner.py tests/rag/benchmarks/test_qasper_protocol.py tests/api/test_llm_dependencies.py tests/rag/test_query_planner.py tests/agent/test_agent_claim_evidence_verifier.py tests/agent/test_grounded_synthesis_partial_verification.py -q`：51 passed。
- 静态检查：Ruff 对四个改动 Python 文件全部通过；`git diff --check` 通过。
- 检索、选证、answerer 初稿/修复 claim telemetry 和 evaluator 的多轮上下文口径均有 fixture 覆盖；这些测试不能代替模型真实回答验收。
- 代码检查点：`ece05455bcb0b27736d7c23cc813ce39b861bf22`，分支 `WebReBuild`。此提交不是 Q1-3 完成标记。

## 相关论文仓库的设计参考

- [SELF-RAG 原仓库](https://github.com/AkariAsai/self-rag)通过训练得到的反思 token 判断检索需求、证据支持程度和答案效用；它不是当前 hosted DeepSeek 环境中可直接替换的启发式 gate。
- [CRAG 原仓库](https://github.com/HuskyInSalt/CRAG)提供独立的检索结果评估器并按置信度路由。后续可以借鉴“评估实际选中的段落”的结构，但需要单独模型、阈值校准和真实数据消融。现在先不复制它的外部知识检索扩展，因为 QASPER 的评估约束是指定论文范围。
- [SciRAG `initial_critic` / `gap_critic`](https://github.com/yale-nlp/SciRAG/blob/main/shortans/scifact/pipe.py)的有界 gap-driven 检索思路与当前任务书相符；本次真实数据表明，关键未解决问题是 query 是否能带来新证据，以及停止判断是否校准。

## 初次 provider 阻断后的复测状态

初次 Smoke28 答案运行曾因 DeepSeek HTTP 402 中断；同日 provider 恢复后，按相同固定题目完成 Smoke28 和 Dev100 的真实复跑，并完成至少 20 个变更/弃答案例的人工检查。下面的复测结论取代本报告较早的“等待额度恢复”状态。旧的 partial run 与单题 canary 仍保留为失败审计记录，未混入完整运行指标。

## 后续探测与 gate 根因诊断（2026-09-24）

- 在 `aitrans` 环境中对 Smoke28 已知 false-abstention 题 `1f085b9b` 做单题 one-shot canary，真实 Dense、BM25、reranker 和 Q1-1 选证均完成；Gold Evidence Recall@5 为 1.0。回答阶段再次收到 `DeepSeek API request failed with HTTP status 402`，run `p1q3-provider-canary-aitrans-20260924-ar-one-shot` 为 partial，完整审计 exit code 2。默认 Anaconda 环境的另一次预检在加载 embedding 时因无 PyTorch 提前失败，不是有效 RAG run；它被记录为 failed，不与真实 canary 混合统计。
- 随后在正确环境再次重测 `p1q3-provider-canary-recheck2-20260924-ar-one-shot`：1/1 检索成功、0/1 答案成功，错误仍为 HTTP 402，审计 exit code 2。当前 Windows Credential Manager 只返回 `deepseek` 为已配置 provider；本地 Hugging Face cache 只有 embedding、reranker 和 Docling 权重，没有生成模型，且无 Ollama/LM Studio 进程。
- 检查 Dev100 的 Gate false positives，确认词面判定把通用词命中当成充分证据。例如 `682e2626` 的要求是 dataset differences，Top5 context Gold Recall@5 为 0，但单一 `data` requirement 仍被标为 covered；`0ec56e15` 的问题是 word subspace meaning，recall@5 同为 0，answer requirement 仍 covered。根因是“任意通用类别词出现”与“可回答问题所需事实齐全”并不等价。
- 作为诊断，按 paper ID 分组做 5-fold 离线检查：只用首轮 Top5 的 reranker score margin，在训练折选阈值预测 Gold context 是否不充分，测试折 macro precision/recall/F1 为 0.335/0.683/0.423，precision 仅 0.25–0.40，折间波动明显。该分数不够可靠，未加入运行时 Gate。现有证据支持改用经校准的段落充分性评估器，而不是再加一个未经真实验证的固定 score threshold。

## 额度恢复后的真实回答复测（2026-09-24）

完整回答 runs 使用同一公开 QASPER v0.3 validation 数据、Q1-1 `p1q1-evidence-selection-v2`、DeepSeek `deepseek-v4-flash`，并固定 Smoke28/Dev100 question ID。所有下表 runs 的完整审计均为 `ok=true`：Smoke28 28/28、Dev100 100/100；每次覆盖 24/86 篇论文，均为 0 运行错误、0 无效选证 offset。数据 source SHA256 为 `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93`；Dev100 question IDs SHA256 为 `06c7992e06c931002d0a211abb61d771ed206459a3fe4ab4236b8a205b25dd38`；Smoke28 qrels SHA256 为 `b569e1a99cbdfdb44e70a4dd3801dae0a542dc718b12c0bd5d90bef9780d3fbd`。

direct-answer recovery 使用 Q1-2 contract v1（SHA256 `4d900f0fd6757c0fb8706c57dd414b45a34114642d42732caaf68392523adee6`）。对应 run IDs 为 `p1q3-smoke28-direct-answer-recovery-v2-20260924-ar-one-shot`、`p1q3-smoke28-direct-answer-recovery-v2-20260924-ar-requirement-aware`、`p1q3-dev100-direct-answer-recovery-v2-20260924-ar-one-shot`、`p1q3-dev100-direct-answer-recovery-v2-20260924-ar-requirement-aware`。答案充分性提示复测 run IDs 为 `p1q3-smoke28-answer-adequacy-v2-20260924-ar-one-shot` 和 `p1q3-dev100-answer-adequacy-v2-20260924-ar-one-shot`。

| 样本 / 变体 | Answer F1 | Evidence F1 | False abstention | Missed abstention | Boolean accuracy | 回答生成 p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Smoke28 one-shot，direct-answer recovery | 0.38973 | 0.15236 | 5/24 | 2/4 | 4/10 | 2138 ms |
| Smoke28 requirement-aware，direct-answer recovery | 0.39393 | 0.15236 | 5/24 | 2/4 | 4/10 | 2182 ms |
| Dev100 one-shot，direct-answer recovery | 0.39962 | 0.14524 | 16/93 | 2/7 | 6/18 | 2325 ms |
| Dev100 requirement-aware，direct-answer recovery | 0.41314 | 0.14524 | 19/93 | 2/7 | 6/18 | 2367 ms |

Dev100 one-shot 与 Q1-2 answer-contract baseline 同题配对 5000 次 bootstrap：Answer F1 delta `-0.02940`，95% CI `[-0.06626, -0.00025]`；Evidence F1、Gold Evidence Recall@10 和 MRR 均不变。Requirement-aware 与 Q1-2 baseline 的 Answer F1 delta 为 `-0.01588`，95% CI `[-0.05427, +0.01984]`，没有确认收益。Q1-0 Dev100 初稿 UCR 为 `346/789=0.4385`；direct-answer recovery one-shot 的初稿 UCR 降至 `19/325=0.0585`，但 repair UCR 仍为 `13/40=0.325`（16 次 repair、7 次成功）。最终 UCR 为 0 的同时出现 16/93 错误弃答，不能把最终零 UCR 单独作为质量通过证据。

Requirement-aware Dev100 有 3/100 题触发真实二次检索，Smoke28 有 2/28 题触发；新增轮次均没有产生 novel chunk。Dev100 观察到 85 个 gate decisions、覆盖 83 个题目：TP/FP/FN/TN=`63/18/2/2`，precision `0.7778`、recall `0.9692`，有 18 个 premature-stop false positive。Smoke28 的两道触发题 `8d4ac4af` 与 `c9b8d385` 第二轮都以 `no_novel_evidence` 结束；challenge cases 中至少四题在首轮已有足够 Gold context 后正确停止。该检索策略没有质量收益，不应默认启用。

### 20 个案例人工审查

审查集由 Dev100 one-shot 的 16 个 Gold 可回答但模型弃答、2 个 Gold 不可回答但模型作答，以及 2 个 direct-answer recovery 输出组成。检查模型答案、Gold 注释和实际传入回答器的 selected evidence；Gold 仅用于离线复核，没有进入 prompt。

- **明确错误弃答：** `4c18081a` 的 selected evidence 明确列出 cosine-similarity noun clustering、CLUTO 与 Carrot2 Lingo，但回答为 Unanswerable；`22ccee45` 的 selected evidence 明确说 English datasets 被翻译为 Spanish，问题询问源语言，回答仍为 Unanswerable。`682e2626` 的摘要说明先前数据集只覆盖若干特定攻击类型，而 OLID 扩展到多个攻击类型及目标；回答弃答，至少应给出有证据支持的差异。
- **Gold/证据缺失或标注歧义：** `1f085b9b`、`a99fdd34`、`133eb4aa`、`58ef2442`、`3c3807f2` 的 Gold `No` 主要依赖论文没有报告该项，选中证据也无明确否定事实；保守弃答比编造 No 更安全。`09a1173e`、`f8c1b17d`、`4a4ce942`、`5bc1dc6e` 需要表格/图中的精确数值或列表，但当前文本证据没有这些值。`b1cf5739`、`c7b6e6cb`、`1dc2da50`、`9c44df75` 存在不同 annotator 的答案或 answerability 分歧。
- **不充分的正答：** `b1a068c1` 只说语料覆盖多种口音，没有列出题目所问口音；`7d483077` 只复述购买模式可能随季节变化，没有说明“如何变化”。二者 Gold 为 Unanswerable，应要求输出明确响应所问槽位。
- **正确恢复：** `53f74250` 恢复了由引用段落支持的 11 层 DNN acoustic model；`71a0c4f1` 恢复了由社区标注的 Wikipedia 质量标签。direct-answer recovery 有实际收益，但不足以抵消总体 F1 下降与错误弃答。

这 20 例中发现至少 2 个明确错误弃答，故不满足“人工复核不得发现因核验而新增的明显错误弃答”的验收要求。QASPER 的负答案 Gold 有时由沉默推导，报告中将其与有明示证据却弃答的情况分开计数。

### 答案充分性提示的隔离实验

为修正“只回答宽泛背景、未填具体问题槽位”的错误，再测了 contract `p1q3-direct-answer-v2-answer-adequacy`（SHA256 `4e5d2dce4e29b0d9f368f232bffc0a46d482aef1a931ab25b9b7c999e5f9e0ce`）。Smoke28 Answer F1 为 `0.43703`，对 Q1-2 Smoke28 baseline 的 delta `+0.01933`，95% CI `[-0.08786,+0.12281]`；False abstention 为 `5/24`，Boolean accuracy `4/10`，小样本区间不支持晋级。固定 Dev100 上 Answer F1 为 `0.40872`，对 Q1-2 baseline delta `-0.02030`，95% CI `[-0.06347,+0.02510]`；Evidence F1 不变。初稿 UCR `21/292=0.0719`，repair UCR `14/39=0.3590`；False abstention 增至 `24/93`，虽 missed abstention 降为 `0/7`，仍属明显过度弃答。另一个同时加入布尔命题极性规则的 specificity profile 在 Smoke28 产生 7/24 false abstention 和 4/10 Boolean accuracy，也不晋级。两种提示文件仅保留为可复现实验配置，不作为默认答案策略。

### Q1-3 阶段决定

Q1-3 检索门、实际第二轮与正确停止路径都已有可审计 trace；运行完整性和初稿 UCR 达标。整体质量门仍未通过：direct-answer recovery Dev100 的 Answer F1 显著低于 Q1-2 baseline，repair UCR 高于目标 0.25，人工复核确认有明确错误弃答；answer-adequacy 提示同样未改善 Dev100 F1 并增加 false abstention。Requirement-aware 没有新增检索证据且误停偏高。Q1-3 结论为**不晋级**，Q1-4 和 P2 暂不启动；下一次质量迭代应先修正“模型已拿到明确答案证据仍弃答”与“正答没有回答所问细节”这两类问题，再重跑固定 Smoke28 和 Dev100。

报告中记录的 provider 调用次数为估算的 LLM invocation count（Dev100 one-shot 116 次）；`ChatResult` 未返回实际 token 用量，因此无法可靠报告美元成本。运行与对照 JSON 保存在各自 `data/benchmarks/qasper/results/<run-id>/` 目录内。
