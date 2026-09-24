# QASPER P1 Q1-4 RAPTOR 检索质量消融报告

> 结论：Q1-4 实验与审计已完成。R1/R2 明显降低真实 Dev100 的证据召回；R3 的微小 Evidence F1 增益没有转化为 Answer F1 或跨章节/全局题收益，且增加回答模型调用。因此保留 R0，不将 RAPTOR 变体晋级 Q1-5。用户要求跳过 Q1-3 后继续本阶段；这不代表 Q1-3 的质量门已通过。

## 实验设置与链路修正

- 数据：QASPER v0.3 validation；原始文件 SHA256 `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93`。固定 Dev100 题目集合 SHA256 `06c7992e06c931002d0a211abb61d771ed206459a3fe4ab4236b8a205b25dd38`，qrels SHA256 `70518f10529c57db724a03a7df92a27e764c9bf652145076364b13b6ecbc6826`。
- 四路共用同一叶子索引、Q1-1 `p1q1-evidence-selection-v2`（SHA256 `23234a32c85878ad5b7baca32ff87d939914d7cfb1ac6a520eccb42ba1b75fc2`）及 Q1-2 `p1q2-direct-answer-v1`（SHA256 `4d900f0fd6757c0fb8706c57dd414b45a34114642d42732caaf68392523adee6`）。真实回答使用 DeepSeek `deepseek-v4-flash`。四路先用 extractive summary 作低成本检索消融。
- 修正了 RAPTOR 路径原先绕过 Q1-1 最终选证的问题，保留原始候选池与最终证据的独立 trace。R1/R2/R3 记录实际检索阶段及摘要命中；空摘要候选回退到同论文 R0。缓存读取时校验论文、叶子、paragraph、子节点与根节点引用，摘要节点不直接作为预测 Gold 证据。
- `run_qasper_raptor_ablation.py` 现在显式加载并记录上述 profile/contract。R0 是当前 Dense + BM25 + rerank；R1 是 dense leaf + summary；R2 是 summary 命中后展开叶子；R3 是当前检索与 summary 融合再 rerank。四路的答案比较固定选证与回答协议。

## 真实 Smoke20 与 Dev100 检索消融

固定 Smoke20 四路 run `p1q4-smoke20-v2selected-audited-20260924-r0` 至 `-r3`，Dev100 四路 run `p1q4-dev100-v2selected-ro-20260924-r0` 至 `-r3`。全部 complete、逐路审计 `ok=true`、0 issue；retrieval-only 的 Answer F1 占位值不用于判断生成质量。

| Dev100 变体 | Recall@10 | 最终证据 Gold Recall@10 | 官方 Evidence F1 | MRR | 平均 context tokens | 检索 p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| R0 | 0.9699 | 0.8002 | 0.14524 | 0.55496 | 999.50 | 1454.8 |
| R1 | 0.8795 | 0.6940 | 0.12819 | 0.55786 | 995.35 | 703.5 |
| R2 | 0.7892 | 0.5780 | 0.11113 | 0.39582 | 1009.97 | 766.9 |
| R3 | 0.9699 | 0.8002 | 0.14581 | 0.54995 | 990.90 | 1749.3 |

Dev100 的 Local / Cross-section / Global 最终证据 Gold Recall@10：R0 为 `0.7658 / 0.8667 / 1.0000`；R1 为 `0.6437 / 0.8622 / 0.8333`；R2 为 `0.5402 / 0.7289 / 0.6771`；R3 与 R0 相同。R3 在 100 题中仅改变 10 题的最终 chunk 列表；官方 Evidence F1 仅 2 题小幅改善，未见 Global/Cross-section 证据收益。

同题严格 bootstrap（5000 次，seed 42）对 Dev100 检索结果：R1 相对 R0 的 Gold Evidence Recall@10 差 `-0.09438`，95% CI `[-0.16667, -0.02811]`；R2 差 `-0.18474`，CI `[-0.26908, -0.10843]`；R3 差 `0`。R3 的官方 Evidence F1 差 `+0.000571`，CI `[0, 0.001714]`；MRR 差 `-0.005012`，CI `[-0.011291, -0.000031]`。因此只让 R3 进入真实回答对照。

