# 原有 PDF 导入与现有 RAG 链路验证

日期：2026-10-01。分支：`electronrebuild`；基线 HEAD：`4b0d802c168a00cf12a967cfcdb24c1ba2ed1f4c`，包含当时工作区已有改动。

## 结论

- **功能链路通过本次分段冒烟验证**：真实 PDF 经原有导入 API 进入现有生产运行时，可以检索；未发现需要修改生产代码的接入断点。
- **检索效果未达候选门槛**：默认 Docling 路径 Recall@5 **0.533**、MRR@8 **0.500**、暖检索 P95 **1059ms**。原有 pypdf 对照也未通过。
- 本轮仅增加评测脚本、冻结题集、评测辅助函数测试和本报告；未修改业务代码、用户配置、现有索引或依赖。原始失败实验保留，补测单独记录。

## 1. 调用链与测试范围

原有阅读入口 `UnifiedReadingWorkspace.importDocument` → `useKnowledgeLibrary` 文件选择/新增 → `addKnowledgeDocument` → `POST /api/knowledge/documents` → `KnowledgeLibraryService` 路径校验 → `IndexService` 解析、切片、嵌入、Qdrant/BM25、READY generation → `RetrievalService`。

`knowledge_dependencies._build_runtime()` 是本轮实际使用的生产工厂。生产 `get_knowledge_library_service()` 和 `get_retrieval_service()` 来自同一个 `get_rag_runtime()`；Agent 的 `_LazyRetrievalService` 转发到该检索服务，知识搜索通过 `VectorSearchFilter` 限定文档范围。RAG 调试 API 也依赖同一运行时。阅读大纲使用同一解析配置；原文预览另经真实 preview router 验证字节一致。

本轮通过进程内 FastAPI 测试客户端调用真实路由，使用真实解析器、本地模型和持久化存储。只替换配置来源以隔离测试存储与允许目录；没有替换解析结果、嵌入、重排或召回结果。

有效配置：Docling CPU，版面/表格开启，OCR/公式增强关闭；语义切片开启；Qwen3-Embedding-0.6B，1024 维；Qwen3-Reranker-0.6B；dense/sparse 各 30、融合 20、最终 8，普通查询重排输入为 8；SmallToBig 开启。Graph、视觉描述 API、原生视觉检索关闭，图片代理文本仍正常入库。本轮未发起 LLM API 调用。

默认允许导入目录为用户主目录。导入其他目录中的 PDF（例如 D 盘文件）需要已有部署配置 `AITRANS_KNOWLEDGE_ALLOWED_ROOTS` 允许该目录；不能把 403 误判为解析故障。本轮仅临时允许各实验 corpus 目录，未放宽生产配置。

## 2. 数据与金标

使用此前已下载的两篇原始公开论文 PDF，重新走完整导入流程，而非使用预解析语料：

| PDF | 原始 SHA256 | 页数 |
| --- | --- | ---: |
| BERT，1810.04805 | `5692a5514787a8c6727b4ff3b726a3385798bc68e12138d1d4af83947e2acf6e` | 16 |
| Attention Is All You Need，1706.03762 | `bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` | 15 |

题集 `tests/rag/fixtures/pdf_import_queries.json` 在召回前按原始 PDF 物理页和原文片段冻结，30 题：中文 10、英文 20。两篇论文各 15 题；所有效果查询同时搜索两篇 PDF，不传入正确文档或答案。BERT 副本采用中文文件名，覆盖本地路径和 URI 编解码。

金标由源页原文锚点定位，再映射到完整包含锚点 span 的文本 chunk；缺失或歧义不猜测，未映射题计零、不删题。图片代理 chunk 不冒充原文证据。两种解析最终均映射 30/30 题。部分事实共享段落；这是工程小样本，**不能等同于独立的公开 QA 数据集或代表性生产验收**。

## 3. 冒烟结果

