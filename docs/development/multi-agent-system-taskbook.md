# AITrans 科研多 Agent 系统：分阶段开发任务书

> 编制日期：2026-09-16；代码评估基线：`WebReBuild @ ad27691`。
> 前置阅读：[评估与架构设计](multi-agent-system-design.md)、[记忆系统任务书](memory-system-taskbook.md)。
> 当前状态：MA00–MA10 的实现与确定性自动验收已完成；MA10 发布报告仍将真实 Qwen3、真实配置 LLM、手工 UI 和语义质量 A/B 标为未验证，因此 workflow 不作为默认发布路径。阶段状态以第 8 节和验证记录为准。
> 路径均相对仓库根目录；不要照抄文档中历史开发机路径。后续 Codex 必须核对当时 HEAD、工作区和 AGENTS.md。

## 1. 完成标准：研究人员能得到什么

完整交付应覆盖同一条工作流：导入/选择论文 → 快速理解 → 深入分析/跨论文比较 → 有来源的笔记与图谱 → 论文写作草稿及局部修订 → 持久保存与后续复用。

| 用户目标 | 最终产物 | 完成判据 |
| --- | --- | --- |
| 快速读懂论文 | 研究问题、贡献、方法、数据、实验、局限、待核查项组成的阅读卡 | 每类标注来源和覆盖；局部输入不宣称完整阅读 |
| 理解图表和实验 | 有页/表/图定位的解释 | 数字、单位和实验条件正确，无法识别时说明局限 |
| 比较论文 | 比较矩阵、共识、分歧、研究方向建议 | 每个事实单元有来源；不比较不同条件的指标而不说明 |
| 记笔记 | 原文引用、AI 整理、用户补充及关联对象 | 原笔记不被覆盖，重复保存不生成重复对象 |
| 生成知识图谱 | 有来源的条目/关系建议与接受后的持久关系 | scoped 候选、允许的关系类型、重复实体处理、accepted/rejected 状态准确 |
| 辅助论文撰写 | 大纲、章节草稿、参考清单、局部修订 diff、Markdown 导出 | 不编造论文/DOI/实验结果，仅修改授权范围，引用可追溯 |
| 执行复杂研究任务 | 真实子任务时间线、部分结果、最终产物 | 可取消/恢复，不重复已提交写入，预算有限 |
| 跨会话继续研究 | 工作区与个人记忆的相关上下文 | 由记忆系统提供，作用域和删除撤销规则贯通所有专家 |

首版不承诺全自动发表论文、完整 Office 编辑器、互联网自主研究或无人监督实验分析。文档中的“Agent”以任务能力为边界，不要求所有节点都有 LLM。

## 2. 执行规则与共享契约

1. 单一权威根图；fast/single/workflow 按任务选择。专业角色为 `document/research/writer/curator`，translation/polish 是共享语言工具。
2. 先修证据作用域，再接新专家。所有检索和工具请求走可信 ScopeContext，空授权集合不能解释为全库。
3. 子任务必须有 ID、依赖、明确输入引用、预期产物及验收条件；结果按 task_id 合并，不按角色名覆盖。
4. 同一次 run 的 profile、scope、memory snapshot 和预算统一解析。并发专家不能直接修改共享可变上下文。
5. 复用原有 RAG、研究笔记、Evidence Ledger/Review Gate、canonical KnowledgeWorkspace 和 typed tools；不要新增另一套事实数据库。
6. 私有专家推理不进入产物或长期记忆。用户可见的简短任务理由、证据、决策和结果可以记录，trace 默认只记录元数据。
7. 已发表文献证据、用户实验材料、Agent 建议和用户个人偏好分别标识，不相互冒充。
8. 简单工具成功后直接交付；Supervisor/Writer 不重复全文生成，只有任务要求的转换才增加模型调用。
9. 业务写入使用稳定 operation_id 和回执；原写工具权限及未知效果处理继续有效，读超时不能作为安全重放写入的理由。
10. 每阶段交付实现、测试、必要回归和记录。禁止删失败测试、跳过 scope 检查或以 mock 结果代替真实质量验收。

建议目录：`backend/agent_core/orchestration/`（调度/预算/契约校验）、`backend/agent_graph/`（根图和专家子图）、`backend/models/agent_tasks.py`、`backend/models/agent_artifacts.py`、`tests/multi_agent/`。名称可遵循实施时项目约定调整，但必须保持一个生产实现，并同步文档。

### 2.1 与记忆开发的依赖

多 Agent 阶段按 `MA00 → MA01 → … → MA10` 推进。Mxx 表示记忆任务书阶段，MAxx 表示本任务书，二者编号不可混用。

| 阶段 | 记忆依赖 | 未完成时的处理 |
| --- | --- | --- |
| MA00–MA02 | 无硬依赖，读取 M01 契约 | MemoryPort 返回 unavailable 的测试替身；不宣称有跨会话记忆 |
| MA03–MA07 | 应与 M01–M04 对齐 | 调度和专家可先通过 NullMemory 测试；身份/作用域不能省略。真正记忆接入在共享改动中完成 |
| MA08 | M01–M07 的真实服务和相关删除接口 | 依赖未落地则此阶段记 blocked，不创建重复 MemoryRepository |
| MA10 | M08/M09 中需要的隐私、删除、备份与综合验收 | 未达到则只能报告非完整预览，不能将最终记忆能力标为完成 |

推荐无环联合顺序：`MA00–MA02 → M00–M03 → MA03–MA07（与 M04 共用一次根图集成）→ M05–M07 → MA08/MA09 → M08/M09 → MA10`。实现可以分开，但共享身份/预算/根图由一份代码和集成测试验收。不能让 M07 等 MA08、MA08 又反过来等 M07。

### 2.2 阶段检查点

- MA03：新运行契约与串行路径预览，不宣称并行和子任务恢复完成。
- MA05：论文阅读/分析/章节草稿预览，不宣称完整知识沉淀闭环。
- MA07：有界协作、恢复和笔记/图谱提交可用。
- MA10：第 5 节全部硬性场景通过，才能标记完整交付。

## 3. 开发阶段

### MA00：生产基线、科研场景和评估集

目标：把当前真实行为与目标场景对应起来，后续每个角色都有业务验收输入。

任务：

- [x] 核对实际 root graph、API/Companion 入口、工具注册、依赖注入、前端调用、scope 与存储路径，记录在 `docs/development/multi-agent-system-validation.md`。
- [x] 绘出 canonical KnowledgeWorkspace、Knowledge V2、旧 graph snapshot、Research Notes、Evidence Ledger 的实际读写关系；为新 Curator 明确唯一目标接口与 note/item 映射规则。
- [x] 建立 `tests/multi_agent/conftest.py`：临时数据根、fake clock、可控 provider/tool、隔离 SQLite/Qdrant，默认无网络且不触碰用户库。
- [x] 将设计文档 F01/F03/F04/F07/F09 变成可重复 characterization 用例：错误关键词分派、scope 被忽略、同名结果覆盖、事件延后、对象重建丢记忆；在后续修复阶段转换为目标行为断言。
- [x] 建立合成科研 fixtures：论文 A/B、同名概念不同工作区、不同数据集的准确率、表格/图片、缺页文档、相互矛盾证据、用户写作稿件与实验数据。
- [x] 固定开发集与留出评估集、评分说明、调用/延迟计数方式和环境。场景至少覆盖第 5 节每项。
- [x] 跑本文件第 4 节既有基线测试，记录现有失败与限制；新评估未做前不声称架构胜过单 Agent。

交付：验证文档、fixtures、`test_baseline_contracts.py`、评估数据 schema。

验收：所有探针可在独立临时目录运行；scope 用例观察最终上下文而非只检查参数；characterization 的已知缺口不得作为“目标功能已通过”。保留已有 92 项与追加 10 项基线测试的可复现结果。

### MA01：任务、产物、角色和状态契约

目标：规划与专家输出能够被代码验证，支持同角色多实例和稳定来源。

任务：

