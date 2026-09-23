# QASPER P1 Q1-1 证据收窄与精确映射报告

> 状态：完成；profile v2 达到 Q1-1 检索质量门槛，可作为后续 P1 阶段的固定选证方案。它尚未被证明能降低 Unsupported Claim Rate，也不代表产品默认检索参数已变更。

## 结论

对固定的真实 QASPER validation Smoke20 / Dev100 完成了检索-only 五路消融和真实 DeepSeek 回答对照。早期 query-score 排序的摘录策略把 Dev100 Gold Evidence Recall@5 从 `0.8002` 降到 `0.5502`，不符合任务书的最多 `0.03` 绝对退化门槛，因此没有晋级。

Profile v2 保留原 Top20 候选池和 reranker 顺序；对前 K 个候选各选一个可映射摘录。摘录未覆盖 source chunk 对应的全部 paragraph 时，trace 会记录受控回退，并把该 source chunk 本身送入回答器。该策略在 Dev100 上保持 Gold Evidence Recall@5 为 `0.8002`，selected Evidence Precision/F1 相比 current20 全量 Top20 提高，同时明显减少上下文 token；严格同题比较中 Evidence F1 增益的 95% CI 不跨 0，Answer F1 差异的 CI 跨 0。

## 实现

- 候选检索池、最终 selected evidence、回答 context paragraph IDs 与预测 evidence paragraph IDs 分开落盘。检索 Recall/MRR 使用完整 Top20；Evidence Precision/F1 使用最终 selected evidence。
- 为 Top8 增加 `@8` 指标。每条预测会同时保存 `retrieved_chunk_ids` 和 `selected_evidence_chunk_ids`。
- Profile v2 在候选顺序内选证，每个 source chunk 最多选一个 span；保留 source offsets 和 paragraph 映射。span 不足以代表 source chunk 的全部 paragraph 时，执行明确标记的 source-chunk fallback。
- 审计验证 selected chunk 属于 Top20、预测 paragraph IDs 与 selected evidence 一致、excerpt offset 是 source chunk 的精确子串，并检查同一 source chunk 上多个不同 span 的合法性。
- 比较套件现会分别输出 `candidate_pool_evidence`、selected `paragraph_evidence`、provider 调用数、answerer 调用数和估算 LLM 调用数。

## 可复现配置

| 项 | 值 |
|---|---|
| 数据 | QASPER validation，source SHA256 `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93` |
| Smoke20 IDs SHA256 | `8390a28d3d88b68373ab49c60653ea52fc723c48779b5c212dd522fb4bf41e9e` |
| Dev100 IDs SHA256 | `856af943ff1f51ba2bc36e392286a731c417dacfb2746e5f575c1ba81076596a` |
| Dev100 qrels SHA256 | `70518f10529c57db724a03a7df92a27e764c9bf652145076364b13b6ecbc6826` |
| Profile | `p1q1-evidence-selection-v2`, SHA256 `23234a32c85878ad5b7baca32ff87d939914d7cfb1ac6a520eccb42ba1b75fc2` |
| 回答器 | DeepSeek `deepseek-v4-flash` |
| 运行 HEAD | `553f1ad42b13cca36626a47c7fcf9324840625c1`；运行时 Q1-1 改动尚未提交，运行代码文件的 bundle SHA256 为 `4e9aed60c8c32cdb99e2248335d47f22161ad873a408b489536ce22d1444fa03` |

`data/benchmarks/qasper/` 下保留每个 run 的 manifest、predictions、retrieval trace、metrics、errors 和比较器报告；该目录由仓库忽略规则排除。每次运行 manifest 另存 profile、sample、index 和源数据指纹。

## Dev100 检索-only 消融

候选池列在所有策略间相同，因为每个策略复用同一 Top20 reranked pool。其 Gold Recall@5/@8/@10 分别为 `0.8002` / `0.9518` / `0.9759`（83 条有映射 Gold 的题）。表中 selected 指标按该策略实际 K 计算；current20 用 K=20。

