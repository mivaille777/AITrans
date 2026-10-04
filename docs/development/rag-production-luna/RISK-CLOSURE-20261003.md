# 原生视觉、性能与全入口 Trace 风险处理

日期：2026-10-03。基准 HEAD `4b0d802c`，分支 `electronrebuild`。只列本次用户请求产生的增量；原有其他工作区改动保留，未提交、未推送。

## 当前结论

| 项目 | 结果与边界 |
|---|---|
| 原生视觉图片编码超时 | 已修复。使用现有 ColQwen 的 SDPA、可选 NF4 和图片 token 上限；真实 GPU 编码、多模型共存、现有两份 PDF 共 50 页发布及范围检索通过。用户环境已保存启用配置。 |
| HTTP、WebSocket、Agent、Debug、缓存 Trace 接线 | 已补齐并做工程验证。真实聊天与原生检索共享根 Trace；缓存消费记录当前请求时间，链接原推理 span；Studio 直接调用编译图也透传根 Trace。 |
| 公开大库单并发检索延迟 | 当前文本候选配置暖 P95=638.48ms，通过 800ms 门。相同 100 题、全部返回排序与修改前一致。 |
| 4 并发检索性能 | 功能通过、性能失败。100 次真实检索无错误，P95=1464.74ms。不能宣告容量验收完成。 |
| 公开效果、独立引用语义准确率 | 仍未通过。Medical Recall@5=0.63、MRR@20=0.5278；两个真实聊天样例通过现有引用校验，不能代替独立语义准确率 ≥0.90 的验收。 |
| 应用常驻启动 | 自动审批拒绝后台启动，仅返回 `blocked by policy`。未绕过拒绝。现有启动脚本已能主动读取最新用户配置，但仍需在本机手动启动。 |

**整体生产验收仍 NO-GO。** QASPER181 holdout 保持未用。没有降低门槛、修改金标、跳过测试或硬编码答案。

## 修改文件与必要性

以下路径相对仓库根目录；19 个实现/启动/依赖文件、9 个测试文件，另更新本文及 3 个状态文档。