- [x] 实现 TaskSpec、TaskResult、ValidatedTaskPlan、ScopeContext、Artifact 及具体 DocumentAnalysis/Comparison/Outline/Section/Revision/KnowledgeDraft DTO。
- [x] 校验唯一 task ID、未知角色/工具、无环依赖、输入产物类型、required 标志和最大任务数；不接受计划任意设置 profile、workspace 或模型。
- [x] 实现任务状态机与尝试记录。重复结果幂等，同任务同版本但不同哈希的结果视为冲突；不同专家实例不得覆盖。
- [x] 实现显式结果 reducer：按 task_id/attempt/version 合并，确定性排序；并发结果不更新同一个 AgentState 对象。
- [x] 建立 role registry：document/research/writer/curator 及各自允许工具；旧 reading/research/translation 名称通过兼容适配而非复制整套执行器。
- [x] 定义 MemoryPort、EvidencePort、ToolRuntimePort、ArtifactPort、BudgetPort，测试可注入纯替身。
- [x] 建立版本化 artifact store，使用数据根下 `agent_artifacts.sqlite3` 保存派生结果/源引用；原始文件只引用。临时模式用内存实现，迁移和内容撤销有接口。

测试：`test_task_contracts.py`、`test_plan_validation.py`、`test_task_state.py`、`test_result_reducer.py`、`test_artifact_store.py`。

验收：循环依赖/越权工具/伪造 scope 拒绝；两个 Document 实例结果都保留；随机不同完成顺序得到相同逻辑结果；重开 artifact store 不丢版本；旧 Agent 请求仍可解析；产物引用没有原始 Python 对象或连接。

### MA02：统一证据入口和工作区范围

目标：封闭协作检索绕过范围的问题，论文事实始终可追溯。

任务：

- [x] 建立服务端 scope resolver，区分 research workspace、board、collection，按持久成员/明确当前选区解析文档、笔记、卡片范围。
- [x] ScopeContext 显式区分 `unscoped_global` 与 `restricted(empty)`。无工作区只在产品既有允许范围搜索；空工作区返回空，不能退回全库。
- [x] 将 KnowledgeInjector/旧 AgentKnowledgeRuntime 的协作调用接到统一 Evidence Service，或先禁用不具 scope 能力的旧路径；禁止携带 raw 全图进入专家。
- [x] 图关系只能在授权集合内扩展候选；相关性为零时不能仅靠度数成为证据。中文关键词语义召回复用既有 RAG，并保留 fallback。
- [x] 对 Research Note 实施确切 note IDs 校验，不能仅按某个来源过滤后读取同来源其他工作区笔记。
- [x] 规范 EvidencePacket：源 ID/版本、引用范围、来源类别、page/element/table/image locator、status；事实引用由既有 citation service 生成。
- [x] 缓存与重复检索合并的键包含 scope_revision、源版本、查询/过滤条件、模型版本；不同范围不得共享结果。
- [x] 复用 Research Memory 新鲜度和 Stage20 Review Gate；机器核查不得改变人工 accepted 状态。

测试：`test_evidence_scope.py`、`test_graph_retrieval_boundary.py`、`test_evidence_provenance.py`、`test_evidence_cache_scope.py`。

验收：F03 合成探针不再返回 B 节点；图扩展、note 查询、RAG、图表读取、建议候选都遵守 scope；标题/图关系不能假充正文证据；不同数据根/工作区缓存不串用；当前知识和 Stage20 回归保持通过。

### MA03：统一路由、串行任务图和所有权

目标：让新计划成为主图执行的一部分，先建立可观测的正确串行路径。

任务：

- [x] 扩展既有路由为 fast/single/workflow：明确选区翻译/润色不经多角色规划；单文档理解选择 Document；独立多文档任务才拆解。
- [x] Supervisor 生成有依赖和产物要求的计划，执行前由 MA01 validator 验证；格式最多修复一次，无法确定目标则返回当前缺失信息。
- [x] 根图在专业调用前解析身份、取得会话所有权、冻结 scope 和 MemoryPacket；替代旧协作结果拼接 `context_before`。
- [x] 以串行拓扑执行连接专家接口；已完成工具输出满足用户目标时直接交付，不再默认额外生成最终全文。
- [x] 整合 AgentState、run/trace/status 和旧 planned_action 兼容投影，避免重复 route/plan 两套权威状态。
- [x] 定义 root graph_version/state schema_version；旧 checkpoint 保留兼容分发，节点映射未验证时明确拒绝，不能丢弃旧库。
- [x] 为旧 `multi_agent_mode=off/auto/force` 制定兼容语义，force 不扩大权限或启动无用角色。
- [x] 与记忆 M04 共用图接入和 source outbox；M04 未实施时保留可注入端口，不能悄悄写第二套记忆队列。

测试：`test_routing_policy.py`、`test_serial_workflow.py`、`test_conversation_ownership.py`、`test_legacy_request_compatibility.py`。

验收：“翻译这篇论文”走一次语言能力；“总结后翻译摘要”明确两步依赖；“比较 A/B 实验”产生两个不同输入任务和一个综合任务；丢失工作区拒绝执行；第二窗口抢占失败前不发生付费调用；取消/异常均释放租约。

### MA04：论文阅读与研究分析专家

目标：得到可验证的阅读卡、图表解释和比较矩阵。

任务：

- [x] 实现 Document Analyst 子图：问题/覆盖计划 → 定位读取 → 按需结构检索/图表读取 → 结构化分析 → 字段与来源验证。
- [x] 阅读卡覆盖研究问题、贡献、方法、数据、实验、局限、待核查项；每项允许 unknown，缺失材料时不捏造。
- [x] 文档覆盖记录 requested/visited/unavailable 的 section/page/element，长文不按前若干字符假定全读；在任务预算内标明未处理范围。
- [x] 实现 Research Synthesizer：从不同 Document artifacts、用户指定问题和授权研究记忆生成条件明确的比较矩阵及共识/分歧。
- [x] 复用已有 cross-document/evidence ledger 能力，限制额外检索次数；研究假设单独标记，不伪装原文结论。
- [x] 将确定性引用/类型/范围检查和必要的 claim-evidence 校验合并成 VerificationReport；partial/failed 不能输出“分析完成”而不提示缺口。
- [x] 对无 OCR/视觉模型/图表元数据的情况提供可验证降级，并允许用户沿源定位自行查看。

测试：`test_document_analyst.py`、`test_document_coverage.py`、`test_table_image_analysis.py`、`test_research_synthesizer.py`、`test_artifact_verification.py`。

验收：A/B 每格结论可追溯；不同数据集指标不被直接比较优劣；B 缺失时只给受限结果；矛盾来源被展示；图表单位/脚注/页号正确；只提供摘要时不能输出已确认的全文实验细节。

### MA05：学术写作、大纲与局部修订

目标：将阅读和研究产物转换为有依据、可编辑的论文写作草稿。

任务：

- [x] 增加 Academic Writer 注册和 gateway/prompt 角色配置，复用现有 provider allowlist，构造服务时不要求立刻有 API key。
- [x] 实现 OutlineArtifact、ManuscriptSectionArtifact、RevisionArtifact：写作目标、章节/段落 ID、版本、证据映射、建议与事实区分、待补项。
- [x] 建 WritingProject 最小管理服务：工作区绑定、大纲/章节版本、草稿保存、按 expected_version 应用局部修订、Markdown 导出及源清单；初版可使用 artifact store 专用表，禁止改造论文原文件。
- [x] 接入既有综述服务生成 review-gated Related Work；一般引言/讨论按授权证据生成，实验章节只使用 user_supplied 数据，未提供结果则保持占位。
- [x] 简单润色/翻译继续通过已有 tools；Writer 只对实际需要组织文章或局部修订的任务执行。翻译段落后检查数字/单位/引用映射。
- [x] 校验参考文献字段来源；未知 DOI/作者/年份保留缺失提示，禁止模型编造。每次草稿变更重检相关 claims。
- [x] 前端提供最小大纲/章节草稿预览、修改范围与 diff、应用/取消、版本冲突、复制/导出；入口从研究工作区进入，不建设新 Office 编辑器。
- [x] 明确草稿生成不等于已应用到用户稿件，应用操作经现有写入策略和稳定 operation ID 执行。

测试：`test_academic_writer.py`、`test_writing_projects.py`、`test_manuscript_revision.py`、`test_writer_review_gate.py`、`test_writing_export.py`；前端 `WritingDraftPanel.test.tsx`。

验收：生成有引用的 Related Work；rejected/unreviewed/stale ledger 条目不进入正式综述；只改第二段时其他段落哈希不变；用户拒绝修订时原稿不变；没有实验数据不生成虚假结果；参考清单完全由来源元数据生成；重启后草稿版本可读，导出内容与选定版本一致。