| 验证项 | 结果 |
| --- | --- |
| 原有新增 API → READY；manifest/Qdrant/BM25 chunk ID 一致 | 两种解析通过 |
| 重复导入复用原 generation；存储重新打开后继续复用 | 通过；复用仍会执行解析，不代表免解析 |
| 原文预览字节 SHA256 与输入 PDF 一致；中文路径 | 通过 |
| 阅读大纲物理页数与导入一致 | 通过 |
| 强制重建切换 generation，新 generation 可经文档范围检索 | 通过；实际 dense/sparse 无错误 |
| 空白/损坏 PDF 不发布 READY，不改变有效索引 | 503；通过 |
| 文件不存在、相对路径、允许目录外文件 | 分别 404、422、403；通过 |
| 删除全部 generation、BM25、向量和对应图片资产 | 通过；原始 PDF 保留，删除后无检索结果 |
| 文本 source span 精确回源 | Docling 242/242、pypdf 44/44，通过 |
| 图片代理的原文 hash、页码和真实隔离资产校验 | 两种解析均 37/37，通过 |

| 解析方式 | BERT 文本/图片 chunk | Attention 文本/图片 chunk | 首次导入耗时 BERT / Attention |
| --- | ---: | ---: | ---: |
| 默认 Docling | 162 / 34 | 80 / 3 | 60.3s / 44.6s |
| pypdf 对照 | 30 / 34 | 14 / 3 | 21.5s / 4.4s |

Docling BERT 检出 8 个表格并提供源页映射；中文文件路径触发已有 ASCII 暂存兼容逻辑，最终 parser 仍为 Docling。未发生用 pypdf 替代后伪报 Docling 成功。另实际执行了已有 Docling 三页双栏/表格/扫描页集成测试；OCR 关闭时扫描页没有文本，不构成 OCR 成功证明。

### 失败实验与补测口径

1. `current-v1` 测试最初错误要求图片代理也具有文本 source span；实际 162 个文本 span 全部正确。修正为分别校验文本 span 和图片资产/页码。该失败记录保留；该次生成的专属图片目录已移入实验归档，未保留在生产资产目录。
2. `current-v2` 已完成全部效果查询和重建，脚本误把重建成功状态设为 201；真实 API 返回约定的 **200 / READY**。
3. `pypdf-v1` 已完成全部效果查询和重建，脚本误用内部 `allowed_document_ids` 参数；真实公共检索接口采用 **`filters=VectorSearchFilter(document_ids=[...])`**。
4. 补测第一次错误读取不存在的 `DocumentChunk.generation_id`，尚未改变索引；失败记录保留。改用实际 manifest 的有效 chunk ID 集合和检索返回的 active generation 校验。

修正测试契约后，使用原实验持久化索引和真实生产运行时补完范围检索、预览、异常输入和删除。Docling 原 11 条 API 请求加补测 9 条；pypdf 原 13 条加补测 9 条，实际状态均符合接口契约。`qualification.json` 记录完成结果及原始文件 hash；原始 `manifest.json` 仍保留 failed，不被改写成一次无中断成功运行。补测验证原始指标、预测、金标和代码快照均未改变。

## 4. 检索效果

每个 profile 均为 30 题、一次不计分预热、检索缓存关闭；P95 包含该 profile 实际检索、融合、重排、上下文扩展耗时，不含导入和首次加载。无正确文档过滤，保留图片代理候选。Recall@5 对完整包含金标片段的 chunk 计算；MRR@8 受最终 8 个候选截断，不冒称无限截断 MRR。语义引用准确率及最终回答未评测。

| 解析方式 | 检索 profile | Recall@5 | MRR@8 | 暖检索 P95 | 降级题数 |
| --- | --- | ---: | ---: | ---: | ---: |
| 默认 Docling | dense | 0.533 | 0.414 | 119.6ms | 0 |
| 默认 Docling | sparse | 0.467 | 0.424 | 11.6ms | 0 |
| 默认 Docling | **现有默认组合** | **0.533** | **0.500** | **1059.3ms** | **0** |
| pypdf 对照 | dense | 0.567 | 0.400 | 87.2ms | 0 |
| pypdf 对照 | sparse | 0.567 | 0.378 | 4.8ms | 0 |
| pypdf 对照 | **现有默认组合** | **0.633** | **0.483** | **1143.9ms** | **0** |

候选门槛 Recall@5≥0.80、MRR≥0.70、暖检索 P95≤800ms：**两种解析的默认组合均不通过**。pypdf chunk 粒度不同，不能据此认定替换 Docling 就能满足效果要求；本轮不切换默认解析器。

