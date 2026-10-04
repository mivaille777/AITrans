# RAG Luna 执行状态

## 最新效果与并发实施（2026-10-03）

- BM25候选按分数筛选后执行原权限/代际检查；推理请求FIFO防抢占，记录实际排队/执行耗时。最终81项定向测试和Ruff通过；800次完整公开检索零错误，700次原配置排序一致。
- 当前环境单请求P95=717ms通过；C2=1047ms、C4=1778ms失败，Medical Recall@5=0.63/MRR=0.5278。候选并集扩大至0.78仍不足，未推广无收益参数。
- Graph当前版本重建259/259零失败；混合Recall@5=0.60、完整证据@5=0.20，效果失败。
- MS MARCO独立验证120条支持判定精度0.70仍不合格；200条原子事实盲评材料、262个AITrans句级单元与44条拒答审查材料已生成，人工标注尚未完成。
- 逐文件必要性、原始证据及待决策见 [本轮报告](QUALITY-CAPACITY-20261003.md)。整体生产NO-GO；未改模型/用户索引/阈值，未提交推送。以下为历史状态，不覆盖本轮结论。

## 最新风险处理与复验（2026-10-03）

- 原生视觉编码超时已修复；NF4+SDPA/256 token 在本机通过三模型共存、50 页实际 PDF 发布及范围检索。用户环境已保存启用配置，完整视觉语义质量仍待验收。
- HTTP/WS、Agent 工具/文档图、缓存、Debug 及 Studio 编译图补齐根 Trace 接线和实际时间。真实 DeepSeek HTTP/WS 答案带引用并通过既有 guard，不等同独立 Citation Accuracy 验收。
- Medical100999/dev100 配对：最小 BM25 优化保持逐题排序完全一致，文本候选配置单并发 P95=638ms；4 并发=1465ms，无检索错误。Recall@5=0.63、MRR=0.5278，质量/并发门仍失败。扩大重排池无收益，未采用；holdout未用。
- 主定向回归148项通过，编译图补充复验另列报告；无新增 Ruff。常驻后台启动被自动审批以 `blocked by policy` 拒绝，现有脚本已支持 `-RefreshRagEnvironment`；需用户在本机手动启动。未提交/推送，生产仍 NO-GO。

详见 [本轮文件、实测及保留问题](RISK-CLOSURE-20261003.md)。以下保留上一轮验收范围。

## 上一轮风险修复（2026-10-03）

- Docker 修复、本机 Qdrant 部署及现有1328点/公开100999点迁移核验：PASS；原库保留。服务端连接环境配置已持久化，应用需重启读取；后台启动后端被自动审批拒绝。
- 原生视觉发布、范围、来源及当前版本读取：局部功能 PASS；真实图片编码120秒超时，开关仍关闭，资源/模型方案待决策。
- 本地推理进程超时/取消/恢复：PASS；真实 GPU 超时无残留。聊天 WebSocket 生命周期与实际检索时间：PASS；全入口 Trace、外部请求及打包硬取消仍 PARTIAL。
- 公开100题服务端 Dense/混合重排暖 P95：728/1227ms；召回/排序和独立引用语义门仍 FAIL/BLOCKED，生产 NO-GO，holdout未用。
- 相关回归155通过，后续直接相关复验81通过；真实接口3份资料的限定检索/来源/JIT和资料目录回答通过。无新增 Ruff；未提交/推送。

详见 [风险修复、文件明细与待决策报告](RISK-REMEDIATION-20261003.md)。下文保留各阶段历史验收范围。

> 当前功能状态（2026-10-02）：Graph/OCR/公式/VLM/QueryRouter/JIT/缓存已启用，三份现有资料均已发布文本和图索引，导入与构图修复已验证。详见 [当前架构](RAG-ARCHITECTURE-CURRENT.md) 与 [问题清单 OI-012](OPEN-ISSUES.md)。下文按阶段保留历史结果与当时开关决策；公开效果验收仍 FAIL/BLOCKED，功能通过不代表生产质量通过。

