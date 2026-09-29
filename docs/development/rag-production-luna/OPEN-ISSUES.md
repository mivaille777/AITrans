# 未解决问题与待用户决策

此文件记录经仓库核验、基准测试和成熟开源项目对照后，仍需要产品/数据所有者提供依据的事项。任务范围内可由代码和故障注入解决的问题继续由后续 Stage 推进。

## OI-001：真实生产语料与证据金标缺失

- 影响：无法验证未知文档发现、跨文档 GraphRAG、真实解析质量、证据定位、引用正确率或对用户任务的收益。QASPER 是已知论文过滤集；S00.2 的 TXT 是合成单文档 smoke。
- 已尝试：冻结 paper-disjoint QASPER dev/holdout；建立真实项目解析/索引/检索路径的合成 TXT smoke；检查公开评测。 [BEIR](https://github.com/beir-cellar/beir) 提供多任务检索基准，[SciFact](https://github.com/allenai/scifact) 提供科学主张与证据检索标注；二者可补充公开学术检索信号，但不能替代 AITrans 用户文档、权限范围与本产品的真实 query 分布。
- 证据：`S00.3.md` 的 100 题结果仍是 QASPER known-paper；开放文档切片 N=0。QASPER holdout 已保留，未被用于调参。
- 需要决策/输入：提供可脱敏的真实文档/文档家族、代表性问题和 source-span/完整证据标注；若不能提供，请明确接受哪些公开 benchmark 仅作代理评估，以及仍不覆盖的上线风险。
- 阻塞：S00 生产门禁、S02/S06/S07 的真实导入与 GraphRAG 收益门、S10/S16 最终验收。

## OI-002：业务指标门槛与预算未确认

- 影响：无法确定可用性及发布的定量标准。
- 已尝试：按任务书把候选 Recall@5 0.80、MRR 0.70、Citation Accuracy 0.90、Retrieval P95 800 ms、最小切片 N=30、绝对回归容差 0.02 写入 `gate.json`；这些值目前均标为候选。基线当前 Recall@5=0.816、MRR=0.518、Evidence Precision@5=0.101、P95=841 ms。回答生成关闭，因此 Citation Accuracy/Faithfulness 没有实测值。
- 需要决策：确认或调整各题型/场景的 Recall、MRR、Citation Accuracy、Faithfulness 下限，P95 计时边界，token/索引成本预算，最小样本量与置信区间规则；确认是否允许先以公共数据完成技术迭代、生产结论继续保持 NO-GO。
- 阻塞：S00 gate 的最终冻结和 S16 Go/No-Go。候选门槛不会被记录成业务批准值。

## 后续代码可自行解决（非待用户裁决）

- Parser、错论文与 no-answer 的端到端坏例缺少真实样本；收到 OI-001 数据后补充标注并回放。
- 注入 Qdrant/BM25/manifest 中途失败、崩溃恢复和 generation 发布检查在 S01 中实现；当前快照三存储均为 1312 个 chunk ID，差集为 0，不代表故障路径已经验证。
- Debug Studio 后端能按 run/case 返回 Trace，但尚未完成人工桌面 UI 点选核查。