| 策略 | Selected K | Selected Gold Recall@K | Evidence Precision@K | Evidence F1@K | 官方 Evidence F1 | 平均 context tokens | Retrieval p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| current_top20 | 20 | 1.0000 | 0.0479 | 0.0890 | 0.0699 | 3844.59 | 1102.7 |
| rerank_top5 | 5 | 0.8002 | 0.1114 | 0.1839 | 0.1452 | 1266.21 | 1062.6 |
| rerank_top8 | 8 | 0.9518 | 0.0828 | 0.1458 | 0.1147 | 1996.16 | 1077.0 |
| rerank_top10 | 10 | 0.9759 | 0.0723 | 0.1290 | 0.1014 | 2394.71 | 1076.3 |
| excerpt selector v1（未晋级） | 5 | 0.5502 | 0.1962 | 0.2730 | 0.2154 | 123.83 | 2405.3 |
| evidence_selection v2 | 5 | 0.8002 | 0.1114 | 0.1839 | 0.1452 | 999.50 | 1511.3 |

Profile v1 的摘录命中率和 Precision/F1 较高，但 Recall@5 绝对下降 `0.2500`，超出门槛。Profile v2 保住了 Recall；Dev100 有 97/100 题至少一次回退到 source chunk，主要因为句子摘录只覆盖多段落 chunk 中的一个 paragraph。没有失效 offset；`no_valid_excerpt_count` 为 0。该回退是有意记录的完整 source evidence，不是隐式扩充全部 Top20。

## Smoke20 与真实回答

Smoke20 的 current20 与 v2 selected Recall@5 均为 `0.8438`，Precision/F1@5 均为 `0.1336` / `0.2157`。官方 Evidence F1 从 `0.0685` 提高到 `0.1726`；平均上下文从 `3937.6` 降至 `914.25` tokens。Top5 的官方 Evidence F1 也是 `0.1726`。

三个回答策略分别对 Smoke20、Dev100 调用 DeepSeek，每题一次：共 60 次 Smoke20 调用和 300 次 Dev100 调用。各 run 均完成，0 error、0 verification fallback、0 policy abstention；provider 记录数与 question 数一致。run artifact 记录调用次数，但没有提供货币成本或 token 账单。

| Split / 策略 | Answer F1 | 官方 Evidence F1 | Unsupported Claim Rate | 平均 context tokens | Retrieval p95 ms | Answer p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| Smoke20 current_top20 | 0.0683 | 0.0685 | 0.4840 | 3937.60 | 1637.8 | 2533.1 |
| Smoke20 rerank_top5 | 0.0773 | 0.1726 | 0.4124 | 1253.00 | 946.5 | 2376.3 |
| Smoke20 evidence_selection v2 | 0.0941 | 0.1726 | 0.4943 | 914.25 | 1284.0 | 2590.4 |
| Dev100 current_top20 | 0.1055 | 0.0699 | 0.4524 | 3844.59 | 1079.3 | 2282.7 |
| Dev100 rerank_top5 | 0.1050 | 0.1452 | 0.4641 | 1266.21 | 1061.8 | 2261.3 |
| Dev100 evidence_selection v2 | 0.1044 | 0.1452 | 0.4616 | 999.50 | 1462.5 | 2081.2 |

相对 current20，v2 的 Dev100 selected Precision/F1 按完整 selected 集统计，从 `0.0479/0.0890` 升到 `0.1114/0.1839`；Gold Recall@5 变化为 `0.0000`。平均上下文 token 减少约 `74%`。相对 Top5，v2 的 Evidence Precision/F1 和答案 Evidence F1 相同，平均 context token 再减少约 `21%`，但检索 p95 增加约 `401 ms`；这是一项 token/延迟权衡。

### 同题 bootstrap（Dev100，seed 42，5000 次）

