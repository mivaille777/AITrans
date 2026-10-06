# AITrans FAISS 迁移实施与真实验收报告

执行日期：2026-10-05，Windows x64，工作区 `D:\AITrans`。迁移前源码基线 `af8c4d6db4a6d23d5683dce97e851b025c525aaf`；交付为当前未提交工作区。

**结论：本机源码、真实用户数据和 Windows sidecar 已切换为 FAISS；真实文本、原生视觉及应用运行时生命周期验收通过。完整发布门槛仍有未验项目，见最后一节。** 没有把源码测试、PATH 隔离或四页视觉样本当作干净机器和大型真实质量评测。

配套：[迁移方案](faiss-migration-plan.md)、[任务书](faiss-migration-taskbook.md)、[迁移/回滚运行说明](../../scripts/migration/README.md)。原始日志和含真实文档的中间产物只留在忽略目录 `test-results/faiss-migration/`，不提交用户原文、向量或配置凭据。

第 1–8 节保留最初 CPU 迁移验收记录；用户随后追加 GPU 优先要求，最新环境与新增验证见第 9 节。此前 CPU 1.15.1 的结果不能当作 GPU 1.9.0 的结果。

## 1. 实际环境与安装

使用的是用户的 `aitrans` 环境，未用默认 base Python 替代验收：

`C:\Users\mivaille\anaconda3\envs\aitrans\python.exe`

| 项目 | 实测版本/设备 |
| --- | --- |
| Python | 3.11.7 |
| 新安装 | faiss-cpu 1.15.1、tomlkit 0.15.1 |
| NumPy | 2.4.6，沿用已有版本 |
| PyTorch | 2.13.0+cu130，CUDA 可用 |
| sentence-transformers / transformers | 5.7.0 / 5.15.0 |
| colpali-engine / bitsandbytes | 0.3.18 / 0.50.2 |
| PyMuPDF / PyInstaller | 1.28.2 / 6.22.2 |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU，8 GB |

`pip check` 通过。安装前后 freeze 清单为 `aitrans-before.txt/aitrans-after.txt`。没有同时升级模型、解析、reranker 或 CUDA 依赖。

视觉验收使用实际 ColQwen 基础模型和 multilingual adapter，NF4、bf16、256 image tokens。新增验收缓存位于 D 盘；应用运行时另使用用户原有的模型配置和缓存。本次实际配置中视觉已开启，切换保留该开关及模型参数。

## 2. 最终实现

| 边界 | 实现 |
| --- | --- |
| 文本 | `FaissVectorStore`，FlatIP/FlatL2/L1、稳定数字 ID、四度量、完整原 `VectorStore` 契约 |
| 视觉 | `FaissVisualMultiVectorStore`，池化 FAISS 召回、候选 token BLOB 回读、NumPy 分块 MaxSim、全量 oracle/失败回退 |
| 持久化 | SQLite schema v1，WAL、FULL synchronous、事务、revision、单路径写入所有权、backup |
| 范围与版本 | 搜索前文档/metadata/reference/active generation 相交，空范围/空 map 返回空 |
| 证据 | 原 SourceSpan、page/bbox、源文件/图片 hash 和 publication 校验继续使用 |
| 运行时 | 工厂和公共协议、文本/视觉共享 repository、原 ProcessInferenceProvider/模型 manager/服务生命周期 |
| 防止空库复用 | 复用和启动均核对 READY 的 dense/BM25 精确 chunk 集合；未完成迁移拒绝启动 |
| 一次性迁移 | 旧环境导出、中立校验、导入、同 digest 幂等 resume、只读 verify、旧完整快照 |
| 发布 | 移除生产 Qdrant import/provider/依赖，收集 FAISS DLL、许可证、真实运算 smoke |

保持 BM25、manifest、Graph、解析/分块、Embedding、reranker、RRF、Agent/Research 和 Knowledge API 的原业务边界。

为控制幅度，SQLite v1 的 dtype 固定为 little-endian float32，归一化由 collection kind/distance 决定，没有增加重复 dtype/normalization 字段；hash 保存在完整 chunk JSON。交换格式采用带 SHA-256 的 `vectors.jsonl`，未同时实现 `.npy/.bin` 两套交换格式。运行时继续共享文本/视觉目录；这些是方案的具体实现选择。

导出器将旧视觉 schema 后缀 `_2stage_mv<dim>_<distance>` / `_mv<dim>_<distance>` 映射到新逻辑 collection，保留 `source_name`；避免导入成功后新运行时看不到视觉数据。并存旧变体或多视觉 index version 必须明确选择，不能悄悄合并不兼容空间。

