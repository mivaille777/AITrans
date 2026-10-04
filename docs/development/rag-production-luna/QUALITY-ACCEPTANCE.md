# 公开数据效果验收与问题处理

日期：2026-09-30；基准提交 `4b0d802c`，含当前未提交 RAG 改动。用户已确认公开数据技术门槛：Recall@5≥0.80、MRR≥0.70、独立语义引用准确率≥0.90、暖端到端检索 P95≤800ms。生产业务门槛、用户语料及成本预算仍未批准。

2026-10-01收尾：补齐答案复放模型来源元信息并完成最终静态检查；下述实测数据及冻结目录仍对应2026-09-30。

## 当前结论

2026-10-03最新复验：原生视觉图片编码超时已修复并保存启用配置，50页实际PDF与真实DeepSeek HTTP/WS普通问答通过功能冒烟。Medical100999/dev100 的同公式 BM25 优化保持逐题排序一致，文本候选配置单并发 P95=638.48ms，4 并发=1464.74ms，Recall@5=0.63/MRR=0.5278；扩大重排池20为0.62/0.5259/976.55ms，未采用。单并发局部门通过，整体效果/并发门继续失败；规则guard的两个正例不替代独立语义引用验收。图/重写/视觉完整链路、持续容量和桌面启动仍需后续验证。详情见 [本轮风险处理](RISK-CLOSURE-20261003.md)，下文保留原实测范围。

**技术验收未通过，生产 NO-GO。** 召回、排序、拒答及独立评审问题已有实测证据；不把局部通过或引用格式正确率当成整体效果通过。Graph/Router 默认开关保持原值。QASPER 181题 holdout 尚未使用，开发集未满足门槛，不消耗它来宣告通过。

## 调用链与最小修改

### 2026-10-03 服务端与风险复验

用户选定本机 Qdrant 后，Docker 已恢复；100999篇既有语料/向量逐条核验迁移，并沿用相同 seed=42 的 Medical dev100。Dense Recall@5=0.62、MRR=0.5293、暖P95=728.15ms；BM25为0.38/0.3254/720.33ms；混合重排8（512 token）为0.63/0.5278/1227.34ms。三组无降级错误。Dense延迟通过，混合重排延迟和整体效果仍不通过；该单请求检索测试不覆盖答案质量或生产并发容量。

同题QASPER查询窗口实验为0.7529/0.5293，低于既有候选，未采用。真实 ColQwen GPU 查询成功，但图片编码120秒超时并终止，无残留；原生视觉不启用。资料范围/来源/JIT、聊天目录和Trace的接口冒烟通过，不替代独立语义引用验收。详情与全部本机证据见 [风险修复报告](RISK-REMEDIATION-20261003.md)。下文数字保持原2026-09-30报告，不覆盖原始结果。

### 原2026-09-30实现说明

- 现有 `Qwen3RerankerProvider → CrossEncoder` 已支持规范的 Qwen 因果模型/LogitScore；核对官方 Sentence Transformers 文档后，未发现需要替换模型架构的证据。
- 重排延迟主要来自候选数和输入长度。复用原有 `rerank_candidate_k/max_input_tokens`。试验过 FP16，但未取得可确认的延迟收益，已撤回新增精度字段、模型构造分支及其临时测试；现有生产配置/接口保持原状。
- 候选配置已保存为 `quality-rerank512.json`，经现有RagConfig验证，与本轮512 token/池8完整配置等价；仅用于后续评测，未晋级生产默认。
- 全库基准复用既有 HF 下载/读取、Embedding、Qdrant Local、BM25、RRF、reranker 和指标函数；所有文档参与检索，金标仅用于评分。公开行是预解析文本，不等同 PDF/权限/解析验收。索引位于忽略的 `data/benchmarks/`，不替换生产索引。
- 答案复放复用已冻结检索与项目既有 `GroundedQasperAnswerer`、答案合同和官方评分器，模型只接收问题与已召回证据。
- 修复复放manifest继承的空answer_model：从实际answerer写入提供方/模型。已有两份报告保留原manifest副本，再用已记录的answer_generation补齐来源，原回答及分数不变；两份均通过现有audit_qasper_run完整审计。未跳过policy fallback来源检查。
- 修复评测门禁：`eval_rag_production.py --judge-calibration` 要求校准合格、错误为0、N≥30、二值一致率与支持精确率均≥0.90，且 assessment 的 calibration_id 等于记录 SHA256。无合格记录不能以 judge 标注宣告独立引用效果已测。
- judge JSON 围栏复用 `normalize_model_output`；数量、标签和额外字段仍严格校验，错误留在分母。保存原来的失败结果，不覆盖原报告。
- Graph基准遇到建图失败返回partial/BLOCKED及退出码2；HTTP402取消尚未开始的API请求，已开始的请求正常收尾。原始失败日志保持不变。

