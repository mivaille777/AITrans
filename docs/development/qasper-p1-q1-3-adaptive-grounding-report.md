# QASPER P1 Q1-3：自适应检索与依据核验阶段报告

> 状态：未完成，质量门未通过。代码检查点 `ece05455bcb0b27736d7c23cc813ce39b861bf22` 已提交至 `WebReBuild`；DeepSeek 回答额度不足，必须完成额度恢复后的真实回答复测和人工抽查，才可关闭 Q1-3。

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
- 两组均固定 Q1-1 `p1q1-evidence-selection-v2`，profile SHA256 `23234a32c85878ad5b7baca32ff87d939914d7cfb1ac6a520eccb42ba1b75fc2`。answer run 未启用 Q1-2 contract，以观察已有 grounded verification/repair 路径。
- 真实 run manifests 的 `git_sha` 为基线 HEAD `dd41453d36f8e4f4a663d54cca25927e39040b29`，因为运行时 Q1-3 工作树改动尚未提交。对应检索实现现已提交为本报告所列检查点；之后仅重新计算了答案 metrics，没有再次请求模型。

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

对已生成的 16 个 one-shot 输出进行离线重评后：初稿共评估 108 条 claim，其中 51 条无支持，Initial Unsupported Claim Rate 为 0.4722，与 Q1-0 任务书基线 0.475 基本相同；14 次 claim repair 仅 1 次成功；13 个最终输出弃答，其中 9 个对应 Gold 可回答问题（9/24，37.5%）。例如 Smoke28 ID `1f085b9b` 的 Gold 为 `No`，本次最终答案为 `Unanswerable`。

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

## 完成 Q1-3 的后续步骤

1. 恢复 DeepSeek `agent_synthesis` 可用额度，或在 AITrans 设置中配置可用的回答 provider；当前 DeepSeek 对答案请求返回 HTTP 402，因此不能完成实际回答验收。
2. 使用同一 Smoke28、同一 Q1-1 profile、相同索引与答案配置重新运行 one-shot 和 requirement-aware；随后在相同冻结 Dev100 上运行两种变体，并审计每个 run。
3. 从 Dev100 中至少人工审查 20 个被改写或弃答的 case，重点检查 Boolean 极性、Gold No 的错误弃答、claim verifier 初稿/修复稿变化和引用对应段落。
4. 比较初稿、修复稿、最终答案三层 claim 指标，同时检查 false abstention、Answer/Evidence F1、Gold sufficiency、Premature Stop Rate、Unnecessary Retrieval Rate、p95 和 provider 调用成本。只有满足 Q1-3 原验收条件后，才继续 Q1-4。

额度恢复后的复跑示例：

```powershell
python scripts/run_qasper_adaptive_retrieval_ablation.py --mode smoke --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-p1q2-smoke28-seed42.txt --quality-profile backend/rag/benchmarks/qasper/profiles/p1q1-evidence-selection-v2.json --evidence-selection-variant evidence_selection --variants one_shot requirement_aware --suite-id p1q3-smoke28-answer-resume
python scripts/run_qasper_adaptive_retrieval_ablation.py --mode dev --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt --quality-profile backend/rag/benchmarks/qasper/profiles/p1q1-evidence-selection-v2.json --evidence-selection-variant evidence_selection --variants one_shot requirement_aware --suite-id p1q3-dev100-answer-resume
```
