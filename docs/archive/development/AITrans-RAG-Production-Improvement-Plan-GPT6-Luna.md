# AITrans RAG 生产级改进任务书：GPT-6 Luna 执行版

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

制定版本：2026-09-29。本文件是执行清单；已执行阶段与验收结果见 [执行状态](rag-production-luna/STATUS.md)，当前调用链与开关见 [当前 RAG 架构](rag-production-luna/RAG-ARCHITECTURE-CURRENT.md)，待解决事项见 [问题清单](rag-production-luna/OPEN-ISSUES.md)。Luna 每次只执行一个编号任务，并在该 Stage 的门禁通过后进入下一 Stage。

## 0. 如何使用本任务书

### 0.1 制定时基线，先验证再修改

以下是制定任务书时的代码基线，保留用于对照；后续已实现的索引发布、Graph 与评测修复以执行报告和当前代码为准。

当前产品主链路是 backend/api/knowledge_dependencies.py 装配的 backend/rag/retrieval_service.py：Qwen3 embedding → Qdrant Local Dense、BM25 Sparse、可选章节检索 → RRF → Qwen3 reranker → small-to-big → evidence/context/citation。config/default.toml 现设 Dense/Sparse 各 Top30、Fusion Top20、Final Top8；backend/rag/config.py 在 rerank_candidate_k 未配置时只重排 Final Top8。backend/rag/index_service.py 将 Qdrant、BM25 与 JSON manifest 分步写入，缺统一发布边界。Knowledge Canvas（backend/api/knowledge_canvas.py）和 Agent 卡片图（backend/services/agent_knowledge_retrieval.py）不在这条论文检索主链路内。RAG Debug Studio 已有后端 API/SQLite 和桌面 Trace 组件，但没有在线 Graph 阶段；backend/services/rag_debug_service.py 的 dataset 评测把 pre-rerank 与最终 ID 列表写成同一值。

QASPER 是“已知论文 ID”过滤的评测，且适配器绕开真实 PDF 解析；它不能单独证明未知文档发现或生产导入质量。docs/development/qasper-p1-q1-5-gate-review.md 的结论是 NO-GO。不要把原方案中的设计目标或待测表格写成已取得的成绩。

### 0.2 锁定架构，避免每次重做设计

1. 保留现有 DocumentChunk、RetrievalCandidate、RetrievalResult、RetrievalService.retrieve 和知识 API 的外部合同；先增加字段与 Adapter，不建立第二套产品 RAG。
2. 统一候选始终带真实 DocumentChunk。Graph 的节点、边、社区摘要只负责找原文，不能直接作为 citation。Graph Candidate 必须能追到原文 span 和有效索引 generation。
3. 所有通道共享 knowledge_scope_resolver 冻结的 allowed_document_ids；查询改写、图遍历、融合与引用不能扩大范围。范围未知时停止知识检索。
4. Graph 存储先用独立 SQLite Adapter，先做 1–2 跳和 passage recovery；PPR 是后续消融对象。Neo4j、Milvus、OpenSearch 等仅在 Stage 15 实测表明本地方案不满足需求时评估。
5. 现有 Docling、Qdrant Client、BM25、RRF、Qwen3 reranker 和 Debug Studio优先保留。GraphRAG、HippoRAG、LightRAG 借鉴设计；不直接复制整个框架。外部包在真正安装前复核官方 LICENSE、版本、模型权重许可并记录。
6. RAPTOR、视觉检索、Knowledge Canvas、Agent 卡片图保持现有边界。没有调用图和兼容测试前，不删任何历史模块，也不将其误称为产品 GraphRAG。

### 0.3 Luna 单任务工作协议

每次 Codex Session 只接受一个任务 ID，例如 S05.2。开始时读取本文件该 ID、前一任务报告和允许修改的源文件，然后运行 git status --short 和精确的 rg 搜索，确认当前类/接口仍存在。若仓库与任务书不符，在报告中写清差异，只做能确认的部分；不能凭任务书猜测 API。每个任务通常只改 1–3 个生产模块及其测试；需要更多文件时先拆成同 Stage 的更小任务。

执行顺序固定：读现有实现 → 写失败用例/可复现实验 → 最小改动 → 定向单测 → 调用方集成测试 → 当前 Stage 基准 → Bad Case 回放 → 查看 diff → 写报告 → 仅暂存本任务文件并 commit。Git 中已有用户修改一律保留；不要使用 git add -A，也不要把未通过结果标为 PASS。命令应从 D:\AITrans 运行，前端命令在文中注明目录。

所有新增文件都在任务表标为“新建”；存在的路径按本次审计核实。未来执行时再次检查。测试所需的模型、网络、样本或权限缺失，记录为 BLOCKED 和具体缺口；不得生成假 Benchmark、空成功报告或绕过门禁。单测/集成测试/指标未过时只修当前任务。可选算法可以以“实现并保留关闭”完成技术验证，但该 Stage 的上线收益门禁未过就不能进入下一 Stage。

每次收尾按以下固定格式写 docs/development/rag-production-luna/SXX.YY.md（新建），并更新同目录 STATUS.md（新建）：

~~~text
任务ID / 状态(PASS|FAIL|BLOCKED) / 基准提交 / 本次提交
实际改动文件、接口变化、保留的旧合同
运行命令与真实退出码；未运行项及原因
数据集/索引/模型/配置/机器指纹
同一数据的 Baseline → New：Recall@5/10、MRR、nDCG@10、P95、成本
Bad Case ID：修复前首个失效阶段 → 修复后证据
安全门：越权/过期引用/半成品索引/崩溃计数
人工 Debug Trace 所见；结论；下一任务 ID
~~~

