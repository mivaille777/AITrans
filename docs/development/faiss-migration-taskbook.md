# AITrans FAISS 迁移开发任务书

日期：2026-10-04；实施更新：2026-10-05（Asia/Shanghai）  
状态：代码、工具、本机数据切换和真实模型链路已实施。完整发布门槛仍有未验项目；[真实验收报告](faiss-migration-acceptance.md) 记录实测结果、旧失败和限制。未勾选的验收条件不视为已通过。  
技术依据：[完整 FAISS 迁移方案](faiss-migration-plan.md)。

## 1. 开发目标

将 AITrans 正常运行和 Windows 桌面发布包中的 Qdrant 全部替换为：

`FAISS GPU 优先文本检索 + FAISS GPU 优先视觉候选召回 + CPU 自动回退 + NumPy MaxSim + SQLite 向量/元数据持久化`。2026-10-05 用户追加 GPU 优先要求；此前 CPU-only 限制被本次要求取代。

尽量减少业务层改动：保留 Embedding、解析/分块、BM25、manifest、reranker、RRF、Agent/Research、引用定位和现有 Knowledge API。完整保留启用原生视觉检索时的能力，默认开关保持关闭。

最终不存在生产 Qdrant provider 分支。一次性旧环境导出工具单独隔离；回滚依靠迁移前应用与数据快照。

### 1.1 验收责任

| 职责 | 负责内容 | 当前负责人 |
| --- | --- | --- |
| 后端开发 | repository、文本/视觉适配器、运行时和恢复 | 待分配 |
| 迁移工具开发 | 数据包格式、导出/导入、审计与切换 | 待分配 |
| 桌面构建 | GPU 优先 / CPU 回退 FAISS 分发、DLL、PyInstaller、干净环境 | 待分配 |
| 测试/评测 | 固定向量、范围/版本、故障注入、真实质量 | 待分配 |
| 发布负责人 | 备份、验收证据、实际切换、回滚记录 | 待分配 |

同一人可以承担多项职责。实现者不能仅凭 import 成功或单一演示宣布迁移完成。

### 1.2 控制改动幅度的规则

- 新存储完整实现现有 `VectorStore`，不改变 `RetrievalCandidate/Result` 公共字段。
- 视觉只补充缺少的存储协议，业务服务继续使用相同方法。
- SQLite 只存向量和 chunk，不顺便迁移 BM25/manifest/Graph。
- 默认 Flat 精确检索；不同时引入 ANN、GPU FAISS、模型升级或新框架。
- 一个简洁工厂足够，不引入 provider 插件系统。
- 不通过修改模型/分块参数“弥补”存储迁移造成的回归。
- 旧 `config/rag` 是待迁移数据，不能在开发测试中覆盖或删除。

## 2. 总体任务清单与依赖

任务表中的完成表示该任务全部验收成立；章节中的未勾选项可能已实现但尚无完整验收证据。P0 为正确性/数据/发布阻断项；P1 仍须在完整发布验收前完成。

| 完成 | ID | 优先级 | 任务 | 前置任务 |
| --- | --- | --- | --- | --- |
| [ ] | T00 | P0 | 冻结现状、契约、数据和验收基线 | 无 |
| [ ] | T01 | P0 | 验证 Windows FAISS GPU 优先、CPU 回退与冻结打包 | T00 |
| [x] | T02 | P0 | 实现 SQLite repository 与写入所有权 | T01 |
| [x] | T03 | P0 | 实现文本 FAISS adapter、CRUD 与度量 | T02 |
| [ ] | T04 | P0 | 实现文档/metadata/reference/generation 过滤 | T03 |
| [x] | T05 | P0 | 视觉存储协议与独立 MaxSim 评分 | T00、T01 |
| [x] | T06 | P0 | 视觉 FAISS 存储、预取、全量评分与回退 | T02、T04、T05 |
| [ ] | T07 | P0 | 接入运行时、配置、状态与关闭生命周期 | T03、T04、T06 |
| [ ] | T08 | P1 | 迁移审计、文本/视觉基准与 Debug 接入 | T07 |
| [ ] | T09 | P0 | 实现旧环境导出器和新环境导入器 | T00、T04、T06、T08 |
| [ ] | T10 | P0 | 修复复用检查，完成恢复与回滚演练 | T07、T09 |
| [ ] | T11 | P0 | 清除生产 Qdrant，完成两套桌面打包 | T07、T08、T09、T10 |
| [ ] | T12 | P1 | 完成正确性、质量、性能及端到端验收 | T08、T10、T11 |
| [ ] | T13 | P0 | 实际数据切换、发布记录及运维交接 | T09、T10、T11、T12 |

### 2.0 本次完成情况

| 任务 | 实施与剩余验收 |
| --- | --- |
| T00 | 旧源码/数据、gold、环境与行为基线已冻结；未预先冻结大型 corpus 的绝对预算和完整质量集 |
| T01 | 实际 `aitrans`、两套打包和 PATH 隔离运算通过；干净 Windows VM/Python 3.12 未验 |
| T02–T06 | 存储、算法、过滤/版本、视觉/回退、真实评分通过；T04 的过滤与子索引阶段独立计时尚未交付 |
| T07 | 实际运行时全链路通过；保持原共享存储，未新增独立视觉目录运行时模式 |
| T08 | 只读审计、基准、trace、前端回归通过；人工 Debug/桌面操作未验 |
| T09 | Local 导出/导入/resume/verify、实际文本及多向量工具通过；远程服务与跨机器 URI 搬迁未验 |
| T10 | 空库复用守卫、事务故障、generation 生命周期及隔离完整回滚通过；未穷举全部跨文件进程强杀点 |
| T11 | 无生产 Qdrant，两个冻结包和离线运算通过；干净 VM/干净依赖安装未验 |
| T12 | 后端 1,582 passed、6 个可复现旧失败；前端 467 passed；真实文本/视觉/runtime 和六档规模通过；大型独立质量集/并发预算未验 |
| T13 | 本机 1,328 条向量和 3 个 READY 文档已切换，原配置视觉保持开启，回滚与维护说明已交付；完整发布条件未全部满足 |

因此 T00–T13 总验收及 Definition of Done 尚未全部勾选。剩余项不能用小语料、源码测试或 PATH 隔离替代。运行命令与实际产物见验收报告/迁移 README，不沿用下文示意文件格式作为已交付实现。