| 文件 | 必须修改的原因 |
|---|---|
| `backend/rag/config.py` | 为原生视觉增加可验证的 NF4、图片 token 上限、专用缓存配置；未配置时不强制量化。 |
| `backend/rag/visual_retrieval.py` | 复用模型加载器启用 SDPA/NF4；视觉塔和检索投影保持原精度。处理器限制图片 token；精度/量化/分辨率进入侧索引版本，避免混用旧向量；总耗时及 span 包含实际视觉检索。 |
| `backend/api/knowledge_dependencies.py` | 生产入口读取并校验上述环境配置，专用视觉缓存不影响文本模型缓存。 |
| `aitranslator-rag-visual-requirements.txt` | 可选视觉环境固定 `bitsandbytes==0.50.2`，现有依赖未升级。 |
| `backend/rag/sparse/bm25.py` | 用项目已有 NumPy 对同一 BM25 公式计算倒排分数，减少 Python/GIL 开销；保留参数及数值含义。 |
| `backend/rag/sparse/store.py` | 只在索引更新时判断参考文献片段，检索复用结果；用堆取 TopK，保持分数和同分排序。重建用新索引后替换，避免修改在途计分数组。 |
| `backend/rag/observability.py` | 复用现有 RAG 事件，绑定请求根 Trace；支持唯一查询 ID、实际阶段 span 和缓存来源链接。 |
| `backend/agent_core/orchestration/evidence_service.py` | 文档证据检索与缓存消费沿用根 Trace；命中时记录真实缓存耗时，禁止把旧推理时间复制为新推理。 |
| `backend/agent_core/reliability.py` | 现有受限工作线程继承 ContextVar，避免节点执行丢失 Trace 和取消上下文。 |
| `backend/agent_core/orchestration/specialist_adapter.py` | Studio/编译图的原生 Send 专家节点绑定请求 Trace，保持并行和检查点合同。 |
| `backend/agent_graph/reading_agent_graph.py` | 正常运行绑定根 Trace；编译图分发时从已有 AgentState 传递同一根 ID。 |
| `backend/agent_graph/document_analyst_graph.py` | 独立文档分析图使用已有运行上下文，缺少外部根时生成本次运行的独立 ID。 |
| `backend/agent_tools/knowledge.py` | 同一 Agent 的多次查询生成不同查询 ID，保留共同根 Trace，避免事件重名。 |
| `backend/services/agent_trace_store_service.py` | 原脱敏白名单会删除 span；仅保留必要 ID/阶段/时间/状态/缓存链接，继续过滤私密正文及错误输入。 |
| `backend/services/companion_chat_service.py` | 检索、生成和验证阶段传递根 Trace；HTTP 复用 WebSocket 的既有证据一致性校验与 fallback，防止非流式绕过校验。 |
| `backend/api/companion.py` | 非流式请求在准备前建 Trace，记录实际生命周期、验证结果及成功/错误终态；核心错误仍按原接口抛出。 |
| `backend/api/companion_stream.py` | 将已存在的聊天根 Trace 传给准备及检索；兼容旧注入服务，保持原消息协议。 |
| `backend/services/rag_debug_service.py` | Debug 原生包装器沿用根 Trace；事件改为真实单调耗时及 UTC 时间，Dense/BM25/答案阶段使用自身耗时，保留真实检索 spans。 |
| `start-electronrebuild.ps1` | 增加显式 `-RefreshRagEnvironment`，从用户配置刷新本进程；修复 Conda 别名被误当成可执行文件导致的启动失败。 |
| `tests/rag/test_visual_retrieval.py` | 检查配置影响索引版本、CPU 不得使用 CUDA NF4、视觉实际耗时及父子 span。 |
| `tests/rag/test_knowledge_dependencies.py` | 检查环境配置验证、缓存位置及非法 token 上限。 |
| `tests/rag/test_bm25.py` | 验证 BM25 数值公式、动态参数、空索引，以及片段替换/重启/删除后的参考文献过滤。 |
| `tests/rag/test_rag_observability.py` | 检查 span 与缓存链接持久化，私密 span 内容不得落盘。 |
| `tests/rag/test_inference_worker.py` | 检查受限节点线程继承并释放 Trace 上下文。 |
| `tests/multi_agent/test_evidence_cache_scope.py` | 用真实索引验证缓存命中不重复推理、当前 Trace 与原 span 链接及源校验。 |
| `tests/multi_agent/test_native_send_dispatch.py` | 直接运行编译后的原生 Root 图，验证专家继承根 Trace，退出后不泄漏上下文。 |
| `tests/test_backend_companion.py` | HTTP 正常/不支持声明/准备失败均走真实服务、引用校验和终态持久化。 |
| `tests/test_rag_debug_companion_trace.py` | 验证 Debug 阶段不重复计算整链耗时，事件时钟单调、带 UTC 时间。 |
| `OPEN-ISSUES.md`、`STATUS.md`、`QUALITY-ACCEPTANCE.md`、本文 | 更新最新验收范围、实测失败和可执行后续方案，保留历史报告。 |

## 原生视觉真实验证与本机启用