STATUS.md 只允许一个 IN_PROGRESS；状态为 PASS 才推进任务指针。Stage 报告按 S00.md、S01.md 等汇总该 Stage 的所有子任务、基准和最终门禁。一个 Stage 至少一个独立 commit；建议每个通过的子任务一 commit，提交信息在下文给出。报告包含 Git SHA 和指纹，便于下一 Session 不重读整仓。

### 0.4 可复制的 Luna 执行提示

~~~text
在 D:\AITrans 执行 AITrans-RAG-Production-Improvement-Plan-GPT6-Luna.md 的任务 <ID>。
先读取该任务、0.2–0.3 的约束、STATUS.md、上一任务报告及列出的真实源码。
只实现本任务表的改动；若接口不同，先核实并记录差异，不新增平行 RAG。
先做可复现失败用例，再最小修复；执行表中的单测、集成测试、基准和坏例回放。
仅在本任务门禁通过时更新状态与提交本任务文件。报告必须填实际命令、退出码、
配置/数据指纹和指标；未运行项写 BLOCKED，不得猜测结果。完成后停止，不开始下一 ID。
~~~

## 1. 统一数据与质量门禁

### 1.1 候选与图的实现合同

S05.1 扩展 backend/rag/models.py 中已有 RetrievalCandidate，保留 chunk: DocumentChunk、dense_score、sparse_score、fusion_score、rerank_score 和 metadata 以免破坏现有消费者。新增 channel_hits（通道、原始分数与 rank）、graph_paths（节点/边 ID、source span）、index_generation、trace_id。S05.2 再新建 backend/rag/retrievers/base.py 的 RetrievalRequest/ RetrieverChannel 协议，旧 RetrievalService.retrieve 继续是对外入口。

S06 的图表至少有 entity、alias、relation、relation_span、chunk_entity、graph_generation；每个关系需存来源 document/chunk/span、提取器版本、置信度和作用域。歧义实体先分开保存。S07 的检索必须从 query entity/alias 找 seed，经有界遍历找关系，再通过 relation_span/chunk_entity 恢复可引用 DocumentChunk，最后进原有融合与重排。图查询没有可用 span 时返回空候选和原因。

### 1.2 指标定义与硬门

S00 冻结三套数据：CI 手算小集、开发集、按论文家族/来源隔离的 holdout；另存真实原文件导入集。QASPER 单列“已知论文”报告，不能与真实 PDF 结果合并。金标用 document hash + page/section/offset + 原文摘录；多条可替代完整证据集用 OR-of-AND 表示。“相关但证据不足”和“没有相关文档”分开。

指标由 S11 落地，但 S00 起必须用已有评测记录基线。Recall@K、Precision@K、Hit Rate@K、MRR、nDCG@10 分别报告文档级和证据级；另报完整证据集覆盖、Context Precision/Recall、claim-level Citation Accuracy、经人工校准的 Faithfulness、错误/正确拒答、P50/P95、token 与索引成本。被测系统自报 supported 不能当 faithfulness 真值。

安全硬门在每个 Stage 都是：越权候选或图路径 = 0，过期/不存在的 citation = 0，半成品 generation 可见 = 0，未处理崩溃 = 0，已修坏例复发 = 0。新功能默认开启还要求同数据集的目标切片提升、总体 Recall@5/10、MRR、nDCG@10 不低于冻结基线超过 0.02 绝对值，并符合 S00 冻结的 P95/成本预算。S00.md 必须写数值门槛 B（基线）、Δ（最小提升）、F（最低可用值）、L（P95 上限）、C（citation/faithfulness 下限）、N（最小有效样本数）；任一待定则不能宣称生产 PASS。Holdout 只用于预登记的最终复核，不能用来调参。

S00.3 的 gate.json 必须按 query 切片分别填这些数值和单位，并写每个值的依据。可从用户原要求中 Recall@5 0.80、MRR 0.70、Citation Accuracy 0.90、P95 Retrieval 800 ms 的示例出发，但它们是待 S00 数据/机器核准的候选门槛，不是已达标事实；不可把示例直接套到不适用的数据集。Δ 对以增益为目标的切片必须大于 0，N 必须足以判断分层差异。若数据或业务依据不足以确定 F/L/C/N，S00.3 标 BLOCKED 并明确缺少哪项依据；后续可继续做只读审计，不能开启“已达生产”结论。

### 1.3 报告的最小 Benchmark 矩阵

S05 起可运行 Vector、BM25、Vector+BM25；S07 起增加 Graph、Graph+Vector、Graph+Vector+BM25；S09 起增加带 Reranker 的组合。所有变体必须同 corpus、分块、embedding、索引 generation、硬件、配置、query 集和回答契约。另做 rewrite on/off、rerank pool 8/12/20、Graph 1-hop/2-hop/PPR 配对消融。报告逐题差异和按文档家族 bootstrap 的区间，标记未运行变体，不填伪造数字。

## 2. 逐阶段任务表

表中的“检查”先列可运行的现有命令；标注“新增后”表示脚本或测试应由该任务创建。每个 Stage 的最终一项负责同机 Benchmark、坏例与人工 Debug Studio 检查；其 Stage 报告未 PASS，下一 Stage 不得开始。

### S00：审计与可复跑 Baseline