### MA06：有界并行、子任务恢复、预算和实时事件

目标：独立任务可以并行执行，失败只影响必要依赖，所有工作受全局预算约束。

任务：

- [x] 将专家执行边界实现为当前 LangGraph 版本支持的节点/子图；为多 Document 实例分配独立 invocation namespace，配置 typed reducer。
- [x] 使用有界 fan-out/fan-in；默认同 run 最多 2 个专家，LLM 并发 2、GPU 作业 1，包含跨 run 限额；相关依赖维持串行。
- [x] 实现进程级资源许可、run 内预算预留/结算、总截止时间、计划/检索/重试上限；provider 和工具在每次调用前领取额度。
- [x] run lease 防止同一任务双重恢复；使用真实 SQLite saver 测试子任务 checkpoint/pending writes，串行 saver 与图 API 匹配。
- [x] cooperative cancel + attempt fence：取消停止调度，迟到结果不能更新终态/持久产物；未结束外部调用仍占资源，不靠不断创建线程规避限流。
- [x] 区分 succeeded/partial/failed/blocked/cancelled/skipped，保留成功子任务；计划最多补证据一次，不能无限递归委派。
- [x] 事件产生时实时送出，包含 event_id、run/task/parent_task、attempt、plan_revision、sequence、status、时间、usage 和原因码；正文默认不进 trace。
- [x] 同步更新 AgentEventType、后端 AgentTraceEventType、前端 union/parser、持久化和回放。每个新增事件独立测试，旧事件继续可读。

至少新增/明确映射：`task_planned`、`task_ready`、`task_started`、`task_progress`、`task_completed`、`task_partial`、`task_failed`、`task_blocked`、`task_cancelled`、`task_skipped`、`task_retrying`、`plan_revised`、`budget_exhausted`、`artifact_verified`、`artifact_rejected`、`workflow_partial`、`workflow_resumed`。已有根终态继续复用 agent_end，不伪造第二个最终回答。sequence 由统一 event sink 分配，重连可去重。

测试：`test_parallel_scheduler.py`、`test_subgraph_checkpoint.py`、`test_run_lease.py`、`test_shared_budget.py`、`test_cancellation_fencing.py`、`test_task_events.py`。

验收：用 barrier 验证 A/B 同时进入执行而不是只比较时间；同角色结果无覆盖；在 A 完成持久化后 B 失败，恢复不重跑 A；两个窗口不能同时恢复；预算耗尽不再发请求；task_started 在任务结束前已到达消费端；旧图恢复用例仍通过。

### MA07：笔记、知识图谱、Curator 与幂等提交

目标：研究产物能成为可管理的笔记/图谱，保留原始来源和用户修改。

任务：

- [x] 实现 Knowledge Curator：根据用户目标生成 NoteDraft/ItemDraft/RelationProposal，而不是将最终回答整段塞进所有数据库。
- [x] 采用 MA00 确认的 canonical item/note 关联规则；AI 整理、原文引用、user_note 分离，修订使用 expected_version/内容哈希。
- [x] 在当前授权文档中提取 paper/concept/evidence/insight/question 等候选；方法/数据集优先用 concept subtype，扩展 enum 时完成 API/UI 迁移。
- [x] 实体归一/去重保留 source_id 和 scope；同名跨工作区实体不自动合并，合并只生成可查看建议。
- [x] 复用 KnowledgeRelationSuggestionService 和 suggestion repository，但先限制候选 ID 集合。边必须有允许类型、有效端点和证据依据，不能因两个节点共现直接判定 supports。
- [x] 生成图谱建议与接受/拒绝/保存分别追踪；复用现有 proposal review 行为，AI 不自行 accepted。
- [x] Commit 节点统一 note/item/relation/manuscript apply 的授权与回执；业务库内变更和 operation receipt 原子提交，跨库使用显式分步状态而非假事务。
- [x] 批量保存支持部分失败报告和安全重试；operation_id 绑定 payload hash/目标/版本，同键不同内容返回冲突。
- [x] 保存后的来源变更、工作区成员移除和对象删除会令产物可引用状态失效，不能依靠旧 artifact 绕过检查。

测试：`test_knowledge_curator.py`、`test_note_preservation.py`、`test_graph_proposals.py`、`test_entity_scope.py`、`test_commit_idempotency.py`、`test_multi_store_commit.py`。

验收：阅读结果可保存并从现有 Research/Knowledge UI 打开；用户笔记保持不变；建议边未经接受不出现在已确认语义关系中；重复接受/恢复提交只生成一个对象/关系；提交后 checkpoint 前崩溃可查回执恢复；A 工作区图谱无 B 私有节点。

### MA08：真实记忆接入与跨会话科研连续性

目标：四类专家和共享语言能力共用记忆服务，且遵守临时会话及删除语义。

前置：记忆 M01–M07 的对应接口可用，MA07 完成。未具备时可以做适配实现，但不可把此阶段标为 verified。

任务：

- [x] MemoryPort 接真实 MemoryCoordinator，使用稳定 profile；检索只在当前 workspace 和允许全局偏好中进行。
- [x] 为 Document/Research/Writer/Curator 定义最小记忆投影：阅读目标、研究决定、写作风格/术语、整理偏好；共享 snapshot ID，不复制整份聊天历史。
- [x] 只有完成且验证过的产物生成 memory candidates；用户笔记/实验事实与模型建议分开，source outbox 复用记忆 M04。
- [x] checkpoint/恢复引用记忆版本；删除/禁用/成员撤销检查贯通专家、Writer、Curator 和 commit 前的再验证。
- [x] temporary 模式贯通专家私有 state、artifact store、写作草稿、trace、jobs、前端缓存；未被用户显式保存的正文不落盘。
- [x] 文稿和研究项目跨会话引用由持久对象 ID/版本解析，不能靠“最近一次输出”猜测应继续哪篇论文。

测试：`test_memory_port_integration.py`、`test_research_continuity.py`、`test_temporary_workflow.py`、`test_memory_revocation_resume.py`。

验收：在新会话继续指定项目，正确找回稿件与已确认决定；换项目不串用；删除记忆后恢复任务不再使用该正文；Language 工具和 Writer 采用相同有效术语偏好；临时任务的唯一标记在测试目录各持久介质中不存在。

### MA09：科研工作区 UI 与真实执行反馈

目标：用户围绕论文/项目操作，能看懂产物和执行状态，不需要理解内部调度框架。

任务：

- [x] 扩展现有 Research/Knowledge/Reader 入口，提供“速读论文、分析图表、比较论文、整理笔记/图谱、起草章节”动作；把明确的资源/交付范围传给后端，不依赖按钮文案被模型猜测。
- [x] 改造固定三角色 MultiAgentTracePanel，按真实 TaskPlan 展示动态节点、依赖、活动任务和部分失败；语言工具与专家角色有正确类型标签。
- [x] 展示每个产物的覆盖范围、来源跳转、版本、待补项与验证状态。比较矩阵每格能打开证据，写作稿每段能查看来源。
- [x] 集成 MA05 草稿 diff/应用与 MA07 图谱建议接受/拒绝；区分已生成、待保存、已保存和保存失败，复用现有 API 和缓存失效信号。
- [x] 取消、重试失败子任务、恢复 run 使用同一后端契约；未满足条件的重试给出原因，不能复用已过期批准。
- [x] 支持 WebSocket 断线后的事件去重/回放和权威 run snapshot，两个窗口看到一致终态；不把客户端动画当执行证据。
- [x] 简单翻译保留快速交互和阅读浮窗；没有启动专家的请求不展示虚假的协作活动。

测试：前端 `TaskExecutionPanel.test.tsx`、`ResearchArtifactPanel.test.tsx`、`WritingDraftPanel.test.tsx`、`GraphProposalPanel.test.tsx` 与既有 reader/companion/trace 回归；后端 `test_task_api_contract.py`。

验收：至少手工演示一次阅读→比较→笔记/图谱→章节草稿；事件顺序和后台状态相符；断线恢复不重复节点/保存动作；工作区切换、失败、无来源、无模型四种空/错误状态清楚。

### MA10：A/B 评估、兼容迁移与最终交付

