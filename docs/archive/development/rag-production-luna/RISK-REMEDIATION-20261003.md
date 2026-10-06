# RAG 风险修复与本机 Qdrant 验证

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../../start.ps1)；最新检索修复见 [语义排序报告](../../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-10-02—03。分支 `electronrebuild`，基准 HEAD `4b0d802c`；本轮改动未提交、未推送。原有工作区改动、原资料及本地索引保留。

## 结论

- Docker 已修复，本机 Qdrant 已部署；现有资料与 100999 篇公开语料均完成逐条迁移核验。
- 原生视觉的发布、范围、来源校验与当前版本读取合同已补齐；真实 GPU 图片编码超时，因此开关继续关闭。
- 本地模型调用已接入可终止进程；真实视觉 GPU 调用超时后成功终止，无残留子进程。
- 聊天 WebSocket 生命周期和检索阶段时间已补齐并验证。不能据此宣告所有 HTTP、Agent、缓存路径的 Trace 均已验收。
- **效果验收仍 NO-GO**：混合重排延迟、公开召回/排序及独立引用语义准确率尚未全部达标。

## 修改文件及必要性

只列本轮增量，包含 14 个实现/依赖文件、8 个测试文件及 4 个验收文档；不是相对 Git HEAD 的全部历史改动。

| 文件（相对仓库根目录） | 必须修改的原因 |
|---|---|
| `backend/rag/config.py` | 增加可选 Qdrant URL、连接超时与本地推理超时；未配置 URL 时保留原本地模式。 |
| `backend/rag/stores/qdrant.py` | 复用原适配器连接服务端；本机地址绕过系统代理，避免迁移/检索连接失败。 |
| `backend/api/knowledge_dependencies.py` | 将生产模型接入进程边界，共享正确的服务端客户端并释放模型进程；读取本机连接环境配置。 |
| `backend/rag/inference_worker.py`（新增） | 原线程不能终止阻塞的 native/GPU 调用；复用模型进程，超时/取消时终止并等待退出，保留错误链，失败启动释放句柄。 |
| `backend/agent_core/reliability.py` | 将既有工具、节点、运行的停止/暂停/超时信号传入本地推理进程。 |
| `backend/sidecar.py` | Windows 打包入口加入 `freeze_support()`，避免推理子进程重新进入服务入口。 |
| `backend/rag/visual_retrieval.py` | 增加 generation、发布标记、源文件/资产哈希、索引版本；失败写入清理自身半成品，保护旧点；补齐可信范围的检索、校验及 JIT 读取。侧索引无独立发布版本时明确禁用组合结果缓存。 |
| `backend/rag/visual_prefetch.py` | 两阶段实际生产 store 使用同一发布合同；粗筛也执行范围/版本过滤，避免范围外候选挤掉范围内资料。 |
| `backend/rag/visual_adaptive.py` | 自适应实际入口透传范围、generation 和既有检索选项。 |
| `backend/rag/retrieval_service.py` | 记录实际阶段起止时间、状态、耗时和独立检索 span ID，避免同一根 Trace 的多次检索重名。 |
| `backend/rag/observability.py` | 将实际检索 spans 接入现有事件；无法取得的 token/cost 保持空值。 |
| `backend/services/rag_debug_service.py` | 持久化聊天阶段与完成/失败/取消状态；路由更新沿用同一 Trace；Debug 取消信号传入推理。 |
| `backend/api/companion_stream.py` | 准备开始即建 Trace，生成/校验/终态均记录；取消后不新分发生成调用；现有消息协议保持不变。 |
| `pyproject.toml` | dev 依赖增加已有可选视觉依赖 PyMuPDF，保证真实 PDF 渲染回归在标准测试安装中可运行；没有升级现有依赖。 |
| `tests/rag/test_inference_worker.py`（新增） | 永久阻塞、取消、错误传递、队列隔离、启动失败恢复及 Agent 工具超时的进程回归。 |
| `tests/rag/test_knowledge_dependencies.py` | 验证生产入口选择服务端及原路径保留。 |
| `tests/rag/test_qdrant_store.py` | 验证服务端参数、密钥环境配置、本机代理隔离及非法 URL。 |
| `tests/rag/test_visual_retrieval.py` | 用真实 PDF/本地 Qdrant 验证来源、资产、版本、范围、JIT、删除与失败发布回滚。 |
| `tests/rag/test_visual_prefetch.py` | 验证先写未发布点、再发布的实际调用顺序。 |
| `tests/rag/test_rerank_pool.py` | 验证真实检索阶段时间及父子 span。 |
| `tests/test_backend_companion_stream.py` | 验证实际聊天接口完整阶段与终态持久化。 |
| `tests/test_rag_debug_companion_trace.py` | 验证完成/失败/取消、重启恢复和终态后不再开启阶段。 |
| `OPEN-ISSUES.md`、`STATUS.md`、`QUALITY-ACCEPTANCE.md`、本文 | 更新修复状态、真实指标、部署恢复方式及待决策项，避免把局部通过当整体生产通过。 |

## Docker、部署及迁移

Docker Desktop 故障是不可访问的零字节 `engine.sock`。删除该文件的操作曾被自动审批拒绝，未执行删除。按 [Docker 官方问题库相同故障记录](https://github.com/docker/for-win/issues/15064)，采用保留式处理：确认通信目录仅含该失效文件后重命名整个目录，再启动 Docker。保留目录为 `C:\Users\huaqi\AppData\Local\docker-secrets-engine.rag-backup-20261002`。Docker server `29.8.0` 已验证；其他用户容器和卷保留。

- 容器：`aitrans-rag-qdrant`，固定镜像 `qdrant/qdrant:v1.19.1`，digest `sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10`。
- 地址：`http://127.0.0.1:6335`，只绑定本机；存储 `D:\AITrans\data\qdrant-server`；重启策略 `unless-stopped`。
- 本次资源上限：2 CPU、2GiB 内存、3GiB memory+swap；不代表其他机器的容量承诺。
- 用户环境配置 `AITRANS_QDRANT_URL=http://127.0.0.1:6335` 已持久化；原默认配置未改为强制依赖 Docker。需要完全重启应用/后端，使新进程读取环境变量。
- 后台启动 AITrans 后端的操作被自动审批拒绝（仅返回“被策略阻止”），未启动常驻后端。接口验证使用临时 TestClient，未通过其他启动方式绕过拒绝。

迁移通过 SQLite 一致性快照读取原 Local 索引，复用已有向量，没有重新嵌入或删除原库。点 ID、payload、generation 全部核验；余弦向量按 [Qdrant 官方归一化行为](https://qdrant.tech/documentation/manage-data/collections/) 比较全部分量。

| 集合 | 点数 | payload 核验 | 归一化后最大分量误差 |
|---|---:|---|---:|
| `aitrans_knowledge` | 1328（含原旧版本点） | 全部一致 | 2.60e-8 |
| `aitrans_benchmark_589cd87e0a1b` | 100999 | 全部一致 | 7.55e-8 |

公开集合已建 payload/HNSW 索引，状态 green，indexed vectors=100999。真实服务器另外验证了文本 generation/范围/定向删除，以及原生单阶段、两阶段粗筛的范围和版本过滤；测试自有集合已清理。

## 效果与性能

复用 MedicalRetrieval 完整 100999 篇语料、相同 seed=42 的 dev100 问题及既有模型，金标只用于评分。每个 profile 先暖启动，关闭检索缓存。以下不含答案生成、并发负载或生产进程边界开销。

| 服务端配置 | Recall@5 | MRR@20 | 暖 P95 ms | 对照原 Local P95 ms |
|---|---:|---:|---:|---:|
| Dense | 0.62 | 0.5293 | 728.15 | 2121.85 |
| BM25 | 0.38 | 0.3254 | 720.33 | 750.08 |
| 混合重排8，512 token | 0.63 | 0.5278 | 1227.34 | 2981.56 |

300 次计分检索无降级错误。Dense 延迟通过，整体效果门仍失败；Dense 与原精确 Local 的 Recall@5=0.63 有 0.01 差异，不能用延迟改善抵消召回门失败。混合重排仍超过 800ms。

另在完全相同的 QASPER 开发100题上试验查询相关窗口提取：Recall@5=0.7529、MRR=0.5293，低于既有候选 0.8333/0.5424，未加入生产代码。首个带脚本错误的诊断运行不用于效果结论，并明确标记其原执行脚本未归档；没有伪造源码版本。QASPER181题 holdout 保持未用，候选门槛未降低。

## 功能与局部验证

- 相关回归 155 项通过；随后修补启动失败、发布失败及服务端入口，最终直接相关定向复验 81 项通过，无 skip。XML 在下述本机证据目录。
- 真实 Qwen GPU 进程：Embedding 1024 维及 reranker 正常；10 次暖模型组合调用约 89–106ms，冷加载各约18秒，关闭后无残留子进程。这不是完整检索 P95。
- 原生 ColQwen adapter/base 下载到 D 盘并固定 revision；补齐本次缓存的基座版本指向，没有修改模型权重。真实 BF16 GPU 查询得到 22×128 向量；两张448×448图片的编码超过120秒，被终止并等待退出，remaining children=[]。不能据此认定原生图片召回/效果通过。
- 临时 API 实例复制原 BM25/manifest/Graph 状态，连接已迁移的真实服务端集合；会话/诊断/测试数据库隔离。3 份现有 READY 文档分别返回8个范围内片段，来源验证及当前版本 JIT 读取均通过、无通道错误；第一次含模型冷加载约33.6秒，随后两个问题约1041/397ms，不作为 P95。
- 文档列表 HTTP200；用户原问题“本地的资料库有什么？”通过真实聊天 WebSocket 返回准确的3份资料清单，终态 `done`，Trace 的 preparing/routing/generating/answer 均完成。该目录请求由本地确定性响应生成，不冒充真实 LLM 答案验收。
- 普通证据聊天的生成/校验、失败/取消、终态及重启恢复由直接相关接口回归验证；未调用付费 LLM，因此不宣告真实 LLM 支持度、费用或 UI 效果通过。
- Windows sidecar 入口帮助命令正常；未重新打包执行二进制验收。按修改前代码行对照，完整 Ruff 无新增诊断，历史问题保留；检查本轮 diff，保留必需修改及测试，实验/模型/日志均位于忽略目录。

## 未解决问题与可执行方案

| 保留问题 | 后续方案与需要的决定 |
|---|---|
| 原生视觉本机图片编码超时，尚未正确启用 | 保持关闭，避免每次查询增加120秒等待。需要明确资源预算，或授权较小模型/量化/独立推理部署，再验证多模型共存、图片编码与检索。当前 LLM 仍消费文字锚点，页图直接进入多模态答案链路也需专项验证。 |
| Medical 召回/排序、QASPER MRR、独立引用语义验收不通过 | 按现有失败阶段选择语料表示/模型方案；当前窗口实验已否决。引用验收需要合格独立 judge 或人工语义金标；不能以引用格式、源哈希或失败 judge 校准替代。 |
| 混合重排 P95=1227ms；大库生产并发/长时间负载未验收 | 优先对现有 BM25、重排的实际慢查询做局部剖析；保持同题、同质量约束。明确目标并发、语料上限及资源预算后，再做生产进程/多进程负载。服务端存在并不等于容量门通过。 |
| 全入口 Trace 覆盖未完成 | 现验收范围是实际 WebSocket 和检索阶段；HTTP 非流式、Agent 独立图/缓存消费及 token/cost 汇总需逐入口验收，不报告100%覆盖。 |
| 外部同步 LLM 请求、打包程序的硬取消未验收 | 本次证明本地模型进程可以终止；外部网络请求需验证提供方超时/中断行为，打包环境需重新构建后运行真实模型取消。 |
| Graph 公开多跳语料曾 HTTP402、真实业务语义金标缺失 | 恢复原提供方额度或明确可用提供方和费用预算，再重跑完整冻结图索引；不自动充值、切换未知模型或将部分图当完整验收。历史缺失快照的坏例继续保留。 |

## 本机证据与恢复

证据根目录：`D:\AITrans\data\benchmarks\rag-risk-remediation-20261002`，已被 Git 忽略。包含 `before/`、`baseline.json`、`current-turn.diff`、`review.json`、测试 XML、`docker-repair.json`、`deployment.json`、两份 `*-migration.json`、`server-contract-smoke.json`、`gpu-worker-smoke.json`、`native-visual-smoke.json`、`production-api-smoke.json` 及 `medical-server-dev100/`。其中 API 会话和实验失败记录仅用于本机验证。

需要回到原 Local 时，将用户环境变量 `AITRANS_QDRANT_URL` 恢复为 `deployment.json` 保存的旧值或删除该变量，再完全重启应用；原 `D:\AITrans\config\rag\qdrant` 保留，迁移未改写原点。Docker 通信目录备份保留；恢复它只用于排错，不应覆盖已正常重建的通信目录。无需删除其他容器或用户卷。