当前问题：QASPER 高候选召回来自已知论文过滤；真实导入、跨文档发现与索引一致性没有同一冻结基线。目标是得到能复跑、能失败、能对照的基准，而不是在此阶段假称质量达标。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S00.1 | 写调用图/索引审计；只新增 docs/development/rag-production-luna/S00.1.md，读取 backend/api/knowledge_dependencies.py、backend/rag/index_service.py、retrieval_service.py、backend/api/knowledge_canvas.py、backend/services/agent_knowledge_retrieval.py。 | 列出真实 API→索引→检索→Agent/Companion 的入口和 Graph 未接入的证据；git status 中用户文件不变。 |
| S00.2 | 新建脱敏 fixture、scripts/rag_production_baseline.py 与对应 tests/rag/test_production_baseline.py；脚本调用现有 QASPER/评测代码，并单独覆盖真实文件导入。 | python -m pytest tests/rag/test_rag_evaluation.py tests/rag/test_production_baseline.py；python scripts/run_qasper_benchmark.py --mode smoke --retrieval-only；脚本失败时退出非零，产物含逐题记录。 |
| S00.3 | 新建 docs/development/rag-production-luna/{STATUS.md,S00.md,baseline-manifest.json,gate.json}；冻结数据哈希、模型/配置/索引版本、机器与 B/Δ/F/L/C/N。 | 同命令重跑指标一致；Qdrant/BM25/manifest chunk-ID 差集已记录；至少保存 parser、错论文、无答案、索引不一致各一坏例。人工 Debug Studio 能按 case 找到 trace。 |

Stage 门禁：基线可复跑且所有未测项明确写 BLOCKED；不要求现有坏指标变好。Commit：chore(rag): freeze luna baseline。

### S01：导入与索引一致性

当前问题：backend/rag/index_service.py 跨 Qdrant、BM25 和 JSON manifest 分步写入，失败可能暴露部分索引。目标是先可审计，再安全发布、恢复和删除。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S01.1 | 新建 backend/rag/index_audit.py、tests/rag/test_index_audit.py；只读核对 manifest/BM25/Qdrant 的 document、chunk ID 与 generation 差集。 | python -m pytest tests/rag/test_index_audit.py tests/rag/test_index_manifest.py；缺一库明确失败，不修改索引。 |
| S01.2 | 只改 backend/rag/index_manifest.py 与 tests/rag/test_index_manifest.py，定义构建中/校验中/READY、active generation 与旧版保留的状态迁移；此任务不改变读写行为。 | python -m pytest tests/rag/test_index_manifest.py；非法迁移、重启恢复、重复发布被拒绝。 |
| S01.3 | 改 backend/rag/sparse/store.py、stores/qdrant.py；新建 tests/rag/test_sparse_lifecycle.py，让两种索引支持按 generation 写入/读取/删除；暂不切换产品入口。 | python -m pytest tests/rag/test_qdrant_store.py tests/rag/test_sparse_lifecycle.py；两个 generation 可并存，显式读取旧版结果不变。 |
| S01.4 | 改 backend/rag/index_service.py、tests/rag/test_index_service.py；构建新 generation、核对 chunk-ID 差集、READY 后切 active pointer，失败保留旧版。 | python -m pytest tests/rag/test_index_service.py tests/rag/test_index_manifest.py；在向量写完/BM25 写完处注入异常，在线读只见旧版。 |
| S01.5 | 改 backend/services/knowledge_library_service.py 与知识 API 测试；重导入/删除/重启恢复走同一版本生命周期。 | 真实 PDF、DOCX、HTML、TXT 导入/删除；0 孤儿 ID、0 半成品可见，记录吞吐/P95/内存与失败注入坏例。 |

Stage 门禁：S01.1 差集为 0 或全部差异有修复记录；重复导入幂等、断点重启结果一致，安全硬门通过。Commit：feat(rag): publish consistent index generations。

### S02：解析、分块和原文锚点

当前问题：DocumentChunk 有页/节/字符字段，但重切 chunk 会让仅靠 chunk_id 的金标和引用失效；扫描 PDF 的 OCR/公式默认关闭。目标是让任何证据可回原文。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S02.1 | 新建 backend/rag/source_span.py、tests/rag/test_source_span.py；为 backend/rag/models.py 的 DocumentChunk 增加向后兼容的 source span/版本字段。 | python -m pytest tests/rag/test_models.py tests/rag/test_source_span.py；旧 JSON 能反序列化，fixture span 能回源文本。 |
| S02.2 | 改 backend/rag/parsers/docling.py、tests/rag/test_parser_quality.py（新建）；输出低文本量、页序、OCR/表格诊断，不默默入库空文档。 | python -m pytest tests/rag/test_parser_quality.py；扫描件/双栏/表格 fixture 有明确状态与来源页，OCR profile 仍由配置控制。 |
| S02.3 | 改 backend/rag/chunking.py、semantic_chunking.py、index_service.py 和对应测试；保留章节与段落边界、表格/公式类型。 | python -m pytest tests/rag/test_semantic_chunking.py tests/rag/test_semantic_index_service.py tests/rag/test_source_span.py；0 空证据 chunk，fixture 引用 100% 可回原文；记录 Chunk Recall/P95 和错页坏例。 |

Stage 门禁：真实导入样本引用定位正确，总体检索指标过回归门；如 OCR 无增益保持关闭。Commit：feat(rag): anchor evidence to source text。

### S03：Embedding 与 Vector Retrieval

当前问题：Qwen3 embedding/Qdrant Local 有可用接口，但模型版本、维度、过滤和升级不具备完整合同。目标是稳定 Vector Only 基线和索引迁移。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S03.1 | 改 backend/rag/embeddings/qwen3.py、embeddings/base.py、backend/rag/index_manifest.py；将模型 ID、维度、归一化、前缀写入 fingerprint。 | python -m pytest tests/rag/test_knowledge_dependencies.py tests/rag/test_qdrant_store.py；不匹配维度/版本明确失败或重建，不能静默混用。 |
| S03.2 | 改 backend/rag/stores/qdrant.py、stores/base.py 与 tests/rag/test_vector_scope.py（新建）；search 前后都检查允许文档集和 generation。 | python -m pytest tests/rag/test_vector_scope.py tests/rag/test_qdrant_store.py；无权限查询返回 0 候选，删除后无旧结果。 |
| S03.3 | 改 backend/rag/embeddings/runtime.py、api/knowledge_dependencies.py 的批量/冷启动配置；不改变公共检索合同。 | 同机 Vector Only 测 Recall@1/5/10、MRR、P50/P95、冷启动/内存，保存缩写和跨语言坏例；重复查询同 generation 排名稳定。 |