目标：用对等评估证明适用任务的收益，同时保留已有快速路径和数据完整性。

任务：

- [x] 实现 `backend/evaluation/multi_agent_benchmark.py`，输出任务级质量、来源覆盖、token/调用数、时延、失败/降级、版本和预算的 JSON 报告；未知 usage 写 `null`，不伪造为零。
- [x] 建立相同模型/资料/权限下的单 Agent、旧协作、新架构盲化交错调度和 recorded-input 协议，同时覆盖同 token 与生产预算；真实语义观测尚缺，报告不宣称收益。
- [x] 执行第 5 节 T01–T36 的 deterministic 契约矩阵；真实 Qwen3、真实配置 LLM、手工 UI 和语义质量 A/B 因运行资源/显式授权缺失记录为未验证，不以 mock 冒充。
- [x] 设置迁移开关并按 simple→single→workflow 验证；检查旧请求、旧 trace、旧 checkpoint 和现有知识/笔记 API。默认 rollout 为 `single`。
- [x] 搜索旧 planner/executor/protocol 消费者：legacy 生产桥仍使用 planner/executor，其余原型仍受兼容/checkpoint 窗口约束，因此本阶段保留，不删除历史解释器或数据。
- [x] 完整 Python 回归、前端 lint/test/build、Tauri check；新增目录与改动文件执行静态检查。
- [x] 更新架构、任务书、README 指向及验证记录，标注真实模型未验证项、性能环境、已知限制、回滚方法和数据备份建议。

验收：全部硬性场景通过；若质量/延迟收益不成立，则该任务保持单 Agent 默认并记录原因；scope 泄漏、虚构实验/引用、静默覆盖笔记、删除复活、重复业务写入任一出现均不能标记完整交付。

## 4. 验证命令与运行约定

以下从仓库根目录执行。MA00 创建 `tests/multi_agent` 后才执行新增目录测试；中间阶段只运行相关测试和必要回归，最终 MA10 再跑全量。

```powershell
git status --short --branch
conda run -n aitrans python -c "import sys; print(sys.executable)"
conda run -n aitrans python -m pytest tests/multi_agent -q
```

已运行的多 Agent/恢复/事件基线（2026-09-16）：

```powershell
conda run -n aitrans python -m pytest tests/agent/test_multi_agent_stage5_6.py tests/agent/test_multi_agent_stage5_7.py tests/agent/test_multi_agent_stage5_8.py tests/agent/test_multi_agent_stage5_9.py tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_trace_event_contract.py -q
```

结果：**92 passed in 7.73s**。

已运行的写作/图谱/综述边界补充基线：

```powershell
conda run -n aitrans python -m pytest tests/agent/test_writing_tool_boundary.py tests/test_knowledge_relation_suggestions_stage15.py tests/api/test_knowledge_relation_suggestions_api_stage15.py tests/research/test_agent_literature_synthesis_review_gate_boundary.py -q
```

结果：**10 passed in 4.97s**。本次合计 102 项既有测试通过；不是全量回归，也不是新多 Agent 质量评估。

必要边界回归示例：

```powershell
conda run -n aitrans python -m pytest tests/agent/test_typed_tool_registry.py tests/agent/test_agentic_rag.py tests/agent/test_agent_grounded_synthesis.py tests/agent/test_cross_document_research_stage18.py tests/agent/test_research_workspace_stage16.py tests/test_conversation_lifecycle.py tests/test_backend_companion_stream.py -q
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
```

最终验收：

```powershell
conda run -n aitrans python -m pytest tests -q
npm --prefix apps/desktop run lint
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml --no-default-features
```

静态检查覆盖新模块和实际修改的既有文件；不要为了通过检查改无关代码。GPU 语义测试沿用 `rag_gpu` 与 `AITRANS_RUN_RAG_GPU_TESTS` opt-in，使用独立测试目录。真实远程 LLM 只在测试配置明确允许时执行；缺少资源须标注未运行，不用 mock 冒充。

并发测试使用 barrier/event 和假时钟；恢复测试覆盖进程关闭/重开 SQLite、失败分支、业务提交与 checkpoint 之间窗口。测试不能对真实用户数据库做删除/损坏操作。

## 5. 最终验收矩阵

| ID | 场景 | 必须观察到的结果 | 阶段 |
| --- | --- | --- | --- |
| T01 | 翻译这篇论文的当前选区 | 一次有效语言调用，无无关 Research；不重复最终翻译 | MA03 |
| T02 | 一篇论文速读，材料包含方法/结果/局限 | 七类阅读字段可追溯，未知字段明确 | MA04 |
| T03 | 只提供摘要要求阅读全文分析 | 显示局部覆盖，不编造方法/实验细节 | MA04 |
| T04 | 解释表格与脚注，含不同单位 | 正确页/元素定位、数值和单位；无视觉模型时明确降级 | MA04 |
| T05 | 比较 A/B，相同领域不同数据集 | 条件化比较，不做不成立的数值优劣结论 | MA04 |
| T06 | 总结后翻译摘要 | Translation 输入来自摘要 artifact 版本，非原始全文 | MA03/MA05 |
| T07 | 两个 Document 任务并行 | barrier 证明并行，两份结果按 task_id 留存 | MA06 |
| T08 | B 无法读取，A 已完成 | 保留 A，比较任务 partial/blocked，不声称完整比较 | MA04/MA06 |
| T09 | scope A 内检索，B 中有高关系度节点 | packet、专家上下文、最终引用均不含 B 私有内容 | MA02 |
| T10 | 受限空工作区 | 空结果，不回退全局数据 | MA02 |
| T11 | 不同工作区笔记来自同一文献 | 只使用允许的 note IDs，不按共同来源扩大权限 | MA02 |
| T12 | 冲突证据并存 | 保留分歧和不同条件，不由多角色多数票判定事实 | MA04 |
| T13 | 大纲与 Related Work 写作 | 段落与引用可追溯，保留 Stage20 gate，不补未经审阅事实 | MA05 |
| T14 | 未提供实验结果，要求结果章节 | 生成结构/待补项，不编造数值、试验或数据集 | MA05 |
| T15 | 只修改稿件第二段 | 未授权段落哈希不变；拒绝后原稿不变 | MA05 |
| T16 | 两窗口应用同一稿件修订 | expected_version 冲突被报告，不静默覆盖 | MA05/MA06 |
| T17 | 源文献缺 DOI/年份 | 导出显示缺失，不生成虚假参考文献 | MA05 |
| T18 | 保存 AI 笔记，原 user_note 有内容 | 原文/AI/用户笔记分离，用户内容不丢失 | MA07 |
| T19 | 生成图谱建议但未接受 | 建议可查看，未作为 accepted 语义边 | MA07 |
| T20 | 同名概念跨工作区，重复接受关系 | 不跨范围自动合并；一条关系只创建一次 | MA07 |
| T21 | 非法关系端点、类型或无证据 supports | proposal/commit 被拒绝并说明原因 | MA02/MA07 |
| T22 | 业务写入成功后 checkpoint 前退出 | 重启先查回执，无重复笔记/卡片/稿件应用 | MA07 |
| T23 | A 成功持久化，B 执行中退出 | 恢复不重跑 A，只继续缺失任务 | MA06 |
| T24 | 两窗口同时恢复同一个 run | 唯一 lease，只有一个执行者 | MA06 |
| T25 | 取消后 provider 返回迟到结果 | 无后续任务，无迟到产物覆盖/业务提交 | MA06 |
| T26 | 达到调用/时间/并行预算 | 停止新请求，预算与 partial/failure 可见 | MA06 |
| T27 | 接收 task_started，任务尚未完成 | 消费端已收到真实进度，不等待整个协作结束 | MA06/MA09 |
| T28 | WebSocket 重连与重复事件 | 节点去重、状态不倒退，最终以 run snapshot 对齐 | MA09 |
| T29 | 旧版本 checkpoint、旧角色 trace | 可兼容解释或明确不兼容，不删除数据/重复外部写 | MA03/MA10 |
| T30 | 新会话继续同一研究项目 | 解析正确稿件/项目版本和记忆，不能猜用其他项目结果 | MA08 |
| T31 | 删除记忆/撤销文献后恢复 | 旧上下文失效，不再注入或保存失效结论 | MA07/MA08 |
| T32 | 临时多任务阅读/写作使用唯一标记 | 非显式保存内容不在 checkpoint/artifact/trace/jobs/cache 落盘 | MA08 |
| T33 | 专家输出/论文含越权工具指令 | 不改变 scope/工具权限，作为内容处理或拒绝非法调用 | MA01/MA02 |
| T34 | 关闭多 Agent/新编排开关 | 既有聊天、选区翻译、知识浏览正常，已保存产物仍可读 | MA10 |
| T35 | 使用相同数据和模型做对照 | 报告质量、成本、延迟及适用任务，不凭 UI 角色数宣称收益 | MA10 |
| T36 | 文献变更后再次导出旧写作稿 | 来源状态可见，未经复核不宣称仍通过最新证据验证 | MA05/MA08 |