## 3. 实际数据切换

| 项目 | 结果 |
| --- | --- |
| 原库 | `D:\AITrans\config\rag\qdrant`，完整保留 |
| 新库 | `D:\AITrans\config\rag\faiss\vector_store.sqlite3` |
| 文本数据 | `aitrans_knowledge`，1024 维 cosine，1,328 条全部导入与核对 |
| 已发布文档 | 3 个 READY 文档，active dense/BM25 与 manifest 精确集合一致 |
| 原生视觉数据 | 原始导出无视觉 collection，无旧视觉数据需要搬迁 |
| 原文 | 3 份原始 PDF 路径存在且内容 hash 一致 |
| 引用/资产 | 747 个 SourceSpan quote hash、62 个图片资产检查通过 |
| 配置 | 仅切换 vector provider/path，保留模型、解析和原视觉开关 |
| 用户查询 | 当前实际 runtime 混合检索，dense 30、最终 8 条，embedding/reranker 无降级，证据验证通过 |

迁移包：`test-results/faiss-migration/real-export-v2`；已验证 staging：`real-staging`。迁移 ledger 状态为 `verified`；最终生产库以最新版导入器再次只读 verify 通过。

完整回滚数据在 `real-export-v2/rollback`，包含向量、BM25、manifest、Graph、资产、页面和另存的原用户配置。旧源码为 `rollback-source.zip`。已有空 FAISS 目录也另存为 `empty-pre-cutover-faiss`，没有覆盖或删除旧数据。

**历史审计例外：** 全版本审计仍为 `divergent`，manifest 记录 782 个 chunk，BM25/vector 各 1,328 个，包含既有 legacy/历史残留。恢复的旧库和新库输出的完整审计报告相等（`audit-baseline-equality.json`）；本次保留这些数据，没有为让审计变绿而删除历史记录。当前 READY 的精确集合和实际检索校验通过。

## 4. 正确性和回归

| 验收 | 实测结果 | 证据 |
| --- | --- | --- |
| 旧行为冻结 | 63 项旧存储/视觉测试通过，独立四度量 gold 保留 | `baseline/pytest.xml`、版本化 `tests/rag/fixtures/faiss-gold.json` |
| 后端相关回归 | 1,582 passed、6 failed、2 skipped、2 deselected | 相关全量测试日志/JUnit |
| 迁移后受影响集合 | 63 passed | `final-affected.xml` |
| 最终存储/恢复/运行时守卫 | 49 passed，含稳定视觉 ID 和 READY 空库拒绝 | `final-storage.xml` |
| 最终迁移工具 | 8 passed，含多向量格式、旧视觉名称映射、只读 preflight、commit 后中断 resume | `final-migration.xml` |
| 实际 CUDA embedding/reranker | 2 passed | `real-models.xml` |
| 前端 | 109 文件、467 tests passed，test typecheck 通过 | npm test 日志 |
| 前端构建 | TypeScript/Vite 与离线 PDF guard 通过 | npm run build 日志 |
| 无 Qdrant 运行时 | 禁止旧包 import 的独立进程创建真实应用并执行文本/合成视觉 | `test_no_qdrant_runtime.py` |

全量的 6 项失败在迁移前源码、同一个 `aitrans` 环境中复现：2 项 `test_agent_knowledge_tools.py` 的工具注册/参数测试，4 项 `test_root_graph_factory_parity.py` 的图工厂测试。旧源码重放为 6 failed、2 passed，见 `test-results/old-agent-baseline.xml`。未将它们改为 skip 或顺手修改无关 Agent 行为。

两个跳过分别涉及 opt-in Docling 场景和不可用 Docker；两个 GPU 测试排除后另行执行通过。相关套件不是“全绿”，发布应保留上述旧失败记录。

24 组固定向量对照（12 个向量 × 全 active/单文档）Top-10 集合均一致，最大误差 `1.31763e-7`。另做每种范围 100 个性能采样：非并列 Top-10 集合一致，最大分数误差 `2.38419e-7`；3 个边界近似并列案例选择的 ID 可以不同，等分候选及有序分数通过容差检查，新库使用确定性排序。

## 5. 真实文本与视觉链路

真实文本生命周期在 `real-text-lifecycle-v2/report.json`：真实 Qwen embedding + reranker，英文/中文混合检索和引用通过；索引、相同文件复用、强制重建、新 generation、保留退休 generation、重开和删除均通过。