Stage 门禁：0 越权/维度静默错误；Vector Only 不低于 S00 同数据基线。Commit：feat(rag): version vector retrieval。

### S04：BM25 与术语召回

当前问题：backend/rag/sparse/tokenizer.py 和 JSON BM25 对符号、缩写、中文及删除后的生命周期需要量化。目标是稳定 Keyword/Identifier 召回。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S04.1 | 改 backend/rag/sparse/tokenizer.py、sparse/bm25.py；用现有 tests/rag/test_sparse_tokenizer.py 增加 DOI、化学式、缩写、中文混排样本。 | python -m pytest tests/rag/test_sparse_tokenizer.py tests/rag/test_special_sparse_retrieval.py；固定标识符 fixture 100% 命中正确文档。 |
| S04.2 | 改 backend/rag/sparse/store.py 与 S01.3 已建的 tests/rag/test_sparse_lifecycle.py；查询/索引 tokenizer 版本一致，重建、删除、重启后无旧 chunk。 | python -m pytest tests/rag/test_sparse_lifecycle.py tests/rag/test_sparse_section_neighbors.py；BM25 Only 分术语/标识符报告 Recall/MRR/P95/索引大小，保存丢符号坏例。 |

Stage 门禁：0 过期/越权 BM25 候选，质量不低于 S00 Sparse 基线。Commit：feat(rag): harden sparse retrieval。

### S05：统一候选和 Hybrid

当前问题：backend/rag/models.py 的候选只有部分通道分数，backend/rag/fusion.py 按 chunk ID 融合，新 Graph 无统一来源记录。目标是在不破坏旧调用方的前提下接入可消融通道。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S05.1 | 只改 backend/rag/models.py、tests/rag/test_models.py，增加 channel_hits、graph_paths、index_generation、trace_id；保留旧字段和反序列化。 | python -m pytest tests/rag/test_models.py tests/rag/test_retrieval_service.py；旧调用方返回模型仍可读。 |
| S05.2 | 新建 backend/rag/retrievers/{base,vector,bm25}.py 与 tests/rag/test_retriever_contract.py；把现有向量/稀疏调用包成共享 RetrievalRequest，不移除原 RetrievalService。 | python -m pytest tests/rag/test_retriever_contract.py tests/rag/test_retrieval_service.py；同 query/filter 两通道作用域一致。 |
| S05.3 | 改 backend/rag/fusion.py、retrieval_service.py；保留旧对外签名，去重键为 generation + chunk_id，并保存各通道原始 rank/score。 | python -m pytest tests/rag/test_fusion_context_window.py tests/rag/test_retrieval_service.py tests/agent/test_knowledge_access_contract.py；跑 V、B、VB 三组，记录 RRF 淹没正确候选的坏例和 Debug 分数。 |

Stage 门禁：API/Agent 合同全绿；Hybrid 在 S00 冻结混合题切片达到目标门槛，总体无超过 0.02 的回退。Commit：feat(rag): unify hybrid candidates。

### S06：可追溯的 Graph Index

当前问题：现有 Canvas/卡片图不是论文主检索图。目标是从已入库 chunk 建立带原文来源、作用域和版本的实体关系图。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S06.1 | 新建 backend/rag/graph/{models,repository}.py、tests/rag/graph/test_repository.py；SQLite schema 含 entity、alias、relation、relation_span、chunk_entity、graph_generation 和查询索引。 | python -m pytest tests/rag/graph/test_repository.py；CRUD、事务回滚、按 scope/generation 过滤、删除均可验证。 |
| S06.2 | 新建 backend/rag/graph/extractor.py、tests/rag/graph/test_extractor.py；从 DocumentChunk 提取 entity/relation，任何边都必须带原文 span 和 extractor 版本。 | python -m pytest tests/rag/graph/test_extractor.py；否定句/表格/无证据关系拒绝发布；固定标注集报告 precision/recall。 |
| S06.3 | 新建 backend/rag/graph/resolver.py、tests/rag/graph/test_resolver.py；标准化别名、候选消歧，同名异物保持不同节点，跨 scope 不合并。 | python -m pytest tests/rag/graph/test_resolver.py；同名歧义、别名和跨文档共有实体坏例有确定输出。 |
| S06.4 | 新建 backend/rag/graph/indexer.py；改 backend/rag/index_service.py、index_manifest.py 及集成测试，构图与删除纳入 generation 发布。 | python -m pytest tests/rag/graph tests/rag/test_index_service.py；两篇真实论文导入/重导入/删除；0 无来源边、0 旧边残留、0 跨 scope 合并，记录构图耗时/图大小。 |

Stage 门禁：graph index 完成且每条可发布边有有效 source span；抽取/消歧达到 S00 标注门槛。此时仍不宣称 GraphRAG 在线。Commit：feat(graphrag): index source-grounded graph。

### S07：在线 Graph Retrieval 与多跳

