# 未解决问题与待用户决策

此文件记录经仓库核验、基准测试和成熟开源项目对照后的功能缺陷、验收缺口和产品/数据决策。2026-09-30 按用户“先解决问题清单中的问题”完成有限抽取修复与路由诊断修复；当前结论及证据见 [问题修复报告](OPEN-ISSUES-REMEDIATION.md)。

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

**2026-09-30 功能修复：运行时身份与防混用已解决。** 实际权重/配置/输入上限/精度的内容摘要进入 provider 指纹，IndexService 写入并比较真实指纹；Dense 拒绝不匹配的 generation，Hybrid 可降级 BM25。加载绑定相同解析目录，旧索引重新导入会重建。见 [功能修复报告](S00-S04-REMEDIATION.md)。以下保留原审计；“选定默认发布 snapshot”是后续发布政策，不再作为未检测同名权重变化的缺陷。

- 原审计缺陷已修复：当前运行时记录实际权重内容摘要；相同模型 ID 下权重变化会导致重建/拒绝混用，不再仅凭模型名复用。
- 剩余发布政策：`backend/rag/model_manager.py` 下载未指定默认 `revision`；S00 实测 snapshot 为 `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`，可作为候选发布版本，尚未获得默认发布版本确认。
- 开源方案核对：Hugging Face 官方文档说明 `snapshot_download` 默认下载最新 revision，可通过完整 commit hash 的 `revision` 固定模型快照：[Download files from the Hub](https://huggingface.co/docs/huggingface_hub/en/guides/download)。
- 需要决策：是否将当前开发基线 snapshot 固定为默认发布版本，或指定另一个已验证的完整 commit hash。已有实际权重指纹保护无需重复实现。
- 影响范围：发布版本选择待确认；模型身份与防混用功能缺陷已关闭。

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

## 当前收尾与后续安排

2026-09-30 用户明确要求“暂时不做效果提升，以功能正常为主，并尽快收尾”，随后要求严格最小修改。本轮只保留真实指纹的写入/复用/检索保护、全已启用通道失败处理、Debug 的重排前排名及直接相关测试。BM25 性能优化和无关格式变化已撤回，效果实验已停止，默认配置保持原值。OI-001/002/004/005 与人工桌面 UI、回答质量、后续 GraphRAG 留待继续执行时处理；原生产门禁保持历史判定。

## OI-006：S05 工程完成，RRF 排序坏例与完整质量验收保留

- 2026-09-30 用户授权“继续 S05”；S05.1–S05.3 已完成，6 个生产模块和直接测试实现共享请求、候选来源和版本隔离，没有效果调参。详见 [S05.md](S05.md)。
- 冻结 QASPER V/B/VB 各 100 查询功能回归完成，87 题有效 gold 的排名与基准一致；Hybrid Recall@5=0.7184、MRR=0.4753，仍未达到候选 0.80/0.70，不能标为生产 PASS。
- 保留 16 个已有 RRF 坏例。示例 `4eaf9787f51cd7cdc45eb85cf223d752328c6ee4`：gold 在 Vector 第 2、BM25 第 14，被 RRF 排到第 7。全量原始分数/rank 与 trace 位于本机 `data/benchmarks/s05/hybrid-results.json`。
- 可行后续方案：恢复效果优化后，用冻结开发集比较现有 reranker 的候选池与融合排序；结合完整公开全库 V/B/VB 和真实用户金标验证。当前证据不足以直接修改权重、阈值或推广 Graph；保留默认配置，依照 S09 的配对评测决定。
- 未运行：完整 SciFact/MedicalRetrieval Dense/Hybrid、人工 Debug Studio UI、回答引用质量和 holdout。用户当前功能优先的约束下不进行这些效果实验；上述事项与 OI-001/002 共同阻塞完整 S05/最终生产质量验收。S06–S08 工程随后已推进，见相应报告。

## OI-007：完整论文抽取功能已修复，生产质量验收仍保留

**2026-09-30 本轮修复完成。** 沿用现有模型/客户端，Graph 专用提示升级为 `graph-1.1.1`；校验反馈包含具体缺失端点和上一份输出，仅修复一次，第二次仍严格校验。两篇固定 PDF 均 READY：BERT 70 chunk / 6 条关系，Attention 26 chunk / 2 条关系；8 条关系全部精确回源，复用无模型调用，重建切换 generation，删除后六表零行。下文保留原失败实验和方案；完整论文功能阻塞已解除，真实实体/关系金标、质量与预算仍缺。详见 [本轮修复及实测](OPEN-ISSUES-REMEDIATION.md)。

- 用户授权继续 S06。S06.1–S06.3 工程完成；S06.4 的可选接线和故障测试完成，但完整论文验收 BLOCKED。建立本问题时停止在 S06.4；随后用户明确要求继续后续开发，已实现默认关闭的 S07 工程通道，原生产门仍 BLOCKED。报告、实际文件/指标指纹见 [S06.md](S06.md)、[S06-benchmark-manifest.json](S06-benchmark-manifest.json) 和 [S07.md](S07.md)。
- 已解决：图关系的原文定位、被动语态方向、跨分句误连、唯一空白映射、权限/版本/私有别名隔离、事务回滚和中断恢复。90 个不同的直接/调用方测试通过。
- 原失败实验：`deepseek-v4-flash` + `research.memory.extract@graph-1.0.0` 对 Attention 训练/Adam 段落反复返回未声明的关系端点；BERT 返回非原文引文。两篇 PDF 当时均图导入失败，重试一次仍失败；未发布边可见数 0，旧 READY 索引保留。删除后六表 0 行。原报告/manifest 保留，未被本轮成功结果覆盖。
- 已尝试：复用已有 schema/提示服务、Graph 专用短句与端点声明约束、仅空白差异的唯一原文匹配及一次有限重试；仍保持严格端点/证据校验。未通过丢边、忽略失败 chunk 或发布空图实现假成功。
- 开源对照：[Microsoft GraphRAG 模型选择说明](https://microsoft.github.io/graphrag/config/models/) 要求可靠结构化输出，并明确非标准模型存在格式错误；[索引 dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/) 提供 TextUnit 关联来源设计。未安装新框架或复制源码。
- 可行路径 A：指定能稳定满足 schema 的图抽取模型，在现有服务注入点替换后重跑固定文件；模型变化记录新图版本和成本。
- 本轮实施路径 B 的最小部分：复用现有 AI 客户端和 schema，增加具体错误/上一份输出反馈，限制一次修复。未改变公共 `complete` 接口；JSON mode 只能保证 JSON 格式，不能保证引用原文和声明端点，本轮未增加接口/依赖。
- 剩余输入：OI-001/002 的真实用户实体关系金标、质量阈值和调用预算；当前保守谓词支持和同定义跨文档合并规则可能漏召回。Graph 继续默认关闭；两篇成功不等于生产质量 PASS。
- 复跑产物：本机 `data/benchmarks/s06/evaluate_graph.py`、`graph-results.json`、`extractor-results.json`、`last-failed-note.json`；原文件 hash、模型/配置/机器、产物 SHA 见 manifest。原文件/缓存不入 Git；最后一轮 24 次新调用的 token/账单未返回，不能当作 0 成本。
- S06.4 的两篇固定 PDF 生命周期功能门已通过；S06/S07/S08 的完整质量门仍保留。修复结束时前置改动与修复保留工作区；随后用户明确授权远端提交推送，范围及状态见 STATUS.md。

## OI-008：S07 工程通过，完整多跳验收未完成

- 证据：139 个不同的相关测试通过；真实模型处理合成 51 字符 TXT，3 条严格回源关系；真实 Qdrant/BM25/图通道的 G/GV/GVB 共 9 个查询均 graph_hits=1，越权交集为空时返回 0，删除后六张图表均 0 行。固定标注小图 1/2-hop、PPR 与证据保留已验证，详见 S07.md / S07-benchmark-manifest.json。
- 未测：真实跨文档多跳金标、同名/类型/定义消歧的生产 recall、总体/实体切片相对 S05 增益、完整论文索引 token/成本、人工 Trace/UI 点击及生产 P95。合成单 chunk 没有排名区分，不能产出这些验收结论；181 题 holdout 未用。
- 时间边界：SQLite 有 bounded wait/进度回调，循环读源前后检查截止时间；同步 get_chunk 已经阻塞时只能等待返回后丢弃结果。当前 VectorStore 合同没有取消/超时参数，硬中断需在后续资源隔离/超时任务解决，不将 250 ms 配置当作生产上限。
- 已解决的生命周期缺陷：ON→OFF→重建→删除曾残留 3 个实体，新增回归先失败；在现有删除入口绑定无需模型服务的同 scope 存储清理后通过。局部 31 项测试通过，六表零残留；OFF 无图时不创建图库，错误继续传播。未将可解决的功能缺陷留待用户决策。
- 后续：OI-007 的两篇完整论文抽取功能已修复；本轮实测 token 已记录，账单金额仍未知。OI-001/002 的真实标注/成本门槛与本节硬中断/UI 缺口保留。Graph 默认关闭，不因功能通过而推广 PPR 或增加通道权重。

## OI-009：S08 工程通过，真实查询路由与改写收益未验收

- 用户明确授权进入 S08。112 项相关测试通过，真实 DeepSeek/Qwen3/Qdrant/BM25 四组开关的合成功能配对完成；16 次调用范围漂移 0，原文固定先检索。应用开关已接线，新路由默认关闭，改写保留已有默认 true；见 S08.md / S08-benchmark-manifest.json。
- 已修复：原始查询被改写挤出、原始标识符被丢掉、模型 policy/query/scope 提权、Reading 被模型 proposal 扩到 workspace、失败时丢失选定文档范围、路由通道失败及计划 JSON 往返不兼容。严格额外字段拒绝与实际错误诊断保留。
- 本轮补修：语义路由返回非对象时曾继续沿用上一轮 `planned` 诊断；现在明确记录 `fallback` 和错误，并保持原来的选定文档范围。新增回归先失败后通过，见修复报告。
- 剩余质量边界：keyword/semantic/comparison 各只有 1 个合成问题，限定 1–2 篇文档；空请求负例不是语料无答案题。真实不确定缩写展开、误路由/漏召回、完整证据覆盖、错误拒答/漏拒答仍缺代表性金标。原文参与能保留词面信号，不能证明所有改写语义正确。
- 指标：每组功能 Recall@5/MRR=1.0，不能作为生产分数。首组有冷启动，末组有真实计划缓存，时延不用于默认策略推广。3 次真实 complete 调用的 token/账单未返回，成本记录 null。
- 方案：按 OI-001/002 冻结真实 keyword/semantic/multi-hop/no-answer 金标、门槛和预算；届时在同缓存/冷暖条件下对关闭/启用做配对评测，只有有净收益的策略才启用。当前用户要求功能优先，不在小型 smoke 上调阈值/权重，也不使用 holdout。
- 同步调用仍复用客户端 timeout/retry，未添加硬中断；人工 Trace/UI 未核验。现有检索全失败/无证据提示的知识专属拒答和 claim-level 验证属于 S10。OI-007/008 原问题保留，S08 完整 Stage/最终生产 Go/No-Go 继续 BLOCKED。

## 历史后续问题（结合上述更新读取）

- Parser、错论文与 no-answer 的端到端坏例缺少真实样本；收到 OI-001 数据后补充标注并回放。
- 注入 Qdrant/BM25/manifest 中途失败、崩溃恢复和 generation 发布检查在 S01 中实现；当前快照三存储均为 1312 个 chunk ID，差集为 0，不代表故障路径已经验证。
- Debug Studio 后端能按 run/case 返回 Trace，但尚未完成人工桌面 UI 点选核查。
- S03.3 配置改造、Vector Only 基准、冷启动/内存、缩写/跨语言 probe 及 generation 排序 smoke 已完成；Vector Only 质量低于 S00 Hybrid，详见 `S03.3.md`。
- 当前状态：OI-003 模型实际权重身份保护已修复；S05–S08 的应用级 scope 已接线并通过功能验证。OI-004 原质量门、真实权限场景及最终生产质量验收仍保留，不能用历史未实现清单覆盖最新工程状态。
- 已按用户明确指示完成 S04.1/S04.2 工程任务和 HF 评测，随后推进 S05–S08 工程。本轮解除 OI-007 的完整论文功能阻塞；S03 原质量门、S04–S08 完整生产质量门仍 BLOCKED，剩余事项按 OI-001/002/004/005/006/008/009 读取。
