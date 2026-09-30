# 未解决问题与待用户决策

此文件记录经仓库核验、基准测试和成熟开源项目对照后，仍需要产品/数据所有者提供依据的事项。任务范围内可由代码和故障注入解决的问题继续由后续 Stage 推进。

## OI-001：真实生产语料与证据金标缺失

- 影响：无法验证未知文档发现、跨文档 GraphRAG、真实解析质量、证据定位、引用正确率或对用户任务的收益。QASPER 是已知论文过滤集；S00.2 的 TXT 是合成单文档 smoke。
- 已尝试：冻结 paper-disjoint QASPER dev/holdout；建立真实项目解析/索引/检索路径的合成 TXT smoke；检查公开评测。 [BEIR](https://github.com/beir-cellar/beir) 提供多任务检索基准，[SciFact](https://github.com/allenai/scifact) 提供科学主张与证据检索标注；二者可补充公开学术检索信号，但不能替代 AITrans 用户文档、权限范围与本产品的真实 query 分布。
- 证据：`S00.3.md` 的 100 题结果仍是 QASPER known-paper；开放文档切片 N=0。QASPER holdout 已保留，未被用于调参。
- 2026-09-30 补充：按用户明确要求自行下载固定 revision 的 HF SciFact 和 MedicalRetrieval，完整 corpus 无已知文档过滤评测完成，见 S04.2。公开代理的授权已取得；真实用户语料、文件解析/回源与本产品 query 分布的验证缺口仍在。
- 需要决策/输入：提供可脱敏的真实文档/文档家族、代表性问题和 source-span/完整证据标注。公开技术代理评测已获授权；尚无依据将其解释为真实用户场景或上线风险已经覆盖。
- 阻塞：S00 生产门禁、S02/S06/S07 的真实导入与 GraphRAG 收益门、S10/S16 最终验收。

## OI-002：业务指标门槛与预算未确认

- 影响：无法确定可用性及发布的定量标准。
- 已尝试：按任务书把候选 Recall@5 0.80、MRR 0.70、Citation Accuracy 0.90、Retrieval P95 800 ms、最小切片 N=30、绝对回归容差 0.02 写入 `gate.json`；这些值目前均标为候选。基线当前 Recall@5=0.816、MRR=0.518、Evidence Precision@5=0.101、P95=841 ms。回答生成关闭，因此 Citation Accuracy/Faithfulness 没有实测值。
- 需要决策：确认或调整各题型/场景的 Recall、MRR、Citation Accuracy、Faithfulness 下限，P95 计时边界，token/索引成本预算，最小样本量与置信区间规则。用户已在 2026-09-30 授权公共数据技术评测；生产结论继续保持 NO-GO。
- 阻塞：S00 gate 的最终冻结和 S16 Go/No-Go。候选门槛不会被记录成业务批准值。

## OI-003：Embedding 权重 snapshot 未固定

- 影响：当前索引指纹记录模型 ID、维度、归一化和 prompt 前缀，但未记录不可变模型权重 revision。相同模型 ID 若解析到新 snapshot，索引复用检查仍可能认为可复用。
- 仓库证据：`backend/rag/model_manager.py` 调用 Hugging Face `snapshot_download` 时没有传 `revision`；当前 S00 基线只在外部 manifest 留有 snapshot `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`，不是运行时索引合同。
- 开源方案核对：Hugging Face 官方文档说明 `snapshot_download` 默认下载最新 revision，可通过完整 commit hash 的 `revision` 固定模型快照：[Download files from the Hub](https://huggingface.co/docs/huggingface_hub/en/guides/download)。
- 建议：扩展模型下载与 provider 合同，把解析后的 commit hash 纳入 fingerprint；模型 revision 变化时必须重建 vector generation。当前任务 S03.1 文件范围没有包含 `model_manager.py`、配置和 Qwen 模型加载合同。
- 需要决策：是否将当前开发基线 snapshot 固定为默认模型版本，或由产品指定另一个已验证的完整 commit hash。确认后可在 S03 Stage 门禁前补齐；在此之前不能声称同 ID 权重变更已被检测。
- 阻塞：S03 Stage 的模型版本迁移门；不阻塞独立的 S03.2 scope 实现与验证。

## OI-004：S03 Vector Only 门禁低于 S00 Hybrid 基线

- 影响：S03 Stage 按任务书要求“Vector Only 不低于 S00 同数据基线”时未通过；S03 质量门仍未解除。
- 证据：同一冻结 QASPER dev100、87 个可评估 gold evidence 问题上，S03.3 Dense Only 的 Recall@5/MRR/nDCG@10 为 `0.6724/0.4640/0.5723`；S00 Dense+BM25+reranker 为 `0.8161/0.5181/0.6122`。Vector Only Recall@10 为 `0.9425`，高于 S00 的 `0.8989`；暖查询 P95 `103.967 ms`，低于 S00 的 `841.468 ms`。见 `S03.3.md` 和本机 `data/benchmarks/qasper/s03-3-vector-only/` 结果。
- 开源方案核对：BEIR 将 dense、lexical/sparse 与 reranking-based retrieval 作为不同架构分别评估，并提供 dense 和 BM25+cross-encoder 示例；适合用于同数据、同指标的消融对照，但无法让 Dense Only 自然达到 Hybrid 指标：[BEIR 官方仓库](https://github.com/beir-cellar/beir)。
- 约束：S03.3 只允许改 embedding 批量/冷启动配置；调整模型或排序策略超出该子任务范围。S00 是 Hybrid 基线，当前任务书没有记录可供同配置比较的 Vector Only 基线。
- 需要决策：门禁是否应改为与同配置的 S00 Vector Only 基线比较；若坚持超过 S00 Hybrid，则批准扩大检索算法/模型调优范围，并明确此门禁允许的实验与资源预算。
- 用户指示：2026-09-30 明确要求自行下载 Hugging Face 数据评测并进入 S04；已按此授权继续工程任务，原 Vector Only 指标与门禁判定保持 BLOCKED。该指示没有冻结生产阈值或 embedding 权重 revision。
- 阻塞：S03 Stage 质量门和最终生产判定；不再将“进入 S04 的许可”列为待决事项。

## OI-005：公开全库 Sparse 检索仍有质量缺口

- 证据：SciFact 完整 5,183 corpus/300 test query 的 S04 BM25 Only Recall@5=0.7094、MRR@100=0.6274、nDCG@10=0.6540；test query `768` 的 gold 排名 4→6，Recall@5 比 S00 Sparse 回放下降 0.00333。中文 MedicalRetrieval 完整 100,999 corpus/1,000 dev query 的 Recall@5=0.3780，Top-5 完全漏召回 622 题；MRR@100=0.3264、P95=452.304 ms。
- 已解决部分：固定标识符 fixture 5/7→7/7；QASPER S00 Sparse 同数据回放 Recall@5/10 持平、MRR/nDCG 上升；中文 seed42 配对 100 题质量完全一致、P95 1731.767→452.620 ms；重建/删除/重启/scope 注入过期或越权候选为 0。
- 已核对的开源评测方案：[MTEB](https://github.com/embeddings-benchmark/mteb) 的完整 corpus/query/qrels 与 [BEIR](https://github.com/beir-cellar/beir) 的 dense、lexical 和 reranker 消融。当前使用真实项目 Sparse Store，未把其他框架的检索成绩当作 AITrans 分数。
- 后续代码路径：S05 在同一固定公开语料比较 Vector/BM25/Hybrid，S09 检验 reranker 增益。当前只测 BM25，不能假定 Hybrid 或 Graph 会自然补齐缺口。保留 SciFact test 回归；后续开发采用 train/新的独立开发语料。
- 待决依据：OI-002 尚未批准这些代理场景的可用下限及回归容差；候选 0.80 不能被降低后伪称已达标。代表性用户文档和中文科学术语问题仍需 OI-001。
- 回放：`data/benchmarks/s04/results/s04-bad-cases.json`，dataset/code/结果 SHA-256 见 S04-benchmark-manifest.json；报告见 S04.1/S04.2/S04。人工 Debug Studio UI 未核验，完整 S04 Stage/生产质量结论保持 BLOCKED。

## 后续代码可自行解决（非待用户裁决）

- Parser、错论文与 no-answer 的端到端坏例缺少真实样本；收到 OI-001 数据后补充标注并回放。
- 注入 Qdrant/BM25/manifest 中途失败、崩溃恢复和 generation 发布检查在 S01 中实现；当前快照三存储均为 1312 个 chunk ID，差集为 0，不代表故障路径已经验证。
- Debug Studio 后端能按 run/case 返回 Trace，但尚未完成人工桌面 UI 点选核查。
- S03.3 配置改造、Vector Only 基准、冷启动/内存、缩写/跨语言 probe 及 generation 排序 smoke 已完成；Vector Only 质量低于 S00 Hybrid，详见 `S03.3.md`。
- S03 Stage 门禁 BLOCKED：OI-004 门禁基准需确认；OI-003 模型 snapshot revision 未进入 runtime fingerprint；RetrievalService/BM25/Graph 的应用级 scope 接线仍未完成。不能宣称 S03 或生产 Go/No-Go 通过。
- 已按用户明确指示进入并完成 S04.1/S04.2 工程任务和 HF 评测；S03 原门禁仍 BLOCKED，S04 相对 Sparse/安全门通过，完整 Stage 尚缺人工 Debug Studio UI 和公开场景质量验收。下一工程 ID S05.1 尚未执行。