当前问题：backend/rag/retrieval_service.py 目前没有图通道。目标是 Graph → Passage → Fusion → Rerank 真正运行，并在多跳题证明价值。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S07.1 | 新建 backend/rag/graph/query_entities.py、graph_retriever.py、tests/rag/graph/test_graph_seeds.py；按 alias/实体类型找作用域内 seed，再通过 chunk_entity/relation_span 找原文候选。 | python -m pytest tests/rag/graph/test_graph_seeds.py；seed 错配/无映射返回空，不生成虚构 chunk。 |
| S07.2 | 改 graph_retriever.py；新建 graph/scoring.py、tests/rag/graph/test_graph_traversal.py；实现 1–2 跳、最大 seed/节点/路径/deadline 限额与 graph_path 来源记录。 | python -m pytest tests/rag/graph/test_graph_traversal.py；热门节点/环/跨 scope/超时受限，路径每条边能点击回原文。 |
| S07.3 | 改 backend/rag/retrieval_service.py、fusion.py、api/knowledge_dependencies.py，图作为可关闭通道进入现有融合，并保持失败降级信息。 | python -m pytest tests/rag/test_retrieval_service.py tests/rag/graph/test_graph_traversal.py tests/agent/test_knowledge_access_contract.py；真实请求 graph_hits > 0，候选含原文 chunk，0 越权。 |
| S07.4 | 在固定小图上用 NetworkX Adapter 做 PPR 对照 1/2-hop；若 S07.3 多跳未过门，先修 seed/span 再比较。记录 Graph Only/GV/GVB 的质量、P95 与 token/构图成本。 | 新增 tests/rag/graph/test_graph_ablation.py 后运行；保存错误桥接、热门节点污染、断路坏例；人工 Trace 可见种子、路径、passage 与融合排名。 |

Stage 门禁：图在真实在线请求中实际贡献可引用候选；多跳/实体切片较 S05 基线达到 S00 的增益门槛，总体和延迟过门。未达则继续 S07，不能靠只建图放行。Commit：feat(graphrag): retrieve grounded multi-hop passages。

### S08：Query Understanding、Rewrite 与 Router

当前问题：backend/rag/query_planner.py 有改写/分解，缺分题型收益证明与统一范围约束。目标是每个 query 保留原文、明确路由理由并可关闭。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S08.1 | 改 backend/rag/query_planner.py、tests/rag/test_query_planner.py；结构化输出 original、normalized、rewrites、query type，原始 query 必须参与检索。 | python -m pytest tests/rag/test_query_planner.py；改写超时/错误回退原 query，禁止改动文档范围。 |
| S08.2 | 新建 backend/rag/query_router.py、tests/rag/test_query_router.py；改 backend/services/knowledge_access_router.py、knowledge_scope_resolver.py；路由 keyword/semantic/multi-hop/no-answer 的通道预算与理由。 | python -m pytest tests/rag/test_query_router.py tests/agent/test_knowledge_access_router.py tests/agent/test_knowledge_scope_resolver.py；scope 不扩大。 |
| S08.3 | 改 backend/services/companion_chat_service.py 与 tests/rag/test_companion_rag.py，进行 rewrite/router on/off 配对消融。 | python -m pytest tests/rag/test_companion_rag.py；分题型 Recall/MRR/P95/token，保存缩写误展开与误路由坏例；Debug 可看原文/改写/策略。 |

Stage 门禁：0 范围漂移、失败稳退原 query；只将有净收益的路由/改写规则默认打开。Commit：feat(rag): route queries with traceable rewrites。

### S09：Reranker 与候选池

当前问题：backend/rag/config.py 默认只让前 8 个候选进入 reranker；backend/services/rag_debug_service.py 的 pre/post 评测列表相同。目标是先修测量，再扩候选池，最后判断净收益。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S09.1 | 改 backend/services/rag_debug_service.py、tests/rag/test_rag_evaluation.py；分别记录 fusion、rerank input、post-rerank、final ID 列表，不复用同一列表。 | python -m pytest tests/rag/test_rag_evaluation.py；一个手算 fixture 中前后顺序不同，指标按真实列表变化。 |
| S09.2 | 改 backend/rag/config.py、retrieval_service.py、tests/rag/test_rerank_pool.py（新建），参数化 8/12/20 的池，final_top_k 仍受原合同限制。 | python -m pytest tests/rag/test_rerank_pool.py tests/rag/test_retrieval_service.py；第 9–20 名的正确候选能进入对应大池，默认值只由测量决定。 |
| S09.3 | 改 backend/rag/retrieval_service.py、rerankers/qwen3.py；保留现有 RRF fallback，补超时、批次、输入截断与失败原因记录。 | python -m pytest tests/rag/test_reranker_provider.py tests/rag/test_qwen3_reranker_provider.py；同融合输入比较无 rerank/8/12/20 的 MRR、nDCG、P95、显存；保存被截断坏例。 |

Stage 门禁：pre/post 指标可信，目标切片的排序增益超过 S00 门槛且延迟预算满足；否则不推广更大池。Commit：feat(rag): measure and tune rerank candidate pool。

### S10：Context、Evidence 与 Citation

当前问题：现有 backend/rag/citation_service.py 主要校验引用 ID 是否来自候选，无法证明陈述被原文支持；全检索失败时 Companion 可能继续一般性回答。目标是逐条事实有可定位证据，证据不足时准确拒答。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S10.1 | 改 backend/rag/evidence_builder.py、context_builder.py、citation_service.py 和对应测试；每个入模证据绑定 source span/generation，引用前再次检查范围和存活版本。 | python -m pytest tests/rag/test_evidence_builder.py tests/rag/test_context_builder.py tests/rag/test_citation_service.py；0 过期、越权或不存在的引用。 |
| S10.2 | 新建 backend/rag/evidence_verifier.py、tests/rag/test_evidence_verifier.py；为 atomic claim 检查完整证据集，输出 sufficient / relevant_insufficient / absent 与原因。 | python -m pytest tests/rag/test_evidence_verifier.py tests/rag/test_evidence_requirements.py；正确 ID 但反向事实、关键否定句被截断的坏例判为不足。 |
| S10.3 | 改 backend/services/companion_chat_service.py、backend/agent_tools/knowledge.py 与调用方测试；检索全失败或证据不足的知识专属问题明确拒答/要求补充，不冒充有文献依据。 | python -m pytest tests/rag/test_companion_rag.py tests/agent/test_agent_knowledge_tools.py tests/agent/test_knowledge_access_contract.py；报告 claim-level Citation Accuracy、Faithfulness、false abstention、context token；人工逐句点引用核对原文。 |