Smoke20 第二次同配置构建 18/18 树缓存命中；Dev100 首次 86 棵树中命中 18 棵，新增 68 棵、476 次 extractive 摘要调用，建树合计约 74.17 秒。后续 Dev100 真实回答对照为 86/86 命中，建树/读缓存合计约 1.08 秒。检索延迟取自不同串行运行，受缓存与机器负载影响；不能据此声称 R1/R2 或 R3 有稳定的延迟收益。LLM summary 未运行：extractive summary 未显示值得支付额外摘要调用成本的质量收益。

## 真实 DeepSeek 回答对照

Smoke20 的 R0/R3 分别 20/20 complete、审计通过，Answer F1 `0.30150 / 0.35132`，paired delta `+0.04982`，95% CI `[-0.01689, 0.16119]`；样本不足以判断收益。因此继续固定 Dev100。Dev100 run 为 `p1q4-dev100-r0r3-answer-20260924-r0` 与 `-r3`，两路均 100/100 complete、0 error、审计 `ok=true`，来源、qrels、题目、索引与模型一致。

| Dev100 指标 | R0 | R3 | R3 - R0 |
| --- | ---: | ---: | ---: |
| 官方 Answer F1 | 0.41533 | 0.41149 | -0.00384 |
| 官方 Evidence F1 | 0.14524 | 0.14581 | +0.00057 |
| 最终证据 Gold Recall@10 | 0.80020 | 0.80020 | 0 |
| 检索 MRR | 0.55496 | 0.54995 | -0.00501 |
| 平均 context tokens | 999.50 | 990.90 | -8.60 |
| 检索 p95 ms | 1596.16 | 1548.64 | -47.52 |
| 生成 p95 ms | 1972.20 | 2107.32 | +135.13 |
| 估算 LLM 调用数（含修复） | 111 | 121 | +10 |
| 错误弃答 / 93 个可回答题 | 17 | 19 | +2 |
| Boolean 正确率 / 18 题 | 0.3889 | 0.3333 | -0.0556 |
| 初始 Unsupported Claim Rate | 0.0414 | 0.0772 | +0.0358 |

最终 Unsupported Claim Rate 两路均为 0；这包含回答器的修复和弃答作用，不能单独证明回答事实质量。R3 的修复调用更多、错误弃答更多。Local / Cross-section / Global 的 Answer F1，R0 为 `0.39464 / 0.38992 / 0.29762`，R3 为 `0.39194 / 0.38098 / 0.27986`；对应 Gold Evidence Recall 三类均未提高。Global 仅 4 题，结论以未观察到收益为限。

严格配对 bootstrap（100 题、5000 次、seed 42）：Answer F1 差 `-0.003839`，95% CI `[-0.037665, 0.029590]`；Evidence F1 差 `+0.000571`，CI `[0, 0.001714]`；候选池 Gold Evidence Recall@10 差 `0`；MRR 差 `-0.005012`，CI `[-0.011291, -0.000031]`。Evidence F1 的微小变化来自少量题，且置信区间下界为 0；不满足 Q1-4 对真实回答与 Global/Cross-section 收益的入围要求。

## 验收与决策

- RAPTOR 缓存与 trace、同论文/有效叶子/源 offset 审计均通过；定向测试 `33 passed`，Ruff 通过。
- R1/R2 在证据召回上有明确退化；R3 未提升 Dev100 Answer F1，Global/Cross-section 无收益且调用成本上升。**R0 保留为默认；没有 RAPTOR 变体晋级。**
- Q1-3 被用户要求暂时跳过，其质量门仍未通过。Q1-2 的人工事实质量门也未通过。Q1-5 需先作候选资格判定；本报告不声称 P1 已达到完整验证/产品晋级条件。

复现入口：`scripts/run_qasper_raptor_ablation.py`（固定题目清单分别传 `--mode smoke|dev`、`--question-ids-file`、`--retrieval-only`；真实回答去掉该参数），`scripts/check_qasper_run.py` 和 `scripts/compare_qasper_runs.py --resamples 5000 --seed 42`。原始运行产物位于忽略的 `data/benchmarks/qasper/results/` 与 `data/benchmarks/qasper/raptor/ablation/`。