T00 先导出冻结旧基线需要的数据；T09 再交付正式可恢复迁移工具。不要先移除旧环境，然后才尝试重现旧基线。

### 2.1 阶段退出条件

| 阶段 | 包含任务 | 退出条件 |
| --- | --- | --- |
| A：基线/环境 | T00–T01 | 旧金标准可重放；目标 Python/Windows 可运行并冻结 GPU 优先 / CPU 回退 FAISS |
| B：存储契约 | T02–T04 | 文本 CRUD、重启、范围和 generation 均通过 |
| C：视觉替换 | T05–T06 | MaxSim 与两阶段路径通过，且全量 oracle 可用 |
| D：集成/迁移 | T07–T10 | 导入、运行时、审计、中断恢复和回滚演练通过 |
| E：发布验收 | T11–T13 | 无生产 Qdrant；真实质量/打包通过；实际迁移记录完整 |

## 3. T00：冻结现状与基线

### 输入和涉及文件

- 当前 commit、工作区状态、`pyproject.toml` 和两份 RAG requirements。
- `backend/rag/stores/base.py`、`stores/qdrant.py`、`index_service.py`、`index_manifest.py`。
- `visual_retrieval.py`、`visual_prefetch.py`、`visual_adaptive.py`。
- `tests/rag/test_vector_store_contract.py`、`test_vector_scope.py`、`test_generation_retrieval.py`、视觉测试。
- 实际 `data_root` 与配置；只提取迁移相关非敏感字段。

### 实施步骤

- [ ] 记录 commit、Python/NumPy/qdrant-client/模型版本、硬件、实际存储路径和 collection schema。
- [ ] 梳理所有 Qdrant import、类型判断、路径、环境变量、构建收集项和 fixture；区分生产代码与历史文档。
- [ ] 冻结接口默认语义：搜索/读取默认 legacy；`list_chunks()` 默认全版本；文档删除默认全版本；`delete_chunks()` 默认 legacy。
- [ ] 对 cosine/dot/euclid/manhattan 导出小型独立 gold 数据，包含零向量、负值和并列分数。
- [ ] 冻结有效/空 allowlist、active generation map、reference 排除及 metadata 类型和嵌套路径行为。
- [ ] 导出固定文本查询向量、视觉 query/page token 向量及旧结果；真实视觉不可用时明确标注，保留后续硬件验收任务。
- [ ] 记录当前端到端、冷启动、检索各阶段耗时和峰值内存；避免在生产库做破坏性测试。
- [ ] 冻结性能绝对预算、试运行窗口和测试语料名单；保留迁移方案中的正确性阈值。

### 交付物与验收

交付 `baseline-manifest.json`、小型可版本化 gold fixture、测试集 ID 清单和基线报告。大批真实文档/向量只存隔离的 `test-results/faiss-migration/<run-id>/`，不提交用户原文与凭据。

验收：另一环境可以不加载模型、不连接 Qdrant，读取冻结 fixture 并复现预期分数与集合。真实模型不可用不能被写成“视觉已验收”。

## 4. T01：验证 Windows FAISS 设备选择与打包

### 实施步骤

- [ ] 在隔离 Python 3.11/3.12 Windows x64 环境选择 `faiss-cpu` 分发，记录来源与版本。
- [x] 验证现有 NumPy/torch/sentence-transformers 组合，无需同时升级模型依赖。
- [x] 实际执行 FlatIP、FlatL2、L1、数字 ID、top-k 大于向量数和空集合行为。
- [x] 用最小 PyInstaller 程序执行 add/search、SQLite 重开与纯 NumPy MaxSim，确认原生库可被收集。
- [ ] 在没有 Conda/Python 安装的干净 Windows 环境运行冻结程序；确认目标 CPU 指令集可用。
- [x] 确定依赖锁定和构建路线；pip 分发不可行时验证官方 Conda CPU 构建作为替代。

### 交付物与验收

交付兼容性矩阵、具体依赖锁定组合、DLL/hook 清单和最小冻结程序结果。