## 6. 质量、成本与性能验收

这些是设计目标，不是本次测试测得的数据。MA00 固定评分集和定义，MA10 提交真实报告。未达到的数值不能写成“已完成优化”。

| 指标 | 初始目标/规则 |
| --- | --- |
| 合同/来源/范围/临时模式/幂等写入 | T01–T34/T36 对应确定性硬性断言 100% 通过；任一越界或静默丢数据阻止发布 |
| 路由 | ≥80 个标注输入（明确翻译、单文档、跨文档、写作、知识整理、一般聊天）；路径选择正确率 ≥95%，明确单步请求的无用协作率为 0 |
| 阅读和比较质量 | ≥30 个独立文档任务，其中至少 10 个多文档、5 个图表、5 个缺失/矛盾场景；按完成度/来源支持/范围声明/数值单位四项各 0–2 分，报告分布及失败例 |
| 引用支持 | 人工标注事实单元的有效来源支持率 ≥95%；scope 正确性 100%；确定性引用检查与人工语义支持评分分开 |
| 写作 | ≥20 个章节/修订任务，至少 5 个无实验数据场景；虚构 DOI/论文/实验结果为 0，局部编辑范围正确率 100% |
| 图谱和笔记 | ≥20 个 proposal/commit 场景；越界端点、未经接受的持久 confirmed 边、重复保存、用户笔记覆盖均为 0 |
| 多任务质量收益 | 同预算下新架构平均得分不低于单 Agent，失败率不高；若某任务没有收益则保留单路径默认，不强制协作 |
| 单步成本 | 明确翻译/润色不额外增加路由或最终综合 LLM 调用；同模型下实际工具调用次数不高于基线 |
| 并发收益 | 受控等时延两读任务的并发执行段不高于串行段的 70%；用 barrier 验证并发，再用性能测量验证收益 |
| 真实成本 | 分别报告 tokens、LLM/tool 尝试数、重复检索率、成功任务成本、cold/warm 延迟；没有 token usage 时标 unknown，不能填 0 |
| 事件与取消 | 在合成可控工具下，事件本地产生至消费 p95 ≤250ms；取消后 500ms 内停止新分发，外部请求真实终止时间单列 |
| 持久恢复 | 成功已提交任务不重做；未提交只读调用的潜在重复及成本如实记录；操作回执与内容一致 |

真实 provider 测试采用固定模型/提示词/索引版本、相同输入与权限，随机交错各策略运行至少 3 次并报告波动；同预算比较与生产预算比较分表。质量评分采用盲评顺序，禁止把模型自评分当唯一验收。机器配置、供应商延迟和并行限额写进报告。

## 7. 交给后续 Codex 的执行提示词

```text
请执行 docs/development/multi-agent-system-taskbook.md 中最早未完成的 MAxx 阶段。

先读 multi-agent-system-design.md、本任务书、memory-system-taskbook.md、
multi-agent-system-validation.md（如存在），检查当前 HEAD、AGENTS.md 与用户未提交修改。
以“论文阅读—研究分析—笔记/图谱—学术写作”的实际产物为目标，
不要为了多 Agent 外观增加无关角色或调用。

完成本阶段实现、对应测试和必要回归，复用既有工具、证据、知识和记忆服务。
作用域/权限在服务端执行；测试用合成资料和临时数据目录。
任何 graph/checkpoint 或写入修改都要验证崩溃恢复与兼容。

维护任务复选框、状态表和验证记录，记录真实 passed/failed/skipped、环境和限制。
未实现/未测试功能不得标记完成。不要只给方案，交付实际改动和验证结果。
共享记忆阶段若缺失，先完成可独立工作并明确阻塞，不创建重复记忆实现。
未收到本次 Git 提交/推送要求时不自行发布。
```

阶段记录模板：

```markdown
### MAxx 实施记录 — YYYY-MM-DD

- 状态：not_started / in_progress / blocked / verified
- 起始 HEAD / 最终提交（未提交则写未提交）：
- 实际改动与对应用户产物：
- 共享记忆阶段与接口版本：
- 数据/图/checkpoint/事件迁移与兼容影响：
- 测试命令：
- 结果：passed / failed / skipped 分开
- 真实模型与 UI 验证、指标：
- 任务书调整与理由：
- 已知限制/阻塞及下一步：
```

## 8. 阶段状态

| 阶段 | 交付主题 | 状态 | 记录 |
| --- | --- | --- | --- |
| MA00 | 基线与科研评估夹具 | verified | `1464581`、`a91f908`；2026-09-16 本地复验 |
| MA01 | typed 任务、角色、状态、产物 | verified | `17f959d`–`7fca71c`；2026-09-16 本地复验 |
| MA02 | scope 与统一证据 | verified | `196a2e1`；2026-09-16 本地复验 |
| MA03 | 路由与串行根图集成 | verified | `decaa74`；2026-09-16 本地复验 |
| MA04 | 论文理解与研究分析 | verified | `43d7a17`；2026-09-16 本地复验 |
| MA05 | 学术写作与局部修订 | verified | `25390a9`；2026-09-16 本地复验 |
| MA06 | 并发、预算、恢复、实时事件 | verified | `98ca7e1`；2026-09-17 本地复验 |
| MA07 | 笔记、知识图谱与提交 | verified | `544ebfc`、`4070400`；2026-09-17 本地复验 |
| MA08 | 真实记忆与跨会话研究 | verified | `4d0b09e6`；2026-09-17 本地复验 |
| MA09 | 科研工作区 UI | verified | `74f6cfb`；自动化 UI/构建复验，手工 UI 仍列为 MA10 未验证面 |
| MA10 | A/B 验证、迁移与交付 | verified | `0417139`–`4163845`；确定性门禁通过，`release_ready=false`、默认 single |

阶段任务发生变动时更新本文件及设计文档，保留原因和验证证据。设计阈值可据实际模型/硬件修订，scope、用户数据保护、引用真实性和幂等写入标准不可为通过验收而降低。

### MA00 实施记录 — 2026-09-16

- 状态：verified。
- 起始 HEAD / 最终提交：`ad27691` / `a91f908`（实现提交 `1464581`，验证记录提交 `a91f908`）。
- 实际改动与对应用户产物：冻结生产调用链、数据所有权、F01/F03/F04/F07/F09 现状、合成科研资料、T01–T36 开发/留出集和隔离测试夹具。
- 共享记忆阶段与接口版本：无真实记忆接入；F09 仅作现状 characterization。
- 数据/图/checkpoint/事件迁移与兼容影响：无生产迁移、无生产行为改动。
- 测试命令：`python -m pytest tests/multi_agent -q`；第 4 节 92 项和 10 项基线命令。
- 结果：本地复验 `32 passed`（含 MA00 与 MA01）、既有基线 `92 passed`、边界回归 `10 passed`；无 skipped/failed。
- 真实模型与 UI 验证、指标：未执行，不声称质量优于单 Agent。
- 已知限制/阻塞及下一步：MA00 仅固化缺口；由 MA02、MA06、MA08 分别关闭 scope、实时事件、持久记忆问题。

### MA01 实施记录 — 2026-09-16

