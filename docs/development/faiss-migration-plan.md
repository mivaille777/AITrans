# AITrans 完整 FAISS 迁移方案

日期：2026-10-04；实施更新：2026-10-05（Asia/Shanghai）  
状态：已实现并完成本机实际数据切换、文本/视觉模型验收及两套 Windows 构建。完整发布仍有待验项目，具体结果以 [实施与真实验收报告](faiss-migration-acceptance.md) 为准。  
配套文件：[FAISS 迁移开发任务书](faiss-migration-taskbook.md)。

## 1. 目标与关键决策

目标：完全移除 AITrans 正常运行和桌面发布包中的 Qdrant，保留文本 RAG、原生视觉检索、文档范围过滤、索引版本隔离和引用定位；尽量把改动限制在存储适配器、依赖装配、审计及打包边界。

采用以下方案：

| 范围 | 最终实现 |
| --- | --- |
| 文本向量搜索 | FAISS GPU 优先；不可用自动回退 CPU，默认 FlatIP + cosine 归一化 |
| 视觉候选召回 | 现有视觉 token 向量均值池化，复用 GPU 优先 / CPU 回退的 FAISS 搜索 |
| 视觉最终评分 | 本地 NumPy float32 MaxSim；保留全量 MaxSim 路径 |
| 向量、chunk、元数据持久化 | Python 标准库 SQLite；向量以 float32 BLOB 保存 |
| FAISS 索引持久化 | 第一版只使用可重建的内存索引，不另存 `.faiss` 文件 |
| 文档发布状态 | 继续由现有 `IndexManifest` 管理 |
| 稀疏检索 | 继续使用现有 BM25 与其 JSON 文件 |
| 模型、解析和业务接口 | 保留现有实现和参数 |
| 旧数据迁移 | 旧环境导出中立数据包，新环境离线导入；必要时从原文件重建 |
| 发布回滚 | 恢复旧应用版本与迁移前完整数据快照，不在新运行时保留 Qdrant 分支 |