> 最新深入检查：来源校验绕过、证据缓存范围/资料状态错误、JIT 当前 generation 读取失败均已修复（OI-016/017/018），并补齐校验/缓存命中期间发布新版本的竞态保护。实际 Qdrant/BM25/manifest 下导入、重建、删除、模型变更及片段/章节读取通过；相关聊天、文档分析、索引回滚和 Studio 共 117 项回归通过，Ruff 无新增诊断。只修改 5 个生产模块，保持现有工具参数、返回合同和默认开关；隔离测试记录见 `data/benchmarks/rag-deep-audit-20261002/`。关闭的原生视觉侧索引接线缺口已记录 OI-019，无来源校验的 Agent 提供方会明确失败；效果、容量、硬中断与完整答案 Trace 验收继续保留。

> 最新功能完善：修复 Agent 无命中/资料删除后的空结果异常（OI-015）；聊天路由与引用校验历史已脱敏持久化并可重启恢复（OI-011 部分补齐）；Agent 查询向量缓存的范围/索引/模型版本隔离通过实际存储集成测试。相关 62 项回归通过，Ruff 无新增诊断。详见 [最新问题清单](OPEN-ISSUES.md)。效果、完整答案 Trace、容量与硬中断验收继续保留。

- 仓库：`mivaille777/AITrans`
- 分支：`electronrebuild`
- 当前执行依据：用户已恢复效果验收，并确认公开数据候选门槛为技术标准。历史功能收尾见 final-benchmark.md；最新效果、失败项及外部阻塞见 [效果验收报告](QUALITY-ACCEPTANCE.md)。完整生产验收仍 NO-GO。
- 本轮基准提交：`4b0d802c168a00cf12a967cfcdb24c1ba2ed1f4c`；本轮修改未提交/推送。
- 最新公开技术验收：FAIL/BLOCKED。QASPER候选Recall@5=0.8333、MRR=0.5424；SciFact回归Recall@5=0.7821；MedicalRetrieval诊断Recall@5=0.63，暖P95约2982ms；独立judge未合格，引用准确率未验收。
- 历史公开多跳Graph评测：30题/259篇，HTTP402导致85篇失败、另1篇逐字证据错误；该次部分索引资格明确BLOCKED，尚需重测。已保存54条排序坏例、44条误拒答；181题holdout保持未用。最新真实资料调用未复现HTTP402，见问题清单。
- 本轮验证：收尾定向38项、补充Graph模块5项、固定CI64项均通过，5个评测脚本及2个新增测试文件Ruff通过；不改变生产默认开关或放宽语义验收。
- 执行计划：`D:\AITrans\AITrans-RAG-Production-Improvement-Plan-GPT6-Luna.md`
- S00.1：PASS
- S00.2：PASS
- S00.3：BLOCKED（已建立基线与数据/模型/索引/机器指纹；生产数据、经确认门槛、完整坏例回放缺失）
- 生产 Go/No-Go：BLOCKED；当前功能开关见页首，不能据此宣称生产质量达标
- S01.1：PASS（只读检查三库 document/chunk/generation 差异；当前 generation 缺失会明确报告 incomplete）
- S01.2：PASS（manifest generation 状态迁移、active pointer、旧版保留和重启恢复）
- S01.3：PASS（Qdrant/BM25 generation 并存、定向读写删除）
- S01.4：PASS（校验后原子发布；检索只读取 active generation；失败清理半成品并保留旧版）
- S01.5：PASS（PDF/DOCX/HTML/TXT 导入、重导入、重启、删除与零残留）
- S01 Stage 门禁：PASS（工程一致性门；不代表生产质量门通过）
- S02.1：PASS（版本化 source span、Unicode codepoint 定位、旧 JSON 兼容）
- S02.2：PASS（Docling 低文本/页序/OCR/表格来源页诊断；空文档拒绝；真实三页 PDF 集成验证）
- S02.3：PASS（Chunk SourceSpan 集成；Qdrant/BM25 共 1312/1312 精确回源；错文本/错页失败关闭）
- S02 Stage 门禁：BLOCKED（缺真实用户文件及引用金标；已知论文集检索 P95 825.297 ms；生产阈值未批准）
- S03.1：PASS（本次补齐真实 provider 内容指纹的写入、复用和 Dense 防混用；同名同维度权重变更可检测，见 S00-S04-REMEDIATION.md 和 OI-003）
- S03.2：PASS（Qdrant search 前后按 allowlist 与 active generation 过滤；注入越权/过期 payload 均拒绝）
- S03.3：PASS（环境化 batch/warmup 配置；Frozen dev100 Vector Only、冷启动/内存、缩写/跨语言 bad cases、generation 排序 smoke 已完成，见 [S03.3.md](S03.3.md)）
- S03 Stage 门禁：BLOCKED（质量门保留；本次已补齐模型内容指纹与防混用；门禁语义和应用级 scope 的完整验收仍待后续。用户授权的 HF 评测及 S04 已完成，当前效果提升延期）
- S04.1：PASS（scientific-v2、DOI/化学式/缩写/CJK 混排；固定标识符 Top-1 7/7；BM25 倒排计算）
- S04.2：PASS（tokenizer 版本迁移；重建/删除/重启/active scope；完整 SciFact 和中文 MedicalRetrieval 评测及坏例保存）
- S04 相对 Sparse/安全门：PASS（补测 S00 Sparse 原代码，冻结 QASPER dev100 Recall@5/10 持平、MRR/nDCG 上升；过期/越权候选 0）
- S04 完整 Stage 验收：BLOCKED（人工 Debug Studio UI 未核验；公开检索质量缺口见 OI-005；生产 Go/No-Go 仍 BLOCKED）
- S05.1：PASS（候选来源/图路径/span/generation/trace 字段向后兼容）
- S05.2：PASS（共享请求快照、Vector/BM25 适配、空范围拒绝、越权/过期候选过滤）
- S05.3：PASS（现有入口接线、generation + chunk ID 去重、原始通道 rank/score 保留；冻结 V/B/VB 同配置排序无变化）
- S05 完整 Stage：BLOCKED（工程完成；效果调优暂缓，公开全库 Dense/Hybrid、人工 UI 和生产质量门未验收，见 S05.md / OI-006）
- S06.1：PASS（SQLite 六表、事务回滚、scope/allowlist/active generation 过滤和删除）。
- S06.2：PASS（工程抽取/回源；10 个功能标注用例 TP=6/FP=0/FN=0，不能解释为生产质量）。
- S06.3：PASS（显式别名、同名异物、跨文档定义和跨 scope 消歧功能验证）。
- S06.4：PASS 功能（本轮有限反馈修复后，两篇固定 PDF 均导入/复用/重建/删除通过，8 条发布关系精确回源；S06 完整生产质量门仍保留，见 OPEN-ISSUES-REMEDIATION.md / OI-007）。
- S07.1：PASS 工程（有界字面实体/别名匹配、同名歧义拒绝、原始 chunk 回源）。
- S07.2：PASS 工程（1–2 跳、逐边 span、scope/版本/过滤保护、节点/路径/边限额与协作截止时间）。
- S07.3：PASS 工程（可关闭 Graph → 原文 → RRF/重排入口，失败降级；真实模型合成输入的 9 个图请求 graph_hits=1）。
- S07.4：固定小图 PPR 与 G/GV/GVB 功能参考通过；真实多跳质量、成本和人工 UI 验收 BLOCKED。
- S08.1：PASS 工程（结构化计划、原文固定参与、标识符保护、异常/超时回退、JSON 往返兼容）。
- S08.2：PASS 工程（可关闭题型/通道预算、可信 scope 不变、语义 proposal 不能提权、空范围/空请求保护）。
- S08.3：PASS 合成功能配对（真实模型/存储四组开关 16 次调用、0 范围漂移；生产分题型收益/成本/P95 与人工 UI 未验收）。
- S08 完整 Stage：BLOCKED；新路由默认关闭，现有改写默认值保留，见 S08.md / OI-009。
- 当前工程任务：按用户“先解决问题清单中的问题”修复完整论文抽取与非对象路由诊断；48 项局部测试、148 项调用链回归通过，Lint 无新增问题，两篇真实 PDF 生命周期通过。S06.4 功能阻塞解除，S06/S07/S08 完整生产质量门仍 BLOCKED。随后用户明确授权提交推送，本次提交范围为 RAG 工程及修复，其他工作区改动保留；这是本轮开始前的历史状态；本轮 S09–S16 结果见下节。详见 [问题修复报告](OPEN-ISSUES-REMEDIATION.md)。
- Holdout：181 个问题、56 篇论文，已冻结、未运行、不得用于调参
- GitHub 写入：S00–S04 原已推送至 `570864be`；本次用户授权将后续功能修复、S05、S06–S08 工程提交推送至 `origin/electronrebuild`，具体远端提交以 Git 推送结果为准；不表示生产质量门通过。
- 工作区原有用户修改：保留；提交时只暂存任务书当前允许的文件