Stage 门禁：安全硬门通过；citation、faithfulness 与错误拒答达到 S00 冻结数值门槛。Commit：feat(rag): verify evidence before citing。

### S11：完整 Evaluation Pipeline

当前问题：backend/rag/evaluation_dataset.py 把 no_answer 与相关 chunk 互斥，无法标注“相关但不足”；claim.supported 可由系统自报，不能作为独立真值。目标是独立、可复跑、能定位分层问题的评测。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S11.1 | 改 backend/rag/evaluation_dataset.py；新建 tests/rag/test_production_eval_schema.py。金标改用 source span、相关等级、OR-of-AND 证据集、answerability、scope；旧 JSON 可迁移，重切后需显式对齐或报错。 | python -m pytest tests/rag/test_production_eval_schema.py tests/rag/test_rag_evaluation.py；“相关但不足”合法，失配金标不静默丢弃。 |
| S11.2 | 改 backend/rag/evaluation.py；新建 tests/rag/test_production_metrics.py。实现文档/证据 Recall@1/5/10、Precision@K、Hit Rate、MRR、nDCG@10、完整证据覆盖；手算 fixture 作独立期望。 | python -m pytest tests/rag/test_production_metrics.py tests/rag/test_rag_evaluation.py；空列表、无答案、部分证据的分母和有效样本数明确。 |
| S11.3 | 新建 backend/rag/evaluation_protocol.py、tests/rag/test_answer_eval_protocol.py；答复评测对 claim/citation 做独立人工或校准 judge 标注，不能信被测系统自报 supported。 | python -m pytest tests/rag/test_answer_eval_protocol.py；人工盲标子集与自动 judge 的一致性、争议样本和复核记录可见。 |
| S11.4 | 新建 scripts/eval_rag_production.py、tests/rag/test_production_eval_runner.py；复用 backend/rag/benchmarks/qasper 的已知论文路径，另跑真实原文件/未知文档路径；输出 manifest/per_case/metrics/bad_cases。 | python -m pytest tests/rag/test_production_eval_runner.py tests/rag/benchmarks/test_qasper_protocol.py；相同指纹重跑指标相同；缺数据非零退出；分层结果和 P95/token 可审计。 |

Stage 门禁：QASPER 与真实导入结果分开，所有指标有定义、分母、N 和逐题证据；金标与报告可复跑。Commit：feat(rag-eval): evaluate retrieval and grounded answers。

### S12：Bad Case 闭环

当前问题：平均分不能指出哪一层首次丢失正确证据。目标是每个已修坏例都能复现、定位并成为回归用例。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S12.1 | 新建 backend/rag/bad_cases/{models,store}.py、tests/rag/test_bad_case_store.py；记录 query、scope、gold span/证据集、分阶段候选、答案/引用、trace/index/config/model 版本、状态。 | python -m pytest tests/rag/test_bad_case_store.py；存取不丢版本，敏感原文默认脱敏。 |
| S12.2 | 新建 backend/rag/bad_cases/triage.py、tests/rag/test_bad_case_triage.py；按首次正确证据消失处分类，人工确认根因。 | python -m pytest tests/rag/test_bad_case_triage.py；至少覆盖 PARSER、CHUNK、EMBEDDING、VECTOR、BM25、ENTITY_EXTRACTION、ENTITY_RESOLUTION、GRAPH_BUILD、GRAPH_TRAVERSAL、REWRITE、ROUTER、RERANK、CONTEXT、CITATION、GENERATION。 |
| S12.3 | 新建 scripts/replay_rag_bad_case.py、tests/rag/test_bad_case_replay.py，改 backend/services/rag_debug_store_service.py；固定 generation 重放并导出修复前后 diff。 | python -m pytest tests/rag/test_bad_case_replay.py；复放 S00–S11 的坏例；修复的每例进入 tests/rag/regression/（新建），报告修复率/复发率。 |

Stage 门禁：已修坏例 100% 可回归且通过；无法重放的例子写明缺失版本，不能标“已定位”。Commit：feat(rag-eval): replay and regress bad cases。

### S13：RAG Debug Studio 与统一 Trace

当前问题：现有 Trace 无 Graph Seeds/Expansion/Path，Agent/Companion 的 query_id 不能自动保证整链路关联。目标是从一个错误回答直接查到首个失真 Stage。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S13.1 | 改 backend/rag/observability.py、retrieval_service.py；新建 tests/rag/test_graph_trace.py。事件有 trace_id、parent_id、query_id、stage、scope hash、generation、输入/输出 chunk IDs、rank/score、耗时、fallback、token/cost。 | python -m pytest tests/rag/test_rag_observability.py tests/rag/test_graph_trace.py；Graph/Vector/BM25/RRF/Rerank/Context 事件能串成一棵树。 |
| S13.2 | 改 backend/services/companion_chat_service.py、backend/agent_tools/knowledge.py 与调用方测试；从入口生成或接收 trace_id，并传到检索/回答。 | python -m pytest tests/test_rag_debug_companion_trace.py tests/agent/test_agent_knowledge_tools.py；Agent 和 Companion 均只有一个贯穿同请求的 trace_id。 |
| S13.3 | 改 backend/services/rag_debug_service.py、rag_debug_store_service.py、backend/api/rag_debug.py 和 API 测试；持久化可脱敏、可按 bad_case 重放的版本快照。 | python -m pytest tests/test_rag_debug_companion_trace.py tests/rag/test_graph_trace.py；重跑显示新旧 trace，不能覆盖旧结果。 |
| S13.4 | 改 apps/desktop/src/api/rag-debug.ts、apps/desktop/src/features/settings/RagDebugStudioTrace.tsx 及其测试；展示原/归一 query、意图、改写、策略、Graph Seed/Path、通道/fusion/rerank 分数、最终 context/citation/延迟/token。 | 在 D:\AITrans 运行 npm --prefix apps/desktop run test；人工点击图边/证据可回原文，未运行、成功空结果、超时、失败显示不同状态；测 Trace 开销。 |