真实视觉在 `real-visual-service/report.json`：独立生成的 4 页 PDF 包含折线图、柱状图、质能公式和翻译流程正文；真实页面编码产生每页 `236 × 128` token 矩阵。6 个独立中英文问题，adaptive k=2、fixed k=2 和 fixed k=4 的 Recall@1/MRR 均为 1.0；k=2 将 MaxSim 页面数减少 50%。模型加载及四页编码合计约 31.2 秒，CUDA peak allocated 4,362,151,424 字节。独立 float32 MaxSim oracle、空 active map、关闭重开、实际 RRF/引用验证和篡改资产拒绝均通过。

用户当前配置的完整应用 runtime 在 `configured-runtime/report.json`：保留原模型、解析、视觉配置，仅把测试数据/资产根指向隔离目录。通过实际 `ProcessInferenceProvider` 处理 PDF，建立 4 页视觉索引；中文 `sparse-only+visual-rrf`、英文 `hybrid+visual-rrf`、引用、重新索引、关闭重启及删除均通过，没有视觉/embedding/reranker 降级。

旧视觉实现另用同一批真实 token、相同 active scope 和 k=2 重放 6 个问题，Top-1 与新库相同，MaxSim 分数通过容差。实际创建旧 named-vector collection，导出、导入并用新视觉 runtime 查到 4 页，验证旧后缀到新逻辑名的迁移映射；记录为 `real-visual-legacy-comparison-v3/report.json`。这补充了真实旧/新视觉对照，但样本量仍为 6。

这是小型真实能力验收，不能代表大型扫描页、复杂排版和跨文档数据集的质量指标。

## 6. 性能和内存

存储性能均使用实际 FAISS/SQLite/NumPy；不把模型推理计入下表。规模语料使用固定 seed 的合成向量。`storage-scale-isolated/report.json` 每项 warm/scoped 搜索 100 次；全量视觉扫描每规模 1 次。文本首次检索包含 SQLite 读取、解码和索引构建。

| 文本量，1024 维 | 首次检索 ms | warm P95 ms | 单文档 P95 ms |
| --- | ---: | ---: | ---: |
| 10,000 | 587 | 16.9 | 14.6 |
| 50,000 | 3,168 | 53.0 | 31.0 |
| 100,000 | 5,824 | 90.3 | 51.7 |

| 视觉页数，128 token × 128 维 | 首次检索 ms | 预取 + MaxSim P95 ms | 全量 MaxSim 单次 ms |
| --- | ---: | ---: | ---: |
| 100 | 16.0 | 10.8 | 50.5 |
| 1,000 | 144 | 73.9 | 510.5 |
| 10,000 | 916 | 156.8 | 5,132 |

进程 peak RSS 为 2,431,553,536 字节（约 2.26 GiB），包含重建期间的矩阵、旧/新索引及缓存副本；100k 文本 steady RSS 约 1.39 GiB。视觉阶段的进程 RSS 包括该进程先前文本分配，不能解读为视觉独立占用。写入后第一次查询重建开销可见；窄范围仍需遍历元数据，是当前 Flat 实现的可测瓶颈。

初次 5 样本规模测试及模型验收同时运行的 100 样本测试也保留，但最终报告使用模型工作进程退出后重跑的隔离规模结果。P95 小样本统计不能当作长期服务 SLO。

真实库新旧同向量对照，每范围 100 次，交替测量顺序：

| 范围 | 旧 Qdrant P95 ms | 新 FAISS P95 ms | 新/旧 |
| --- | ---: | ---: | ---: |
| 全 active | 81.86 | 10.69 | 0.131 |
| 单文档 | 51.39 | 9.53 | 0.186 |

上述真实库的存储性能通过方案建议的 1.2 倍门槛。没有预先冻结大型 corpus 的绝对性能预算，也没有宣称端到端 p95 和并发排队已完整比较。

## 7. Windows 发布与回滚

两套构建在 `aitrans` 环境通过：

- PowerShell：`scripts/build_rag_backend.ps1` → `dist/AITransBackend`。
- Node/Electron：`apps/desktop/scripts/build-backend-sidecar.mjs` → `build/electron-resources/backend/AITransBackend`。

