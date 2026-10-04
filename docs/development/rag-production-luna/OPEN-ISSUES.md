# 未解决问题与待用户决策

此文件记录经仓库核验、基准测试和成熟开源项目对照后的功能缺陷、验收缺口和产品/数据决策。2026-09-30 按用户“先解决问题清单中的问题”完成有限抽取修复与路由诊断修复；当前结论及证据见 [问题修复报告](OPEN-ISSUES-REMEDIATION.md)。

## 效果、并发与独立引用执行（2026-10-03，最新）

- 最小修改候选筛选与推理等待顺序，增加实际队列/执行 Trace；最终81项定向测试及Ruff通过。完整公开检索800次零错误，700次原配置排序保持一致。详见 [本轮报告](QUALITY-CAPACITY-20261003.md)。
- 当前环境 Medical单请求P95=717ms；C2=1047ms、C4=1778ms仍FAIL。FIFO降低尾延迟，未提升吞吐；不得把限流当容量验收通过。内存接近本机上限，硬件/推理微批处理方案保留决策。
- 原召回候选并集0.72，扩大两路各100后0.78；未采用没有充分收益的融合权重/候选数变更。Recall@5=0.63、MRR=0.5278仍FAIL，冻结坏例待独立复核。
- Graph公开构图按当前抽取版本259/259零失败，旧402/逐字错误不再复现；混合Recall@5=0.60，完整证据@5=0.20仍FAIL。科学关系白名单与通用多跳数据的差异另列，未放宽守卫。
- 新MS MARCO120条独立验证：裁判支持精度0.593→0.700、二分类一致率0.75→0.80，仍不合格。200条原子事实盲评材料、两份空表、262个AITrans句级单元及44条拒答待审已导出；人工标注为零，独立引用验收BLOCKED。
- 本轮未改生产模型/接口/阈值/用户索引，未提交推送；整体生产NO-GO。后续模型/资源/关系类别及人工裁决见本轮报告。

## 目录元数据与工具接线复验（2026-10-03）

- 目录工具/API 已提供源文件格式、最近修改 UTC 时间及缺失/拒绝/不可用状态；前端真实目录问题显示3份资料的 PDF/Markdown 与时间，未发生证据校验回退。详见 [本轮逐文件报告](METADATA-RISK-20261003.md)。
- 修复普通 Agent Auto 问答被旧编排抢占、返回分析 JSON 而没有正文引用的问题；compat/native 默认入口都由模型选择工具。搜索找到候选后必须先尝试 Read；无结果、服务故障和预算耗尽仍明确报告，引用校验未放宽。
- 83项最终定向测试及4项 Electron 进程合同通过，无新增 Ruff。80条冻结意图问题真实模型复验通过；一条缺少指代数值的原金标单独纠正并保留原报告，这不是生产 Recall/Citation Accuracy 验收。
- **OI-019 本轮功能复验通过，容量保留**：原配置原生视觉完成页图编码、查询和三模型共存；真实 HTTP/WS/Agent/Debug 查询包含视觉结果且无视觉回退。不能排除其他负载导致GPU/RAM不足，复杂图表语义和持续容量仍缺。
- **Agent 首次加载风险已局部闭环**：已有 READY 库在启动接受请求前准备模型，本机冷启动64.55秒后首条真实Agent9.23秒完成，2条正文证据/2条引用、guard通过；未放宽20秒工具/45秒总预算。空库后首次导入等生命周期仍沿已有加载机制，需要后续容量场景覆盖。
- **OI-020 开发版启动阻塞已解除**：实际复现并一行修复 PowerShell 依赖探测丢引号，常规启动脚本成功启动 Electron/Vite/后端，前端目录显示通过。开发版验证不能代替安装包与长期运行验收；中断后端口已停止，未反复启动。
- **效果/独立引用/并发门继续 FAIL/BLOCKED**：Medical Recall@5=0.63、MRR=0.5278，4并发P95=1465ms；独立judge仍未合格。本轮没有用意图工具冒烟或引用guard通过替代生产指标，也没有修改阈值。整体生产NO-GO，未提交/推送。
- 另保留开发启动的主题IPC未授权sender日志，未扩大身份白名单；当前RAG目录问答未受阻。详细证据、环境隔离和后续方案见本轮报告，以下历史状态保留。

## Function Calling 接入后复验（2026-10-03）