Stage 门禁：受测请求 100% 可由 trace_id 串起 Query→Retrieval→Graph→Rerank→Context→Answer；三个已知坏例能只看 Studio 定位首个失效层。Commit：feat(rag-debug): show end-to-end evidence trace。

### S14：Regression 门禁

当前问题：现有测试分散，无法阻断坏例复发和跨题型退化。目标是小集每次跑、冻结大集定期跑，并输出逐题差异。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S14.1 | 新建 tests/rag/regression/、docs/development/rag-production-luna/regression-manifest.json；把 S12 已修例、范围/引用/索引异常与小规模真实导入加入固定 CI 集。 | python -m pytest tests/rag/regression tests/agent/test_knowledge_access_contract.py；所有已修例通过，数据/版本哈希固定。 |
| S14.2 | 新建 scripts/check_rag_regression.py、tests/rag/test_regression_gate.py；比较同数据 baseline/new 的硬门、分层质量、P95 与新坏例，非通过时非零退出。 | python -m pytest tests/rag/test_regression_gate.py；新增后运行 python scripts/check_rag_regression.py --suite ci；构造退化样本应阻断。 |
| S14.3 | 先用 rg 查仓库真实 CI 配置，再把小集接入；夜间或发布前运行 QASPER/真实导入 holdout 和前端 Debug 合同。 | python -m pytest tests/rag tests/agent/test_knowledge_access_contract.py；npm --prefix apps/desktop run test；报告逐题 pass→fail，人工审核所有退化。 |

Stage 门禁：CI 小集 100% 通过；0 已修坏例复发，硬门与总体质量门过关。Commit：test(rag): gate production regressions。

### S15：性能、缓存与故障隔离

当前问题：Qdrant Local、BM25 JSON、同步模型和长文档在并发下尚无生产负载证据；缺统一带版本缓存。目标是先测，再做最小且可回滚的性能改动。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S15.1 | 新建 scripts/load_test_rag.py、tests/rag/test_load_harness.py；不先优化，先固定冷/热、1/多并发、导入同时检索、大文档与故障场景。 | python -m pytest tests/rag/test_load_harness.py；新增后运行 python scripts/load_test_rag.py --scenario mixed --queries 1000；记录 P50/P95/P99、CPU/GPU/内存、错误率、QPS。 |
| S15.2 | 新建 backend/rag/cache.py、tests/rag/test_rag_cache.py；只缓存重复安全的 embedding/检索结果，键含 scope、generation、模型和 query 版本；删除/重建失效。 | python -m pytest tests/rag/test_rag_cache.py；不同 scope/版本绝不互用，比较命中率、P95 与内存。 |
| S15.3 | 改 backend/rag/retrieval_service.py、api/knowledge_dependencies.py；新建 tests/rag/test_rag_failure_isolation.py。每通道有 deadline、异常隔离、明确 degraded；仅幂等操作重试，全部失败不得生成假引用。 | python -m pytest tests/rag/test_rag_failure_isolation.py tests/rag/test_retrieval_service.py；1000 次冻结混合查询无进程崩溃、0 半成品/越权/旧引用；保存超时与缓存污染坏例。 |
| S15.4 | 用 S15.1–S15.3 实测判断本地存储是否达到容量/多进程/锁/P95 门槛；若达到，写 Qdrant Server 或其他服务端方案的 Adapter 试验与迁移/回滚报告，不直接替换。 | 同一召回/权限/故障基准比较；没有收益或没有部署条件则维持 Qdrant Local。Graph SQLite 与 BM25 JSON 也按相同门槛判定。 |

Stage 门禁：S00 冻结 SLO 与资源预算均通过；异步化只有在证明当前同步调用阻塞事件循环时实施，必须带取消/并发测试。Commit：perf(rag): harden retrieval under load。

### S16：最终 Benchmark、消融与 Go/No-Go

当前问题：任何单次 Stage 结果都不能单独证明产品可用。目标是用冻结代码、数据和机器对全部方案给出可重复的质量/成本结论。

| ID | 单一交付物与允许修改文件 | 检查与通过条件 |
|---|---|---|
| S16.1 | 新建 scripts/run_rag_final_benchmark.py；固定 V、B、VB、VR、G、GV、GVB、GVBR 及 rewrite/候选池/遍历消融，冻结索引、模型、prompt、硬件与 seed。 | python -m pytest tests/rag tests/agent/test_knowledge_access_contract.py；新增后运行 python scripts/run_rag_final_benchmark.py --manifest docs/development/rag-production-luna/regression-manifest.json；逐题产物和有效 N 完整。 |
| S16.2 | 新建 docs/development/rag-production-luna/{final-benchmark,architecture-decisions}.md，填写第 3 节表格，按文档家族 bootstrap 区间；注明 QASPER 已知论文、真实原文导入与未知文档各自结论。 | 不同配置不得混表；Graph 对哪类题增益/退化、P95/token/建图成本、哪些题不启用 Graph，均有逐题证据。 |
| S16.3 | 只有全部门禁 PASS，才在 config/default.toml 设置有证据支持的默认 Graph/Router/Reranker 参数；保留受控回滚开关，完成 Debug 人工抽检与 1000 查询复测。 | 0 安全硬门失败，质量达到 gate.json 的 F/Δ/C，P95 达 L；否则结论为 NO-GO，指回失败任务 ID 继续修复，不改默认。 |