- 状态：verified。
- 起始 HEAD / 最终提交：`a91f908` / `7fca71c`。
- 实际改动与对应用户产物：新增 typed task/artifact/scope/result DTO、角色与工具权限注册、计划验证、任务状态机、确定性 reducer、可注入端口、SQLite/内存 artifact store。
- 共享记忆阶段与接口版本：只定义 `MemoryPort`；未建立重复记忆存储。
- 数据/图/checkpoint/事件迁移与兼容影响：新增独立 `agent_artifacts.sqlite3` schema v1；尚未接入生产根图，旧 Agent 请求不受影响。
- 测试命令：`python -m pytest tests/multi_agent -q` 以及第 4 节两个回归命令组。
- 结果：`32 passed`、`92 passed`、`10 passed`；无 skipped/failed。
- 真实模型与 UI 验证、指标：纯契约阶段，不适用。
- 已知限制/阻塞及下一步：产物/任务契约尚未进入生产执行；MA02 先建立服务端 scope resolver 和统一 Evidence Service。

### MA02 实施记录 — 2026-09-16

- 状态：verified。
- 起始 HEAD / 最终提交：`c3bf7e5` / `196a2e127b29d620db73716ee63e5a490b2b6c8b`。
- 实际改动与对应用户产物：新增服务端 `AuthoritativeScopeResolver`、显式 global/restricted scope、统一 `ScopedEvidenceService`/`EvidencePacket`、精确 note/文档/知识条目过滤、RAG 表图定位、CitationService 适配、来源新鲜度/Review Gate 接入和 scope-aware 关系建议候选。
- 共享记忆阶段与接口版本：复用现有 Research Memory reliability，只读来源状态；未创建新记忆库。
- 数据/图/checkpoint/事件迁移与兼容影响：无 schema 迁移；旧 scoped Knowledge Runtime 在无可信 Evidence Service 时安全停用，全局兼容路径保留；F03 转为目标行为断言。
- 测试命令：`pytest tests/multi_agent -q`；第 4 节 92/10 项回归；Research Workspace/Memory/Evidence Review 组；Knowledge/RAG 组；changed-files Ruff 与 compileall。
- 结果：`47 passed`、`92 passed`、`10 passed`、`60 passed`、`53 passed`；Ruff/compileall 通过；无 failed/skipped。
- 真实模型与 UI 验证、指标：未执行；本阶段验证确定性范围与来源契约，不声称真实模型质量收益。
- 已知限制/阻塞及下一步：MA02 服务尚未由权威根图统一解析/注入；MA03 完成 fast/single/workflow 路由、串行 task DAG 与生产接入。

### MA03 实施记录 — 2026-09-16

- 状态：verified。
- 起始 HEAD / 最终提交：`031d5f9` / `decaa74f8eb2f6164fd6f65a2c1cf4febe10696b`。
- 实际改动与对应用户产物：新增 fast/single/workflow 路由、typed Supervisor planner（最多修复一次）、确定性串行 task DAG、生产 Bridge 接入、直接交付短路、根图先取得会话所有权、稳定 profile/scope/memory snapshot 冻结及旧 `planned_action` 投影。
- 共享记忆阶段与接口版本：使用可注入 `MemoryPort` 和显式 `NullMemoryPort`；未创建第二套 outbox/记忆库，等待 M04 真实接入。
- 数据/图/checkpoint/事件迁移与兼容影响：Agent graph version `reading-agent-ma03-v1`、state schema v2；无版本旧 state 自动标记并迁移，未知图/未来 schema/未知节点明确拒绝；SQLite checkpoint 库未删除或重建。
- 测试命令：`pytest tests/multi_agent -q`；ReadingGraph/checkpoint/Stage5 兼容组；Agent API/observability 组；完整 `pytest -q`；changed-files Ruff 与 compileall。
- 结果：`63 passed`、`19 passed`、`28 passed`；完整回归 `1126 passed, 2 skipped, 1 failed`，唯一失败仍为 MA00 已记录的 Knowledge V2 `_IncludedRouter.path` 既有测试缺陷；Ruff/compileall 通过。
- 真实模型与 UI 验证、指标：未执行；本阶段是串行架构预览，不声称并行、真实专家质量或恢复到单个子任务。
- 已知限制/阻塞及下一步：Document/Research 仍通过 legacy compatibility executor 返回 partial，Writer/Curator 明确 blocked；MA04 实现 typed Document/Research 专家，MA06 处理实时事件和子任务恢复。

### MA04 实施记录 — 2026-09-16

- 状态：verified。
- 起始 HEAD / 实现提交：`5f7da73` / `43d7a17`。
- 实际改动与对应用户产物：新增真实 LangGraph `DocumentAnalystGraph` 与 `ResearchSynthesizerGraph`，生产运行时替换 Document/Research legacy preview；生成带 claim/evidence、来源版本、requested/visited/unavailable 覆盖、图表定位和 `VerificationReport` 的阅读卡与条件化比较矩阵；末端 typed 产物直接交付，不再二次无依据生成。
- 共享记忆阶段与接口版本：消费同一 run 冻结并已授权的 `MemoryPort` snapshot；研究设想单独存为 `ResearchHypothesis`，不进入文档事实单元。生产仍使用 MA03 `NullMemoryPort`，等待记忆 M04/MA08 接入，未新建记忆库或 outbox。
- 数据/图/checkpoint/事件迁移与兼容影响：Artifact schema 以向后兼容默认字段增加 `VerificationReport`/`ResearchHypothesis`；artifact store schema 版本不变，无数据库迁移；根图/checkpoint/state/event 版本不变。TaskSpec 新增默认空的 `target_source_ids`，旧 payload 可继续解析。
- 测试命令：MA04 五组定向测试；`pytest tests/multi_agent -q`；旧 Agent/ReadingGraph/checkpoint/trace 回归；Research/Knowledge/RAG 相关测试；完整 `pytest -q`；changed-files Ruff 与 compileall。
- 结果：MA04 定向 `12 passed`；multi-agent `77 passed`；旧运行时回归 `118 passed`；Research/Knowledge/RAG `452 passed, 2 skipped`；完整回归 `1142 passed, 2 skipped`；Ruff/compileall 通过，0 failed。两个 skip 均为需 `AITRANS_RUN_RAG_GPU_TESTS=1` 的既有 Qwen3 embedding/reranker 真实 GPU 测试。
- 真实模型与 UI 验证、指标：未调用付费/远程模型，未做 UI 人工质量评测；本阶段只声明确定性契约、来源和降级行为通过，不声称真实模型阅读质量收益。
- 任务书调整与理由：测试文件按任务书固定为 `test_document_coverage.py` 与 `test_table_image_analysis.py`；增加来源层全文覆盖证明、不可变 artifact hash、scope/type 和非叶节点直接交付检查，防止模型自报完成或中间产物越过末端任务。
- 已知限制/阻塞及下一步：无原图/视觉模型时仅交付 OCR/描述、单位、脚注和 locator 并明确 partial；语义质量由后续真实模型评测校准。MA05 实现 Academic Writer、WritingProject、版本化局部修订与导出。

### MA05 实施记录 — 2026-09-16

- 状态：verified。
- 起始 HEAD / 实现提交：`9f2145736109f15b61865da21bb9ebf9a46af91a` / `25390a92b89a3fe9d5c7b5d6f996452d1fd266ef`。
- 实际改动与对应用户产物：生产角色注册真实 `AcademicWriterGraph`，输出有写作目标、稳定章节/段落 ID、事实/解释/建议/用户材料分类、证据映射和待补项的 typed 大纲、章节与修订；正式 Related Work 只消费既有 Stage20 accepted Review Gate，实验/结果仅消费显式 `user_supplied` 材料，否则输出可见占位；新增本地 `WritingProjectService`、REST API 和研究工作区 `WritingDraftPanel`，支持大纲/章节版本、局部 diff、取消、显式应用、冲突提示、复制及 Markdown/来源清单导出，不修改原论文文件。
- 共享记忆阶段与接口版本：继续消费 MA03 冻结的 `MemoryPort` snapshot；仅将显式 `user_supplied` 项作为用户实验材料，生产仍为 `NullMemoryPort`，未创建第二套记忆存储。
- 数据/图/checkpoint/事件迁移与兼容影响：在 `agent_artifacts.sqlite3` 增加独立 writing schema v1（project/section-version/operation receipt 表）；artifact DTO 只增加有默认值的 reference/revision 字段；根图、checkpoint、AgentState 和事件 schema 未变。应用使用 `expected_version`、段落 hash 和稳定 `operation_id`，重复同请求返回 replay receipt，不同内容复用 ID 或陈旧版本返回冲突。
- 测试命令：MA05 五组专项测试、写作 API 与 planner/output-guard 回归；`pytest tests/multi_agent -q`；完整 `pytest -q`；`npm --prefix apps/desktop test`、lint、build；changed-file Ruff 与 Python compileall。
- 结果：专项后端 `58 passed`；multi-agent `93 passed`；完整 Python `1160 passed, 2 skipped`；桌面端 `64 files / 266 tests passed`（新增面板 `3 passed`）；typecheck/build/Ruff/compileall 通过，lint 仅保留 5 条既有 Reading/PDF warning，0 failed。两个 skip 为需 `AITRANS_RUN_RAG_GPU_TESTS=1` 的既有 Qwen3 embedding/reranker 真实 GPU 测试。
- 真实模型与 UI 验证、指标：未调用付费/远程模型，未做人工 UI/语义质量评测；确定性 fallback、契约、来源真实性、版本冲突和用户确认路径已自动验证，不声称达到最终写作质量指标。
- 任务书调整与理由：无降低验收标准；增加写作 API 路由测试和前端 409 冲突测试，明确“预览草稿不等于应用”。
- 已知限制/阻塞及下一步：首版是 Markdown 草稿管理而非 Office 编辑器；Agent artifact 通过 ID/版本附加到写作项目，真实语义质量留到 MA10 固定评估集。MA06 实现有界并发、子任务 checkpoint/lease、共享预算、取消 fence 与实时事件。