- 生产 Companion HTTP/WS、Reading Agent 已接入原生工具决策；规则不再提前关闭生产 Auto 知识工具。真实模型意图冒烟 7/7，真实文本/GraphRAG 的搜索、正文读取、引用 guard 与目录链路通过。完整文件必要性、验证和限制见 [实施报告](FUNCTION-CALLING-20261003.md)。
- **OI-019 追加风险**：本轮视觉预检出现 CUDA 显存分配失败，未通过无视觉回退断言；原启用配置、索引保留。实际接口验收明确采用文本/GraphRAG 配置，不能代替视觉验收。Agent 严格预算下的首次模型加载、独立大样本意图效果和应用重启仍待验证。
- 历史能力矩阵有 4 项测试 fixture 未接收 `trace_id`，修改前源码可复现，未顺手修改；整体生产 NO-GO 和既有效果/容量结论保持。

## 上次风险闭环结论（2026-10-03）

- **OI-019 编码超时和本机启用已处理**：复用现有 ColQwen 加载参数，SDPA+NF4/256 token 完成多模型共存与两份实际 PDF 共50页发布/检索，启用配置已持久化。图表/小字/公式语义验收尚未完成。
- **OI-011 Trace 接线工程完成**：HTTP/WS、Agent 工具/文档图/缓存、Debug、Studio 编译图都透传根 Trace、记录实际时间或缓存来源链接并保留脱敏；真实 LLM 普通问题生成/引用 guard 通过。Token/cost、外部硬取消、打包和持续负载仍单列待验收。
- **性能局部修复、效果仍失败**：BM25 同公式优化后 Medical100999/dev100 单并发 P95=638ms，4 并发=1465ms；200次无错误、逐题排序与改动前一致。Recall@5=0.63/MRR=0.5278。重排池20实验无收益，未改默认；QASPER181 holdout未用。
- **OI-020 保留：桌面常驻启动**：自动审批再次拒绝后台启动（`blocked by policy`）。启动脚本已修复 Conda 别名并支持刷新最新用户环境；需在本机执行 `.\start-electronrebuild.ps1 -RefreshRagEnvironment`。临时真实 API 冒烟通过，不冒充桌面重启已完成。
- 问题的可执行方案、逐文件必要性、真实指标及本机证据见 [本轮风险处理报告](RISK-CLOSURE-20261003.md)。整体生产 NO-GO，未提交/推送。以下记录保留当时状态，不覆盖本轮结论。

## 上一轮风险处理（2026-10-03）

- **本机 Docker/Qdrant 已就绪**：保留通信目录后 Docker 恢复；服务只监听 `127.0.0.1:6335`。现有1328点及公开100999点逐条迁移核验通过，原 Local 库保留；生产入口已支持服务端及本机代理隔离。用户连接环境变量已持久化，应用需重启读取。后台启动后端被自动审批拒绝，未启动常驻后端。
- **OI-019 接线缺口已修复，启用仍阻塞**：视觉发布/回滚、源文件与资产哈希、generation/范围过滤、证据校验和当前版本 JIT 已补齐。真实 ColQwen GPU 查询成功，图片编码超过120秒，被终止且无子进程残留；原生视觉开关继续关闭，需决定资源或模型方案。
- **OI-011 部分完成**：生产本地模型已接入进程超时/取消；永久阻塞、工具超时、错误及启动失败恢复通过；真实 GPU 超时退出已验证。WebSocket 的准备/生成/校验/终态和实际检索时间已记录；HTTP 非流式、全部 Agent/缓存、外部网络及打包环境仍未全面验收。
- **效果门仍 FAIL/BLOCKED**：公开 dev100 的服务端 Dense 暖 P95=728ms；混合重排=1227ms，Recall@5=0.63、MRR=0.5278。QASPER 窗口试验无收益，未加入生产；独立语义引用验收和 Graph HTTP402问题继续保留，holdout未用。
- **验证**：相关回归155通过，后续直接相关复验81通过，无新增 Ruff；真实接口验证3份原资料的限定检索/校验/JIT，以及准确资料清单和完成 Trace。完整文件增量、证据、恢复方法及待决策项见 [风险修复报告](RISK-REMEDIATION-20261003.md)。本轮未提交/推送。

## 最新深入检查与修复（2026-10-02）