本轮文件范围：`scripts/eval_rag_production.py`修复校准门禁；新增`run_hf_rag_benchmark.py`、`run_hf_graph_benchmark.py`、`run_qasper_answer_replay.py`、`calibrate_rag_judge.py`复用现有执行链；新增两份`test_hf_rag_benchmark.py`、`test_rag_judge_calibration.py`验证金标隔离/失败状态/校准合同。文档仅更新本报告、`OPEN-ISSUES.md`、`STATUS.md`、`gate.json`及候选配置；其余工作区改动不属于本轮新增实现。

## 冻结数据与评测口径

- QASPER 原始 JSON SHA256 `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93`；开发100题、80篇论文、1312 chunks。检索可对齐金标 N=87；答案可回答 N=94、不可回答 N=6，不能混用分母。
- 开发 ID SHA256 `217baa80d7d2802a428074fe660d1278902db5f7cba9144b52439dad5f76a37c`；holdout ID SHA256 `6403117043331c0ac4ef1b983e0203afa5aadd483fbf90e5c1beea765ef8982a`。
- SciFact revision `cf10ab6856b15b0e670ef8ae5dae4e266c12d035`，完整5183文档。参数比较只使用 train 随机100题；test300 是已在 S04 使用过的回归集，不称未见 holdout。
- MedicalRetrieval revision `bc05e883de33f26fb745fe57092796ceb65a48bb`，完整100999文档。固定 seed=42 的100题诊断与原 S04 全部1000题报告分开记录。
- HF 报告使用 MRR@20（保守截断，非 S04 MRR@100），关闭检索缓存；每个 profile 先执行一次不评分 warmup，再计完整检索 `elapsed_ms`，不含答案生成。QASPER 原生报告含首次加载，暖分位另行核对。
- 产物记录源文件/权重/配置摘要与逐题通道、融合、输入/输出候选列表；增强后的 runner 另记代码摘要。早于增强启动的报告保留原状态，不虚补当时未记录的内容。FP16 未晋级实验的两个实际源文件快照保存在 `data/benchmarks/quality-acceptance/precision-experiment-sources/`，复现该实验需要这两个快照，当前接口不接受实验字段。

## 已完成的开发集比较

### QASPER 同一100题，既有切块/已知论文范围

| 配置 | Recall@5 | MRR | 暖检索P95 ms（99题） | 结论 |
|---|---:|---:|---:|---|
| 重排8，原输入上限 | 0.8161 | 0.5181 | 633.69 | MRR未过 |
| 重排12，原输入上限 | 0.8126 | 0.5351 | 815.53 | MRR/延迟未过 |
| 重排20，原输入上限 | 0.8011 | 0.5344 | 995.93 | MRR/延迟未过 |
| 重排8，512 token | 0.8333 | 0.5424 | 460.43 | MRR未过；输入限制有观测收益 |
| 切块256 token，重排8/512 | 0.7759 | 0.5234 | 562.60 | Recall/MRR未过；不采用 |

证据：`data/benchmarks/qasper/s03-3-vector-only/results/quality-dev100-{pool8,pool12,pool20,rerank512,chunk256}-20260930/`。暖值从逐题完整检索时长剔除首次重排加载后计算；原报告100题 P95 为669.36/820.86/1148.68/476.57/565.37ms。小切块的段落Evidence Precision@5为0.1123（原切块/512输入为0.1060），但段落召回0.7776低于0.8333，未解决噪声与覆盖的取舍；块ID金标随分块重建，跨分块对照同时核对稳定段落指标。