### MA06 实施记录 — 2026-09-17

- 状态：verified。
- 起始 HEAD / 实现提交：`8fc8378b73fd97265d3e26f2da2b31fba7d16369` / `98ca7e1fae6bc12dc4161b344f04fdff4e8ed4b3`。
- 实际改动与对应用户产物：生产编排由串行执行器切换为 typed `ParallelTaskGraphExecutor`，独立 frontier 最多同时执行 2 个专家，依赖任务保持 fan-in 后串行；同角色结果继续按 task ID reducer 合并。增加进程级 LLM 2/GPU 1 许可、run 级模型/工具/检索/重试/总期限预算、SQLite task checkpoint 与单 owner lease、已完成任务恢复、cooperative cancel 和迟到 artifact 撤销 fence。明确保留 succeeded/partial/failed/blocked/cancelled/skipped，失败只阻塞其依赖分支。
- 共享记忆阶段与接口版本：仍使用同一冻结 `MemoryPort` snapshot；并发 worker 获得副本，不能更新共享可变记忆。未新增记忆数据库。
- 数据/图/checkpoint/事件迁移与兼容影响：在既有 `agent_checkpoints.sqlite3` 增加独立 `multi_agent_task_runs`/`multi_agent_task_checkpoints` 表，不修改 LangGraph 原表；任务 checkpoint 绑定 plan hash，运行租约带过期时间，恢复只重跑 interrupted attempt。Agent graph/state schema 不变。新增 17 个任务/工作流事件，同步到后端 enum/Literal、前端 union/时间线和脱敏观测存储；事件产生即转发并追加持久化，resume sequence 单调递增，旧事件仍可解析。
- 测试命令：任务书六组 MA06 专项测试；`pytest tests/multi_agent -q`；旧 Agent checkpoint/trace/observability/产品写入确认回归；完整 `pytest -q`；`npm --prefix apps/desktop test`、lint、build；changed-file Ruff 与 compileall。
- 结果：MA06 专项 `31 passed`；multi-agent `125 passed`；checkpoint/trace/产品边界回归 `129 passed`；完整 Python `1226 passed, 2 skipped`；桌面端 `64 files / 267 tests passed`；typecheck/build/Ruff/compileall 通过，lint 仅保留 5 条既有 Reading/PDF warning，0 failed。两个 skip 为需 `AITRANS_RUN_RAG_GPU_TESTS=1` 的既有 Qwen3 embedding/reranker 真实 GPU 测试。
- 真实模型与 UI 验证、指标：未调用远程模型；barrier 证明两个独立专家同时进入执行，事件测试证明 `task_started` 在任务结束前到达 sink。未做真实 provider 延迟/成本基准，MA10 再报告 p95 与质量成本对照。
- 任务书调整与理由：无降低验收标准；补充显式保存选区继续走既有写工具确认的回归，避免多 Agent 直接交付绕过副作用确认。
- 已知限制/阻塞及下一步：Python 无法强杀已进入第三方阻塞调用的线程，取消后该调用仍占全局许可和 lease，完成后迟到 artifact 被撤销；这是有意的安全 fence。MA07 实现 Curator、typed note/item/relation proposal 与幂等业务提交。

### MA07 实施记录 — 2026-09-17

- 状态：verified。
- 起始 HEAD / 实现提交：`eff5cb671d016d07c18d4977d47d5c37532ddae8` / `544ebfc`（同库原子 step receipt 加固 `4070400`）。
- 实际改动与对应用户产物：生产运行时用真实 `KnowledgeCuratorGraph` 替换 Curator compatibility executor；从已验证依赖产物生成 typed `NoteDraft`、`KnowledgeItemDraft` 与 pending `RelationProposal`，不复制整段最终回答。新增统一 `CuratorCommitService` 与 `/api/curator/commit`、operation receipt 查询接口；保存结果可由既有 Research Notes 与 canonical KnowledgeWorkspace 读取。
- 笔记与知识对象规则：Research Note 保持原文引用、AI 整理、`user_note` 三者分离，AI 草稿不能写 `user_note`；canonical note item 通过 `metadata.research_note_id`、`workspace_id`、来源及内容哈希稳定关联。已有 note/item 修改同时检查 `expected_version=1` 与内容哈希，新建对象要求版本 0；方法和数据集使用 `concept + metadata.subtype`，未扩展公开 enum。
- 图谱与 scope：去重只扫描当前 `allowed_item_ids`；跨工作区同名对象不自动合并。关系端点必须来自当前 scoped 候选或本次新建对象，类型限制为既有 AI allowlist，`supports` 必须有 artifact 内真实 evidence ID。保存只产生 pending suggestion；接受/拒绝保持独立并改为幂等，重复接受不会产生第二条关系。
- 写入、恢复与撤销：`operation_id` 绑定 artifact ref、scope ref、workspace 与选中 draft IDs；不同 payload 复用 ID 返回冲突。跨 Research Notes/Knowledge SQLite 写入按 target 持久记录 `in_progress/completed/partial/failed`，对象 ID、note fingerprint 和 suggestion ID 均稳定，业务写成功但父 checkpoint 未前进时可先查询回执并安全重放。Commit 前重新核对 artifact scope、工作区存在性、来源授权、对象存在性和版本/哈希；旧 artifact 不能绕过来源或成员变化。
- 数据/图/checkpoint/事件迁移与兼容影响：canonical knowledge SQLite 新增 `curator_commit_operations` 与 `curator_commit_steps` 表；Knowledge item/suggestion 变更与对应 step receipt 在同一连接事务提交，聚合回执落后时可由 step 重建。Research Note、Knowledge item/relation/suggestion 原表不重建。Artifact DTO 只增加带默认值的 notes/proposals 与版本字段，旧 payload 可继续解析。修复重复附加同一 note 到 Research Workspace 被误报不存在；FastAPI 0.141 嵌套路由仅增加平坦只读 `app.routes` 兼容视图，请求分发与 dependency override 保持框架原实现。
- 测试命令：任务书六组 MA07 专项测试；`pytest tests/multi_agent ...` Research/Knowledge/API 关键回归；完整 `pytest -q`；桌面端 test/typecheck/lint/build；changed-file Ruff、compileall 与 `git diff --check`。
- 结果：MA07 专项 `13 passed`；multi-agent 与 Research/Knowledge 关键回归 `167 passed`；最终完整 Python `1239 passed, 2 skipped`；桌面端 `64 files / 267 tests passed`；typecheck/build/Ruff/compileall 通过，lint 仅保留 5 条既有 Reading/PDF warning，0 failed。两个 skip 为需 `AITRANS_RUN_RAG_GPU_TESTS=1` 的既有 Qwen3 embedding/reranker 真实 GPU 测试。
- 真实模型与 UI 验证、指标：未调用远程模型，未做人工 UI 端到端演示；确定性 fallback、typed provider 边界、持久化和安全约束已自动验证。Graph Proposal 的专用审阅 UI 属于 MA09，不在本阶段声称完成。
- 已知限制/阻塞及下一步：当前 Research Note 历史 schema 没有递增版本列，因此已有 note 的版本契约固定为 1，并以内容哈希/updated_at 组合检测并发修改；跨库不宣称单 SQLite 事务，而以逐项回执和稳定键恢复。MA08 接入真实 MemoryCoordinator、临时模式、删除撤销和跨会话科研连续性。