详细指标见 [S00.md](S00.md)、[S00.3.md](S00.3.md)、[baseline-manifest.json](baseline-manifest.json) 和 [gate.json](gate.json)。S01 汇总和子任务报告见 [S01.md](S01.md)、[S01.1.md](S01.1.md)、[S01.2.md](S01.2.md)、[S01.3.md](S01.3.md)、[S01.4.md](S01.4.md)、[S01.5.md](S01.5.md)；S02 汇总和子任务报告见 [S02.md](S02.md)、[S02.1.md](S02.1.md)、[S02.2.md](S02.2.md)、[S02.3.md](S02.3.md)；S03 子任务报告见 [S03.1.md](S03.1.md)、[S03.2.md](S03.2.md)、[S03.3.md](S03.3.md)；S04 汇总见 [S04.md](S04.md)、[S04.1.md](S04.1.md)、[S04.2.md](S04.2.md)、[S04-benchmark-manifest.json](S04-benchmark-manifest.json)。待用户提供/确认事项见 [OPEN-ISSUES.md](OPEN-ISSUES.md)。

## 最新收尾：S09–S16（2026-09-30）

- 当前用户范围：**功能正常为主，效果验收暂缓**；最小修改、现有接口兼容、只做直接验证，不调整默认 Graph/Router/重排池。
- 连续按四批执行，完成重排测量/输入边界、证据锚点/context引用保护、独立评测输入/指标工具、坏例快照/图回放、Graph Trace/页面、固定CI、版本缓存/故障负载及8组最终功能矩阵。
- 当前受测功能：PASS_FUNCTIONAL；完整S09–S16 Stage及生产验收：DEFERRED/PARTIAL，不能宣称全部原任务条件满足。各任务ID的实现证据与未完成项逐条见 [最终报告](final-benchmark.md)。
- 验证：RAG/权限/Companion统一回归603通过、3个原有opt-in skip；随后新增终态/导出/换行问题16项定向通过；固定CI64通过；前端全套466通过，新增Trace定向14通过，类型检查通过；Python45个相关文件无新增Ruff诊断。
- 真实模型：8组×4题=32次功能调用通过；独立原文gold对齐runner32条预测可复跑；Graph冻结案例回放通过。单chunk合成输入不代表检索质量或答案支持度。
- 负载：最终1000请求、并发4、未预期错误0；12次预期失败关闭（9全通道故障、3过期版本），全部无引用；P95=139.766ms。小语料/warm/cache条件，生产容量结论暂缓。
- 实际页面：Graph seeds/paths/source chunk显示及点击通过；修复StrictMode重挂载后Trace不结束问题。此前S04/S05/S07/S08的Studio“未看实际页面”缺口在本轮合成功能路径上解除；真实论文逐句答案核对仍暂缓。
- 保留：独立人工答案标注、代表性真实语料/消融/holdout、同步硬取消/大库多进程容量、历史缺版本坏例、完整答案Trace与Agent缓存消费链。参见OPEN-ISSUES OI-010/011。
- 临时浏览器及本轮开发服务已关闭；生产数据目录未被验收runtime替换。当前未提交/推送，远端CI尚未执行。