512输入与原上限的配对开发集复核：87题/72篇论文，按paper ID聚类、seed42、5000次bootstrap。Recall@5差值+0.0172，95%区间[-0.0118,0.0549]；MRR差值+0.0243，区间[0.0026,0.0508]。论文是现有可用聚类单位，没有更高层文档家族标注；这是开发集上的探索性比较，未校正多配置选择，观测收益未经独立holdout确认。不能仅扩大池或根据相关文本放宽答案校验来绕过问题。

补齐同题同库 Dense/BM25-RRF 比较：Dense Recall@5=0.6724、MRR=0.4640；Hybrid 无重排=0.7184/0.4753。两者均 N=87，索引复用。FP16/512/B3 的0.8333/0.5383属于撤回实验，不混为当前默认结果。结果位于 `ablation/quality-dev100-baselines-20260930/comparison.json`。

### SciFact train100，全库

| 配置 | Recall@5 | MRR@20 | 暖P95 ms | 检索门 |
|---|---:|---:|---:|---|
| Dense | 0.8425 | 0.7477 | 156.63 | PASS |
| BM25 | 0.7017 | 0.6492 | 54.26 | FAIL |
| Dense+BM25/RRF | 0.7925 | 0.7041 | 202.47 | FAIL |
| 混合+重排8 | 0.8725 | 0.7835 | 954.74 | 延迟FAIL |
| 混合+重排12 | 0.8825 | 0.7835 | 1046.27 | 延迟FAIL |
| 混合+重排20 | 0.8800 | 0.7877 | 1516.25 | 延迟FAIL |
| 混合+重排8，512 token | 0.8725 | 0.7710 | 639.35 | PASS |

### SciFact test300，冻结512 token/重排8的回归

| 配置 | Recall@5 | MRR@20 | 暖P95 ms | 检索门 |
|---|---:|---:|---:|---|
| Dense | 0.7718 | 0.6651 | 153.10 | FAIL |
| 混合+重排8，512 token | 0.7821 | 0.7209 | 667.53 | Recall FAIL |

RRF 前8候选金标覆盖只有0.8173，限制了后续排序；更大候选池需同时解决延迟，不能用 test 决定参数。随后仅在 train100 试验 FP16/512：池8/12/20 的 Recall@5 为0.8725/0.8825/0.8800，MRR为0.7715/0.7697/0.7705，P95为709.33/953.16/1677.57ms。未解决较大池的延迟门，撤回此实现，也未据此重复调试 test。

### MedicalRetrieval 全100999文档，固定诊断100题

| 配置 | Recall@5 | MRR@20 | 暖P95 ms |
|---|---:|---:|---:|
| Dense | 0.63 | 0.5343 | 2121.85 |
| BM25 | 0.38 | 0.3254 | 750.08 |
| Dense+BM25/RRF | 0.57 | 0.4691 | 2921.62 |
| 混合+重排8，512 token | 0.63 | 0.5237 | 2981.56 |

所有 profile 未过检索门，无通道降级。Embedding使用现有fp16/batch32选项，同一模型内容指纹与完整corpus；不把此100题诊断当成原1000题全量验收。完整索引已落盘，可直接复放。主要排序/候选不足之外，10万文档下Qdrant Local检索是秒级；运行库也提示超过20000 points不推荐Local模式。需要容量限制或在既有接口下评估服务端部署，单纯换重排参数无法解决。

## 公开多跳 Graph 诊断：外部阻塞，非验收通过