Stage 门禁：完整产物、许可证记录、回滚方法、全部自动与人工检查齐备；最终提交 docs(rag): publish production benchmark and decisions。

## 3. S16 最终结果表模板

这张表只能由 S16.1 实测填写；“待测”不能删除成空白，也不能把不同数据集的分数放在同一张表。每张表头另列 dataset/split、N、commit、index/model/config 指纹和机器规格。

| 方案 | Recall@5 | Recall@10 | MRR | nDCG@10 | 完整证据覆盖 | Faithfulness | Citation Accuracy | P95 ms | Token/题 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V：Vector Only | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| B：BM25 Only | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| VB：Vector + BM25 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| VR：Vector + Reranker | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| G：Graph Only | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| GV：Graph + Vector | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| GVB：Graph + Vector + BM25 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| GVBR：最终方案 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |

## 4. Bad Case、Trace 和生产验收的固定字段

Bad Case 必填：case_id、query、allowed_document_ids/scope hash、预期 source spans/完整证据集合、各通道及融合前后排名、graph seeds/paths、final context、answer/citations、trace_id、index/model/config/data 指纹、first_failed_stage、failure_type、root_cause、修复 commit、回归用例。failure_type 至少覆盖 S12.2 的 15 类，另含 SCOPE_ERROR、INDEX_CONSISTENCY_ERROR、EVALUATION_LABEL_ERROR。

Trace 必填：trace_id、parent_id、query_id、stage、开始/结束时间、document_id/chunk_id、retrieval_method、raw score/rank、fusion/rerank score、graph_path、source span、scope/generation、latency、token/cost、fallback/error。Studio 要显示 Original/Normalized Query、Intent、Rewrite、Route、Vector/BM25/Graph Seed/Expansion/Path、Fusion、Rerank、Context、Evidence/Citation、Latency/Token；每层的输入/输出可点击比对。

生产验收只看实际证据：原文件导入→Graph 在线召回→证据→答案，作用域和引用安全，generation 回滚/删除/重启，1000 请求与大文档，分层质量和成本，回归门禁、Bad Case 修复率、开源许可与回滚手册。Agent 使用 RAG 时，检索故障或证据不足必须带状态返回，不能沿错误 context 继续作知识结论。

## 5. 开源复用与外部依赖检查

| 来源 | 只借鉴/复用的部分 | 本仓改动边界 | 引入前要核验 |
|---|---|---|---|
| [Docling](https://github.com/docling-project/docling) | 已用的 PDF/版面解析 | backend/rag/parsers/docling.py 的 Adapter | 锁定版本、OCR/公式配置与[许可文件](https://github.com/docling-project/docling/blob/main/LICENSE) |
| [Qdrant Client](https://github.com/qdrant/qdrant-client) | 已用的本地向量 API；必要时服务端同 API | backend/rag/stores/qdrant.py | 版本、Local 锁/并发、服务端迁移测试与[许可文件](https://github.com/qdrant/qdrant-client/blob/master/LICENSE) |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag) | entity/relation、text-unit 来源映射、local search 思路 | backend/rag/graph/*，不接管 AITrans 主流水线 | 官方 docs、[许可文件](https://github.com/microsoft/graphrag/blob/main/LICENSE)、依赖规模 |
| [HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) | 查询种子、PPR 与 passage recovery 思路 | S07 的 traversal/消融 Adapter | [许可文件](https://github.com/OSU-NLP-Group/HippoRAG/blob/main/LICENSE)、模型许可、复杂度、实测收益 |
| [LightRAG](https://github.com/HKUDS/LightRAG) | 增量图生命周期和查询路由思路 | S06/S08 设计，不引入第二数据库 | [许可文件](https://github.com/HKUDS/LightRAG/blob/main/LICENSE)、增量删除语义 |
| [NetworkX](https://github.com/networkx/networkx) | 小图 PPR 对照 | S07.4 对照 Adapter | [许可文件](https://github.com/networkx/networkx/blob/main/LICENSE.txt)、图规模与延迟 |
| [Ragas](https://docs.ragas.io/en/latest/) | 自动评估辅助信号 | S11 judge 插件，不替代盲标金标 | [许可文件](https://github.com/vibrantlabsai/ragas/blob/main/LICENSE)、judge 偏差与成本 |
| [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) | Reranker 挑战者 | S09 可选 Adapter | [代码许可](https://github.com/FlagOpen/FlagEmbedding/blob/master/LICENSE)与权重许可分别核验 |

已有原方案还列出 RAGFlow、Haystack 等比较对象；Luna 只有在表内任务明确要求对照且有真实收益证据时才引入，避免扩大一次任务的依赖面。所有外部来源只参考官方仓库/文档；复制源码前需要在 Stage 报告记录确切版本和许可证。FAISS 当前不是产品实现，无需做“现有 FAISS 迁移”。

## 6. 面试与技术复盘产物

S16 的 architecture-decisions.md 用真实数据回答：纯 Vector 为什么不够，Hybrid/Reranker 的增益，GraphRAG 的实体消歧、图污染防范、1/2-hop 与 PPR，Graph/Vector 如何融合，什么时候不启用 Graph；Recall/MRR/nDCG、Faithfulness、Citation Accuracy 的金标和局限；Bad Case 怎样定位和防复发；Neo4j/Qdrant Local/服务端与 FAISS/Milvus 的选型触发条件；Agent 如何消费成功、空证据和故障状态。每个回答引用对应任务报告、逐题例子和 Benchmark，不以通用架构口号替代实验。

下一次开始时执行 S00.1。任何 Session 只推进一个 ID；当前 ID 没有报告和 PASS 证据，STATUS.md 指针不得前移。