FAISS 官方定位是向量相似度搜索库，因此本方案称为“FAISS 检索 + SQLite 存储”，不将 FAISS 视为具备完整数据库能力的组件。[FAISS 官方介绍](https://github.com/facebookresearch/faiss)

### 1.1 GPU 优先追加方案

`stores/faiss_runtime.py` 是文本与视觉粗召回共用的设备边界。先构建保留稳定 SQLite ID 的 CPU Flat 索引，检测 GPU 编译 API 与 CUDA 设备，尝试克隆到 GPU Float32；任一步不可用或搜索异常，立即使用已有 CPU 索引。GPU Flat 的位置 ID 映射回原 SQLite ID，不改变存储、过滤或 generation。

同一进程每设备共享一份 CUDA resource，scratch 为 64 MiB，操作以共享锁串行保护；CPU 副本保留以支持回退。发生 CUDA 异常的索引在当前缓存周期使用 CPU，索引重建/运行时重开时再次探测。Manhattan 距离始终 CPU；top-k > 2048、全量边界 tie 展开使用 CPU，普通后续查询仍使用 GPU。SQLite 仍是持久化来源，无需重新嵌入已有向量。[GPU API、资源与限制](https://github.com/facebookresearch/faiss/wiki/Faiss-on-the-GPU)

默认 `AITRANS_FAISS_DEVICE=auto`；`cpu` 强制 CPU，`AITRANS_FAISS_GPU_DEVICE` 默认 0。成功使用的设备和回退原因写入 store 的 `execution_info`，sidecar smoke 输出真实查询的设备。CPU/GPU Float32 可以有微小误差；边界同分集合应按 tie 规则评估，不要求跨设备逐位一致。

Windows GPU 安装由 `scripts/install_faiss.ps1` 管理，优先 GPU 构建，平台/硬件不满足时检查 CPU方案；GPU 包本身已包含 CPU 类，不重复安装 `faiss-cpu` wheel。当前测试组合是 FAISS GPU 1.9.0、NumPy 1.26.4、OpenBLAS 0.3.34、OpenCV 4.11.0.86。OpenBLAS 避开实测 MKL DLL 冲突；后端及打包进程默认 `OPENBLAS_NUM_THREADS=1` 控制多进程内存，显式环境设置优先。模型与 NumPy MaxSim 算法保持原实现。

此前讨论的 JSON 快照适用于很小的原型。完整迁移需要处理多版本 chunk、删除、批量视觉向量和中断恢复，本方案统一采用 SQLite，避免自行实现多个 JSON/NumPy 文件间的提交协议。SQLite 属于 Python 标准库组件，无需另部署数据库服务。[Python sqlite3 文档](https://docs.python.org/3.12/library/sqlite3.html)

## 2. 范围和交付边界

### 2.1 必须保留的能力

- 文本解析、结构/语义分块、Qwen Embedding、BM25、RRF、Qwen Reranker。
- `DocumentChunk`、`RetrievalCandidate`、`RetrievalResult` 和 `SourceSpan` 的业务字段。
- Knowledge 导入、重建、删除、查询、JIT 读取和运行状态接口。
- Agent/Research 文档范围约束、引用校验与证据缓存版本语义。
- ColQwen/ColPali 页面和图片多向量编码。
- 视觉粗召回、固定/自适应候选数量、MaxSim、文本视觉融合与文本降级路径。
- QASPER/真实导入/视觉评测与桌面离线部署能力。

### 2.2 第一版不扩展的范围

第一版服务于现有 Windows 桌面 sidecar 的本地知识库。不会同时引入服务集群、跨机器共享索引、HNSW/IVF/PQ、模型替换、重新设计前端或重构 BM25/manifest。2026-10-05 根据用户追加要求，FAISS 调整为 GPU 优先、CPU 自动回退。

这些限制控制改动幅度，不代表 FAISS 无法用于更大规模的系统。若第一版达不到规模和延迟门槛，应先基于测量增加索引缓存或优化过滤，再单独规划 ANN。

### 2.3 “完全移除 Qdrant”的定义

最终 `backend/`、`app/` 的正常运行代码没有 Qdrant import、client 或 provider 分支；核心依赖、默认 requirements、冻结发布包和常规测试环境不依赖 `qdrant-client`。

一次性导出脚本放在 `scripts/migration/`，仅在旧环境运行，使用单独的旧工具依赖清单；不会进入 PyInstaller 包，也不会被生产运行时 import。新应用只读取中立迁移包。

旧数据备份和历史文档可以保留名称 Qdrant。这不构成正常运行依赖。回滚时运行迁移前版本。

## 3. 当前仓库接入点

以下为编写时检查到的事实；实施开始时需重新记录 commit 和文件清单。

| 位置 | 当前情况 | 迁移处理 |
| --- | --- | --- |
| `backend/rag/stores/base.py` | 已有 `VectorStore` Protocol、`VectorSearchFilter`、范围交集与参考文献识别 | 保留接口，复用范围逻辑 |
| `backend/rag/stores/qdrant.py` | 文本持久化、CRUD、搜索和 generation 过滤 | 新增 FAISS 适配器后删除生产实现 |
| `backend/api/knowledge_dependencies.py` | 直接创建 Qdrant；视觉启用时共享 client；配置的 provider 目前没有负责选择实现 | 替换工厂和生命周期；改类型声明 |
| `backend/rag/config.py`、`config/default.toml` | 默认 `qdrant_local`，路径为 `config/rag/qdrant` | 改为 `faiss` 和独立路径；处理旧配置 |
| `backend/rag/index_service.py` | 向量/BM25 写入、精确校验 chunk ID 后发布 manifest；错误文本包含 Qdrant | 保留发布流程，仅作复用校验补强和措辞修正 |
| `backend/rag/index_manifest.py` | 原子 JSON 文件、generation 状态及恢复 | 保留；作为已发布版本的权威 |
| `backend/rag/visual_retrieval.py` | 模型、渲染、视觉存储和融合共处；有 Qdrant `isinstance` 判断 | 拆出存储依赖，保留模型和业务服务 |
| `backend/rag/visual_prefetch.py` | 已有归一化均值池化；Qdrant 实现两阶段查询 | 保留纯函数，把搜索交给 FAISS 视觉存储 |
| `backend/rag/visual_adaptive.py` | 已有候选数量策略；存储继承 Qdrant 类 | 保留纯策略和元数据，替换存储工厂 |
| `backend/rag/index_audit.py` | 直接读取 `_client.scroll`，报告名称为 `qdrant` | 改成公共读取接口，名称为 `vector` |
| `backend/rag/benchmarks/runtime.py` | 基准运行时直接创建 Qdrant | 共用新工厂，继续严格隔离生产目录 |
| `backend/evaluation/visual_retrieval_benchmark.py`、`scripts/benchmark_visual_retrieval.py` | 依赖具体视觉 Qdrant 类型 | 改为视觉/基准协议 |
| `scripts/run_hf_rag_benchmark.py`、`scripts/run_pdf_rag_benchmark.py` | 路径、指纹或运行数据含 Qdrant 假设 | 更新路径与代码指纹 |
| `backend/sidecar.py`、`aitrans_backend.spec`、两套 sidecar 构建脚本 | 显式导入/收集/检查 Qdrant | 收集 FAISS 原生依赖并增强实际运行烟测 |
| `tests/rag/`、`tests/agent/`、`tests/multi_agent/` | 多个 fixture 和断言创建 Qdrant 或检查其内部对象 | 转为新适配器和行为契约 |
| 桌面 Knowledge UI | provider 字段是字符串，主要按运行信息展示 | 仅更新测试数据与必要提示 |

默认文本模型维度为 1024；默认视觉模型为 `tsystems/colqwen2.5-3b-multilingual-v1.0`，维度为 128；默认视觉检索关闭，开启时默认池化预取 48、视觉返回 12。应保留这些模型和检索参数，避免同时改变模型与存储影响评测归因。

## 4. 目标结构与最小新增文件

```text
现有 API / Agent / Knowledge / Research
                 |
       现有 IndexService / RetrievalService
                 |
       +---------+--------------------------+
       |                                    |
FaissVectorStore                现有 VisualRetrievalService
       |                                    |
       |                       FaissVisualMultiVectorStore
       |                         |                  |
       |                  FAISS 池化召回       NumPy MaxSim
       |                         |                  |
       +-------------------------+------------------+
                                 |
                   LocalVectorRepository（SQLite）

BM25 JSON、manifest JSON、Graph 和页面图片继续由现有组件管理。
```

建议新增文件：

| 文件 | 职责 |
| --- | --- |
| `backend/rag/stores/local_repository.py` | SQLite schema、批量事务、只读枚举、数字 ID、revision、关闭与写入所有权 |
| `backend/rag/stores/faiss.py` | 文本 `VectorStore` 实现和 FAISS 内存缓存 |
| `backend/rag/stores/visual_base.py` | 视觉存储 Protocol 与基准能力 Protocol |
| `backend/rag/stores/faiss_visual.py` | 视觉事务、池化召回、MaxSim、全量扫描和基准视图 |
| `backend/rag/visual_scoring.py` | 无模型依赖的多向量校验、归一化与 MaxSim |
| `scripts/migration/export_qdrant_vectors.py` | 旧环境导出，不被正常运行时引用 |
| `scripts/migration/import_faiss_vectors.py` | 新环境导入、校验与恢复 |
| `scripts/migration/requirements-legacy-export.txt` | 仅导出所需旧客户端版本 |

通过 `stores/__init__.py` 提供一个简单的 `create_vector_store` 入口即可。最终只接受 `faiss`，无需引入多 provider 注册框架。

## 5. 本地存储设计

### 5.1 目录布局

```text
<data_root>/config/rag/
  bm25_index.json                 # 现有文件，原位保留
  index_manifest.json             # 现有文件，原位保留
  graph.sqlite3                   # 已启用 Graph 时的现有文件
  assets/                         # 文本多模态提取资产，实际位置另行核对
  visual_pages/                   # 现有图片资产
  faiss/
    vector_store.sqlite3          # 文本、视觉及元数据
    vector_store.sqlite3-wal      # SQLite 管理
    vector_store.sqlite3-shm      # SQLite 管理
    owner.lock                    # sidecar/导入器写入所有权

<迁移输出目录>/
  migration-metadata.json
  text-chunks.jsonl
  text-vectors.npy
  visual-items.jsonl
  visual-vectors.bin
  visual-offsets.jsonl
  index_manifest.json
  bm25_index.json
  graph.sqlite3                   # 有 Graph 数据时携带
  asset-path-map.json              # 原 URI、包内相对路径、目标 URI 与 checksum
  assets/                         # 需要迁移到另一根目录时携带
  checksums.json
  migration-report.json
```

实际根目录通过 `app/infrastructure/paths.py::data_root()` 和现有 `_resolve_runtime_storage_path()` 解析。源码运行默认是项目根；冻结应用默认是 `%APPDATA%/AITranslator`；`AITRANSLATOR_DATA_DIR` 可以覆盖。不要把模型缓存根 `%LOCALAPPDATA%/AITrans/models` 当成知识库存储根。

当前 `multimodal.py` 的资产根还受 `AITRANS_RAG_ASSET_DIR` 和工作目录影响，并不统一通过 `data_root()` 解析。导出前必须从真实 chunk 的 `metadata.asset_uri` 和配置核对所有实际资产根，不能只复制示意目录中的 `assets/visual_pages`。

实施采用带 SHA-256 的 `vectors.jsonl` 作为跨环境交换格式；上面的文件树是方案示意，实际包结构和命令见 [迁移运行说明](../../scripts/migration/README.md)。最终向量统一入 SQLite，不建立必须与数据库同时提交的外部向量文件。

### 5.2 逻辑 schema

第一版只需要三张表，实际 SQL 由实施任务实现并锁定 schema version。

| 表 | 必要字段 |
| --- | --- |
| `store_meta` | `schema_version`、`store_uuid` |
| `collections` | name、kind（text/visual）、dimension、distance、fingerprint、revision |
| `items` | vector_id（64 位正整数）、collection、chunk_id、document_id、generation、index_version、完整 chunk JSON、vector BLOB、token_count、可选 coarse BLOB |

实现锁定 schema v1：dtype 固定 little-endian float32，normalization 由 kind/distance 决定，content_hash 保存在完整 chunk JSON，视觉 index version 同时用于 collection fingerprint 和 row 身份。不为这些固定/已保存字段增加重复列。

关键约束：

- `vector_id` 使用 SQLite 分配的稳定整数，不用 Python `hash()` 或截断 UUID。
- 文本唯一键为 `(collection_name, chunk_id, generation_key)`；视觉唯一键增加 `index_version`。
- 未标记的 legacy generation 在 SQL 内部用空字符串表示，公共接口仍遵循 `None` 语义；不能让 SQL `NULL` 唯一性产生重复数据。
- 完整 `DocumentChunk.model_dump(mode="json")` 原样保留。generation 列和 JSON 中的值必须一致，异常值在导入时报告。
- 不允许同一个文本唯一键从一个 document 悄悄转移到另一个 document。
- 为 `(collection_name, document_id, generation_key)` 建索引；为 chunk 查找建立索引。
- 向量采用 little-endian 连续 `float32`；文本 BLOB 长度是 `4 × dimension`，视觉 BLOB 长度是 `4 × token_count × dimension`。
- 入库前与反序列化后均检查维度、长度、有限值；float32 转换溢出也视为无效输入。
- 文本向量按 collection 的固定度量准备；dot 不做额外归一化。任何度量/模型语义变更都需重新建 collection，不能覆盖 schema。
- 一个文本/视觉 collection 的模型 fingerprint 和视觉 index version 必须记录。维度相同也不意味着新旧模型向量可以混用。

### 5.3 数据权威与事务

SQLite 是向量和 chunk 的持久化权威；manifest 是文档当前发布 generation 的权威。二者各负责自己的数据，不宣称它们与 BM25 JSON 具有跨文件 ACID 事务。

每个 `upsert_chunks`、`delete_chunks`、`delete_document`、`replace_document` 批次在单个 SQLite 事务中执行，变更和 collection revision 一起提交。SQLite 设置 WAL、外键、合理的 busy timeout 和 `synchronous=FULL`。

一个数据库路径只能有一个活跃的应用写入所有者。文本与视觉适配器共享 repository；线程操作先用一个 `RLock` 串行化数据库和 FAISS 缓存访问，模型编码在锁外进行。第二个 sidecar 或导入器应在获取写入所有权时明确失败，不能各自持有过期内存索引写入。只读审计使用只读连接。

第一版优先选择简单锁机制，并实测其排队影响。FAISS CPU 可并行只读搜索，但索引修改需要应用自己互斥；增加读写锁或不可变快照并发属于后续优化。[FAISS 线程说明](https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls)

WAL 目录必须位于同机本地磁盘；网络共享目录不在第一版支持范围。[SQLite WAL 限制](https://www.sqlite.org/wal.html)

### 5.4 FAISS 内存缓存

- 缓存由 SQLite 的数据生成，数据库 revision 与内存 revision 必须一致。
- 首次打开/首次搜索时构建索引；批次提交后标记对应 collection 缓存失效。
- 下一次搜索在同一 repository 锁保护下重建必要索引；不得使用旧 revision 返回被删除的数据。
- 默认 `IndexIDMap2(IndexFlatIP(d))`，维护显式数字 ID 与 chunk 映射；其他度量使用对应 Flat 索引。
- 第一版可以按批次重建，不能逐 chunk 全量重建。基准导入应按批写入、最后一次构建。
- 缓存构建失败抛出 `RagVectorStoreError`，由现有检索层记录并降级；不能假装查询成功且结果为空。
- 不引入磁盘 `.faiss` 缓存，避免双写恢复问题。只有启动性能不满足门槛时再加可丢弃缓存，并校验 UUID/schema/revision/向量 ID 摘要。

## 6. 文本检索适配

### 6.1 接口契约

`FaissVectorStore` 完整实现现有 `VectorStore`。另外提供当前实现已有的 `dimension`、`collection_name`、`count_chunks`、`close` 和上下文管理，以满足基准/生命周期使用。

| 方法 | 必须保持的语义 |
| --- | --- |
| `ensure_collection()` | 建立或校验 collection；维度、度量和数据格式不符时明确失败 |
| `upsert_chunks(chunks, vectors, generation_id=None)` | 数量匹配，整批事务，同唯一键幂等；同 chunk 的不同 generation 共存 |
| `search(vector, top_k, filters, allowed_document_ids, generation_id, active_generations)` | 先范围和版本过滤，再检索；返回现有 `RetrievalCandidate` |
| `get_chunk(chunk_id, generation_id=None)` | 指定 generation 精确读取；不指定时维持 legacy 读取契约 |
| `list_chunks(generation_id=None)` | 不指定时枚举全部持久化 generation；指定时只返回该版本 |
| `delete_document(document_id, generation_id=None)` | 不指定时删除该文档全部 generation；指定时只删除目标 generation |
| `delete_chunks(chunk_ids, generation_id=None)` | 不指定时只处理 legacy 唯一键，与旧实现一致；指定时只处理指定版本 |
| `count_chunks(document_ids=None, generation_id=None)` | 支持文档过滤；空 document allowlist 返回 0 |

注意：`search/get_chunk` 的默认 legacy 视图与 `list_chunks` 的全版本枚举语义不同，不能用一个默认 generation 规则覆盖所有方法。

### 6.2 分数和排序

保留现有四种文本度量，避免升级后非默认配置无法使用。

| 配置 distance | FAISS 实现 | 返回 `dense_score` | 排序 |
| --- | --- | --- | --- |
| cosine | 单位归一化 + FlatIP | 内积即 cosine | 高分优先 |
| dot | FlatIP，保持向量尺度 | 原始内积 | 高分优先 |
| euclid | FlatL2 | 对 FAISS 的非负平方距离开方 | 小距离优先 |
| manhattan | Flat + METRIC_L1 | L1 距离 | 小距离优先 |

FAISS 的 L2 输出是平方距离；cosine 使用入库和查询的单位归一化。[FAISS 度量文档](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances)

Qdrant Local 的可见 Euclid/Manhattan 分数按小值优先，因此不能无说明地把 `dense_score` 改成负距离。实施时用旧版本冻结的金标准验证实际语义。[Qdrant Local 距离实现](https://github.com/qdrant/qdrant-client/blob/master/qdrant_client/local/distances.py)

为兼容旧 Local 数据，cosine 的零向量保留为零并产生 0 分；不得除零。dot 的零向量保持有效。稳定排序以分数为主，以 `(document_id, chunk_id, generation_key)` 为同分次序；并列项以并列集合比较，不要求复现 Qdrant 未约定的顺序。分数误差用浮点容差判断。

### 6.3 范围、metadata 和 generation

1. 用现有 `effective_document_ids` 求请求文档与调用方 allowlist 的交集。
2. 空交集、`allowed_document_ids=[]` 或 `active_generations={}` 直接返回空，不能退回全库。
3. `active_generations` 给出每个 document 可查询的 generation；其中 `None` 只表示该文档 legacy 数据。它优先于单个 `generation_id`。
4. 未传 active map 但给定 generation 时只查该 generation；都未传时只查 legacy。
5. 匹配 `source_kind`、`language`、metadata 条件；metadata 必须保留类型语义，特别避免 `True == 1` 的 Python 简化造成匹配错误。嵌套路径行为以冻结旧契约为准。
6. `exclude_references` 继续使用 `is_reference_chunk`，含旧索引标题/文本识别。
7. 在符合条件的全集内取 top-k；最后再次校验范围和 generation，并保持连续 rank。

最小实现采用“筛选候选 ID → 对筛选后的向量建临时 Flat 索引 → 精确搜索”。没有有效限制且覆盖整个缓存时可复用全库索引。不能采用“全库 top-k 后过滤”，否则窄文档范围可能漏掉实际最相关结果。

限制选择器和子索引缓存可以后续优化，但不得改变上述契约。实际产品请求经常携带 active generation map，应把这类查询的临时索引构建耗时单独测量。

## 7. 视觉检索替换

### 7.1 两阶段流程

```text
页面/图片 -> 现有 ColQwen/ColPali -> [页面 token 数, 128] 多向量
                                  |                |
                                  |                +-> SQLite BLOB
                                  +-> 均值池化/L2归一化 -> FAISS 粗索引

问题 -> 现有视觉编码 -> [查询 token 数, 128]
                      |
                      +-> 同样池化 -> FAISS 候选页面
                                           |
                           读取候选页面完整 token 向量
                                           |
                           NumPy MaxSim -> 视觉 top-k
                                           |
                               现有 RRF 文本/视觉融合
```

模型仍输出多向量，只有粗召回使用单向量。文本 1024 维向量与视觉 128 维池化向量分别建 collection，不合并到一个索引。

### 7.2 MaxSim 语义

对查询矩阵 `Q=[Tq,d]` 和页面矩阵 `P=[Tp,d]`：

```python
# 示意评分，不是本次已经实现的生产函数。
# Q/P 必须已完成 float32、shape、finite 与 padding 校验。
similarity = Q @ P.T
score = similarity.max(axis=1).sum(dtype=np.float32)
```

即 `score(Q,P) = sum_i max_j similarity(Q_i,P_j)`；按查询 token 求和，不按页面 token 求和，也不改成平均。与 Qdrant 使用的 MaxSim 定义一致。[Qdrant 多向量说明](https://qdrant.tech/documentation/manage-data/vectors/)

- 默认 `distance=dot`：保持模型输出的 token 向量，不额外归一化改变尺度。
- `distance=cosine`：逐 token 归一化后评分，零 token 向量按旧兼容策略处理。
- 页面真实 token 数不相等，必须用真实长度或 mask。零 padding 在负相似度场景会抢走正确的最大值，不能作为普通 token 参与 max。
- 返回已有 `metadata.visual_score`，不填入文本 `dense_score`；维持融合的 rank 和来源字段。
- 逐页面或受控小批计算，必要时对页面 token 分块并累计每个查询 token 的最大值；不创建全库巨大四维 tensor。
- NumPy CPU 是必须交付的基线；PyTorch/GPU MaxSim 可作为有测量依据的后续优化，不要求新引入评分模型或重新加载模型。

ColPali 项目也提供多向量评分入口；本方案使用独立 NumPy 函数，便于在不加载模型时做确定性评分和回归。[ColPali 官方项目](https://github.com/illuin-tech/colpali)

### 7.3 视觉存储接口

新增 `VisualVectorStore` Protocol，承接现有业务使用的方法：

- `ensure_collection()`、`dimension`、`collection_name`、`close()`。
- `has_document(document_id, index_version, generation_id=None, content_hash=None)`。
- `replace_document(document_id, chunks, vectors, index_version)`。
- `search(query, top_k, filters=None, active_generations=None)`。
- `get_chunk(chunk_id, generation_id=None)`，供现有视觉证据校验精确回读。
- `delete_document(document_id)` 和只读视觉 item 枚举。

视觉 `get_chunk` 必须限定当前 index version；明确 generation 时精确读取，`None` 按 legacy 读取。未给 active map 的视觉 search 同样只查询 legacy，避免保留历史版本后出现无约束结果。正常业务由 manifest 传 active map。`has_document` 的 `None` 仍表示未给版本约束，协调器应传实际 generation（legacy 传空字符串）。这些方法的默认值语义分别实现并测试。

另定义基准能力：`estimate_candidate_count`、`search_full_maxsim`、`fixed_prefetch_store`。所有检索与计数方法接收与生产检索一致的范围和 active generation 条件，固定预取视图的 search 使用同样条件，保证 oracle 与候选召回比较同一个有效语料集合。

视觉基准 CLI 从 `runtime.manifest.list_active_generations()` 获取冻结 map，传入 benchmark runner，并按每个 case 的文档范围求交。不能沿用旧 runner 不传版本的调用，否则采用 legacy 默认视图后可能得到空结果，或比较到错误版本。

`fixed_prefetch_store` 只是共享 repository 的配置视图，不重复获取写入所有权，也不负责关闭父对象连接。

### 7.4 可见性与替换

- `VisualIndexCoordinator` 去掉 Qdrant 特定 `isinstance`，对所有存储传当前 generation 和 content hash。
- 同文档、同 generation、同视觉 index version 的替换在一个事务中完成：全批验证、新 rows 写入、该版本旧 rows 删除、revision 增加。
- 其他 generation 保留，避免新文本版本发布后提前删除仍被在途查询使用的旧视觉版本。
- 查询同时匹配文档范围、active generation 和当前视觉 index version；未发布或不同 hash 的条目不能作为当前证据。
- 图片资产仍由现有 `visual_pages` 管理并保存 checksum，SQLite 不存图片二进制。
- 删除文档应清理数据库中的所有视觉版本和原有资产，失败沿用现有日志/降级机制，后续审计报告残留。

### 7.5 预取、回退与可观测性

复用现有 `pool_multivector` 算法和 `AdaptivePrefetchPolicy`，避免同时改算法。候选数量按经过范围、generation、index version 过滤后的有效 item 数计算。

`prefetch_enabled=False` 直接对全部有效页面做 MaxSim；启用时先用池化 FAISS 召回，再做候选 MaxSim。查询池化出现零能量或粗召回失败时，按现有 `prefetch_fallback_to_full_scan` 决定是否全量评分。页面池化无效时，预取索引写入应明确失败并报告，不允许悄悄丢掉该页面。

最终评分和元数据保留以下字段：

- `retrieval_channel=visual`、`visual_score`、`visual_search_mode`。
- `visual_prefetch_limit`、`visual_prefetch_k`、`visual_candidate_count`、`visual_prefetch_adaptive`。
- `visual_prefetch_fallback_reason`、`visual_maxsim_candidate_reduction`、`visual_store_search_ms`。
- 原有 query/span、generation 和视觉错误字段。

search mode 可使用 `faiss-coarse-maxsim`、`faiss-adaptive-coarse-maxsim`、`full-maxsim`、`full-maxsim-fallback`。全量回退继续以 `full-maxsim` 开头，保持现有 reduction 计算正确。

粗召回失败后仍失败时，视觉服务继续返回文本结果并记录 `visual_error`。不因迁移强制开启视觉检索。

## 8. 索引发布、恢复和删除一致性

### 8.1 文档重建的现有流程

```text
manifest.begin_generation
    -> SQLite 写入新 generation（durable）
    -> BM25 写入新 generation
    -> 精确验证新 generation 的 chunk ID 集合
    -> manifest.validate_generation
    -> manifest.publish_generation
    -> 视觉协调器建立该已发布版本的视觉索引
```

保留上述顺序。不能在开始重建时删除旧 generation，不能在向量未持久化时把 manifest 标为 READY。写入失败时只清理失败的新 generation，旧 READY 版本继续工作。

缓存是可重建的：SQLite 提交后缓存失效，搜索前按 revision 重建；缓存未立即构建不意味着向量未持久化。构建错误必须通过检索错误字段可见。

### 8.2 中断恢复矩阵

| 中断位置 | 重启后处理 |
| --- | --- |
| SQLite 批次提交前 | SQLite 回滚；旧 generation 保持可见 |
| SQLite 已提交，BM25 未完成 | manifest 未发布新版本；现有恢复标记中断，新 generation 不进入生产搜索 |
| 两个存储均写入，manifest 尚未发布 | 新 rows 保留但不可见；按中断任务审计并可重建 |
| manifest 发布后，FAISS 尚未构建 | 从 SQLite 重建 FAISS，恢复新版本 |
| 新文本已发布，视觉未建好 | 文本检索可用；视觉明确降级，后续重新索引该文档 |
| 删除中断，manifest 与向量/BM25 不一致 | 报告缺失或残留；不得把损坏版本当成有效证据；提供重新删除/重建 |

启动时执行现有 `manifest.recover_interrupted_operations()`，再检查 READY 文档的 chunk 集合。轻量启动检查和完整只读审计分开，避免每次启动加载所有视觉 BLOB。

历史 RETIRED 版本第一版保留，不实现自动垃圾回收。在应用停止、完整备份和审计通过后，维护工具可按明确版本做清理。对 FAILED/中断版本的清理必须记录，不得按“不是当前版本”统一删除。

### 8.3 避免空库复用 READY manifest

当前 `_can_reuse()` 主要比较内容/解析/分块/Embedding fingerprint，不能证明新 SQLite 中存在数据。

最低修正：复用前验证目标 generation 的实际 vector chunk ID 集合与 manifest 完全相等；有 BM25 时同时验证其集合。若缺失，走正常重建，不能只因 manifest READY 而跳过。

迁移时还必须完成目录级校验和数据导入，再改变 provider；不能指望首次启动自动修好所有旧数据。

## 9. 旧数据迁移流程

### 9.1 路线 A：导出向量后导入（默认）

优点：保留原 chunk、模型输出、generation、SourceSpan 与视觉 token，减少重新编码成本，也便于比较存储变化。

1. 记录旧版本 commit、客户端版本、配置、实际根目录、文本/视觉 collection schema、模型 fingerprint 和基准结果。仅保存需要的配置，不把 API key 写进迁移报告。
2. 停止旧 sidecar 和写入任务，备份完整 `config/rag` 状态和必要的配置快照。旧 Local collection 不能与运行中的应用同时被第二个 client 打开。
3. 旧环境导出器用 `scroll(with_vectors=True, with_payload=True)` 获取文本和视觉数据，不直接解析 Qdrant 私有 SQLite 布局。
4. 导出文本单向量及视觉 named vectors；对旧单 multivector 视觉 schema 只读取 late vectors，并在新环境用相同池化函数构建 coarse vectors。
5. 导出 manifest、BM25、资产索引；记录 row 数量、长度、hash、generation、模型/度量/index version。旧视觉未启用时报告“无视觉索引”，不伪造已迁移。
6. 新环境导入器先校验整个包与 schema，再分批导入独立 staging SQLite。完全不 import Qdrant。
7. 保留文本全部可审计 generation；不一致/无效 rows 写入问题清单。导入旧视觉数据时仅接受符合 schema、已发布标记、index version 和 hash 的完整条目，其他条目明确报告为需重建。
8. 对三方 `(document_id, generation_key, chunk_id)` 集合做审计；不得只比较总数。视觉另做 item/version/hash/资产存在性校验。
9. 对冻结向量和查询进行文本检索、视觉全量 MaxSim 和两阶段结果比较。
10. staging 通过检查后，停止应用，关闭 SQLite 连接并 checkpoint，将新目录置于目标路径，更新用户 provider/path 设置及迁移完成标记。
11. 启动新 sidecar，执行 Knowledge 导入、查询、重建、删除、重启和引用打开 smoke test；保留旧备份与旧应用。

分批导入可以重复执行。以迁移包 digest、已提交 batch 和唯一键实现幂等恢复；失败不能留下被误认为完成的 READY 标记。

payload 转换须沿用旧 adapter 的业务解码规则：将 Qdrant 顶层 `source_kind/index_generation/visual_published/visual_search_schema/visual_index_version` 等存储字段提取到中立包的专用字段，再校验 `DocumentChunk`；generation 补入 metadata。不能把原始 payload 整体送入 `extra=forbid` 的模型，也不能丢掉已有 `SourceSpan`。

只切换同机向量目录时，尽量保留图片资产原路径。如迁移数据根或设备，导入器按 `asset-path-map.json` 复制并校验图片，再更新文本/视觉 SQLite payload 和 BM25 chunk 中的 `metadata.asset_uri`；记录允许改变的 URI 字段，其余 payload 保持一致。原文 `source_uri/SourceSpan` 不因索引目录搬迁自动改写。原文件也移动时，按路线 B 重建并记录身份映射，避免稳定 document ID 与引用定位失配。Graph 使用稳定的关闭文件或 SQLite backup 一并迁移；已有证据缓存应清空或随路径变更显式失效。

### 9.2 路线 B：从原始文档重建（备选）

适用于旧向量不可导出、schema 冲突、已有索引损坏或旧原始编码版本不兼容。

先备份旧目录，在独立 staging 根创建 FAISS/SQLite、BM25 和 manifest；通过现有导入/强制重建流程逐文档重建，记录旧 source URI 与新 document/chunk 对应。

这条路线需要模型和原始文件。原文件缺失的文档不能假定能重建；必须列为未迁移项。分块或模型版本变化会产生新 chunk/generation，旧证据缓存必须失效，质量对比不能宣称只改变了存储。

本路线不复制旧 READY manifest 到空新库。所有可用文档重建和验收后再切换路径。

### 9.3 配置兼容

- 新默认 `provider=faiss`、`storage_path=config/rag/faiss`。
- 用户已有 `qdrant_local` 配置时，应用给出明确迁移状态；仅当目标导入/重建已验证时才改写持久化设置。
- 旧路径不能直接被当成 FAISS 目录，也不能用新默认掩盖未迁移数据。
- 迁移器负责在 staged 配置中保留 collection 名称、度量、Embedding fingerprint、视觉模型和功能开关。
- 原 `url`、`timeout_seconds` 字段可作为弃用兼容字段保留一版，以免 `extra=forbid` 让旧配置无法解析；不再创建远程客户端。
- `AITRANS_QDRANT_URL`/API key 不再影响新运行时。若旧环境实际依赖远程 collection，应先在旧导出环境完成导出；未迁移时明确提示。
- `visual_retrieval.provider=colpali_engine` 表示模型提供方，不改成 `faiss`。视觉存储实现由运行时工厂固定选取。
- 视觉 `storage_path` 独立解析，默认与文本相同则共用 repository；不同则分别打开并关闭。不能继续无条件覆盖为文本路径。
- `on_disk` 旧字段兼容保留并说明 SQLite 的 durable 存储与 FAISS 内存缓存语义，不假装它能控制 FAISS mmap。
- `state_directory=vector_storage_path.parent` 仍用于现有 BM25/manifest；默认新旧路径共享 `config/rag` 父目录。自定义路径迁移时必须把它们作为整体搬迁，不能只移动向量数据库。

## 10. 审计、评测及界面兼容

### 10.1 审计

文本审计继续比较 manifest、BM25 和 vector 三份目录，使用公共 `list_chunks`/只读 iterator，不访问 `_client`。审计不能创建 collection、写 revision 或修改文件。

报告 key 统一为 `manifest/bm25/vector`，附加 `vector_store_provider=faiss` 或等效 provider 信息。更新 Debug Studio、脚本与测试中读取旧 `qdrant` key 的位置；历史报告保留原内容，不重写实验结果。

视觉审计不与文本 chunk 集合强求相等，单独比较 document/generation/index version、视觉 item 身份、资产定位和 content hash。

### 10.2 评测方法

- 旧基线先导出固定查询向量和页面 token 向量，新旧后端使用同一批数据，不把模型随机性误当成存储差异。
- 文本：精确 top-k 集合、分数、rank、空范围、窄范围、metadata、reference 排除和 generation 切换。
- 视觉：全量 MaxSim 为 oracle，再比较池化候选覆盖率、最终视觉 top-k、固定/自适应 prefetch、全量回退。
- End-to-end：沿用 QASPER、真实文档导入与现有评测 protocol；检查引用 SourceSpan 和原文定位。
- 性能：分开记录模型编码、过滤、子索引构建、FAISS 搜索、BLOB 读取、MaxSim、rerank、端到端耗时。
- 当前默认关闭视觉。没有真实视觉模型基线时，CPU 合成测试只能证明评分与协议，不能证明真实页面召回质量。

### 10.3 建议发布门槛

这些是本项目的验收建议，不是 FAISS 官方性能承诺；T00 冻结后作为发布判定标准。

| 项目 | 门槛 |
| --- | --- |
| 有效文本数据迁移 | 每个 document/generation 的 chunk ID、payload 和向量核对通过；未迁移项为 0，或有明确保留旧版本的处置清单 |
| 范围/版本隔离 | 违规返回 0；空 allowlist/map 均返回空 |
| 文本分数 | `abs_err <= 1e-5 + 1e-5 * abs(reference_score)`；非并列集合一致 |
| 视觉 MaxSim | `abs_err <= 1e-4 + 1e-5 * abs(reference_score)`；负值/padding/变长/分块一致 |
| 真实视觉粗召回 | 相对同配置旧基线的 oracle-top-k 覆盖率下降不超过 1 个百分点；报告每类问题；显著差异不能只用整体均值掩盖 |
| 端到端质量 | 冻结的 Recall/nDCG/证据及引用指标下降不超过 1 个百分点；任何范围泄漏、错位引用均阻断发布 |
| 性能 | 同硬件同语料，存储阶段 p95 建议不超过旧基线 1.2 倍；端到端 p95 建议不超过 1.1 倍；无法达到时记录瓶颈并优化 |
| 冷启动 | 测量首次构建及重启，不承诺未测得的秒数；绝对时间预算在 T00 按目标设备冻结 |
| 打包 | Windows x64 干净环境离线 smoke test 通过，不需要 Conda/Python 安装或 Qdrant；视觉模型能力另按其现有依赖验证 |
| 故障恢复 | 写入、发布、删除、导入中断测试通过；不会把未发布版本当 READY 数据返回 |

性能样本至少包含 10k、50k、100k 个 1024 维文本向量和 100、1k、10k 个视觉页面；小规模实库不足时用可复现合成向量补充性能测试，但不能替代真实质量评测。每类查询至少记录 100 个样本；不足时明确样本数，不把少量重复查询当成独立质量样本。

## 11. 容量与成本边界

Flat 索引保存 float32 向量，基础向量内存约 `N × d × 4` 字节。[FAISS 索引说明](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes)

| 数据 | 仅向量的基础体积 |
| --- | --- |
| 10k 文本 × 1024 维 | 约 39 MiB |
| 100k 文本 × 1024 维 | 约 391 MiB |
| 单视觉页面，768 token × 128 维 | 384 KiB |
| 10k 视觉页面，同样 token 数 | 约 3.66 GiB |
| 10k 页面池化向量 × 128 维 | 约 4.9 MiB |

以上不含 payload、SQLite 页、ID 映射、Python 对象、模型权重、图片、WAL 或重建时的额外副本。文本子索引构建可能增加一份向量内存，必须测量 peak RSS。视觉完整 token 向量只按候选读取，不一次性全载入内存。

文本 Flat 搜索计算量随有效候选数增长；MaxSim 计算量近似 `C × Tq × Tp × d`。单锁和临时索引可以减少实现工作，但不能据此承诺高并发服务能力。

## 12. Windows 依赖与发布

当前 Python 范围是 3.11–3.12，桌面打包目标为 Windows x64。GPU 优先安装使用实际 Conda win-64 仓库构建；不能直接套用 Linux GPU pip wheel。上游与 conda-forge 的平台支持范围不同，具体发行包、ABI 和 PyInstaller 可用性必须实际验证。[FAISS 安装说明](https://github.com/facebookresearch/faiss/blob/main/INSTALL.md)、[conda-forge 构建配置](https://github.com/conda-forge/faiss-feedstock)

先前 CPU 基线为 `faiss-cpu==1.15.1` / NumPy 2.4.6；GPU 环境使用 conda-forge `faiss-gpu=1.9.0`、CUDA Toolkit 11.8、NumPy 1.26.4，具体新增验收见报告。GPU 包已包含 CPU 类，不能再安装覆盖同名 `faiss` 模块的 CPU wheel。Python 3.12 和干净 Windows VM 未验；最终用户接收冻结 sidecar，无需安装 Conda。

依赖改动：

- `pyproject.toml`：保留显式 NumPy 依赖，FAISS 由 `scripts/install_faiss.ps1` 按 GPU 优先安装；CPU wheel 放入 `faiss-cpu` extra，避免普通 pip 安装覆盖 Conda GPU 模块。
- `aitranslator-rag-requirements.txt`：同一 FAISS/NumPy 锁定组合，移除 Qdrant。
- `aitranslator-rag-visual-requirements.txt`：保留现有模型依赖，不因存储迁移顺便升级 colpali-engine/torch。
- `aitrans_backend.spec`：移除 Qdrant 收集项，使用验证过的 FAISS hook/原生库收集方式；检查 `_swigfaiss`、OpenMP/BLAS DLL 及许可证。
- `backend/sidecar.py`：实际执行 FAISS add/search、SQLite 写入/重开与 MaxSim 合成评分，不能只有 import 成功。
- 两套构建入口都更新：`scripts/build_rag_backend.ps1` 和 `apps/desktop/scripts/build-backend-sidecar.mjs`。
- 普通 sidecar 不打包模型权重；视觉可选依赖的既有发布策略独立验证。默认视觉关闭的包不能自动声称支持真实视觉推理。

## 13. 实施顺序与回滚

详细逐任务输入、输出和验收见开发任务书；推荐顺序：

1. 冻结旧基线与迁移包格式。
2. 验证 Windows FAISS GPU 优先、CPU 回退及冻结打包。
3. 实现 SQLite repository、文本适配器、过滤和 generation 契约。
4. 实现视觉协议、MaxSim、FAISS 粗召回和回退。
5. 替换运行时装配、配置、审计和基准入口。
6. 完成导出/导入、恢复、重建和回滚演练。
7. 删除生产 Qdrant 依赖，运行全链路与桌面验收。
8. 实施实际数据切换并保存最终迁移报告。

迁移前备份必须包括：旧应用版本/commit、实际配置、完整旧向量目录、BM25、manifest、graph 和页面资产。SQLite 备份使用关闭并 checkpoint 后的稳定文件，或标准库 backup API；不要在线只拷贝一个 `.sqlite3` 文件而漏掉 WAL。[SQLite 备份 API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)

回滚时停止新应用，保留新数据目录供排查，恢复旧应用和迁移前完整数据集合。若切换后发生新增/修改/删除，回滚恢复快照会丢失这些之后的状态；在试运行窗口冻结写入，或在恢复前记录并从原始文档重放这些操作。不能声称一键回滚可自动保留新系统产生的一切变化。

## 14. 完成交付物

- 文本 FAISS 适配器、SQLite repository、视觉 FAISS/MaxSim 实现。
- 修改后的配置、运行时、审计、基准、测试和 Windows 打包入口。
- 一次性旧环境导出器、新环境导入器和迁移包 schema。
- 数据迁移校验报告、旧/新固定向量对比报告、真实视觉质量报告。
- 目标设备容量/延迟/冷启动报告、无 Qdrant 干净环境发布验证。
- 数据切换记录、回滚演练记录和剩余问题清单。

所有硬性正确性检查通过才能完成迁移。缺少真实视觉模型验收时，只能标记文本迁移和视觉算法验证完成，不能把完整视觉迁移标记为已验收。