冻结程序实际执行 add/search、SQLite reopen、MaxSim；最终 Node 包又在子进程 PATH 仅有 Windows/System32、Windows 且 Hugging Face offline 的环境下运行通过（退出 0，捕获实际 JSON）。FAISS 1.15.1 版本可识别，模型权重外置，许可证包含 FAISS、第三方 notices、NumPy 与实际分发项。生产代码/构建依赖无 Qdrant；打包明确排除旧客户端和迁移工具。

最终 Electron staging 中的 **冻结 exe 还启动了实际 HTTP 服务**：隔离用户目录、原模型及视觉设置、Hugging Face offline，Knowledge runtime 返回 `faiss_local`；PDF 导入返回 201，真实模型 Debug 检索返回视觉候选与证据，删除返回 200。`frozen-api/report.json`、`import-response.json`、`query-response.json` 和 `server.log` 留存。该验收禁用测试目录中的 query rewrite、`include_answer=false`，只验证本地 RAG，不调用外部答案服务；实际用户配置未改动。测试服务和其工作进程已停止。

PATH 隔离是在当前 Windows 上执行，**不等于无 Python/Conda 的干净 Windows VM**。没有自动安装或发布 Electron 安装包，也没有把 API 测试当作桌面 UI 手工验收。

隔离回滚演练在 `rollback-rehearsal-v3/report.json`：解压旧源码、恢复完整旧状态，真实查询返回 dense 30、hybrid、有效引用，无模型降级。旧应用 Local 回滚明确清除该进程的 `AITRANS_QDRANT_URL`。Graph 文件已恢复，本次查询未启用 Graph；生产新库未切回旧版本。

## 8. 尚未满足的完整发布门槛

以下为任务书剩余验收，不能标为完成：

1. 无 Python/Conda 的干净 Windows x64 VM/另一台机器上的离线包验收，以及完整桌面 UI 导入/打开引用操作。
2. 大型独立真实视觉质量集（扫描页、正文混排、跨文档；每类至少 100 个独立问题），同配置旧基线与端到端 nDCG/质量、延迟比较。
3. 大型 corpus 的预先冻结绝对时间/内存预算、并发锁排队与端到端 P95 统计。
4. 实际远程 Qdrant 服务与跨机器资产 URI 搬迁；当前本机 Local 切换及保持 URI 已通过。
5. 既有 6 项 Agent 回归失败的独立修复；历史无 publication 的索引残留如需清理，应另做备份与审核。

本次生产数据切换后，验收写入全部发生在隔离目录，没有新增/删除用户生产文档；无需重放测试写入。用户继续使用后发生的新增、重建、删除须在回滚前记录并重放。旧库和快照未清理。

## 9. GPU 优先追加实施与验收

2026-10-05 按用户追加要求，实际在同一个 `aitrans` 环境安装 conda-forge win-64 `faiss-gpu=1.9.0`、`faiss=1.9.0`、`libfaiss` CUDA 11.8 构建。GPU 包已包含 CPU 索引；先卸载同名模块冲突的 pip `faiss-cpu` wheel，没有同时安装两种发行包。

| 项目 | 最新实测状态 |
| --- | --- |
| FAISS | 1.9.0，GPU API 可用，1 个 CUDA 设备 |
| CUDA / GPU | FAISS CUDA Toolkit 11.8；RTX 4060 Laptop 8 GB |
| NumPy / OpenCV | 1.26.4 / 4.11.0.86；旧版本因 GPU ABI/NumPy 要求改为兼容组合 |
| BLAS | OpenBLAS 0.3.34；规避实测新 MKL 与现有模型环境 DLL 冲突 |
| Python / Torch / 模型 | Python 3.11.7、Torch 2.13.0+cu130、现有模型版本保留 |
| 安装完整性 | `pip check` 通过，重复安装脚本数值探针通过且保留已有 GPU 安装 |
| 环境路径 | Python 路径保留；`Library` 因 C 盘容量不足转到 `D:\PythonEnvironments\aitrans-library`，原路径使用 junction |

OpenBLAS 默认线程数会在多进程构建/模型验收中分配大量工作内存，首轮冻结构建因此失败；已在后端入口与打包脚本默认设置 `OPENBLAS_NUM_THREADS=1`，显式用户设置优先。原生 DLL 崩溃通过切换 OpenBLAS 修复，完整应用探针随后通过，不能把最初只导入 FAISS 的成功当成完整兼容验证。