下载HF `framolfese/2WikiMultihopQA` 固定revision `fe713bfbd1afbca1a65246741a75890405d56a3a`，原数据与证据结构对照[原项目](https://github.com/Alab-NII/2wikimultihop)。validation12576题中 seed=42 抽30题，全部上下文/干扰文档的并集259篇；抽取不接收金标。使用真实GraphExtractionService/GraphIndexer/SQLite/GraphRetriever，原文由真实BM25 chunk catalogue回源，不用硬编码实体、关系或路径；未接入Dense。

**DeepSeek HTTP402 导致85篇抽取失败，另1篇逐字证据校验失败。** 已完成173篇、572实体、1关系；因此是部分图索引，Graph质量结论 BLOCKED。下列值仅诊断，不可公平推断完整Graph能力：

| 通道 | Recall@5 | MRR@20 | 完整证据文档集@5 |
|---|---:|---:|---:|
| BM25 | 0.5833 | 0.9375 | 0.20 |
| Graph部分索引 | 0.1667 | 0.3500 | 0 |
| Graph部分索引+BM25 | 0.5833 | 0.9542 | 0.20 |

多跳任务中命中首篇可使MRR很高，但完整证据集覆盖只有20%，不能据MRR宣布可用。已完成抽取的拒绝计数：unsupported_predicate=371、missing_entity=59、missing_claim=1、negated_or_uncertain=7；关系词表/逐句实体/指代限制确有覆盖缺口，完整Graph收益仍不能从部分索引推断。路径源范围校验通过，没有用缺失图伪造成功。原完成日志保留；追加 `qualification.json`标明PARTIAL/86错误；runner已修正此种运行返回partial/失败退出。

**待用户决定：检查DeepSeek余额/计费并恢复可用额度，或指定另一个已配置、获授权且可用的提供方。** 未自动充值或切换到未知模型；当前阻塞解除前停止额外API抽取。需要复放85篇HTTP402失败文档及1篇逐字证据坏例，再冻结Graph评测；不把当前结果当作跨文档Graph生产验收。

## 答案与评审

同一冻结检索、DeepSeek v4 Flash，模型输入不含金标；原答案服务与已有 `p1q3-direct-answer-v2-answer-adequacy` 合同比较：

| 指标 | 原答案格式 | 复用直接答案合同 |
|---|---:|---:|
| 官方 Answer F1 | 0.1901 | 0.3582 |
| 误拒答（94道可回答题） | 72 / 94 | 44 / 94 |
| 漏拒答（6道不可回答题） | 0 / 6 | 0 / 6 |
| 布尔答案准确率（N=20） | 0 | 0.15 |
| 合同/允许引用格式有效率 | 不适用 | 0.99 |

格式改善提高了可评分性并减少误拒；官方 F1 的提升不等于语义支持度同幅提升。合同仍有1题格式失败、答案及布尔拒答仍未解决。被测 verifier 自报最终 Unsupported Claim Rate=0，伴随大量拒答，不能充当独立 Citation Accuracy。

独立参考：[RefChecker](https://github.com/amazon-science/RefChecker)，revision `1df1b25cee792ba2b171302e31ca4f768bd67703`；原文来自 HF Dolly revision `bdd27f4d94b9c1f951818a7da7fd7aeea5dbff1a`。保留上游许可证；按问题ID划分校准/复核，各抽取支持/矛盾/中立30条（每折90条）；人工标签从不发送给 judge。同一问题内的多条标注相关，不作独立样本置信推断。

| Judge复核 | 错误 | 二值一致率 | 支持精确率 | 校准可用于验收 |
|---|---:|---:|---:|---|
| Flash | 0 | 0.8889 | 0.7941 | 否 |
| Pro，原严格JSON | 32 / 90 | 0.5667 | 0.8696（有效输出） | 否 |
| Pro，复用围栏清理 | 0 | 0.9000 | 0.8387 | 否 |

Pro 格式修复使用相同公开折复核，不能称新未见样本。校准折也未合格，因此不生成“已校准judge”标签来虚填引用准确率。三元组的指代、上下文和上游标注差异仍需人工裁决；现有自动评审无法可靠替代。

## 问题清单与后续决策

| 问题 | 本轮处理 | 保留项/可执行方向 |
|---|---|---|
| OI-001 | 补齐全库 Dense/Hybrid 与公开人工评审参考 | 用户真实语料/源锚点/跨文档问题仍缺 |
| OI-002 | 记录用户已批准公开技术门槛 | 生产业务及资源/LLM预算待定 |
| OI-003 | 运行记录真实 embedding 指纹、reranker权重/配置摘要 | 默认发布snapshot政策待定 |
| OI-004/006 | 同题Dense/Hybrid、池8/12/20、输入限制；撤回无收益FP16实现 | QASPER MRR未达0.70，不宣告已修全部坏例 |
| OI-005 | 英文全库消融与test回归；中文完整索引/诊断 | 按实测记录失败；保留库规模、语义召回问题 |
| OI-007/008/009 | 新增公开30题/259文档真实Graph流程诊断，保留安全默认开关 | HTTP402导致部分索引，不作为合格多跳验收；真实用户关系金标及路由收益仍缺 |
| OI-010 | 恢复效果验收，完成200次实际答案复放及180条/模型人工标签校准；封堵未校准标签入口 | 需要独立人工裁决/更可靠且经校准的评审；拒答与答案完整性仍不合格 |
| OI-011 | 开始100999文档规模的真实存储/模型评测 | 同步native硬取消、多进程部署、完整答案Trace与历史缺版本问题仍保留 |

明确建议：采用已验证的有界重排作为候选配置；排序未过门的域继续开发集诊断；语义答案校验保持保守，先补标注再调整。Qdrant Local/BM25 JSON 的大库成本达到限制时，才在现有接口下评估服务端存储迁移；本次不进行未经验证的数据库或依赖替换。

后续最小实施顺序：

1. 恢复API可用性后，仅重放失败抽取，先处理逐字证据坏例及谓词拒绝记录，再比较完整Graph与BM25。参考[Microsoft GraphRAG数据流](https://microsoft.github.io/graphrag/index/default_dataflow/)的实体/关系抽取和TextUnit回源方式，保留本项目已有source span/范围/版本门禁；先标注并验证关系覆盖，不能直接接受全部未知谓词。
2. 在已导出的54条QASPER排序坏例中核对融合池、重排输入、top5与上下文的原文覆盖；8→12/20会越过延迟门，256切块会降召回，因此下一轮按失败阶段选择一种策略做同题开发集比较。
3. 对44条误拒答人工核对模型首次输出、修复与最终拒答原因；保留语义门，区分模型拒答与校验器误拒。自动judge未合格，先完成独立裁决后再调整答案策略。
4. 中文10万文档的容量方案先确认部署约束；[Qdrant官方本地服务部署](https://qdrant.tech/documentation/quickstart/)可作为现有存储接口下的验证方向，需要实际对比召回、过滤、持久化与并发P95，不能假定迁移后已经达标。

## 验证与复现

收尾定向验证38项通过（候选池、reranker、HF数据/门禁、judge、生产评测runner、答案合同）；随后Graph失败状态保护加入后，对该评测模块5项验证全部通过。固定CI64项通过；本轮5个评测脚本/2个新增测试文件Ruff通过。候选配置通过RagConfig验证并与实际完整配置比较等价；git diff空白检查通过。存量 `config.py` 的4项UP037、旧reranker测试的1项ISC004与HEAD相比无新增诊断，保留历史问题。

逐题审计保存在 `data/benchmarks/quality-acceptance/quality-audit-20260930/`：按单题Recall@5/MRR候选值筛查的54条排序诊断问题（整体门槛仍按聚合指标判定）、44条误拒答、论文聚类bootstrap与源文件SHA256。排序定位的阶段覆盖仅表示“任一金标段落出现”，不等于完整证据充分性或语义支持。Graph的`qualification.json`包含原日志/指标摘要；所有原评测保留。当前代码无额外API请求。

复现入口：

```powershell
conda activate aitrans
python scripts/run_hf_rag_benchmark.py --dataset scifact --split train --limit 100 --profiles dense rerank8 --config-json docs/development/rag-production-luna/quality-rerank512.json --output data/benchmarks/quality-new-train
python scripts/run_qasper_answer_replay.py --run <冻结QASPER目录> --output <新目录> --answer-contract backend/rag/benchmarks/qasper/profiles/p1q3-direct-answer-v2-answer-adequacy.json
python scripts/calibrate_rag_judge.py --root data/benchmarks/quality-acceptance/refchecker --output <新目录>
```

输出目录必须新建；校准模型如需比较，通过现有 `AITRANS_MODEL_AGENT_SYNTHESIS` 进程变量选择，不修改用户持久设置。公开原文/预测/模型缓存位于忽略目录；本轮未提交推送，远端CI未执行。
