# QASPER P1 Q1-3：摘录覆盖与枚举回答修复实验

> 状态：候选方案；真实 Smoke28 已完成，Dev100 回答因 DeepSeek HTTP 402 未完成；Q1-2/Q1-3 质量门尚未通过，不晋级默认策略。

## 问题与修正

复核 `retrieval_trace.jsonl.final_candidates[].text` 后发现，先前报告把 `predictions.jsonl.predicted_evidence` 映射回的完整段落误认为回答器实际收到的文本。`4c18081a` 的 v2 实际摘录仅提到“两种算法”，遗漏 CLUTO 与 Carrot2 Lingo；`22ccee45` 的 v2 实际摘录遗漏“English datasets were translated into Spanish”。原始检索块均包含这些事实。Q1-3 原报告和任务书已加入勘误。

候选 `p1q1-evidence-selection-v3-contextual` 使用确定性原文相邻句窗口：当 source chunk 不超过 180 tokens 时保留全块；较长块对每个锚句至多向前保留四句、向后保留一句，始终验证原文 offset 与 token 上限。v2 配置不变，v3 仅按 profile 显式启用。`p1q2-direct-answer-v3-enumeration` 指示模型对普通 what/which 枚举题回答证据中明确出现的项目，不因无法证明列表穷尽而弃答；明确要求 all/every/complete 的题仍需完整证据。

## 真实数据结果

- 数据：公开 QASPER v0.3 validation，source SHA256 `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93`；固定 Dev100 和 Smoke28 question IDs。Dense、BM25、reranker、选证和 DeepSeek 调用均由实际 benchmark 管线执行。
- v3 profile SHA256：`1ecfc0faec16569d6dceb442aa6cae151bc82818e15c8669dc6d8a0cde8b263b`；v3 answer contract SHA256：`7013d9978e2380cebb842117eabbd6d9353578c3a7a52b83f5b27492c1d89ea3`。
- Dev100 检索-only run `p1q3-dev100-contextual-v3-ro-20260924-es-evidence-selection`：100/100，完整审计 `ok=true`，0 error，0 无效 offset。与 v2 同题相比，selected Gold Evidence Recall@5 均为 `0.80020`、Precision@5 均为 `0.11144`、F1@5 均为 `0.18393`、官方 Evidence F1 均为 `0.14524`。这些是段落级指标，无法直接体现段内答案句是否被截掉。平均 context 从 `999.50` 增至 `1174.01` tokens；检索 p95 从 `1511.3` 增至 `1964.4` ms，主要增加在摘录 embedding 评分。
- 定点真实回答 run `p1q3-contextual-diagnostic2-answer-20260924-es-evidence-selection`（v3 摘录、v1 合约）审计 2/2 通过：`4c18081a` 从弃答变为“CLUTO and Carrot2 Lingo were used for clustering”；`22ccee45` 的最终上下文已有 English→Spanish，但模型仍错误地因“没有列出其他源语言”而弃答。改用枚举合约的 `p1q3-contextual-diagnostic2-enumeration-20260924-es-evidence-selection` 在同两题分别答“CLUTO and Carrot2 Lingo”和“English”。定点测试只验证修复路径，不代表总体收益。
- Smoke28 真实回答 run `p1q3-smoke28-contextual-enumeration-20260924-es-evidence-selection`：28/28，审计 `ok=true`，0 error。相对同题 Q1-2 v1 基线，Answer F1 `0.41771 → 0.48180`，paired delta `+0.06410`，5000 次 bootstrap 95% CI `[+0.00290,+0.15232]`；官方 Evidence F1 两者均为 `0.15236`。False abstention `4/24 → 3/24`，missed abstention 均为 `2/4`，boolean accuracy `5/10 → 6/10`。候选初稿 UCR `0.05`、最终 UCR `0`；平均 context `913.32 → 1116.29` tokens。候选有 1/28 结构解析失败：模型为布尔题输出“ Yes, ...”而非合约要求的单独 Yes/No，运行时回退为 Unanswerable；该题的 Gold 标注存在 boolean/none 分歧，应单独复核，不以评分结果证明解析回退合理。

## Dev100 回答阻断与阶段决定

完整 Dev100 回答 run `p1q3-dev100-contextual-enumeration-20260924-es-evidence-selection` 在 83/100 条预测写入时被中止，其中仅 11 条回答成功、72 条出现 `DeepSeek API request failed with HTTP status 402`。manifest 已标记 `failed` 并说明中止原因；完整审计 `ok=false`，不计算 Dev100 Answer F1 或 paired delta，也不将部分结果与基线混合。上述已完成的 Dev100 检索-only 与 Smoke28 回答运行保持独立。

因此候选目前不能通过 Q1-2/Q1-3 的 Dev100 质量门；不启用产品默认策略，不启动 Q1-4/P2。DeepSeek 可用后需用同一冻结 Dev100 和 v3 profile/contract 跑完整回答，进行严格同题比较，并人工复核至少 20 个回答变化或弃答案例。还需分离验证上下文策略与回答协议的贡献、检查布尔解析失败、repair UCR、答案细节和二次检索是否确有新增证据。

## 代码检查

`tests/rag/test_evidence_selection.py` 与 `tests/rag/benchmarks/test_qasper_runner.py`：23 passed；Ruff 对改动 Python 文件通过；`git diff --check` 通过。真实 QASPER 检索和回答结果保存在被仓库忽略的 `data/benchmarks/qasper/` 下，阶段未提交为通过状态。