设备策略集中在 `faiss_runtime.py`，文本和视觉粗召回共用。默认 `auto`，实际 GPU 创建/搜索成功才记录 `cuda`；无 GPU 编译 API/设备、初始化/OOM/搜索异常使用已有 CPU 索引。`cpu` 可强制 CPU，设备号默认为 0。64 MiB CUDA scratch 跨索引复用并串行保护。Manhattan、超出 GPU 2048 top-k 限制及大规模 tie 展开用 CPU，后续正常查询仍可回到 GPU。MaxSim 保留 NumPy。

新增验证：

- `gpu-device-tests.xml`：8 passed，包括真实 GPU 三度量、非连续 int64 ID、两个共享资源索引的多线程查询、超限 CPU 回退后重用 GPU；无 GPU 构建/设备、初始化/搜索异常回退用模拟故障覆盖。
- `gpu-final-affected.xml`：39 passed，覆盖四度量、范围、视觉、MaxSim、无 Qdrant 的应用探针。源码 sidecar 自动模式输出真实 `last_search_device=cuda`；强制 CPU 模式输出 `cpu_requested` 并完成真实运算。
- `gpu-full-tests.xml`：1593 passed、6 failed、2 skipped、5 deselected；6 项仍是第 4 节记录的原有 Agent 失败。额外 3 个 GPU 索引测试已独立运行通过。
- `gpu-runtime-live.json`：原 1328 条向量、3 个 READY 文档，真实 Qwen hybrid 查询 dense 30 / final 8、引用校验通过，FAISS 实际 CUDA，无文本或 reranker 降级。
- `gpu-real-visual/report.json`：真实 ColQwen 编码四页、每页 236×128 token，六个独立问题，adaptive/fixed 与 oracle、重开、融合和引用校验通过；FAISS 粗召回实际 CUDA，模型 CUDA peak 4,362,151,424 bytes。
- `gpu-configured-runtime/report.json`：原视觉/model 设置，真实进程推理，中文 sparse-only+visual-rrf、英文 hybrid+visual-rrf，文本和视觉查询实际 CUDA，重建/重开/删除通过；写入隔离目录。
- `gpu-real-vector-comparison.json`：1328 条原向量，全库与三单文档范围各 100 次 CPU/GPU 对照；共同 ID 分数最大误差 2.38419e-7。原始 Flat top-10 有边界同分选择差异，验证差异 ID 均在边界误差 1e-5 内；非边界结果集一致，不宣称全部原始 ID 数组逐位相同。这是索引数值检查，延迟观测不能替代端到端发布预算。

最初并行执行多个真实模型验收曾触发视觉模型显存不足；随后按单个完整运行时重测，生产真实文本查询和配置运行时均通过，无该模型降级。该结果不代表支持多个 ColQwen 模型同时占用此 8 GB GPU。

最新 Node/Electron GPU 构建与 staging 通过（`gpu-node-build-v3.log`），FAISS 1.9.0、CUDA 11.8 与 OpenBLAS DLL 已随 sidecar 收集，许可证 ZIP 包含 FAISS、CUDA Toolkit 和 OpenBLAS notices；模型仍外置。PowerShell 构建入口共用本次 spec，之前 CPU 构建已通过，本轮 GPU 未重复构建该入口。

冻结 exe 在 PATH 仅 Windows/System32、Windows，移除 Conda/Python 路径且 Hugging Face offline 的子进程中验证：自动模式实际 `cuda`；强制 CPU 实际 `cpu_requested`；额外设置 `CUDA_VISIBLE_DEVICES=-1` 后自动模式实际回退 `gpu_device_unavailable`，三种模式均完成 add/search、SQLite reopen、MaxSim，退出 0。记录在 `gpu-frozen-probe-report.json`、`gpu-frozen-path-auto.log`、`gpu-frozen-path-cpu.log`、`gpu-frozen-hidden.log`。

`gpu-frozen-api/report.json`：最新 Electron staging 的冻结 exe 实际启动 HTTP 服务，隔离用户目录、原模型/视觉设置、Hugging Face offline，PDF 导入、真实模型检索、视觉候选/证据及删除全部通过；服务和子进程已停止。测试不调用外部答案服务，不写生产库。

无 NVIDIA 驱动的干净 Windows、Python 3.12 和大型独立真实质量集仍属于未验范围。隐藏 GPU 的本机验证不能替代物理无驱动机器。

日志还包括 `gpu-install.log`、`gpu-openblas-install.log`、`gpu-source-smoke-v2.log`、`gpu-source-cpu-smoke-v2.log`、`gpu-installer-idempotent.log`，以及安装前/后 pip freeze 与 Conda explicit 清单。