- **OI-016（已修复）来源校验绕过**：修复前，无 `source_span` 的候选只要文档/chunk/generation 匹配，伪造正文、哈希、文件位置、页码或字符范围也能通过。现复用当前源 chunk 校验正文及定位；已有锚点不得丢弃，锚点的引用哈希、字符范围、原文版本、来源页与文件位置必须一致。源校验期间切换 active generation 会明确拒绝旧结果。旧无锚点数据仍允许与实际存储一致的完整正文或逐字子范围，不能据此宣称已有完整原文锚点。
- **OI-017（已修复）证据缓存范围与状态错误**：文档分析会缩小 allowlist 而保留 `scope_ref`，原键可能复用另一文档结果；原缓存还会保留导入前的空结果、重建前的正文，以及已编辑笔记/已撤回审核。键现使用实际完整 scope 和当前发布版本、内容哈希、嵌入指纹、检索配置及提供方实例；缓存命中重新核验源 chunk，过期后重新检索，当前源仍损坏时明确失败。只缓存文档证据，笔记、知识卡片和审核每次读取当前状态；无 manifest 的实际检索服务不复用文档结果缓存。缓存保留最多 128 项，证据与原检索快照均深拷贝。API 和 Studio 的延迟服务均已接入相同版本及校验接口。
- **OI-018（已修复）JIT 搜索后读取当前索引失败**：实际 Agent → Qdrant/BM25/manifest 路径复现搜索返回片段、读取却报 `Knowledge chunk no longer exists`。原因是读取入口只查 legacy generation。现沿检索服务的可信范围与 active generation 定位片段，章节邻居沿锚点 generation 读取；旧版/已删除片段不得返回。公开工具参数和返回合同保持原样。
- **验证**：新增 28 项测试，并加强既有真实 Agent 存储集成测试。先完成定向 45 项，再复现并修复 4 项字符范围/发布竞态问题，补充 2 项未接线提供方的明确失败测试；最终 51 项定向用例随相关聊天 WebSocket、文档分析、来源证据、索引发布/失败回滚和 Studio 回归，共 **117 项通过**。覆盖导入、空结果缓存、重建、相同 chunk ID 跨版本、删除、全库新资料、模型指纹变更、源 chunk 丢失、范围缩小、审核撤回、知识卡片编辑/删除和缓存查找期间发布新资料。关键 Ruff 检查通过；与本轮修改前对照无新增完整 Ruff 诊断（保留原 `__all__` 排序问题）。diff 检查通过。
- **证据与边界**：本机忽略目录 `data/benchmarks/rag-deep-audit-20261002/` 保留修改前备份、失败复现、测试 XML、本轮 diff 和校验汇总。测试采用隔离数据目录、实际本地存储和受控向量，没有改动用户资料、默认功能开关或调用付费模型。本次为功能/来源一致性检查；公开效果门仍 FAIL/BLOCKED，容量、native/GPU 硬中断和完整答案 Trace 仍按 OI-011 保留。未提交/推送。

## OI-019：原生视觉侧索引合同（2026-10-02历史诊断；接线已修复，启用仍阻塞）