验收：开发源码及冻结程序都执行真实运算成功，而非仅 `find_spec/import`。本次追加要求：安装 GPU 构建，检测到实际可用 CUDA 设备后优先使用 GPU；无 GPU 构建/设备、分配或搜索失败时使用 CPU。安装平台依据 [官方安装说明](https://github.com/facebookresearch/faiss/blob/main/INSTALL.md) 与实际 conda-forge win-64 包。若此项失败，应先解决环境，不能完成文本存储后才发现无法发布。

### T01-GPU：追加开发任务

- 安装脚本优先 Conda GPU；没有 NVIDIA GPU / Conda 或 GPU 下载不可用时检查 CPU 方案。GPU 包与 CPU wheel 不同时安装。
- 统一 `faiss_runtime.py` 创建和搜索索引，文本及视觉粗召回复用；保持存储格式、业务 API、SQLite ID 和 scope 契约。
- 自动检测实际 CUDA 设备并尝试分配/克隆；GPU 初始化、OOM、搜索异常自动回退 CPU并记录原因。
- GPU Float32；全进程共用每设备 64 MiB scratch resource，并以锁保护跨 repository / 线程操作。
- Manhattan 保持 CPU；top-k > 2048 和全量边界 tie 展开使用 CPU，后续普通查询仍可使用 GPU。
- `AITRANS_FAISS_DEVICE=auto` 为默认；`cpu` 强制 CPU；`AITRANS_FAISS_GPU_DEVICE=0` 默认设备号。
- 在 `aitrans` 真实 GPU 上比较 CPU/GPU ID 与分数，验证并发、范围、generation、重开、删除、真实文本/视觉模型及冻结程序。
- 打包收集 Conda FAISS、CUDA、BLAS DLL 与许可证，分别验 GPU 与强制 CPU；缺少 NVIDIA 驱动的干净机器仍需后续验收。

MaxSim 保留 NumPy；本任务不改视觉模型和最终评分算法，不重建已有向量。

## 5. T02：实现 SQLite repository

### 涉及文件

新增 `backend/rag/stores/local_repository.py`、`tests/rag/test_local_vector_repository.py`。

### 实施步骤

- [x] 实现迁移方案第 5 节的三表 schema、schema version、稳定数字 ID 和唯一键。
- [x] 实现文本/视觉 collection 校验、模型 fingerprint/index version 校验。
- [x] 存完整 chunk JSON 和 little-endian float32 BLOB；提供严格长度/shape/finite 解码。
- [x] 批量写入/替换/删除和 revision 变更在同一事务；禁止逐行 commit。
- [x] 实现幂等 upsert：同唯一键更新时保留数字 ID；跨 document 冲突明确拒绝。
- [x] 使用 WAL、外键、busy timeout、`synchronous=FULL`，明确连接线程使用方式。
- [x] 实现单路径写入所有权：应用与导入器不能同时拥有可写 repository；文本/视觉同路径复用对象。
- [x] 使用 `RLock` 串行化第一版操作；统一锁顺序，锁内不调用模型或网络。
- [x] 实现只读枚举、按 collection/document/generation 读取和标准 backup 接口。
- [x] `close()` 幂等；注入 repository 的 adapter 不擅自关闭外部所有者连接。

### 测试与验收

- ST-01：同唯一键重复 upsert，row 数不增长、ID 不改变。
- ST-02：同 chunk 不同 generation 共存；文本/视觉 collection 不串数据。
- ST-03：批次中有错误、commit 前中断，整个批次不部分写入。
- ST-04：commit 后重开，payload/BLOB/revision 恢复一致。
- ST-05：错误维度、BLOB 长度、NaN/Inf 和 float32 溢出均报错。
- ST-06：两个写入进程竞争，第二个明确失败；只读审计不改变数据库。
- ST-07：backup/checkpoint 后恢复得到相同逻辑集合；关闭释放锁。
- ST-08：拒绝未来不支持 schema 与模型/度量混写，不自动清空旧数据。

验收：所有 repository 测试在临时目录运行；能够独立恢复持久化数据，不依赖 `.faiss` 或其他向量文件。

## 6. T03：实现文本 FAISS adapter

### 涉及文件

新增 `backend/rag/stores/faiss.py`、`tests/rag/test_faiss_store.py`；修改 `stores/__init__.py`；保留 `stores/base.py` 现有契约。

### 实施步骤

- [x] 实现 `VectorStore` 全部方法，补齐 `count_chunks`、属性、关闭与上下文管理。
- [x] 默认 `IndexIDMap2(IndexFlatIP(d))`；SQLite 数字 ID 与返回 chunk 显式对应。
- [x] cosine 单位归一化、dot 保持尺度、euclid 对 L2 平方距离开方、manhattan L1。
- [x] 输入转连续 float32 后再次检查 finite；不要原地修改调用方的向量。
- [x] legacy 零向量按冻结行为处理，避免除零和浮点 NaN。
- [x] 实现 collection revision 缓存失效，搜索前刷新；失败返回有类型的错误。
- [x] 批量导入仅失效缓存，第一次需要时构建；不逐 chunk 重建。
- [x] top-k 大于 corpus 时只返回有效条目，过滤 FAISS 的 `-1` 占位 ID。
- [x] 同分稳定排序，按现有 `RetrievalCandidate` 写入分数和连续 rank。

### 测试与验收

- TX-01：四度量与 T00 gold 对齐，euclid 返回距离而非平方/负距离。
- TX-02：upsert、精确读取、枚举、计数、批次删除、文档删除相互一致。
- TX-03：关闭重开仍能搜索，且无 `.faiss` 文件也可恢复。
- TX-04：删除/更新使缓存失效，下次搜索不返回旧 row。
- TX-05：相同 chunk 的 legacy、新旧 generation 均可独立读/删。
- TX-06：完整 `SourceSpan`、bbox、related_ids、source_uri、document_hash 往返一致。
- TX-07：数量不匹配/维度错误在任何写入前失败；输入 list/array 不被修改。
- TX-08：空 collection、top-k 边界与并列项排序稳定。

验收：生产接口满足 `VectorStore`；基础 CRUD 与分数阈值通过，未引入新候选模型或 ANN。

## 7. T04：实现范围与 generation 过滤

### 涉及文件

`stores/faiss.py`、`stores/base.py`（只添加必要公共帮助函数）；更新 `test_vector_store_contract.py`、`test_vector_scope.py`、`test_generation_retrieval.py`。

### 实施步骤

- [ ] 复用 `effective_document_ids` 与 `is_reference_chunk`。
- [ ] 实现 active map/指定 generation/默认 legacy 的优先级。
- [ ] 将元数据条件转换为有效候选 ID；保留 bool/int/string 类型及冻结的嵌套路径语义。
- [ ] 全局无过滤时复用全库索引；有范围时对有效候选建临时 Flat 索引。
- [ ] 不在全库截断后才做过滤；保留输出二次范围校验。
- [ ] 对参考文献旧标题/文本兜底也做预过滤，返回有效集合内真正的 top-k。
- [ ] 分开统计过滤和子索引构建耗时，为 T12 性能定位提供信息。

### 必须覆盖的断言

| ID | 场景 | 预期 |
| --- | --- | --- |
| FL-01 | allowlist 为空 | 不触发全库搜索，返回空 |
| FL-02 | 请求和 allowlist 无交集 | 返回空 |
| FL-03 | `active_generations={}` | 返回空 |
| FL-04 | 同文档 g1/g2/legacy，map 只允许 g2 | 仅 g2；其他文档同名 g2 也不能混入 |
| FL-05 | active map 中指定 `None` | 仅该文档 legacy |
| FL-06 | 默认 search/get 与 list/delete 语义 | 按方案第 6.1 节分别验证 |
| FL-07 | 大量高分未授权项占据全库 top-k | 仍返回允许集合里的 top-k |
| FL-08 | metadata 为布尔/数字/字符串 | 按冻结类型语义匹配，不能自动互转 |
| FL-09 | references、旧 headings、chunk_type | 排除策略与原契约一致 |
| FL-10 | generation 列和 JSON 相冲突 | 输入拒绝或报告，不能进入结果 |
| FL-11 | source_kind/language/metadata 联合条件 | 全部条件相交 |
| FL-12 | 全部候选被过滤、候选少于 k | 返回正确数量和连续 rank |

验收：范围和版本违规返回数为 0。不能用“最后又过滤了一遍”代替有效集合内 top-k 正确性。

## 8. T05：视觉协议与 MaxSim

### 涉及文件

新增 `backend/rag/stores/visual_base.py`、`backend/rag/visual_scoring.py`、`tests/rag/test_visual_scoring.py`。

### 建议接口

以下为接口约定，具体类型引入及装配由实现补齐：

```python
class VisualVectorStore(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def collection_name(self) -> str: ...

    def ensure_collection(self) -> None: ...

    def has_document(
        self, document_id: str, *, index_version: str,
        generation_id: str | None = None,
        content_hash: str | None = None,
    ) -> bool: ...

    def replace_document(
        self, document_id: str, chunks: list[DocumentChunk],
        vectors: list[list[list[float]]], *, index_version: str,
    ) -> None: ...

    def search(
        self, query: list[list[float]], *, top_k: int,
        filters: VectorSearchFilter | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]: ...

    def get_chunk(
        self, chunk_id: str, *, generation_id: str | None = None,
    ) -> DocumentChunk | None: ...

    def delete_document(self, document_id: str) -> None: ...
    def list_chunks(self) -> list[DocumentChunk]: ...
    def close(self) -> None: ...
```

基准协议另加 `search_full_maxsim`、`fixed_prefetch_store` 和可按同一范围/generation 估计候选数量的方法。`has_document` 的空字符串表示 legacy generation；`None` 表示未给版本约束，协调器必须传实际版本以免复用旧视觉数据。内部 SQL 统一使用空字符串 sentinel。

`get_chunk` 供现有 `_validate_visual_chunk` 校验原始证据，必须限定当前视觉 index version。其 `generation_id=None` 和无 active map 的 `search` 都按 legacy 视图处理；保留历史 generation 后不能做无约束回读。`list_chunks` 为全版本只读枚举，不能套用相同默认过滤。

### 实施步骤

- [x] 将多向量校验从 Qdrant 模块依赖中分离，避免循环 import。
- [x] 实现 `sum(max(Q @ P.T, axis=page_tokens), axis=query_tokens)`。
- [x] dot 与 cosine 分支显式区分；不把 dot 自行改成单位向量。
- [x] 真实 token 长度/mask 生效；非有效 padding 不参与 max。
- [x] 实现单页面及受控 token 分块评分；float32 累加，保证峰值中间矩阵受控。
- [x] 不因调用评分函数而加载 ColQwen/torch 模型。

### 测试与验收

- VS-01：`Q=[[2,0],[0,3]]`、`P=[[1,0],[0,1]]`，dot 为 5，cosine 为 2。
- VS-02：`Q=[[1,0]]`、`P=[[-1,0]]`，有效结果为 -1；添加无效零 padding 后不能变为 0。
- VS-03：变长页面、变长查询、token 分块与未分块分数一致。
- VS-04：转置/求和轴错误能被测试识别；保持 query token 求和。
- VS-05：空 token、错误维度、非数值、NaN/Inf、溢出按契约失败。
- VS-06：与 T00 固定视觉向量的旧 MaxSim 分数在容差内一致。

验收：纯 CPU、无模型的全部评分测试通过。算法依据 [Qdrant MaxSim 定义](https://qdrant.tech/documentation/manage-data/vectors/)，模型继续复用 [ColPali/ColQwen](https://github.com/illuin-tech/colpali)。

## 9. T06：视觉 FAISS 存储和回退

### 涉及文件

新增 `backend/rag/stores/faiss_visual.py`、`tests/rag/test_faiss_visual_store.py`；修改 `visual_prefetch.py`、`visual_adaptive.py` 的存储工厂和纯函数边界。

### 实施步骤

- [x] `replace_document` 在单事务内替换相同 document/generation/index version 的完整批次；其他 generation 保留。
- [x] 持久化完整 token BLOB、长度、chunk、hash、index version；粗向量由现有均值池化生成。
- [x] 建 128 维默认视觉粗索引，与文本 collection 独立。
- [x] 使用与文本一致的范围/metadata 规则，加上当前视觉 index version 和 active generation。
- [x] 实现视觉 `get_chunk` 回读，使 `_validate_visual_chunk` 可逐字段校验存储内容和当前文档版本。
- [x] 先确定有效页面集合，再按现有策略选择 candidate k；计数不包含其他 generation。
- [x] 仅读取候选完整 token BLOB 做 MaxSim；避免全库常驻完整多向量。
- [x] 保留 prefetch 关闭的全量路径与 prefetch 失败的全量回退。
- [x] `search_full_maxsim` 接受相同范围和 active map，作为稳定 oracle。
- [x] `fixed_prefetch_store(k)` 共享 repository，使用只读配置视图；不重复持锁或关闭父 repository。
- [x] 输出方案第 7.5 节的元数据，特别保持 full-scan reduction=0。
- [x] 视觉失败时由现有服务记录并退回文本结果。

### 测试与验收

- VR-01：固定候选已含 oracle top-k 时，候选评分与全量结果一致。
- VR-02：prefetch disabled 对全部有效页面评分；能命中 pooled score 较低的相关页面。
- VR-03：候选召回失败，fallback true 全量评分；false 明确抛错。
- VR-04：空范围/map、不允许的文档、旧 generation/index version 都不被读入评分。
- VR-05：重新写入同版本、写入新版本、删除、重启后的数据身份一致。
- VR-06：视觉批次中途失败，旧完整批次仍可查询。
- VR-07：页面/查询 token 负值、长度不同和 padding 得分正确。
- VR-08：自适应 k 使用有效 collection 数，不用含旧版本的全库计数。
- VR-09：完整视觉向量只读候选，记录读取数量；all-scan 模式按页面流式读取。
- VR-10：图像资产和页面定位保持原值，缺失资产不能产生错误引用。
- VR-11：共享基准视图关闭不破坏生产/父视图；cache revision 更新正确。
- VR-12：`visual_score`/模式/reduction/错误字段保持可观测。
- VR-13：视觉 `get_chunk` 能读指定版本；默认 legacy 和当前 index version 约束生效，引用校验能发现缺失/篡改源数据。

验收：合成向量实现全量与两阶段路径；真实视觉召回质量留在 T12 正式评估，不把协议测试当质量评估。

## 10. T07：运行时和配置接入

### 涉及文件

`backend/api/knowledge_dependencies.py`、`backend/rag/config.py`、`config/default.toml`、`stores/__init__.py`、`visual_retrieval.py`、`visual_adaptive.py`；必要的 Settings/Knowledge 状态代码及测试。

### 实施步骤

- [ ] `RagRuntime.vector_store` 改为 `VectorStore`，视觉类型改为新 Protocol。
- [ ] 删除 `shared_qdrant_client` 与创建分支，按解析后的路径复用一个或多个 repository。
- [ ] 工厂创建 FAISS adapter；最终只支持新 provider，旧配置通过迁移状态处理。
- [ ] `VisualIndexCoordinator` 去掉 Qdrant 类型判断，统一传 generation/content hash。
- [ ] 保留 `ProcessInferenceProvider`、模型 manager、视觉 model provider 和融合 service。
- [ ] 文本和视觉路径各自解析；默认同目录共享 repository，自定义不同目录独立管理。
- [ ] 默认 provider/path 改为 faiss；visual model provider 保持 `colpali_engine`。
- [ ] 旧 url/timeout/on_disk 字段的兼容解析与弃用行为明确定义；不创建旧远程连接。
- [ ] 未完成数据导入时不能自动把旧设置改成空库 faiss；提供可读的迁移状态/错误。
- [ ] 不再读取旧 Qdrant 环境变量来影响生产搜索；保留原视觉开关。
- [ ] close 顺序明确：先停止使用方，再关闭 provider/adapter/repository，每个资源只由所有者关闭一次。
- [ ] Knowledge runtime provider 展示为 `faiss`；API 字段保持兼容。

### 验收

更新 `test_config.py`、`test_knowledge_dependencies.py`、`test_knowledge_api.py`、`test_visual_retrieval.py`、`test_offline_runtime.py`。

必须测试：视觉关闭、启用、独立路径、共享路径、连续关闭、重开、无模型懒加载、旧配置未迁移、迁移完成配置、默认/自定义 BM25/manifest 父目录。

源码正常运行使用 FAISS；业务接口无无关变化，视觉关闭时不加载 colpali 模型。

## 11. T08：审计、基准与 Debug Studio

### 涉及文件

- `backend/rag/index_audit.py`、`tests/rag/test_index_audit.py`。
- `backend/rag/benchmarks/runtime.py`、`tests/rag/benchmarks/test_runtime.py`。
- `backend/evaluation/visual_retrieval_benchmark.py`、`scripts/benchmark_visual_retrieval.py`。
- `scripts/run_hf_rag_benchmark.py`、`scripts/run_pdf_rag_benchmark.py`。
- `backend/services/rag_debug_service.py`、`rag_debug_store_service.py` 和读取报告字段的 UI/脚本。

### 实施步骤

- [ ] 用公开只读枚举替代 `_client.scroll`，删除 Qdrant 私有数据布局依赖。
- [ ] 报告 store key 改为 `vector`，同步所有消费者；历史报告不重写。
- [ ] 对 manifest/BM25/vector 的 document/generation/chunk 集合保持精确审计。
- [ ] 给视觉增加独立的 hash/version/asset 目录检查；不要求视觉 item 等于文本 chunk。
- [ ] 基准 runtime 通过同一工厂创建 FAISS，不读取生产 settings 单例。
- [ ] 路径隔离检查同时排除新生产 faiss 和旧 qdrant 备份根，避免 benchmark 改写真实数据。
- [ ] 更新 HF 代码指纹、PDF 存储目录和数量核对。
- [ ] 视觉 benchmark 依赖能力 Protocol，oracle 与各模式使用同一 scope/generation。
- [ ] CLI 将 `runtime.manifest.list_active_generations()` 的冻结 map 传给 benchmark runner；每个 case 求文档范围交集，全量 oracle/预取/计数共享它。
- [ ] 保留 stage timing、候选 reduction 和错误字段；新增过滤、构建、读取、MaxSim 细分时长。

### 验收

缺失/损坏/版本冲突数据能被报告；审计不能创建 collection 或修复数据。基准输出带 commit、config、store schema、corpus digest 和模型 fingerprint。

已有文本/视觉 benchmark 入口可运行，Debug Studio 正常展示 provider 与一致性报告，不依赖旧 class 名。

## 12. T09：导出和导入工具

### 涉及文件

新增 `scripts/migration/export_qdrant_vectors.py`、`import_faiss_vectors.py`、`requirements-legacy-export.txt`、包格式说明；新增 `tests/rag/test_faiss_migration.py`。

### 迁移包契约

| 文件 | 必要内容 |
| --- | --- |
| `migration-metadata.json` | format version、来源 commit/client version、collection schema、dtype、模型 fingerprint、导出状态和数量 |
| `text-chunks.jsonl` | row_index、chunk 完整 JSON、规范化 generation 与 source point 身份 |
| `text-vectors.npy` | 与 row_index 对齐的二维 float32；`allow_pickle=False` |
| `visual-items.jsonl` | visual item 身份、document/generation/index version/hash、完整 chunk、published 状态 |
| `visual-vectors.bin` | 连续 little-endian float32，可变长度 token 矩阵 |
| `visual-offsets.jsonl` | row_index、byte offset、token_count、dimension、长度和 checksum |
| manifest/BM25/资产索引 | 原文档状态、稀疏索引、图片 locator 与 hash |
| `asset-path-map.json` | 原 asset URI、包内相对位置、目标 URI、checksum；覆盖文本多模态与原生视觉 |
| `graph.sqlite3`（可选） | 已启用 Graph 的稳定备份及版本信息 |
| `checksums.json` | 每个文件长度与 SHA-256；包总 digest |
| `migration-report.json` | 已迁移/未迁移数量、文档清单、错误、对比和状态 |

### 实施步骤

- [ ] 导出器仅在旧环境运行，Local 模式要求旧应用停止；远程模式也须冻结一致快照。
- [ ] 导出器通过客户端公共 scroll 取 payload 和 vector，禁止直接读其私有 SQLite 表。
- [ ] 支持文本、旧视觉单 multivector、现有 coarse/late named vector schema。
- [ ] 按旧解码规则处理顶层存储字段，generation 回填 metadata 后校验完整 `DocumentChunk`，不直接把原始 payload 当业务模型。
- [ ] 核对 `AITRANS_RAG_ASSET_DIR`、工作目录和所有 `metadata.asset_uri`，收集实际资产路径而非假定固定目录。
- [ ] 搬迁资产时生成路径映射并同步修改 SQLite/BM25 的 asset URI，校验图片 bytes/hash；原文 source URI 不随索引根搬迁而自动改写。
- [ ] 迁移 Graph 稳定备份；原文件也移动时改用强制重建与身份映射，记录证据缓存失效。
- [ ] 大语料流式导出到 `.partial`，成功后封存 checksums 与 complete 状态。
- [ ] 导入器不 import Qdrant，只接受支持版本、完整校验通过的包。
- [ ] 所有数据导入独立 staging；保留唯一键、generation、SourceSpan；不依赖旧 point UUID 作为 FAISS ID。
- [ ] 无效 payload、generation 冲突、缺向量、token length/index version/hash 不一致必须报告，不静默跳过。
- [ ] 缺/过期视觉 item 标为需重建；旧 collection 不存在时保留原视觉关闭状态。
- [ ] 幂等 checkpoint 包含包 digest、已提交批次、目标 store UUID；跨包恢复拒绝。
- [ ] resume 时检查实际 DB 和 checkpoint，以唯一键消除 crash 后重复批次，不重复增加数据。
- [ ] 严格校验最终文档/generation/chunk 集合、向量与 asset；只有通过后标记 validated。
- [ ] importer/切换工具与 sidecar 使用相同所有权锁，禁止在线覆盖目标库。
- [ ] 实现从原文重建的独立 staging 路线和无法重建的文档清单。
- [ ] 迁移工具不会进入冻结应用；不把 API key、完整凭据写入 report。

### CLI 约定

以下为需要开发的接口，不是当前已存在的命令。所有显式路径以用户实际存储根为准。

```powershell
# 旧环境：仅在旧应用停止后导出；server 模式另用已记录的安全连接参数。
python scripts/migration/export_qdrant_vectors.py --source-root "D:\isolated\old-rag" --output "D:\isolated\migration-package"

# 新环境：只校验包，不创建或修改目标。
python scripts/migration/import_faiss_vectors.py --package "D:\isolated\migration-package" --validate-only

# 导入到隔离 staging，可续传；不自动改写当前生产配置。
python scripts/migration/import_faiss_vectors.py --package "D:\isolated\migration-package" --target-root "D:\isolated\new-rag-staging" --resume

# 验证导入目录，生成可读报告。
python scripts/migration/import_faiss_vectors.py --package "D:\isolated\migration-package" --target-root "D:\isolated\new-rag-staging" --verify-only
```

`--resume` 在无 checkpoint 时开始新导入；目标非空且 digest 不一致必须失败。`--validate-only/--verify-only` 只读，不触发索引创建。独立迁移 README 写明参数、路径、退出码、old/server 区别和配置切换步骤。

导出器参数须覆盖以下实际接入方式：

| 参数 | 契约 |
| --- | --- |
| `--source-root` | 旧 RAG 状态根，读取 manifest/BM25/Graph；不能仅凭它推断所有外部资产 |
| `--qdrant-path` | Local 向量目录；未给时使用 source root 下的 qdrant 子目录，支持显式自定义路径 |
| `--source-url` | 远程 Qdrant；与 Local path 模式互斥，source root 仍提供同一冻结版本的文档状态 |
| `--api-key-env` | 指定读取密钥的环境变量名称，禁止在命令行直接传密钥或写入输出 |
| `--text-collection`、`--visual-collection` | 来源 collection 名称；默认从已记录配置读取，视觉可不存在 |
| `--config-snapshot` | 脱敏的旧配置快照，用于模型/度量/开关/fingerprint 核对 |
| `--output` | 新迁移包目录；非空且不同导出批次时拒绝覆盖 |

metadata 必须区分 Local/Server 模式和冻结时点；远程导出缺少配套 manifest/BM25 的一致版本时不能标记完整迁移包。

### 测试与验收

- MG-01：纯中立 fixture 的 text+visual 导入、读取、重启和查询通过。
- MG-02：中断在 batch commit 前/后、checkpoint 保存前/后，resume 无遗漏或重复。
- MG-03：损坏 checksum、截断 BLOB、offset 越界、schema 未知和错模型明确失败。
- MG-04：两个包混用、非空目标冲突和正在使用的目标不能被覆盖。
- MG-05：旧 legacy 与多 generation 数据全部按身份核对。
- MG-06：无视觉数据、单多向量视觉、named vectors 两阶段视觉均处理正确。
- MG-07：READY manifest 指向缺数据、资产缺失和 hash 冲突能发现。
- MG-08：正式旧环境运行一次真实导出，再在无 Qdrant 新环境导入；输出迁移报告。
- MG-09：搬迁图片根后文本/视觉/BM25 的 asset URI 一致；原文路径保持或明确重建，引用打开仍正确。
- MG-10：Local 自定义路径/远程模式与状态根一致性核对正确；没有凭据进入参数日志或 report。

常规自动化测试使用中立 fixture，不因 MG-08 把旧客户端引入新运行时测试依赖。

## 13. T10：复用检查、故障恢复与回滚

### 涉及文件

`backend/rag/index_service.py`、`index_manifest.py`（只在必要时增加恢复检查）、新 repository/adapter；新增 `tests/rag/test_faiss_recovery.py`；更新 `test_knowledge_generation_lifecycle.py`。

### 实施步骤

- [ ] 在 `_can_reuse` 或紧邻复用分支验证 vector 和 BM25 的目标 generation chunk 集合。
- [ ] 保留 begin/write/validate/publish 顺序，禁止提前发布或删除旧 READY generation。
- [ ] 写入失败仅清理失败的新版本，旧版本可继续查询。
- [ ] 重启先恢复中断 manifest，再检查 READY 数据存在性；完整审计保持独立只读。
- [ ] 缓存从 durable SQLite 重建；错误不能退回旧 cache 伪造新数据。
- [ ] 保留退休版本，第一版不做运行中自动 GC。
- [ ] 删除失败提供错误与重新执行路径，引用校验阻断已缺失的 source chunk。
- [ ] 编写停止应用、backup/checkpoint、路径切换与回滚步骤。
- [ ] 演练恢复旧应用+旧向量+旧 BM25+旧 manifest+资产/graph 的完整数据集合。
- [ ] 定义试运行写入冻结或修改记录重放；回滚后的新增文档损失必须明确记录。

### 故障矩阵

| ID | 注入点 | 预期 |
| --- | --- | --- |
| RC-01 | SQLite 提交前终止 | 无部分批次，旧 generation 正常 |
| RC-02 | SQLite 提交后、BM25 前终止 | 新 generation 不可作为 active 返回 |
| RC-03 | BM25 完成、manifest publish 前终止 | 新版本未发布，重启状态明确 |
| RC-04 | publish 后、cache build 前终止 | 重启重建，查询新版本正确 |
| RC-05 | 文本发布后、视觉写入前失败 | 文本可用；视觉记录降级 |
| RC-06 | 空 SQLite + 旧 READY manifest | 导入提示或重建，不能跳过索引 |
| RC-07 | 仅向量/BM25 一方缺 chunk | 精确集合检查失败，不能复用 |
| RC-08 | 删除中断、cache build 失败 | 报告不一致/错误，不返回已删除旧 cache |
| RC-09 | 数据新建后回滚旧快照 | 写入冻结或操作重放结果可追踪 |

验收：上述矩阵和端到端旧版本保留验证通过。仅修改错误文案不算完成此任务。

## 14. T11：清除生产依赖与桌面打包

### 涉及文件

- 删除/替换 `backend/rag/stores/qdrant.py` 及视觉具体 Qdrant 类。
- `pyproject.toml`、`aitranslator-rag-requirements.txt`、视觉 requirements。
- `backend/sidecar.py`、`aitrans_backend.spec`。
- `scripts/build_rag_backend.ps1`、`apps/desktop/scripts/build-backend-sidecar.mjs`。
- `apps/desktop/scripts/archive-sidecar-licenses.py` 的许可证检查。
- 全部常规测试中的 Qdrant import/fixtures/provider 文案。

### 实施步骤

- [ ] 锁定 T01 验证过的 FAISS/NumPy 组合，移除核心和默认 RAG 中的 `qdrant-client`。
- [ ] 视觉模块保留模型/业务服务，去除直接 Qdrant import 和继承。
- [ ] `test_qdrant_store.py` 中有价值的行为迁入 FAISS 测试；内部 filter 对象测试改为行为断言。
- [ ] 更新 agent、多 agent fixture、API 与 UI 测试中的旧 provider/path；不批量改写历史报告。
- [ ] 新增 `test_no_qdrant_runtime.py`：无旧包环境创建应用和 runtime、执行文本检索与合成视觉检索。
- [ ] PyInstaller 收集 FAISS 扩展与 DLL；只保留实际需要的收集，不引入整个 Conda 安装目录。
- [ ] sidecar smoke test 使用临时目录执行 add/search、SQLite 重开和 MaxSim，不触碰用户数据或下载模型。
- [ ] 两套脚本的预检查和打包结果一致；保留模型权重外置约束。
- [ ] license 输出含实际 FAISS/BLAS/OpenMP 分发所需信息；生产包不含旧导出工具/客户端。
- [ ] 在无 Python/Conda 的 Windows x64 干净环境离线运行冻结程序。
- [ ] 单独说明默认包与视觉依赖增强环境的覆盖范围，不把合成评分 smoke 当模型推理 smoke。

### 验收

PK-01：源码无生产 Qdrant import、client、继承或 provider 分支。  
PK-02：干净依赖安装中不存在 `qdrant-client`，普通测试可运行。  
PK-03：两套 sidecar 构建成功，冻结 add/search/重开/评分成功。  
PK-04：冻结包运行不依赖构建机器 PATH 的 DLL 或外部 Python。  
PK-05：默认离线模式不下载模型、不打包权重、不包含迁移工具。  
PK-06：视觉增强环境在 T12 完成真实模型加载/查询验证。

旧导出工具依赖清单只留在 `scripts/migration/`，在静态检查中作为唯一明确例外。回滚运行旧版本，不恢复新代码的 Qdrant provider。

## 15. T12：完整回归、质量和性能验收

### 测试层级

| 层级 | 必须验证 |
| --- | --- |
| 纯算法 | 四度量、cosine/dot、MaxSim/padding/分块、稳定排序 |
| 存储 | 事务、ID、幂等、重启、只读审计、所有权锁 |
| 契约 | 所有过滤、legacy/active generation、读取/删除默认语义 |
| 服务 | index/reindex/delete、检索融合、引用检查、证据缓存失效 |
| API/Agent | Knowledge、JIT、Research、workspace 范围和跨轮 evidence cache |
| 视觉模型 | 实际页面编码、两阶段检索、文本降级、图片定位 |
| 迁移 | 导出/导入/resume/verify、真实库对应和回滚 |
| 桌面 | 打包离线启动、导入、查询、打开引用、重建、删除和重启 |

### 实施步骤

- [ ] 运行所有相关纯 CPU 测试，记录 failed/skipped 与原因。
- [ ] 旧/新同一固定向量、同一配置、同一有效 scope/generation 做集合和分数比较。
- [ ] 全量视觉 oracle 比较同一范围；报告粗召回覆盖率，而非只比较最后一条答案。
- [ ] 真实问题按图表/公式/扫描页/正文混排、中英查询及跨文档分别报告。
- [ ] 保留模型加载耗时分离，warmup 后测存储阶段与端到端延迟；记录冷启动。
- [ ] 覆盖 10k/50k/100k 文本和 100/1k/10k 页性能规模，按目标设备实际容量执行。
- [ ] 覆盖空范围、单文档窄范围、多文档、active map、写入后首次搜索和全量回退。
- [ ] 测 peak RSS、子索引构建副本、候选 BLOB I/O、MaxSim 和并发排队，不只看 FAISS search。
- [ ] 根据方案第 10.3 节判定质量/性能；门槛未达到则修复或明确阻断，不修改 gold 来“过线”。
- [ ] 验证前端 runtime 展示、文档列表、导入状态、引用打开与 Debug trace。

### 建议测试命令

下面的存储/迁移文件现已创建，相关命令已在本机运行；具体版本、数量和失败归因见验收报告。命令仍作为复验入口。

```powershell
# 新增存储、算法、迁移和恢复测试。
python -m pytest tests/rag/test_local_vector_repository.py tests/rag/test_faiss_store.py tests/rag/test_visual_scoring.py tests/rag/test_faiss_visual_store.py tests/rag/test_faiss_migration.py tests/rag/test_faiss_recovery.py tests/rag/test_no_qdrant_runtime.py

# 已有接口与版本契约，完成适配后运行。
python -m pytest tests/rag/test_config.py tests/rag/test_vector_store_contract.py tests/rag/test_vector_scope.py tests/rag/test_generation_retrieval.py tests/rag/test_index_audit.py tests/rag/test_knowledge_dependencies.py tests/rag/test_knowledge_api.py tests/rag/test_knowledge_generation_lifecycle.py tests/rag/test_visual_retrieval.py tests/rag/test_visual_prefetch.py tests/rag/test_visual_adaptive.py tests/rag/test_visual_retrieval_benchmark.py tests/rag/test_offline_runtime.py tests/rag/benchmarks/test_runtime.py

# 最终相关后端回归；真实模型测试单独安排。
python -m pytest tests/rag tests/agent tests/multi_agent -m "not rag_gpu"

# Windows sidecar 构建入口之一。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_rag_backend.ps1
```

桌面目录执行：

```powershell
npm test
npm run build
npm run backend:package
```

执行目录为 `apps/desktop`。两套构建入口均需通过；如沿用既有 lint/release 检查规则，同步运行其必需检查。其他已存在的失败需记录和归因，不能以全量套件有旧失败为理由跳过受影响测试。

真实模型验收：运行已有 `rag_gpu` 测试及实际 `scripts/benchmark_visual_retrieval.py` 入口。先检查目标模型、可用内存与视觉依赖；若硬件不足，保留未完成状态。只有合成 CPU 测试通过时，不标记整个 T12 完成。

### 交付物与验收

交付测试报告、固定向量 diff、真实视觉 quality report、端到端 report、规模与延迟/RSS report、桌面截图或日志，以及未通过项清单。报告记录 commit/config/corpus digest/模型版本与硬件。

判定必须同时满足：正确性零违规、分数容差、真实质量门槛、T00 性能预算和干净打包。性能更快不能抵消范围泄漏或引用错位。

## 16. T13：实际切换与交接

### 切换步骤

- [ ] 核对实际数据根、旧应用版本、配置和所有写入任务已停止。
- [ ] 保存完整旧数据快照并验证可恢复，不只备份向量 collection。
- [ ] 实际导出、导入 staging、resume/verify；未迁移文档必须列明并处理。
- [ ] 对真实库执行文档/generation/chunk、视觉/asset 审计和抽样搜索/引用定位。
- [ ] staging 连接关闭并 checkpoint 后，按绝对路径校验执行目录切换。
- [ ] 更新用户 provider/path 配置及迁移标记，保持模型/功能开关。
- [ ] 新 sidecar 启动，完成导入、查询、原文定位、重建、删除与重启 smoke。
- [ ] 试运行按冻结写入策略执行，保存需要重放的修改记录。
- [ ] 将备份位置、旧版本位置、恢复步骤、报告和剩余限制交接给维护者。
- [ ] 仅在约定保留期结束且用户数据验收通过后另行清理旧备份；本任务不自动删除旧库。

### 完成标准

文本与视觉迁移全部通过 T12；实际库审计通过；目标设备打包运行通过；回滚演练已完成；最终运行不使用 Qdrant；所有交付物可追溯。

没有旧视觉索引的用户库可以报告“无视觉数据需要搬迁”，但启用视觉功能的实际编码/检索能力仍需验收。没有真实视觉模型验证时，发布状态为“文本已完成，视觉验收待完成”，不得写成完整迁移完成。

## 17. 必须修改的文件核对表

路径均为仓库相对路径，根目录 `D:\AITrans`；本表用于实施时检查范围，不要求对无行为依赖的历史文件做批量重命名。

| 分组 | 文件 |
| --- | --- |
| 配置 | `backend/rag/config.py`、`config/default.toml` |
| 文本存储 | 新 `stores/local_repository.py`、`stores/faiss.py`；`stores/__init__.py`；删除生产 `stores/qdrant.py` |
| 视觉 | 新 `stores/visual_base.py`、`stores/faiss_visual.py`、`visual_scoring.py`；`visual_retrieval.py`、`visual_prefetch.py`、`visual_adaptive.py` |
| 运行时 | `backend/api/knowledge_dependencies.py`；必要的 `backend/rag/__init__.py` 导出 |
| 索引与审计 | `index_service.py`、`index_audit.py`；`index_manifest.py` 只作必要调整 |
| 评测 | `backend/rag/benchmarks/runtime.py`、`backend/evaluation/visual_retrieval_benchmark.py`、三个相关 benchmark scripts |
| 迁移 | 新 `scripts/migration/` 工具、旧工具 requirements 和说明 |
| 发布 | `pyproject.toml`、RAG requirements、`aitrans_backend.spec`、`backend/sidecar.py`、两套 sidecar build scripts |
| 后端测试 | `tests/rag/` 受影响测试；`tests/agent/test_agent_knowledge_search_read.py`；`tests/multi_agent/conftest.py` 与范围/缓存测试 |
| 桌面测试 | `apps/desktop/src/api/rag-contracts.test.ts`、Knowledge/Companion runtime 测试 |
| 文案 | `backend/rag/models.py`、`backend/api/agent_dependencies.py` 等生产注释和错误名称中的旧存储假设 |

实施时再次用 `rg` 检查遗漏；参考文献中提到 Qdrant、历史输出和 migration 工具不按生产依赖处理。

## 18. Definition of Done

- [ ] T00–T13 的必需交付物与验收全部完成。
- [ ] 正常运行、依赖安装、普通测试及冻结包均不依赖 Qdrant。
- [ ] 文本四度量、CRUD、范围、reference、generation 契约完整通过。
- [ ] 视觉池化召回、MaxSim、全量 oracle、回退、模型和融合完整通过。
- [ ] 旧数据导出/导入、重建备选、中断恢复和回滚均有可执行工具或流程。
- [ ] 文档身份、版本、SourceSpan、图片资产和原文引用定位通过真实数据校验。
- [ ] 无空库 READY 假复用、无全库 top-k 后过滤造成的范围漏召回。
- [ ] 审计只读；基准隔离；性能、冷启动、内存与质量均有报告。
- [ ] Windows x64 干净环境和两套构建入口均通过。
- [ ] 实际切换记录、备份、操作重放和维护交接完整。
- [ ] 当前方案/任务书中的待定版本、硬件预算和未完成状态更新为实测结果。

## 19. 后续优化独立立项

仅在上述完整迁移完成且实测瓶颈明确后考虑：磁盘 FAISS 可丢弃缓存、过滤子索引 LRU、读写锁/不可变快照并发、HNSW/IVF/PQ、GPU FAISS、PyTorch MaxSim、token 压缩及退休 generation GC。

这些优化不能作为第一版迁移的隐含前提；若第一版性能门槛未过，应选最小必要优化并补充本任务书的验收，不能直接宣布完成后把问题全部留给后续。
