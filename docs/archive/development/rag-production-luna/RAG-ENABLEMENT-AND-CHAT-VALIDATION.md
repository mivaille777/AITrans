# RAG 功能启用与聊天链路验证

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../../start.ps1)；最新检索修复见 [语义排序报告](../../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-10-01。分支：`electronrebuild`；起始 HEAD：`4b0d802c168a00cf12a967cfcdb24c1ba2ed1f4c`。

本轮遵循最小修改原则，保留工作区已有 Agent、RAG、文档改动；未提交、推送或调整检索权重。配置已写入并重启当前后端。**目录查询与真实论文内容问答已恢复；GraphRAG 已启用，但三份现有资料只有一份构图成功。功能冒烟不代表生产效果验收通过。**

## 1. 用户坏例与根因

用户问题：`本地的资料库有什么？`。用户原结果是引用校验降级后返回开发任务书的随机片段。

| 问题 | 实际定位 | 最小修复 |
| --- | --- | --- |
| 目录问题进入错误路径 | 知识访问路由未识别“资料库”，Auto 模式可能判为当前上下文足够；文档数量问法在下一层也未完整识别 | 两个现有路由补充同义词和数量问法；继续复用 manifest 目录响应与服务端范围过滤 |
| READY 文档无法使用 Dense | 原三份 manifest 没有实际 embedding 指纹及有效 generation；Dense 正确拒绝旧索引，只剩 BM25 | 重建三份真实资料的文本索引，保留指纹检查 |
| 检索偏向另一篇论文结论 | “一句话结论”被当作 Conclusions 章节；LLM 改写进一步引入章节限制与通用章节查询 | 区分回答格式和章节意图；章节约束只信任用户原问，真实章节查询仍保留 |
| 关系问题未触发 Graph | “有什么关系”不在关系/多跳识别表达式中，带 PID/MATLAB 的问题进入关键词通道并关闭 Graph | 补充中英文关系及影响问法，保留现有有界通道和可信文档范围 |
| 真实关系问题的图通道降级 | 原 250ms 图预算下三次检索有两次超时，另一轮真实返回图结果 | 当前应用图预算改为 1000ms，保留耗时诊断、范围及路径边界，不放宽来源校验 |
| 图片描述无法使用已配置凭据 | VLM 继承 DeepSeek 模型/端点，却仍查 OpenAI-compatible 凭据 | 仅同端点继承当前提供方的凭据名称；不复制或输出密钥 |
| Agent JIT read 校验抛错 | 全库模式把 `None` 传入严格 list 字段，同时可能丢掉选定文档范围 | 始终传入现有文档列表，空列表表示全库；保留显式范围 |
| 完整论文图抽取逐字引文失败 | 模型修复输出仍改动原文标点/断词 | 一次修复反馈提供现有摘录器生成的原文句子 ID；服务端解析已提供 ID，再执行原有严格校验 |
| 一张 PDF 图片描述失败 | JPEG 2000 `.jp2` 不被当前系统 MIME 识别 | 用已有 Pillow 在内存转换 PNG；检查输入/转换后大小，保留损坏图片错误与原文件 |

没有关闭在线引用校验。目录问题应直接回答真实目录，内容问题才进入检索、上下文与 LLM。

## 2. 关闭原因及最终状态

| 功能 | 原状态与关闭原因 | 本轮处理 / 最终状态 |
| --- | --- | --- |
| GraphRAG | 显式关闭；早期功能测试无法证明所有真实文件均可严格构图，已有格式与引用失败历史 | 开启，抽取提示版本 `graph-1.1.2`；真实水箱论文构图成功，另外两份待处理 |
| OCR | 显式关闭；原路径主要使用可抽取文字的 PDF，OCR 增加计算开销 | 开启；扫描文字实测通过；设备使用 `auto` |
| 公式增强 | 显式关闭；首次真实 CPU 解析耗时长，120 秒配置未覆盖实际增强过程 | 开启并自动使用可用 CUDA；真实 14 页论文解析完成；公式语义质量未验收 |
| VLM 图片描述 | 显式关闭；独立模型/端点为空，且凭据继承路径不完整 | 修复同端点凭据并开启；水箱论文 19 张、Measurement 7 张图片描述进入索引 |
| QueryRouter | 已接线但默认关闭，历史合成测试不足以推广所有问题类型 | 按本轮明确授权开启；内容问题使用原问及有界改写，关系问题可启用 Graph |
| 查询改写 | 原本已启用 | 保持开启；修正改写误引入章节约束的问题 |
| Agent JIT | 默认关闭；聊天入口本就直接准备有界证据，Agent 入口缺少实际严格校验覆盖 | 修复 read 的过滤器并开启；仍仅用于 Agent search→read |
| 查询嵌入缓存 | 容量为 0，未实际缓存 | 容量设为 128，复用已有版本/范围隔离逻辑 |
| 通道/重排预算 | 原未配置有效预算；图默认 250ms 在真实问答中触发超时 | 通道/重排各 30000ms，图 1000ms；复用现有预算检查，不承诺运行中计算硬中断 |
| ColQwen 原生视觉检索 | 显式关闭；模型资源需求超出当前可用资源 | 仍关闭，详见 OI-013；图片代理文本及 VLM 描述已经进入现有文本检索 |
| 在线回答与引用校验 | 前一版架构图状态标注有误；原来已经接入聊天终结阶段 | 保持启用；无效引用与严格失败测试继续保留 |
| 离线 gold 断言验证 | 是依赖金标准的评测辅助函数 | 保持离线用途，不作为独立在线开关 |

只调整本轮必要的功能开关、设备与软预算；未升级已有依赖。`aitrans` 中补装已有项目要求的 `colpali-engine==0.3.18` 及缺失依赖 `peft==0.20.0`、`onnxruntime==1.30.0`、`flatbuffers==25.12.19`；原生视觉模型权重未下载。诊断工具 py-spy 仅用于环境内定位 CPU 调用，不进入项目依赖。

## 3. 三份真实资料迁移

未修改原 PDF/Markdown 文件。三份文本索引现在均 READY，具有同一当前 Qwen3 1024 维实际权重指纹、新 generation 和来源定位；BM25 当前 generation 的 chunk ID 集合与 manifest 完全一致。

| 资料 | 文本 chunks / sections | 有效 generation | Graph |
| --- | --- | --- | --- |
| Computers and Chemical Engineering（水箱论文） | 185 / 40 | `dd2b7e7d248e43f69f52cc36150ed36a` | 4 条严格回源关系，已发布 |
| Measurement | 255 / 60 | `0d722b9bad6449319fb31d3a0f9d7ed2` | 模型结构化输出失败，未发布 |
| AITrans 科研多 Agent 系统：分阶段开发任务书 | 29 / 23 | `aa1c9d418ae6491c81625b74bb143228` | 模型结构化输出失败，未发布 |

后两份 Graph 重建失败时旧 READY 未切换。随后使用现有 Graph 关闭配置分别完成真正的文本重建；完成后恢复 Graph 开启并重启后端。没有忽略失败 chunk、伪造空图或降低证据校验。

水箱论文全功能重建约 469.33 秒；Measurement 文本重建约 448.31 秒；任务书文本重建约 6.17 秒。这些是导入耗时，不是查询 P95。

Measurement 的一张大学标识 `.jp2` 在上述已发布 generation 中仍记录描述失败。修复后对同一原图单独调用真实 VLM 已成功；该单图验证没有改写已发布 generation，下一次成功重建才会更新其描述。

## 4. 前端到回答的链路实测

使用正在运行的桌面前端代码（浏览器访问 `127.0.0.1:5173`）与真实后端 `127.0.0.1:8766`，使用已配置的 DeepSeek、Qwen3、Qdrant、BM25；没有用 mock 替代这条链路。

| 环节 | 实测结果 |
| --- | --- |
| 前端发问 | Auto 模式、全库范围提交用户原问；最终目录列出真实三份资料，数量与重建后的 chunk 数一致 |
| 目录路由 | `local · deterministic` 与 `Knowledge · directory`；目录不调用 LLM、不拿正文片段冒充文档清单 |
| 内容召回 | “本地资料库中的水箱控制论文研究了什么系统？请给出一句话结论并附引用。”原问参与召回；最终 2 个检索查询，Dense/Sparse 各 60 个候选；未强制 Conclusions 章节 |
| 返回 LLM | 有界证据与程序分配的引用 ID 交给真实 `deepseek-v4-flash`；最终没有应用随机证据替代降级 |
| 内容回答 | 正确描述非线性单容水箱液位系统及固定 PID、自整定 PID、直接 LLM、混合 LLM-PID 四种架构 |
| 流式与最终显示 | 前端显示最终文本、Sources 与引用按钮；会话 API 保存的答案、证据与引用用于复查 |
| 引用来源 | 点击 `[4]` 展示实际水箱论文、Page 2、章节和单容水箱/SISO 原文；无无效引用 |
| 图通道 | 恢复开启后的真实资料 Debug run 完成，Dense 30、BM25 30、Graph 12 个候选，图阶段启用且无失败 |
| 聊天实际 Graph 路由 | 限定水箱论文询问 autotuned PID controller 与 MATLAB PID Tuner 的关系；修复后为 multi-hop，三次检索均为 `hybrid+graph`，降级原因为空，返回真实关系和引用 |

最终内容请求的检索阶段耗时约 **1522ms**，这是单次观测，不是 P95，也没有达到 800ms 的生产门槛证明。最终校验仍报告 `partial_grounding=true`、`strict_passed=false`、`cross_language_support_unscored`，没有将程序校验的 `passed` 等同于语义引用准确率达标。

最后一次关系问答在后端重启后的检索总耗时约 **24.16 秒**，包含模型冷启动及三次检索，不能算作暖检索 P95。最终点击 `[1]` 展示 Page 5 的 `2.3.2. Autotuned PID controller` 原文；浏览器测试结束时已恢复 Auto 和全库范围。

浏览器中的“打开原文”明确提示需要桌面应用。已核对 Electron preload→IPC→本地路径校验→`shell.openPath` 调用链，并执行已有引用组件测试；原生 Electron 窗口实际打开文件的动作未实测，不能宣称 PDF 已在原生窗口打开或定位指定页码。

## 5. 最小范围验证

以下批次有重叠，不相加作为不同测试总数。

| 验证 | 结果 |
| --- | --- |
| 知识路由/目录/范围相关 4 个测试文件 | 45 项通过；原问及文档数量回归先失败后修复 |
| 配置、运行时、VLM、JIT、缓存、聊天流测试 | 56 项通过；严格失败/部分支持/无效引用路径仍测试 |
| Graph 抽取、索引及运行时装配 | 46 项通过；未知摘录 ID 仍失败，一次修复上限保留 |
| 自动设备配置、PDF 解析及路由相关 | 64 项通过 |
| 章节意图、聊天 RAG 与执行计划 | 22 项通过；三个新增回归先失败后修复 |
| 查询通道路由与查询规划 | 26 项通过；五个关系问法回归先失败后修复 |
| 最终配置文件验证 | 12 项通过，确认 Graph/OCR/公式/VLM/Router/JIT 开启、ColQwen 关闭 |
| JPEG 2000 后图片描述测试 | 11 项通过；格式、原图不变、转换后大小与损坏图片回归已覆盖 |
| 前端 runtime/recovery/CitedAnswer | 3 个文件 16 项通过 |
| 前端类型检查、改动组件 oxlint | 通过 |
| Python Ruff | 新增规则违规为 0；现有模块的历史违规与修改前一致，未为无关 Lint 重构 |
| 真实 OCR | 扫描句子正确识别；合成公式结果不正确，未标记公式质量通过 |
| 真实 CUDA PDF 解析 | 水箱论文 14 页约 51.30 秒，保留表格、图片和公式结果；公式语义未评分 |
| 真实 VLM | 合成流程图、真实论文图片及原失败 JP2 图片成功调用 |
| 隔离 Graph 冒烟 | 真实模型抽取 Alpha→Beta→Gamma，READY、两边路径与三节点访问可见；不当作多跳质量分数 |
| 真实资料 Graph 检索 | 当前配置下图阶段完成，返回 12 个候选 |
| 浏览器完整问答 | 目录、内容、真实 LLM、最终显示与引用卡片验证通过；原生文件打开待测 |

## 6. 本轮改动文件及必要性

此表仅列本轮新增变化；已有未提交变化不是本轮重构结果。

| 文件（仓库相对路径） | 必须修改的原因 |
| --- | --- |
| [config/default.toml](D:/AITrans/config/default.toml) | 启用可用功能并配置自动设备、缓存和软预算 |
| [backend/services/knowledge_access_router.py](D:/AITrans/backend/services/knowledge_access_router.py) | 识别用户原问“资料库”及目录数量意图 |
| [backend/services/companion_query_router.py](D:/AITrans/backend/services/companion_query_router.py) | 将文档数量问题交给现有目录响应 |
| [backend/rag/config.py](D:/AITrans/backend/rag/config.py) | 严格配置模型接受实际查询开关及 VLM 凭据提供方 |
| [backend/api/knowledge_dependencies.py](D:/AITrans/backend/api/knowledge_dependencies.py) | VLM 同端点继承已配置 DeepSeek 凭据 |
| [backend/rag/vision.py](D:/AITrans/backend/rag/vision.py) | 使用正确凭据名称；兼容真实 PDF 的 JP2 图片 |
| [backend/agent_tools/knowledge.py](D:/AITrans/backend/agent_tools/knowledge.py) | 修复 JIT read 的严格 list 类型并保留选定范围 |
| [backend/rag/graph/extractor.py](D:/AITrans/backend/rag/graph/extractor.py) | 在一次修复中提供可信原文 ID，保留逐字校验并升级抽取版本 |
| [backend/rag/structure_retrieval.py](D:/AITrans/backend/rag/structure_retrieval.py) | 避免回答格式“一句话结论”变成章节过滤 |
| [backend/rag/query_router.py](D:/AITrans/backend/rag/query_router.py) | 关系与影响问题触发已启用 Graph，不因英文缩写转为纯关键词 |
| [backend/services/companion_chat_service.py](D:/AITrans/backend/services/companion_chat_service.py) | 避免改写内容改变用户原始章节意图 |
| [apps/desktop/src/features/companion/CompanionWorkspaceV2.tsx](D:/AITrans/apps/desktop/src/features/companion/CompanionWorkspaceV2.tsx) | 正确显示目录路由状态，避免 General 被标为 Reading 上下文充足 |
| [tests/test_companion_capability_routing_matrix.py](D:/AITrans/tests/test_companion_capability_routing_matrix.py) | 用户原问、数量问法与真实内容意图回归 |
| [tests/rag/test_config.py](D:/AITrans/tests/rag/test_config.py) | 严格配置字段与最终启用配置回归 |
| [tests/rag/test_knowledge_dependencies.py](D:/AITrans/tests/rag/test_knowledge_dependencies.py) | 同端点继承凭据、异端点不借用凭据回归 |
| [tests/rag/test_visual_understanding.py](D:/AITrans/tests/rag/test_visual_understanding.py) | 正确凭据及 JP2 成功/大小/损坏图片回归 |
| [tests/agent/test_agent_knowledge_search_read.py](D:/AITrans/tests/agent/test_agent_knowledge_search_read.py) | 全库和选定范围 read 类型与证据校验回归 |
| [tests/rag/graph/test_extractor.py](D:/AITrans/tests/rag/graph/test_extractor.py) | 原文 ID 修复、伪造 ID 拒绝及修复次数回归 |
| [tests/rag/test_structure_retrieval.py](D:/AITrans/tests/rag/test_structure_retrieval.py) | 中英文一句话回答格式不限制章节 |
| [tests/rag/test_query_router.py](D:/AITrans/tests/rag/test_query_router.py) | 中英文关系、影响问法的通道和范围回归 |
| [tests/rag/test_companion_rag.py](D:/AITrans/tests/rag/test_companion_rag.py) | LLM 改写添加 Conclusions 不能触发结构约束 |
| [docs/development/rag-production-luna/RAG-ARCHITECTURE-CURRENT.md](D:/AITrans/docs/development/rag-production-luna/RAG-ARCHITECTURE-CURRENT.md) | 更新真实启用状态，区分部分图数据、在线校验与离线评测 |
| [docs/development/rag-production-luna/OPEN-ISSUES.md](D:/AITrans/docs/development/rag-production-luna/OPEN-ISSUES.md) | 保存两份构图失败、原生视觉资源与当前验收限制 |
| [docs/development/rag-production-luna/RAG-ENABLEMENT-AND-CHAT-VALIDATION.md](D:/AITrans/docs/development/rag-production-luna/RAG-ENABLEMENT-AND-CHAT-VALIDATION.md) | 记录本轮原因、改动、实测、证据和未解决风险 |

## 7. 保留问题与可行下一步

### OI-012：两份真实资料构图仍失败

Measurement 与任务书均在一次修复后返回 `Research-memory extractor returned invalid structured output.`，Graph 未发布。复查任务书前五个旧 chunk 未复现同一错误，不能声称已经定位具体 JSON 字段。当前两份资料的真实文本检索已恢复。

已核对 [Microsoft GraphRAG 模型选择](https://microsoft.github.io/graphrag/config/models/) 对可靠结构化输出的要求，以及 [TextUnit 来源关联设计](https://microsoft.github.io/graphrag/index/default_dataflow/)。本轮借鉴来源由服务端持有的思路，在现有摘录器上实现原文 ID；没有引入 GraphRAG 框架或放宽 schema。

可行下一步：在失败样本上捕获原始输出与具体校验错误，再比较现有提供方的 schema 能力或选定单独图抽取模型；模型/预算变化需由用户决定。简单 JSON mode 不能保证端点声明及原文引用正确。**Graph 当前开启，因此新的导入或重建仍可能因严格构图失败而失败；已有 READY 版本会保留。** 将构图改为后台独立补建涉及现有原子发布合同，本轮未扩大范围实现。

### OI-013：原生 ColQwen 仍无法正确启用

[当前模型](https://huggingface.co/tsystems/colqwen2.5-3b-multilingual-v1.0) 是依赖 Qwen2.5-VL-3B 基座的 LoRA。核对文件大小后，基座与适配器权重约 8.47GB（约 7.89GiB）；本机 8GiB GPU 检查时仅约 2.62GiB 可用，系统空闲内存约 2.1GB，C 盘空余约 2.8GB。计算还需激活与现有模型内存，当前配置不能直接装载。

代码检查还发现视觉检索包装器未完整接收新 QueryRouter 的通道参数，也没有转发现有证据验证入口；因此获得资源后仍需补齐接线和范围/证据回归，不能只翻开关。可选后续为更大资源、经验证的小模型/量化配置；本轮未安装新推理栈或下载大权重。

### OI-014：语义、时延与原生桌面验收未通过

跨语言断言仍未逐句通过严格支持度校验；图关系稀疏、公式质量及图片/图注对齐未独立评估；检索软预算不是硬中断。本轮没有运行公开质量门、独立 holdout 或生产负载，历史质量不合格结论继续保留。Companion 引用证据当前保留来源正文，图路径详情主要在 Debug trace 查看；旧 `knowledge_enabled/document_scope` trace 字段与新的 policy 路由状态可能不一致，核验需以实际 route、通道及服务端范围为准。

浏览器测试不能覆盖 Electron 系统文件打开。另在测试中新建聊天曾出现旧会话异步恢复现象，刷新后可建立新会话；未修改无关会话生命周期，作为后续独立复现项保留。

历史公开评测的 HTTP402 本轮未复现，当前已配置模型可以完成真实调用；这不证明后续额度或账单预算充足。

## 8. 本机验证产物

产物在 `D:/AITrans/data/benchmarks/rag-enablement-20261001/`（已忽略，不提交原始资料/模型/调试脚本）：

- `manifest-before.json`、`reindex-results.json`、`text-reindex-results.json`、`migration-final.json`：原索引、失败构图与最终有效 generation。
- `chain-after-first-reindex.json`、`chain-before-final-restart.json`、`chain-final.json`、`conversation-final.json`：章节误路由前后、最终证据/引用及持久化回答。
- `final-runtime-graph-trace.json`、`graph-probe.json`：真实资料图召回及隔离两跳冒烟。
- `chat-graph-before-router-fix.json`、`chat-graph-before-budget-fix.json`、`chat-graph-final.json`、`conversation-graph-final.json`：聊天关系路由、250ms 超时与最终三轮图检索结果。
- `parse-probe.json`、`formula-cuda-probe.json`、`formula-cpu-stack.txt`：OCR/公式与设备结果。
- `vlm-probe.json`、`jp2-probe.json`：真实视觉调用。
- `graph-failure-replay.json`、`lint-comparison.json`：有限回放与历史 Lint 对比。
- `chat-citation-proof.png`、`graph-citation-proof.png`：内容及关系问答的真实引用卡片截图。
