# QASPER P1 Q1-5 候选资格与全量验证入口审查

> 状态：入口审查完成；**没有可冻结的质量候选，Full1005/Holdout905 双臂验证未启动，Q1-5 晋级验收未完成，P2 不启动。** 用户要求先跳过 Q1-3、继续后续任务；该顺序调整不等于豁免 Q1-5 的质量门。

## 已完成的同题验证

Q1-4 的固定 Dev100、真实 DeepSeek R0/R3 两组均 100/100 complete，审计 `ok=true`、0 issue；来源文件、100 个题目 ID、qrels、索引指纹、Q1-1 v2 选证 profile 和 Q1-2 v1 回答 contract 对齐。严格配对 bootstrap 5000 次、seed 42 的结果如下。原始产物见 `data/benchmarks/qasper/results/p1q4-dev100-r0r3-answer-20260924-{r0,r3}/`，详见 [`qasper-p1-q1-4-raptor-ablation-report.md`](qasper-p1-q1-4-raptor-ablation-report.md)。

| R3 − R0 | 点估计 | 95% CI | 判断 |
| --- | ---: | ---: | --- |
| 官方 Answer F1 | -0.003839 | [-0.037665, 0.029590] | 未见同题收益 |
| 官方 Evidence F1 | +0.000571 | [0, 0.001714] | 增益很小、下界为 0 |
| 候选池 Gold Evidence Recall@10 | 0 | [0, 0] | 无变化 |
| MRR | -0.005012 | [-0.011291, -0.000031] | 明确退化 |

R3 的 Global/Cross-section Answer F1 均低于 R0，Gold Evidence Recall 未提高；估算回答模型调用从 111 次增加到 121 次，错误弃答从 17/93 增至 19/93。因此 R3 不满足 Q1-4 的候选入围条件。R1/R2 在 Dev100 的证据召回有明确退化，也不入围。

## 候选清单与入口决定

| 来源 | 已有证据 | Q1-5 冻结决定 |
| --- | --- | --- |
| Q1-1 选证 v2 | Dev100 相对 current20 官方 Evidence F1 有收益，Answer F1 无明确变化；但 Unsupported Claim Rate `0.4616` 高于基线 `0.4524`，且 Q1-1 报告明确未证明 groundedness 改善。 | 可作为固定实验组件；不能单独认定满足 Q1-5 的事实质量/groundedness 门。 |
| Q1-2 直接答案 contract v1 | Dev100 Answer F1 提升，但人工复核发现 16/93 错误弃答，18 道布尔题仅 7 题正确，阶段人工事实质量门未通过。 | 保留可审计实现；不冻结为质量晋级候选。 |
| Q1-3 自适应依据核验 | 用户要求本轮跳过；此前质量门未通过。 | 不作为候选。 |
| Q1-4 RAPTOR R1/R2/R3 | 本轮真实四路消融与 R0/R3 回答对照已完成；R1/R2 证据退化，R3 无真实回答或 Global/Cross-section 收益。 | 保留 R0，不冻结 RAPTOR 候选。 |

Q1-5 要求在冻结一个候选后，对完整 validation 1005 题分别真实运行 baseline 与 candidate，并单独判断 Holdout905。当前没有满足入口条件的 candidate；把 R0 与自身跑成两个全量臂只能检验运行稳定性，不能构成质量改进验证。即使直接放大 Q1-2 或 R3，也会绕过已经失败的人工或 Dev100 入围条件。故本次**不将 Full1005/905 标成已运行或通过**，不改变产品默认策略，不进入 P2。

## 后续恢复条件

1. 产生一个能通过 Dev100 真实回答、证据和人工事实质量审查的候选；特别处理多段落摘录丢失信息、布尔方向错误和错误弃答。Q1-3 可继续暂停，但若其能力缺口仍影响候选，则需要等价的可验证修复。
2. 冻结版本化配置与代码 SHA；同一题目、索引和模型完成 Dev100 baseline/candidate 严格比较，必要时同配置重复生成以估计模型波动。
3. 仅当入口条件满足时启动完整 1005 题双臂真实运行，单列 Holdout905 的官方 Answer/Evidence F1、检索、groundedness、成本/延迟、分层和配对 95% CI；按任务书全部门槛决定是否晋级。

本审查是 Q1-5 的 **no-go 决定**，不是 Full1005/Holdout905 的替代结果。Q1-4 阶段提交为 `27f4ba32`，已推送 `WebReBuild`。