### MA08 实施记录 — 2026-09-17

- 状态：verified。
- 起始 HEAD / 实现提交：`237321b549c9fef8138e4afceeda95b507c492c7` / `4d0b09e6`。
- 实际改动与对应用户产物：新增 canonical 本地 MemoryRepository/MemoryCoordinator、显式记忆 CRUD/候选激活/遗忘 API，以及 Document、Research、Writer、Curator 的有界记忆投影。四类专家与 Language 能力读取同一 run snapshot；跨会话项目通过持久 `PROJECT_REFERENCE` 的对象 ID/版本恢复，不使用“最近输出”猜测。
- 共享记忆阶段与接口版本：落地 MA08 所需的 M01–M07 对应接口子集，包括稳定 `local-default` profile、workspace/全局偏好 scope、不可变版本、run snapshot、候选、job、撤销与乐观版本冲突；memory SQLite schema v1。该记录不宣称独立 `memory-system-taskbook.md` 的 M00–M09 已全部完成。
- 候选与 outbox：只有 verified artifact 可在 artifact 事务内写入 memory outbox；artifact store schema 升级到 v2。投递可重放、幂等并按精确 `scope_ref` 过滤，`user_supplied` 声明不会被当作模型记忆候选，避免跨工作区排空或事实/建议混写。
- 恢复、撤销与提交：checkpoint 保存 snapshot/版本引用，同一 run 恢复保持冻结视图；记忆删除、禁用或 scope revision 变化会使旧 snapshot 失效。Research 恢复、Writer 与 Curator 在业务持久化前重新验证引用，失效或越界记忆不能继续注入或提交。
- 临时模式：临时运行使用无 checkpointer 的 ReadingGraph、内存 artifact/executor，跳过会话、trace/event、memory snapshot/jobs 和前端 pending-run localStorage；仅用户确认后的显式业务保存允许持久化。FAST lane 仍不伪装为多 Agent 活动。
- 共享语言能力：术语偏好在路由判断前进入运行状态；Translation 与 Writer 使用同一 memory item/version。存在术语约束时翻译自动进入可遵守 glossary 的 AI 路径，避免 Web provider 静默忽略术语。
- 数据/图/checkpoint/事件迁移与兼容影响：新增 memory SQLite schema v1；artifact SQLite 原位升级到 schema v2 并增加事务 outbox，原 artifact 数据与 API payload 保持兼容。`AgentRunRequest`/桌面请求仅新增默认关闭的 `temporary` 字段。
- 测试命令：四组 MA08 专项测试及 `tests/api/test_memory_api.py`；相关 Agent/AI 回归；完整 `python -m pytest -q`；桌面端 `npm test`、`npm run lint`、`npm run build`；changed-file Ruff、compileall 与 `git diff --check`。
- 结果：MA08 所在 multi-agent/API 集合 `154 passed`；相关 Agent/AI 回归 `66 passed`；完整 Python `1258 passed, 2 skipped`；桌面端 `64 files / 269 tests passed`，测试 TypeScript 类型检查与 build 通过；Ruff/compileall/diff-check 通过。lint 仅保留 5 条既有 Reader/PDF warning，0 failed；两个 skip 为需显式启用的 Qwen3 embedding/reranker GPU 集成测试。
- 真实模型与 UI 验证、指标：未调用远程模型，未做人工 UI 演示；跨会话、scope 隔离、删除恢复、术语一致性、outbox 崩溃重放与临时模式持久化边界均由确定性自动测试验证。
- 任务书调整与理由：同步修正 MA07 状态表的陈旧 `not_started`；MA08 只按多 Agent 接入所需接口验收，不扩大为完整记忆系统阶段声明。
- 已知限制/阻塞及下一步：本地稳定 profile 目前固定为单用户 `local-default`，未来多用户部署需由身份层提供 profile。MA09 完成科研工作区 UI、产物来源/版本/状态展示及断线恢复反馈。

### MA09 实施记录 — 2026-09-17

- 状态：verified（自动化范围）。
- 起始 HEAD / 实现提交：`4d0b09e6` / `74f6cfb`。
- 实际改动与对应用户产物：Research 工作区新增显式科研动作、动态任务执行面板、可追溯产物面板、写作 diff/应用、图谱建议审阅，以及取消、失败重试、恢复和跨窗口事件回放；FAST 语言请求不伪装成专家协作。
- 共享记忆阶段与接口版本：复用 MA08 MemoryCoordinator/run snapshot；UI 只展示服务端权威状态，不创建浏览器侧事实或记忆副本。
- 数据/图/checkpoint/事件迁移与兼容影响：无数据库迁移；前端仅扩展现有 Agent、Research、Writing、Knowledge API 类型和查询失效规则，旧接口保持可读。
- 测试命令：完整 `python -m pytest -q`；桌面端 `npm test`、`npm run lint`、`npm run build`；changed-file Ruff、compileall 与 diff-check。
- 结果：完整 Python `1263 passed, 2 skipped`；桌面端 `69 files / 281 tests passed`；typecheck/build/Ruff/compileall 通过；lint 仅 5 条既有 Reading/PDF warning。
- 真实模型与 UI 验证、指标：组件行为、事件回放和后端契约由自动化测试覆盖；本次没有可用的 Windows UI 控制能力完成手工点击演示，故不记录为手工 UI 通过。
- 已知限制/阻塞及下一步：MA10 将手工 UI 与真实模型明确留在未验证面；不能据自动化契约推断最终模型输出质量。

### MA10 实施记录 — 2026-09-17

- 状态：verified（确定性实现与安全门禁）；发布报告 `release_ready=false`。
- 起始 HEAD / 实现提交：`74f6cfb` / `4163845`（基准脚手架提交 `0417139`–`bc3ca3e`）。
- 实际改动与对应用户产物：完成版本化 JSON benchmark、盲化公平调度、重复观测聚合、recorded-input/CLI、T01–T36 证据矩阵、simple/single/workflow rollout、复合“总结后翻译”artifact handoff、prompt-injection scope/tool 防护，以及写作导出时的来源新鲜度警告。
- 数据/图/checkpoint/事件迁移与兼容影响：无 schema 破坏；`AITRANS_MULTI_AGENT_ENGINE=typed|legacy|off` 保留，新增 `AITRANS_MULTI_AGENT_ROLLOUT=simple|single|workflow`，默认 `single`。legacy planner/executor 仍有生产消费者，旧 checkpoint 解释器与历史数据全部保留。
- 测试命令：`python scripts/run_ma10_contract_matrix.py`；完整 `python -m pytest -q`；桌面端 lint/test/build；Tauri `cargo check --no-default-features`；Ruff、compileall、diff-check。
- 结果：T01–T36 deterministic `36/36`；矩阵选择器 `57 passed`，前端事件回放 `3 passed`；完整 Python `1306 passed, 2 skipped`；桌面端 `69 files / 282 tests passed`；Tauri、typecheck、build、Ruff、compileall 通过，lint 仅 5 条既有 warning。
- 真实模型与 UI 验证、指标：本机无 PyTorch，两个 Qwen3 GPU 集成测试按既有 opt-in 策略 skipped；未发现允许真实远端 LLM 基准的显式测试配置；当前任务未暴露 computer-use 所需 `node_repl`，未执行手工 UI。语义质量、真实 token/调用成本和生产时延不以零代替，均保持 `null`/未验证。
- A/B 结论：公平协议已就绪，但没有真实三策略语义观测，不能证明 workflow 优于单 Agent；因此默认 rollout 为 `single`，仅显式设置 `workflow` 才启用复杂编排。
- 回滚与备份：紧急回滚依次可设 rollout=`single`、`simple`，或 engine=`legacy`/`off`；切换前备份本地数据根中的 checkpoint、artifact、memory、Knowledge 与 Research SQLite 文件。切换开关不删除数据库，禁止通过删 checkpoint“修复”兼容问题。
- 验证产物：`docs/development/ma10-deterministic-report.json`；其 `working_tree_dirty=false` 且绑定实现提交 `4163845`。