| 比较 | 指标 | 候选 - 基线 | 95% CI | 配对题数 |
|---|---|---:|---:|---:|
| rerank_top5 − current_top20 | Answer F1 | -0.00051 | [-0.00734, 0.00609] | 100 |
| rerank_top5 − current_top20 | 官方 Evidence F1 | +0.07533 | [0.05491, 0.09702] | 100 |
| evidence_selection v2 − current_top20 | Answer F1 | -0.00113 | [-0.00960, 0.00769] | 100 |
| evidence_selection v2 − current_top20 | 官方 Evidence F1 | +0.07533 | [0.05491, 0.09702] | 100 |
| evidence_selection v2 − rerank_top5 | Answer F1 | -0.00062 | [-0.00845, 0.00855] | 100 |
| evidence_selection v2 − rerank_top5 | 官方 Evidence F1 | 0.00000 | [0.00000, 0.00000] | 100 |

比较器的 Gold Evidence Recall@10/MRR 使用完整候选池，三个同池策略的 delta 均为 0。Selected Recall@5 单独按最终证据计算，也经审计确认相对 current20 无下降。

## 人工抽查与剩余问题

逐题核对了 Smoke20 的 20 个 current/top5/v2 回答、Gold 答案、预测证据 paragraph 和 grounding 计数。上下文缩小后，部分答案更短、引用证据更集中；也观察到以下待后续阶段解决的问题：

- Boolean 方向错误仍存在，例如 `2c7494d4…` 的 Gold 为 No、三组回答都答 Yes；`7438b6b1…` 同样是 Gold No、三组答 Yes。
- 不可回答题 `fb2b536d…` 的回答仍包含无支持陈述。Dev100 Unsupported Claim Rate 在 v2 为 `0.4616`，略高于 current20 的 `0.4524`，故本阶段不声称改善 groundedness。
- `b85fc420…` 在 Top5 回答为 Yes，v2 回答转为“证据不能明确建立”，与 Gold Yes 不一致；更短 context 仍可能丢失跨段落语义。

这些问题分别进入 Q1-2 的 boolean/unanswerable answer contract 和 Q1-3 的 claim verification 评估。不能因为 Evidence F1 提升就把答案可靠性视为已解决。

## 验证

- `pytest tests/rag/benchmarks tests/rag/test_evidence_selection.py -q`：40 passed。
- Ruff 检查所有改动的 RAG、QASPER benchmark、CLI 与测试文件：通过。
- Smoke20/Dev100 全部真实 run 的严格审计：question IDs、paper scope、Dense/BM25/reranker 记录、provider 数量、selected/pool 一致性和 offset 均通过；error 为 0。
- CLI `--help` 校验通过。

## 复跑命令

```powershell
$py = "C:\Users\mivaille\anaconda3\envs\aitrans\python.exe"
$profile = "backend/rag/benchmarks/qasper/profiles/p1q1-evidence-selection-v2.json"
& $py scripts/run_qasper_evidence_selection_ablation.py --mode smoke --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-smoke20-seed42.txt --quality-profile $profile --retrieval-only --suite-id p1q1-smoke-evidence-v2
& $py scripts/run_qasper_evidence_selection_ablation.py --mode dev --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt --quality-profile $profile --retrieval-only --suite-id p1q1-dev-evidence-v2
& $py scripts/run_qasper_evidence_selection_ablation.py --mode smoke --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-smoke20-seed42.txt --quality-profile $profile --variants current_top20 rerank_top5 evidence_selection --suite-id p1q1-smoke-answer-v2
& $py scripts/run_qasper_evidence_selection_ablation.py --mode dev --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt --quality-profile $profile --variants current_top20 rerank_top5 evidence_selection --suite-id p1q1-dev-answer-v2
& $py scripts/compare_qasper_runs.py --baseline data/benchmarks/qasper/results/p1q1-dev-answer-v2-es-current-top20 --candidate data/benchmarks/qasper/results/p1q1-dev-answer-v2-es-evidence-selection --resamples 5000 --seed 42
```