- **核验**：当前关闭的 ColQwen 原生多向量路径使用 `VisualRetrievalService` 包装器，其接口只有 `retrieve`，缺少 `validate_evidence_candidates`、`evidence_cache_version` 和当前版本 JIT 读取。它返回的视觉页片段属于独立侧索引，不能直接交给文本源 chunk 校验器证明出处。用实际包装器实例、受控依赖复现 API/Studio 接口缺口，无需加载视觉模型。
- **本轮防护**：Agent API/Studio 对无发布版本接口的提供方禁用结果缓存，对无来源校验接口的结果抛出明确 `RagRetrievalError`，不静默信任或误报来源校验通过。当前原生视觉开关仍关闭；现有 OCR、VLM 文本描述和 Graph 路径的功能状态见页首。
- **可实施方案（推导）**：基于 [Qdrant payload 过滤](https://qdrant.tech/documentation/concepts/payload/)、[Qdrant 多向量](https://qdrant.tech/documentation/manage-data/vectors/) 和 [ColPali 官方页图检索实现](https://github.com/illuin-tech/colpali)，复用现有视觉 store/coordinator：为页图记录加入源文件/资产哈希、文档、页码与 generation；检索和读取都按可信范围及当前发布版本过滤；校验页图资产，补齐视觉证据读取接口；文本与视觉发布失败时保留上一组可用版本。再测试删除、重建、源图丢失、失败回滚及真实模型容量。
- **保留原因与决策**：该修复涉及视觉写入、资产、侧索引发布和读取的完整生命周期，当前原生模型资源/性能仍未验收；不能通过复用文本校验器或跳过校验宣布通过。本轮不扩展多模块视觉重构。待用户决定继续保持原生视觉关闭，或安排专项接线并明确 CPU/GPU 容量预算。公开效果、通用大库容量与硬中断问题继续按原条目保留。

## 最新功能完善与验收（2026-10-01）

- **OI-015（已修复）Agent 空结果异常**：真实 Qdrant/BM25/manifest 与 Agent 工具集成测试复现：限定文档无命中、删除资料或请求不存在文档时，默认合并 limit 变成 0，抛出 `multi-query result limit must be positive`。只在知识工具调用合并前保证容量至少为 1；结果仍为空、无证据/引用，不放宽范围，也不把真实通道故障改成成功。
- **OI-011 部分补齐：聊天路由历史持久化**。复用既有 Debug SQLite 快照表及脱敏函数；保留最近 100 条路由、检索、证据 ID、引用和校验结论，支持后端重启恢复及恢复后的校验更新。更新不改变原请求排序，清理只作用于聊天诊断记录；普通 Trace/坏例的不可覆盖合同保留。问题原文和证据正文不落盘，当前进程的实时查看保持原行为。
- **聊天实际接口合同验证**：临时数据目录内执行 WebSocket 生成/校验及诊断列表 API；正常持久化、路由记录写入失败、校验结果写入失败三种路径均正确返回有引用的最终答案。记录失败有异常日志；未通过吞错或替换答案使测试通过。
- **Agent 查询嵌入缓存已核验**：实际工具 → RetrievalService → Qdrant/BM25/manifest 调用链中，同查询/范围/版本只计算一次向量；换范围、发布新 generation 或更换模型指纹会失效。模型指纹不匹配时 Dense 拒绝旧索引并降级 BM25，删除和不存在文档不会返回旧内容。模型用受控测试向量，不解释为真实模型效果或性能验收。
- **验证**：新增 9 个测试场景，3 个历史诊断测试在修复前失败；缓存集成测试另外复现上述空结果异常。修复后 6 个相关测试文件共 **62 项通过**。关键 Ruff 检查通过，完整 Ruff 与本轮修改前对照无新增诊断，diff 检查通过。证据在本机忽略目录 `data/benchmarks/rag-followup-20261001/`；原有工作区改动保留，未提交/推送。
- **保留边界**：本次补齐的是聊天路由/证据/校验历史及 Agent 查询向量缓存调用验证，未完成完整答案事件树、ScopedEvidenceService 缓存的所有消费路径、多进程容量或 native/GPU 硬中断；公开检索/答案质量门仍未通过。

## 最新功能启用与聊天链路更新（2026-10-01）

详见 [启用与聊天验证报告](RAG-ENABLEMENT-AND-CHAT-VALIDATION.md)。以下是本轮状态，后文“Graph 默认关闭”等描述保留为历史记录。

- 已修复“本地的资料库有什么？”目录路由、旧索引缺失 embedding 指纹、回答格式误当章节、关系问法未触发 Graph、VLM 同端点凭据继承及 Agent JIT read 类型/范围问题。三份现有资料文本索引重建成功；真实前端目录、论文内容问答和引用卡片通过。
- Graph/OCR/公式/VLM/QueryRouter/JIT/缓存已启用；真实水箱论文 4 条严格回源关系，真实资料 Graph 通道召回通过。图预算从 250ms 调为 1000ms 后，聊天关系问题三轮均 `hybrid+graph`、无超时降级。当前模型真实调用可用，本轮没有复现历史 HTTP402。
- **OI-012（本轮功能修复通过）**：已定位模型漏声明原文关系端点的缺陷，Graph 专用解码补齐来源可核验的声明；Measurement 与任务书已完整重建并发布图，新增导入、复用和图检索通过。详见下节；模型持续错误仍明确失败并保留旧 READY。
- **OI-013（未解决）**：ColQwen 权重约 7.89GiB，当前 GPU 可用约 2.62GiB、系统空闲内存约 2.1GB，不能直接加载。另需补齐 QueryRouter 参数与证据验证转发，继续关闭；VLM 图片代理文本已在用。
- **OI-014（验收保留）**：跨语言逐句支持度、公式/图片语义质量、暖检索 P95 与硬中断未达成生产证明；原生 Electron 文件打开未实测。浏览器新聊天偶发旧会话异步恢复单列待复现，未扩大修改会话生命周期。
- 真实 JP2 图片描述兼容已修复；Measurement 本轮已成功重建，当前 generation 的 8 张图片均生成描述，旧失败状态已随正常发布更新。

## OI-012 资料构图与导入修复验收（2026-10-01）

- **根因**：捕获 Measurement 当前分块 `chunk_f4eb16eb85649adf8340c271` 的首次与修复输出。两次均漏声明原文中存在的 `deterministic` 端点，严格 schema 拒绝整个对象，继而阻断索引原子发布；不是文件路径、文本解析或向量写入失败。
- **最小修复**：只修改生产模块 `backend/rag/graph/extractor.py`，版本 `graph-1.1.3`。复用原校验器；仅当字段 schema 已通过、错误仅为端点漏声明时，补齐能在源 chunk 中匹配的实体声明，类型为 `other`，不推断类型、描述或新关系。随后重新执行完整 schema、原文引用和关系方向/谓词校验。虚构端点、无效证据、超出容量仍失败；一次模型修复及事务回滚合同保持原样。
- **原文件验收**：Measurement 255 chunk / 8 条图关系，任务书 29 chunk / 2 条；原水箱论文保持 185 chunk / 4 条。三份资料均 READY，14 条已发布关系的引用范围和源哈希全部核验通过，三份原文件 SHA-256 未变。Measurement 8 张图片描述均成功，包括此前失败的 JP2。来源核验不等同于语义引用准确率验收。
- **接口冒烟**：新 TXT 导入 HTTP201，真实模型生成 2 条关系；重复导入 HTTP201、`reused_existing=true`，generation 不变。新资料、Measurement、任务书的限定文档检索均 completed，Graph 分别召回 1/2/1 个 chunk，无文档范围漂移。临时资料经原删除接口清理，原 3 份资料保留。
- **局部验证**：新增 6 个回归场景（补齐端点、拒绝无支持谓词、虚构实体、部分词匹配、伪造证据、实体容量），修复前两个正例失败；修复后 extractor/indexer/index_service 共 53 项通过。失败原始输出及三次真实模型调用复放通过；两份修改的 Python 文件 Ruff 无错误，diff 检查通过。
- **剩余边界**：36 页 PDF 本次完整重建耗时约 845.5 秒，任务书约 104.4 秒；长文档导入耗时仍需后续评估。提供方断连、持续错误 JSON/证据仍会明确失败，不发布不完整图。本轮为功能验收，未新增效果指标或原生 Electron UI 验收；OI-013/014 保留。
- **证据**：本机 `data/benchmarks/graph-import-remediation-20261001/` 下 `replay-doc_d4d1a15d06f79a7534f4a812.json`、`failed-chunk-fixed.json`、两份 `reindex-*.json`、`validation.json`、`source-and-scope-checks.json`、三份 `trace-*.json`。模型原始输出与源内容仅保留于本机忽略目录。

## 最新效果验收更新（覆盖下文历史“暂缓”状态）

用户已确认公开数据按Recall@5≥0.80、MRR≥0.70、独立引用准确率≥0.90、暖检索P95≤800ms做技术验收；生产业务批准仍未取得。详见 [效果验收报告](QUALITY-ACCEPTANCE.md)。

- OI-004/006：已补同题Dense/Hybrid与池8/12/20；512 token/池8候选将QASPER Recall@5提升至0.8333、MRR0.5424、暖P95约460ms，MRR仍不合格。低精度试验无确认收益，相关实现已撤回。
- 256 token切块诊断Recall@5=0.7759、MRR=0.5234，不采用；候选有界重排配置已保存为quality-rerank512.json。已导出54条排序坏例及论文聚类bootstrap，开发集提升尚未通过独立holdout确认。
- OI-005/011：完成SciFact全5183文档/开发100题与test300回归、MedicalRetrieval全100999文档/固定100题诊断。SciFact test Recall@5=0.7821；中文最佳Recall@5=0.63、混合重排P95约2982ms，门槛未过。Qdrant Local大库限制不能靠重排参数消除。
- OI-010：完成同题200次真实答案复放；复用原有直接答案合同后误拒答从72/94降到44/94，仍未解决。公开人工标签校准显示当前Flash/Pro judge支持精确率低于0.90；已封堵仅凭calibration_id宣告已校准的评测入口，引用语义验收继续BLOCKED。
- OI-007/008：已下载公开多跳标注，30题/259篇（含干扰）执行真实抽取/Graph/Graph+BM25。**DeepSeek HTTP402造成85篇抽取失败，另1篇证据逐字校验失败**，只有部分索引；不得宣告Graph质量通过。保留源文件、原失败日志、诊断与qualification记录。
- 已完成抽取仍有371条unsupported_predicate、59条missing_entity拒绝，关系覆盖缺口保留；按原文金标验证后修复，不能直接放行未知关系。基准工具已修正失败状态和HTTP402后的待执行请求取消。
- **用户待决策：检查DeepSeek余额/计费并恢复额度，或指定已配置且可用的提供方；确认真实用户文档/问题/语义标注及容量/预算。** 当前不自动充值或切换未知提供方，停止额外API抽取。
- QASPER181题holdout保持未用；Graph/Router默认开关保持原值；本轮不推送。历史没有版本的坏例、硬取消、完整Trace/用户权限覆盖仍按原条目保留。

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


## OI-010：S09–S16功能收尾，效果验收按用户决定暂缓

- 用户明确确认“仍以功能正常为主，效果验收暂缓”；工程功能结果见final-benchmark.md。603项RAG回归、64项固定CI、32次8组真实模型功能调用及两轮1000次混合请求通过；实际Studio图路径/原文查看通过。合成输入只有单文档单chunk，所有检索排序指标1.0无区分力，不作为生产质量分数。
- 已补齐source gold/answerability/OR-of-AND/独立答案标注协议和冻结runner；有标注时才能报告语义支持度。未收集新的真实用户金标、人工盲标或校准judge，答案N=0；生产Citation Accuracy/Faithfulness/false abstention均暂缓。正例有召回也不能自动认为claim充分支持。
- 暂缓原任务：S09质量池实验、S10语义/完整答案验收、S11真实/QASPER/未知文档新评测、S14质量与holdout门、S16真实消融/bootstrap/默认策略推广。181题holdout未运行；历史HF/QASPER质量问题仍保留。
- 可行恢复顺序：先冻结真实原文件/source/claim/answerability金标及人工标注，再运行开发集分层配对和judge一致性，最后冻结后运行holdout；只有满足正式门槛才启用默认策略。本轮不再要求重复批准功能开发。

## OI-011：历史工程边界（最新状态以2026-10-03更新为准）

- 同步hard cancellation：每通道/图/reranker使用协作deadline，晚结果拒绝并保留原因；已阻塞native/GPU调用不能硬中断。1000次负载使用可返回的注入故障，不能据此证明hang隔离。后续若有实际阻塞复现，优先在既有服务边界做受限worker/process隔离及取消/并发回归，不把线程future.cancel当硬取消。
- 容量：1000查询是51字符单文档warm功能负载，reranker关闭，结束RSS不是峰值；大库、多进程、长文档持续导入/答案生成的资源预算与生产P95尚未验收。保留现有Qdrant Local/BM25 JSON/Graph SQLite，先以代表性输入实测，再决定adapter迁移。
- Trace：Graph seeds/paths/generation/root及Studio终态持久化已完成；Companion路由/证据/校验历史的持久化与重启恢复、Agent查询嵌入缓存的调用和版本隔离已验证；ScopedEvidenceService范围/发布/原文一致性与API/Studio缓存接线已补齐定向验证，见OI-017。绝对阶段起止时间、完整answer事件树和Studio独立Agent图仍未全面核验，不能宣称全部请求100%全链记录。
- 历史坏例：当前冻结Graph case实际回放通过，旧generation/config/model不可用时失败；S00–S11质量坏例缺失的旧索引/原文/各阶段记录不能自动补成“已定位/已修复”。恢复旧快照或原文后再回放，未修质量坏例按OI-010暂缓。
- 旧引用：无source_span的legacy JSON继续兼容，当前生产消费点校验scope/generation/源chunk，完整原文锚点需重建。现有逐字claim检查不能替代语义faithfulness；本轮不将未核验正例标充分支持。
- 远端：本轮未提交/推送，GitHub CI未执行。保留其他任务工作区改动；后续只暂存最终报告列出的RAG相关文件。