复用已下载且固定 revision 的 `tsystems/colqwen2.5-3b-multilingual-v1.0` 和基座，没有改写模型权重。根据 [Transformers Qwen2.5-VL 官方接口](https://huggingface.co/docs/transformers/en/model_doc/qwen2_5_vl)、[bitsandbytes 官方 Windows/CUDA 支持](https://huggingface.co/docs/bitsandbytes/main/en/installation) 与本机 ColPaliEngine 源码采用现有加载参数。只在 `aitrans` 环境安装新的可选 bitsandbytes，未升级 PyTorch/Transformers。

- 原 BF16 图片编码超过 120 秒；NF4+SDPA、256 图片 token 实测模型加载 17.08 秒，第一张图 1.47 秒，第二张 0.30 秒，查询 0.14 秒。加载后 GPU 分配约 3.88GB；数字来自小图编码探针，不是整链 P95。
- 生产默认文本 Embedding、reranker 与 NF4 视觉进程共同驻留测试通过；使用单独视觉缓存，不设置全局 HF 缓存，文本模型仍从原缓存解析。10 次暖模型组合调用约 187–734ms；关闭后无残留子进程。
- 原资料 14 页与 36 页 PDF 分别成功发布原生页图侧索引，合计 **50 页**；generation、源文件和资产校验保留。各文档限定查询都返回本范围页图，无范围泄漏。文本索引及原文档未改写。
- 新版本包含精度、量化和图片 token；旧侧索引不会被当作新版本使用。后续切换这些参数须重新构建对应侧索引。
- 用户配置已持久化：本机 Qdrant URL、native enabled、NF4、256 token、固定 adapter 路径、D 盘视觉缓存、local-files-only。变更前值在本机 `environment-before.json`。

首次完整三模型加载约 **83.83 秒**，未超时；这是冷启动成本。实际 Debug 暖样例的视觉阶段约 889ms，完整文本/图/视觉链路包含更多阶段。上面的单并发 638ms 公开文本基准不包含该视觉链路，不能据此宣告全部入口都小于 800ms。

常驻后台启动再次被自动审批拒绝，原因为 `blocked by policy`，没有进一步说明。未采用等价后台方式绕过。关闭旧应用后，在仓库根目录手动执行：

```powershell
.\start-electronrebuild.ps1 -RefreshRagEnvironment
```

已验证 PowerShell 语法、旧进程环境刷新为实际用户配置、真实 Conda 可执行文件解析和执行。该参数显式启用，不改变启动脚本默认环境优先级；不需要重启 Codex 才能读取新用户配置。未验证重新打包后的旧安装程序。

## 大库配对效果与并发

沿用 MedicalRetrieval 完整 **100999 篇**语料、seed=42、相同 dev100 问题、相同源文件 SHA256、Qwen 模型与服务端集合。缓存关闭；生产 `ProcessInferenceProvider` 实际执行 GPU Embedding/reranker。采用原文本候选配置：重排池 8、512 token、无 Small-to-Big；不调用答案生成、查询重写或原生视觉。金标只用于评分。

| 配置 | 请求数 | Recall@5 | MRR@20 | 暖 P95 ms | 错误 |
|---|---:|---:|---:|---:|---:|
| BM25 原逐项计分，单并发 | 100 | 0.63 | 0.5278 | 1019.51 | 0 |
| NumPy 同公式，单并发 | 100 | 0.63 | 0.5278 | **638.48** | 0 |
| BM25 原逐项计分，4 并发 | 100 | 0.63 | 0.5278 | 1942.58 | 0 |
| NumPy 同公式，4 并发 | 100 | 0.63 | 0.5278 | **1464.74** | 0 |
| 扩大重排池至 20，单并发诊断 | 100 | 0.62 | 0.5259 | 976.55 | 0 |

两种并发各 100 题的修改前后返回顺序**逐题完全一致**，无召回/排序回归。查询阶段进程树峰值 RSS 从约 7.72GiB 降至 7.30GiB；优化测试时系统已用内存最高约 15.79GiB。监测从运行时初始化后开始，不冒充启动阶段峰值；Docker等其他本机应用保留。100 次/组属于短时负载，不等同持续容量验收。

重排池 20 的输入池召回仅 0.69，扩大候选未达到质量或延迟门，未改生产默认。该数只约束这个实际输入池，不能据此断言其他查询、融合或模型方案不可能达标。Recall/MRR 未通过时，不用 holdout 报喜，不把数据集简化成已知答案。

## Trace 与完整链路验证

临时 TestClient 使用隔离会话/诊断数据库，复制原 manifest、BM25 和 Graph SQLite；连接真实 Qdrant 集合和已有原生页图。没有启动常驻端口。

- 文档列表 HTTP200、3 份资料目录回答正常。
- 普通水箱文档问题由原生+文本/图检索提供范围内证据，真实 `deepseek-v4-flash` 生成答案；HTTP200、WebSocket `done`，两个最终答案都带引用并通过现有 guard，无 fallback。先前额度故障未在这两次聊天重现，不能据此宣布旧公开 Graph 部分索引已验收。
- HTTP/WS 的 preparing、routing、retrieving、generating、verifying、answer 均记录真实时间和终态；实际检索 spans 使用相同根 Trace。准备阶段包括路由前工作，生命周期里的 routing 是已产生路由决定后的边界，不是独立路由计算 profiler。
- Debug 实际检索保留原生阶段时间和根 ID；Agent ScopedEvidenceService 的真实资料检索返回 8 份证据、8 个 RAG 事件，沿用同一根 Trace。
- 原生检索关闭包级证据缓存，因为侧索引无独立发布版本；文本路径的真实缓存命中用定向回归验证：当前缓存 span 链接原推理 span，既有范围/源版本复验不变。
- 直接运行编译的 Root/Studio 图验证 Send 专家继承根 Trace；检查点、并行任务及独立文档图保留定向回归。
- HTTP/WS 失败、取消、重启恢复、私密数据脱敏由接口回归覆盖。提供方暂未返回可用用量数据的记录保留 `token_usage/cost=null`，不得填零或估算成真实账单。外部网络硬取消、打包程序与前端长时压力仍未完成生产验收。

## 验证与证据

- 主定向回归 **148 项通过**，无 skip；包括 HTTP/WS、视觉发布/范围/读取、BM25、进程超时、证据缓存、事件存储和 Root/Studio。
- 编译图增补测试与 Native Send/检查点/DocumentAnalyst/Studio 定向复验 **19 项通过**；与主回归部分重复，不相加为独立用例数。随后 BM25 在途数组保护的定向复验 **23 项通过**，见本机 `sparse-final-tests.xml`；只改变重建发布，没有重复全量性能测量。
- Ruff 按本轮修改前的源代码逐条比较，无新增诊断；历史问题未顺手修复。当前增量 diff 和 Git whitespace 检查通过。
- 本轮实验、模型、日志及审计均在 Git 忽略目录，没有添加到源码或生产文档索引。

本机证据目录：`D:\AITrans\data\benchmarks\rag-final-risk-20261003`。主要文件：`baseline.json`、`before/`、`current-turn.diff`、`review.json`、`final-tests.xml`、`studio-tests.xml`、`native-probe.json`、`native-production-defaults.json`、`native-pdf-enable.json`、`final-api-smoke.json`、`before-public-production-load.json`、`public-production-load-optimized.json`、`public-production-load-rerank20.json`、`startup-validation.json`、`environment-before.json`。配对优化执行脚本为 `public_production_load-optimized.py`；后续候选实验脚本为 `public_production_load.py`。失败的首轮接口脚本记录亦保留，不计为通过。

## 保留问题与后续方案

| 保留问题 | 可执行方案/待决定项 |
|---|---|
| Medical 召回/MRR 未达标，独立 Citation Accuracy 未验收 | 下一步在同一开发集做语料表示/查询策略或检索模型的受控对照，按效果和资源门选型；当前扩大池已否决。需代表性人工语义金标，或通过精度校准的独立 judge。既有规则 guard 不作为独立评审。 |
| 4 并发 P95>800ms，图/重写/视觉完整生产链更慢 | 先确认目标并发、语料规模与资源预算。当前 16GiB RAM/8GiB GPU 已实测受限；可选增加内存/独立推理服务，再测相同输入的持续负载。只有实测通过才能承诺并发 SLO，不能凭资源不足直接认定扩容必然达标。 |
| NF4 与 256 token 视觉语义效果未验收 | 建立有页码金标的图表/小字/公式问题，验证原生页图召回与最终答案；页图直接进入多模态 LLM 尚无验收，当前生成仍消费文字锚点。先维持功能启用配置，不能承诺细小视觉内容识别率。 |
| 常驻应用启动被策略拦截 | 用户运行上面的现有启动入口，再检查桌面实际展示；本轮已完成临时真实 API 验证。旧打包应用须重新构建后验收。 |
| 计费/外部请求取消/长时负载/旧公开 Graph 部分索引 | 取得提供方真实 usage 后补汇总；做真实超时/中断及持续负载；保留完整图索引和质量重跑任务，不将恢复的两次聊天当作全部问题关闭。 |

需恢复本轮视觉配置时，按 `environment-before.json` 恢复用户环境变量，再启动新进程。已发布的页图版本可保留；开关关闭后文本链路继续可用。原资料、原文本/图索引及旧 Local Qdrant 没有删除。