Docling 最初两题因将 `0.1` 导出为 `0 . 1` 而未映射，原始默认组合指标为 Recall@5=0.467、MRR@8=0.433、P95=1059.3ms。仅修正小数空白等价映射后离线重评分，原预测排名、问题和时延不变；保留小数点、正负号和百分号，不能把 `1e-4` 等价成 `1e4`。本表采用修正后的 30/30 金标口径；原始指标和重新对齐结果分别保存。

### 坏例定位

默认 Docling 的 14 个 Top5 未召回坏例：**7 个金标不在融合候选中，7 个在融合候选中但未进入 8 条重排输入**。pypdf 的 11 个坏例：融合候选缺失 4、重排输入截断 5、进入重排但未完整进入 Top5 为 2。

| 默认组合 | 中文 N / Recall@5 / MRR@8 | 英文 N / Recall@5 / MRR@8 |
| --- | --- | --- |
| Docling | 10 / 0.100 / 0.100 | 20 / 0.750 / 0.700 |
| pypdf | 10 / 0.300 / 0.300 | 20 / 0.800 / 0.575 |

英文 PDF 的中文提问是明显薄弱点，但分组样本很小且相关，不能据此给出普遍的跨语言性能结论。Docling Top5 的 150 个位置中有 26 个图片代理候选；pypdf 有 25 个，仅记录现象，未经消融不能认定它们造成召回失败。

后续最小改动实验应按坏例分两组：先检查中文查询在现有候选通道的排名和融合截断；再仅试验已有 `rerank_candidate_k` 配置并同步测 P95。扩大重排池可能改善覆盖并增加耗时，需要对照结果后决定。SmallToBig 最终上下文可能补回证据，本轮 chunk 排名不能直接推导最终回答错误。

## 5. 验证与产物

- 已有 PDF/parser registry/runtime dependency/knowledge API/generation lifecycle 测试：**25 passed**。
- 实际开启的 Docling 质量集成测试：**1 passed**，有已有表格图片 API 弃用警告。
- 新金标规范化与页码/span/歧义测试：**2 passed**；最终脚本和新测试 Ruff 检查通过。
- 两篇 PDF × 两种解析 × 三个检索 profile × 30 题，共 **180 条计分检索**，各 profile 预热另计。生命周期补测仅验证功能，不用于替换原效果时延。

产物根目录：`D:/AITrans/data/benchmarks/pdf-rag-20261001/`（实验数据按项目规则忽略，不提交模型/PDF/索引）。

- `current-v2/`：`indexed.json`、`catalogue-original.jsonl`、原始 `metrics.json`/预测/金标、`format-audited-metrics.json` 与对应预测/金标、`runner-source.py`、`qualification.json`、`lifecycle-completion-smoke.json`、`pdf-bad-cases.jsonl`。
- `pypdf-v1/`：`indexed.json`、`catalogue.jsonl`、`metrics.json`、预测/金标、原脚本快照、补测 qualification/smoke、坏例。
- `analysis.json`：按语言、失效阶段、候选类型分析；`finish_lifecycle.py` 和 `analyze_results.py` 为归档中的实验复核工具，hash 与失败尝试均保留。

可重复运行：激活 `aitrans` 后，`python scripts/run_pdf_rag_benchmark.py --parser current --output <新的隔离目录>`；pypdf 对照将 parser 改为 `pypdf`。输出目录必须不存在，原始 PDF hash 必须一致，模型须已缓存。

## 6. 未覆盖风险

- 未实操 Electron 文件选择及界面事件，也未验证完整后端/操作系统重启；本轮证明路由/生产工厂及持久化存储接入。
- OCR 当前关闭；纯扫描 PDF 不能按文本正常召回。Docling 导出阅读顺序未做完整人工版面审查。
- 两篇论文和相关的 30 道题不足以生产验收；未评测独立语义 Citation Accuracy、回答质量、Graph 接入、并发与容量。
- 导入 CPU 解析开销明显，重复导入仍重新解析；现有效果和检索延迟不足已用坏例及指标记录，未在本轮进行效果调参。
