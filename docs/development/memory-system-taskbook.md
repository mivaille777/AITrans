# AITrans 记忆系统：分阶段开发任务书

> 用途：指导后续 Codex 按阶段实现、验证并交付记忆系统。
> 编制日期：2026-09-16。
> 核对基线：`WebReBuild`，`ad27691d18b49a4e180c641d1a6a12773cbf1ddd`。
> 状态：设计完成，以下开发阶段均未实施、未验收。本文中的新路径、API 和测试名是实施目标，不表示已经存在。
> 后续执行以当时的工作区和最新代码为准；本文中的仓库相对路径从仓库根目录解析，不依赖本机盘符。

联合实施说明（2026-09-16）：参见[科研多 Agent 设计](multi-agent-system-design.md)及[多 Agent 任务书](multi-agent-system-taskbook.md)。本任务书 M04 的协作接入节点在新架构中由统一任务分发/专家子图承担；M07 的 reading/research 映射到 document/research，translation 偏好由共享语言能力使用，writer/curator 按需领取局部记忆。记忆的存储、隔离、删除、恢复验收保持不变；避免两套任务各自实现一个 MemoryCoordinator 或相互覆盖根图。

## 1. 最终应达到的效果

完成 M00–M09 后，AITrans 应当具备以下用户可见能力：

1. 用户在会话 A 说“记住：翻译技术文档时保留英文缩写”，在新的会话 B、主窗口或浮窗中继续翻译时，相同本地用户能够得到符合该偏好的结果；重启应用后仍然有效。
2. 长会话超过原先的历史窗口后，仍能保留当前目标、已确认决定和未解决问题，并能追溯摘要来自哪些消息。
3. 用户在新会话问“我们上次讨论 PID 优化到哪了”，系统能召回相关历史结论、待办及来源；没有可靠记录时明确表示未找到，不能编造。
4. 用户全局偏好、工作区项目决定、文献证据分别管理。工作区 A 的私有项目记忆不会自动进入工作区 B；当前明确指令优先于过去偏好。
5. Reading、Research、Translation Agent 能在权限允许的范围内使用同一轮记忆快照，专用偏好按角色分发；Agent 生成的结论只能作为候选记忆。
6. 中断任务恢复时不重复保存记忆、不重复执行已提交的记忆写入。恢复期间已删除或禁用的记忆不得再次注入模型。
7. 用户可以查看、修改、固定、删除、导出记忆，知道哪些记忆被提供给本次回答，以及为什么被选中。
8. 临时会话不读取既有长期记忆、不写入历史或长期记忆，其正文不进入持久化 checkpoint、trace 或后台任务。临时会话不承诺跨进程恢复。
9. 默认落盘在本地；Embedding/Reranker 可使用现有本地 Qwen3。模型依赖缺失时，显式记忆管理和关键词召回仍可用。
10. 后台提取、索引、合并任务在进程崩溃后可重试，并且不会阻塞已完成回答的展示。

“本地持久化”不等于“所有推理离线”：用户选择远程 LLM 时，注入回答或用于提取的记忆片段可能随请求发往该提供商。设置页必须说明这一点，并提供禁止后台远程处理的选项；完全离线模式仅使用本地能力，没有本地提取模型时跳过自动提取。

最终交付以第 7 节验收矩阵为准；不能仅以数据库存在、API 返回 200 或几个 mock 测试通过判定完成。

## 2. 已确认的现状与接入边界

| 已有能力 | 当前入口 | 对实施的约束 |
| --- | --- | --- |
| Agent 执行状态 | `backend/agent_core/state.py` | 新增独立、JSON 可序列化的 memory context；兼容 `sync_contract()`，避免被重建时覆盖 |
| LangGraph 图 | `backend/agent_graph/reading_agent_graph.py` | 当前前序是 `resolve_context → run_collaboration → prepare_conversation → route_request`，不能只在协作后召回记忆 |
| 本地 checkpoint | `backend/services/agent_checkpoint_service.py` | SQLite/WAL，`thread_id = run_id`；保持此语义，新增会话记忆时不得改成 `conversation_id` |
| 对话保存 | `backend/services/conversation_store_service.py` | 默认最多 50 个会话且会裁剪；长期历史召回需要将分页与删除策略分开 |
| 对话生命周期 | `backend/services/conversation_lifecycle_service.py` | 生产注入使用此子类；覆盖 rewind、删除、上下文切换及浮窗所有权，不能只改基类 |
| Agent 对话上下文 | `backend/services/agent_conversation_service.py` | `_history()` 当前最多 32 条完整消息，后续以 token 预算和可追溯摘要替代纯条数裁剪 |
| 普通聊天 | `backend/services/companion_chat_service.py`、`backend/api/dependencies.py` | Agent Workspace 和 Companion/AI Chat 两条路径都要接入 |
| 多 Agent 记忆 | `backend/agent_core/multi_agent/context/memory_adapter.py` | 默认内存字典；生产必须注入持久化协调器，内存实现可留作测试替身 |
| 多 Agent 桥接 | `backend/services/multi_agent_runtime_bridge.py` | 当前以 `state.session_id` 传递 `user_id`，必须改成服务端解析的稳定 profile |
| 多 Agent 执行 | `backend/agent_core/multi_agent/orchestration/executor.py` | 当前执行结果直接交给 `memory_adapter.save()`；改成受策略控制的候选提交 |
| 研究记忆 | `app/research/memory.py`、`backend/services/research_memory_service.py` | 复用已有 claim/evidence/entity/relation 和可靠性检查；笔记与文献仍为证据来源 |
| 本地向量库 | `backend/rag/stores/qdrant.py`、`backend/api/knowledge_dependencies.py` | 复用 Embedding/Reranker 与客户端生命周期；记忆单独 collection，禁止并发打开同一 Qdrant Local 路径 |
| 可观测性 | `backend/agent_core/events.py`、`backend/models/agent_tools.py`、`apps/desktop/src/api/agent.ts` | 核心枚举、`AgentTraceEventType`、序列化、前端解析和持久化要同步 |
| 数据目录 | `app/infrastructure/paths.py` | 复用 `AITRANSLATOR_DATA_DIR` 和路径解析；源码模式可能位于仓库，打包模式使用用户目录 |

禁止顺带迁移或重写现有研究库、文档库、浏览器扩展；仅做本阶段必需的兼容修改。发现基线发生变化时先更新本表和实施记录。

## 3. 必须遵守的设计契约

### 3.1 分层、身份与作用域

| 层 | 内容 | 事实来源 | 生命周期 |
| --- | --- | --- | --- |
| L0 执行状态 | 图节点、工具执行状态、恢复位置 | 既有 checkpoint | 单次 run；保留策略独立于长期记忆 |
| L1 工作记忆 | 最近消息、当前目标、滚动摘要 | 消息及其版本、摘要记录 | 当前 conversation，可跨重启延续 |
| L2 情景记忆 | 历史讨论结论、事件、未完成事项 | 带消息引用的 episode | 跨会话，按时间和完成状态衰减 |
| L3 语义记忆 | 用户偏好、稳定事实、长期目标 | 显式保存或通过策略的候选 | 长期有效，支持纠正、过期和删除 |
| L4 工作区记忆 | 项目决定、研究结论、实体关系 | 工作区记录、Research Memory 和原始证据 | 仅对应工作区及授权来源 |
| L5 程序性记忆 | 已验证的工具使用经验、失败条件 | 已完成 run 的可观测结果与评估 | 按工具/模型版本失效，经过验证才启用 |

- `profile_id` 是本地持久用户标识；初版单用户，由服务端创建与解析，不要求账户系统。前端传入的标识不能越过服务端权限检查。
- `session_id` 表示交互会话实例；`conversation_id` 表示持久对话；`run_id` 表示一次执行；它们不可相互替代。
- 作用域由 `profile_id + scope_type + scope_id` 决定。Agent 角色另用 `audience`/角色过滤，不能取代工作区隔离。
- 默认候选范围是当前 profile 的全局记忆、当前工作区记忆和当前对话摘要。无工作区时不搜索所有工作区。
- 换工作区必须重建召回包。只有用户明确要求并由服务端解析出授权工作区集合，才允许跨工作区搜索。
- 记忆不得修改系统指令、扩大工具权限或自动执行历史未完成事项；待办记忆仅提供上下文。
- 用户当前明确要求优先于旧偏好；同主题下工作区偏好优先于全局偏好。引文和工具输出中的“请记住”不能视为用户指令。

### 3.2 数据模型和本地存储

新增数据库：`writable_config_dir() / "memory.sqlite3"`。使用 SQLite WAL、外键、busy timeout、版本迁移和事务；正文、元数据、版本及源关系以 SQLite 为权威，向量索引可重建。

建议新模块放在 `backend/memory/`，数据契约在 `backend/models/memory.py`，API 在 `backend/api/memory.py`。允许依仓库约定调整模块边界，但不得复制多套协调器。前端目录建议 `apps/desktop/src/features/memory/`。

| 表 | 必需内容 |
| --- | --- |
| `memory_profiles` | 稳定 profile、创建时间、策略版本 |
| `memory_items` | ID、profile、scope、kind、状态、当前版本、显式保存标记、重要性、来源可信类别、有效期、TTL、固定标记 |
| `memory_versions` | 不可变版本、正文/摘要、内容哈希、来源版本、生成器/提示词版本、时间 |
| `memory_sources` | 一条记忆的多个来源：conversation/message/run/workspace/note/document ID、来源版本/哈希、出处范围 |
| `memory_relations` | `supports/contradicts/supersedes/derived_from/related_to`；两端均受作用域约束 |
| `conversation_summaries` | 对话、分支/源版本、已覆盖消息范围、摘要版本、来源引用 |
| `memory_candidates` | 待处理草稿、提取版本、策略判定、原因、幂等键 |
| `memory_snapshots` | 本轮选中的记忆版本引用、顺序、策略/撤销版本、token 预算；不含向量 |
| `memory_usage_logs` | run/message、snapshot、记忆 ID/版本、选中原因、时间；默认不复制正文 |
| `memory_policies` | 各开关、工作区覆盖、远程处理权限、保留策略 |
| `memory_jobs` | 持久后台队列：类型、版本、幂等键、状态、租约、重试、下次运行时间、错误类别 |
| `memory_tombstones` | 防止旧任务重新写回已删除内容所需的最小标识/哈希和撤销版本；不保存已删除正文 |
| `schema_migrations` | 版本、执行时间；重复启动不重复迁移 |

`memory_items.status` 固定为 `candidate/active/superseded/forgotten/expired/rejected`，候选工作流详情放候选表。置信度若来自模型只能称“提取置信度”，不得当作校准概率；来源类型、证据有效性和用户确认是独立字段。

更新采用版本号的乐观锁；过期版本更新返回冲突，不悄悄覆盖。实体、哈希和唯一约束必须包含 profile/scope，禁止把不同工作区相似事实自动合并。

### 3.3 策略开关与临时会话

| 设置 | 初版默认值 | 行为 |
| --- | --- | --- |
| `saved_memory_enabled` | true | 允许用户明确保存及召回已保存记忆 |
| `reference_chat_history` | false | 用户启用后才进行跨会话情景召回和对应索引 |
| `auto_extract_enabled` | false | 用户启用后才自动提取一般长期候选 |
| `workspace_memory_enabled` | true | 在授权当前工作区内使用记忆；不能扩大文档权限 |
| `background_remote_processing` | false | 后台摘要/提取不默认调用远程 LLM |
| `allow_sensitive_memory` | false | 默认拒绝保存敏感记忆，不做敏感偏好推断 |
| `temporary` | 每个对话创建时确定 | 无既有记忆读取，无内容持久化，无后台任务 |

- 开关在服务端执行；UI 只是操作入口。策略变化必须令缓存和进行中的后台任务重新检查。
- 关闭读取不会删除已保存数据；关闭历史参考也不得删除原始聊天。重新启用不自动回扫全部旧历史，用户可选择具体会话/时间范围。
- 临时会话允许使用用户本轮主动提供的文档/片段，不允许通过“记忆”旁路召回过去资料。其短期上下文和 checkpoint 使用进程内实现。
- 临时会话的 HTTP 日志、异常、trace、工具调用快照、前端 localStorage、后台队列均不得写入正文；只允许无正文的计数和错误码。
- 临时会话调用记忆写工具应返回禁用原因；创建可持久文档等用户主动操作仍沿用产品既有权限，不得通过该动作隐式保存聊天记忆。
- 初版将敏感记忆保存开关保持不可用，直到 M08 完成加密和验收；密钥、密码、验证码始终拒绝记忆化，不能因开关开启而保存。

### 3.4 写入、异步任务和崩溃一致性

显式保存：用户意图 → 服务端校验 → 同步 SQLite 事务提交 → 返回成功 → 异步建立索引。索引失败不能把已提交记忆报告为不存在；UI 显示索引待处理。

自动提取：已持久化的完整交换 → 持久队列 → 按策略提取草稿 → 来源与冲突校验 → 提交记忆和索引任务。`cancelled/error/confirmation_required` 或仍在 streaming 的回答不作为已完成结论。

- 记忆变更和它的索引 outbox 必须在 `memory.sqlite3` 的同一事务中写入。
- 对话消息位于 `web_chat.sqlite3`：应在该库的完成事务中写 source outbox，再以幂等转交到 memory jobs。禁止“先完成消息，再仅在内存发一个任务”留下崩溃丢失窗口。
- 交付消息按至少一次执行设计，业务效果用唯一键保证至多一次；不能声称外部 LLM/工具网络调用 exactly-once。
- 去重键至少包含任务类型、源 ID、源版本、提取器/策略版本；显式工具写入使用稳定 tool-call ID。不能只用正文哈希区分所有操作。
- 队列支持租约到期回收、有限重试、退避和 dead-letter。关闭进程时停止领取新任务；进程重启后恢复未完成任务。
- 先写 tombstone 和撤销版本，再清理向量、摘要和历史引用；旧任务提交前再次检查撤销状态，不能复活被删除记忆。
- 统一由后端生命周期管理一个 worker 和 Qdrant 客户端；后台任务只携带 ID/版本，按需读取来源，不复制整段消息。

### 3.5 检索、预算与来源

默认检索顺序：授权范围硬过滤 → 少量明确固定偏好 → FTS5 关键词和 Qwen3 向量并行召回 → RRF 排名融合 → 可用时 Qwen3 rerank → 去重、有效期/冲突检查 → token 截断 → MemoryPacket。

- 中文 FTS 必须有明确策略：保存规范化搜索列，中文按字符 bigram、拉丁文本按词生成词项，查询与索引采用相同版本分词器；保留原文供展示，短字符查询有受限精确匹配补偿。不能假定默认 unicode61 已实现中文分词。
- 不直接相加 BM25、余弦相似度和 reranker 原始分值。先使用 RRF（初值 `k=60`），时间、固定标记和作用域只作可解释的策略排序；后续调参需用冻结评估集。
- 初始候选上限：关键词 30、向量 30、合并后最多重排 30，输出最多 8 条普通记忆，固定偏好也计入预算。无关查询允许返回空集合。
- `MemoryPacket` 预算初值 `min(2048 tokens, 当前可用输入预算的 15%)`；最近历史初值上限 4096 tokens、滚动摘要 1024 tokens，由统一上下文预算器统筹并预留输出和工具空间。
- 使用模型可用的 tokenizer；不可用时使用保守估计并标注估计方式。测试长中文和中英混排，不能假设一字等于一个 token。
- 每条记忆包含 ID、版本、作用域、来源引用和选中理由；完整原文/表格仍从知识库按引用获取，记忆不复制整个文档。
- `memory_snapshot_id` 固定本轮选择；新版本通常从下一轮开始生效。删除、禁用、来源撤销优先于快照复现：下一次模型调用前必须检查，受影响的恢复任务返回明确失效状态，需要构造新上下文再继续。
- checkpoint 中仅保存可解析引用、预算与状态；若已有其他状态字段包含已注入记忆的 prompt/工具结果，也必须纳入撤销清理或使对应恢复失效。
- “使用来源”表示片段被提供给模型，不能声称能证明模型最终答案因果上依赖该片段。

### 3.6 初始保留策略

- 显式记忆默认无 TTL，用户删除或设有效期后失效；固定不等于绕过权限、删除或预算。
- 自动情景记忆默认 90 天未使用后过期，可在设置中修改；已完成待办降权，不继续作为待执行任务注入。
- 自动候选默认 30 天未决则过期；摘要随消息版本失效，不无限叠加“摘要的摘要”。
- 原始会话不再因达到 50 条自动删除，列表用分页控制；清理历史是独立可见设置。
- 已完成 run 的 checkpoint 默认保留 30 天；未完成可恢复 run 不静默清除。日志/任务错误记录默认 30 天，使用记录默认 90 天；清理过程不得留下已删除正文副本。
- “忘记”立即停止未来使用；“清除此来源及派生记忆”包含来源消息、派生版本、索引、快照/trace 引用的清理。UI 分别说明其范围。
- 已导出的外部文件、用户另存备份不在应用可撤销范围。不得承诺文件系统/SSD 上的取证级擦除。

## 4. 阶段安排与执行规则

按顺序推进：`M00 → M01 → M02 → M03 → M04 → M05 → M06 → M07 → M08 → M09`。

M04 完成可作为显式记忆预览版，M06 完成可作为自动记忆测试版；只有 M09 通过才可称“完整记忆系统”。预览版不得提前打开尚未实现的功能。

每阶段必须完成：实现 → 对应测试 → 与旧功能的边界回归 → 更新第 9 节记录。失败应修复或明确记录真实阻塞；不能把未运行、跳过和通过混写。单纯改变状态或补文档不算实现。

后续 Codex 每次执行先检查当前 HEAD、工作区差异和本地 `AGENTS.md`。保留用户未提交修改；必要的常规实现自主完成。仅在用户要求提交/推送时执行对应 Git 操作，本文本身不授予发布权限。

### M00：现状基线与可重复评估夹具

目标：后续每个阶段都能对比行为，并且不会误连真实用户数据库或真实远程服务。

开发任务：

- [ ] 核对第 2 节入口，记录真实运行时、数据目录、图顺序、生产依赖注入与全部聊天入口。
- [ ] 建立 `tests/memory/conftest.py`：临时 `AITRANSLATOR_DATA_DIR`、可控时钟、假 LLM、假 embedding、独立 SQLite/Qdrant 路径。
- [ ] 建立 `tests/memory/fixtures/`：profile A/B、workspace A/B、偏好修正、长对话、中文术语、已删除来源、临时会话等纯合成数据。
- [ ] 建立 `docs/development/memory-system-validation.md`，记录测试命令、环境、基线失败和指标定义。
- [ ] 跑现有 checkpoint、对话和多 Agent 相关回归；现有失败独立记录，不改动无关业务来“修绿”。

验证与退出条件：

- `tests/memory/test_baseline_contracts.py` 验证测试实例重开可访问自己的库、不能访问其他 fixture 的库。
- 能稳定复现 32 条历史窗口与 50 会话裁剪现状，并以行为用例记录待改进目标。
- 记录 `python -c "import sys; print(sys.executable)"` 结果和依赖可用性；测试默认不使用网络和真实用户内容。
- 所有后续阈值都能映射到可执行场景和固定输入。

### M01：持久存储、稳定身份、策略和队列底座

目标：在无 Embedding/LLM 的环境下完成可靠的记忆 CRUD，并在重启后保持一致。

开发任务：

- [ ] 实现 `backend/models/memory.py` 和 `backend/memory/{repository,policy,identity,jobs}.py`，采用第 3 节契约。
- [ ] 创建版本迁移；空库、旧库、迁移失败回滚、重复启动都要可用。新增表不覆盖现有用户数据库。
- [ ] 稳定 profile 只在首次运行创建；浏览器刷新、主窗口/浮窗、进程重启使用同一标识。
- [ ] 实现 item/version/source/relation CRUD、乐观锁、最小来源校验和 scope 隔离。
- [ ] 实现 memory jobs/outbox、租约和幂等消费；变更与索引任务同事务写入。
- [ ] 接入后端 startup/shutdown；建立健康状态，明确 unavailable/degraded/ready，禁止把数据库损坏伪装成空库并声称保存成功。

测试文件：`test_repository.py`、`test_migrations.py`、`test_scope_policy.py`、`test_jobs.py`。

验收：重开数据库内容和 profile 不变；跨作用域读写被拒；相同幂等请求只产生一个逻辑变更；并发更新不丢失；在“已提交但消费者未确认”故障点重启不会重复版本；缺少 torch 不影响 CRUD。建议命令：`conda run -n aitrans python -m pytest tests/memory -q`。

### M02：显式记忆 API、管理界面和临时会话

目标：用户能明确保存/修改/忘记记忆，界面与后端真实状态一致。

开发任务：

- [ ] 增加 `/api/memory/items` GET/POST、`/{id}` GET/PATCH/DELETE，以及 `/api/memory/policies` GET/PATCH；列表有过滤和分页，修改传 expected_version。
- [ ] 增加 `memory.remember/search/list/update/forget/explain_usage` typed tool 契约并沿用现有读写工具机制；本阶段 search 用有界关键词/精确检索，M05 扩展语义能力。
- [ ] 写权限和作用域由服务端注入，不能让模型把 `profile_id/workspace_id` 改成其他范围；明确用户指令可直接保存普通偏好，含糊指令按既有确认交互澄清对象。
- [ ] 新增记忆中心基本列表、详情、编辑、删除、作用域、来源、固定状态和开关；空态、索引待处理、保存失败均有可见反馈。
- [ ] 在 Agent 与 Companion 主窗口/浮窗贯通 temporary 标记，接入进程内会话和 checkpoint，禁止正文落入 trace/日志/浏览器存储。
- [ ] UI 中保留自动提取、历史参考等功能入口但在对应阶段完成前禁用；显示尚未可用的原因。

测试文件：`test_memory_api.py`、`test_memory_tools.py`、`test_temporary_mode.py`；前端 `MemoryWorkspace.test.tsx` 和 temporary runtime 测试。

验收：HTTP/API/UI 都能列出重启前保存的记忆；版本冲突可见；服务不可用时无虚假成功；将唯一测试标记写入临时会话后，扫描测试目录全部 SQLite 表和日志/JSON/localStorage mock，找不到该正文；临时会话不得调用持久写工具或产生后台任务。

### M03：短期上下文、滚动摘要和历史保留

目标：长会话保留早期目标及决策，原始会话不因列表容量被静默删除。

开发任务：

- [ ] 分离 ConversationStore 的列表 limit 与保留策略；API 和前端增加游标分页，旧 limit 调用保持兼容。
- [ ] 实现统一上下文预算器和 working-memory builder；当前消息必保留，完整工具调用/结果配对不得被切断。
- [ ] 使用最近完整消息 + 带证据范围的滚动摘要，替代 Agent 仅截取 32 条消息的逻辑，同时接入 Companion。
- [ ] 摘要字段固定为当前目标、已确认决定、未解决问题、关键来源；不得将假设、取消回答或助手建议变成用户决定。
- [ ] 摘要记录 source message ID/顺序、分支 revision、内容哈希与覆盖范围；rewind/edit/delete 后使相关摘要和情景候选失效。
- [ ] 摘要失败、超时或不允许远程处理时使用有界原始片段回退；禁止为了摘要阻止用户继续发送消息。
- [ ] 在用户允许的处理策略下，增量生成摘要；定期根据权威源重建，防止反复压缩导致事实漂移。

测试文件：`test_working_memory.py`、`test_summary_lineage.py`、`test_history_retention.py`，扩展现有 conversation lifecycle 测试。

验收：创建 60 个会话后第一个仍可分页访问；构造 100 条完整消息，开头的项目目标仍在最终上下文中且未重复加入当前消息；中文长输入不超过预算；rewind 之后不再使用被撤回结论；摘要器超时仍能得到有效上下文；无关阅读材料不污染 General Chat。

### M04：LangGraph/聊天接入与幂等恢复

目标：已保存偏好能影响所有聊天入口，恢复任务时记忆选择可复现且遵守最新删除策略。

开发任务：

- [ ] 实现 `MemoryCoordinator` 与 `MemoryPacket`，在 State 中使用 typed `memory_context`；快照引用必须独立于可被 `sync_contract()` 覆写的 legacy 字典。
- [ ] 调整图前序为 `resolve_context → prepare_conversation → resolve_memory → run_collaboration → route_request`，验证所有权释放和失败清理。若保留原顺序，必须提供等价的前置身份/记忆解析并通过相同验收。
- [ ] 在 planner、ReAct、最终回答及 Companion provider prompt 组装点注入经过预算的上下文；记忆作为来源数据，不能作为高优先级指令拼接。
- [ ] checkpoint 保存 snapshot ID、引用和状态；普通更新不改变正在恢复的 run，删除/禁用/权限撤销使对应快照失效。
- [ ] 引入 graph/state schema version，并为升级前 checkpoint 制定兼容路径：缺少 memory 字段时采用空记忆默认值；已有 pending 节点只能按验证过的映射恢复。无法安全映射时保留原数据并返回明确的不兼容原因，禁止清空旧库或盲目重跑前序写操作。
- [ ] 显式 memory tool 的重放使用稳定调用键；保持已有“未知写工具效果需人工恢复”的保护，不得借记忆改造将全部写工具变成可自动重放。
- [ ] 完成会话时事务性写 source outbox，再异步转交到 memory jobs；覆盖进程在两个数据库提交之间崩溃的窗口。
- [ ] 新增记忆事件并贯通核心枚举、后端 literal、WebSocket、trace store、前端事件处理；每种事件有独立测试。

事件至少包括：`memory_retrieval_started`、`memory_retrieval_completed`、`memory_context_ready`、`memory_write_committed`、`memory_write_rejected`、`memory_forgotten`、`memory_fallback`、`memory_snapshot_invalidated`。后台 job 状态另走 jobs API，不在已经结束的流中伪造新事件。事件仅包含 ID、版本、耗时、原因码和计数，不默认附全文。

测试文件：`test_agent_memory_integration.py`、`test_companion_memory_integration.py`、`test_checkpoint_memory.py`、`test_memory_event_contract.py`、`test_source_outbox.py`。

验收：跨新 conversation 重用显式偏好；所有入口一致；中断重启后只保存一次；在 source outbox 转交前后分别注入故障，最终各产生一个任务；写入新偏好版本后恢复旧 run 的快照不漂移；删除引用记忆后恢复返回可解释失效状态，不再次调用模型使用旧正文；使用升级前格式的 checkpoint 夹具验证兼容或明确拒绝，不重复外部写入；既有 checkpoint 测试继续通过。

### M05：跨会话情景检索和混合召回

目标：不同措辞、中英混排和历史事件都能被召回，未授权或失效内容绝不入包。

开发任务：

- [ ] 按 `reference_chat_history` 策略建立 episode 索引；每个 episode 对应主题/完整交换组，保留时间、决定、待办和消息引用，不机械复用文档 chunk 大小。
- [ ] FTS5 使用第 3.5 节中文分词策略，特殊字符安全转义，查询长度和匹配数有界。
- [ ] 新增 `aitrans_memory_v1` 向量集合；记录模型 ID、revision、维度和索引版本，同维度换模型也必须重建。
- [ ] 与知识 RAG 共享后端管理的 embedding/reranker runtime；独立集合与 scope filters，索引线程不另开同路径 Qdrant 客户端。
- [ ] 实现 RRF、重排、来源时效检查、预算和空结果阈值；不相关输入可返回空包。
- [ ] 向量模型不可用时降级 FTS；reranker 不可用时降级 RRF；提供 health 和 fallback 事件。
- [ ] 向量更新使用版本化 point ID/校验，读索引后回 SQLite 验证当前状态，旧删除任务不得误删较新版本。

测试文件：`test_fts_chinese.py`、`test_retriever.py`、`test_vector_index.py`、`test_retrieval_fallback.py`；真实模型测试使用 `rag_gpu` opt-in marker。

验收：固定集中“保留英文缩写/英文简称不要展开”、中文短词、项目名/错误码均有正确结果；跨 scope 结果为零；删去模型依赖仍可关键词召回和保存；独立模型索引重建后没有旧向量混用；使用独立测试目录运行真实 Qdrant reopen 测试。

### M06：自动提取、合并、纠正与遗忘

目标：系统在用户启用后逐渐积累有来源的长期记忆，并能更新过时内容。

开发任务：

- [ ] 实现结构化 MemoryExtractor，只输出候选；记录源消息、源版本、提取器版本、提示词版本和证据片段。
- [ ] Policy Gate 校验用户来源、敏感性、作用域、引用匹配和未来价值；不能因模型声称“用户喜欢”就写入。
- [ ] 首版允许自动激活的类别限定为用户直接表达的普通风格/术语偏好、明确项目决定及未完成目标；其他推断保留 candidate 或 rejected。
- [ ] 合并按主题、scope 和来源版本执行；相同信息补充来源，真正修正创建新版本和 supersedes 关系。
- [ ] 冲突不能只依赖 embedding 相似度；“全局学术风格”和“当前项目简短文案”并存。未解决冲突标记待确认，不同时当成确定事实注入。
- [ ] 实现 TTL/衰减/过期 worker 和可重建的 Memory Summary。摘要是视图，条目和来源是事实依据。
- [ ] 用户忘记后写 tombstone，重试、重新索引、旧摘要与旧来源回扫均不能无提示地恢复内容；用户主动再次保存同一内容才允许新授权版本。
- [ ] 历史回扫仅处理用户选择的范围，支持进度、取消、重试及费用/提供商提示；默认不开启远程后台调用。

测试文件：`test_extraction_policy.py`、`test_consolidation.py`、`test_forgetting.py`、`test_history_backfill.py`。

验收：每个候选都有真实源或被拒绝；否定、引用、助手建议不会误记成偏好；显式纠正优先；两个作用域不误合并；时间推进使 episode 过期但不让显式固定记忆过期；保存后忘记再重放旧 job，活动记忆仍不存在；后台任务失败不改变已完成回答状态。

### M07：多 Agent 和研究工作区记忆

目标：现有三个 Agent 使用同轮一致的记忆，研究结论保留证据，程序性记忆只提供经验证建议。

开发任务：

- [ ] 生产 `AgentMemoryAdapter` 注入 Coordinator；移除生产路径默认匿名 bucket，使用服务端 profile + scope + agent audience。
- [ ] Supervisor 冻结共享 snapshot，将术语/语言/风格偏好交给 Translation，阅读目标交给 Reading，工作区研究证据交给 Research。
- [ ] AgentExecutor 的 save 改成候选 DTO；禁止序列化完整 AgentResult、无限增长历史列表或保存运行时对象。
- [ ] 为 ResearchMemoryService 建只读适配器，复用 fresh/stale/orphaned/detached/conflict 检查；通用记忆删除不能删除原始研究笔记。
- [ ] L5 程序性候选只记录工具名、前置条件、脱敏参数模式、验证结果、失败边界和版本；不保存隐含推理或历史执行权限。
- [ ] 首版程序性激活条件：至少 3 个独立成功 run 的可观测证据，且通过对应工具链 fixture 回归；不满足则保持候选。工具契约版本变化后失效并重新验证。
- [ ] 为程序性记忆提供开关、来源和停用入口；建议不直接触发工具调用，也不绕过已有确认机制。

测试文件：`test_multi_agent_memory.py`、`test_workspace_memory_adapter.py`、`test_procedural_memory.py`。

验收：三个 Agent 获得相同 snapshot ID 与各自允许的片段；服务重建后仍能读取；workspace A 的历史内容无法通过全局/匿名路径进入 B；错误 Agent 输出不直接激活；过期研究来源不会被包装成可信新事实；程序性建议不能触发未获授权的外部写操作。

### M08：完整记忆中心、删除链路、备份与迁移

目标：用户能够理解、管理和迁移本地记忆，并验证所有内容删除路径。

开发任务：

- [ ] 记忆中心补齐全局/工作区/类型筛选、candidate 审阅、版本/冲突、有效期、来源跳转、summary 和使用记录。
- [ ] 回答旁增加“参考记忆”入口，显示实际 MemoryPacket 引用；没有注入时不显示“已使用”。断开的来源有明确状态。
- [ ] 区分单条忘记、清理该来源及派生内容、清理工作区、清理全部。将删除范围与处理进度显示给用户。
- [ ] 对 message rewind/delete、workspace 删除和用户清理执行统一失效传播，覆盖 FTS、Qdrant、摘要、缓存、snapshot、checkpoint 恢复入口、trace 与 jobs。
- [ ] 提供版本化 JSON 导出/导入；导入校验 schema/大小/来源、按目标 profile 映射 scope，默认不自动激活导入的程序性候选或任意指令。
- [ ] 使用 SQLite 在线 backup API 生成一致备份；不能运行中仅复制 `.sqlite3` 而遗漏 WAL。跨数据库备份应暂停写入并记录统一清单，或实现明确的一致性协调；向量通过重建恢复。
- [ ] 配置迁移路径，验证 `AITRANSLATOR_DATA_DIR` 切换和旧库升级；不硬编码开发机用户目录。
- [ ] 若启用敏感记忆：正文/版本/来源摘录均加密，密钥交系统凭据存储；不进入 FTS、向量或明文导出，默认不自动注入远程请求。解密不可用应显示锁定而非空记录。
- [ ] 多窗口缓存失效统一处理；关闭/删除记忆后，其他窗口下一次请求也使用新策略。

测试文件：`test_deletion_cascade.py`、`test_backup_restore.py`、`test_import_export.py`、`test_sensitive_storage.py`；前端记忆管理与来源面板测试。

验收：测试正文可在保存后检索；执行彻底清理后，应用管理的测试数据库、索引、日志中均不可读取该正文，恢复旧 run 不能重新注入；恢复备份后条目版本和关系一致且向量可重建；导入错误回滚；敏感标记不出现在数据库明文、全文索引、向量 payload 和日志中。

### M09：端到端验收、性能与交付

目标：用真实用户流程证明第 1 节能力，提供可复现的结果与限制。

开发任务：

- [ ] 建立 `backend/evaluation/memory_benchmark.py`，输入合成评估集，输出指标、延迟、错误类别、模型/索引/提示词版本的 JSON 报告。
- [ ] 执行第 7 节全部场景；API/State 验收用确定性 provider，真实 Qwen3 和实际配置 LLM 的效果单独报告。
- [ ] 完成旧 Agent、Companion、会话生命周期、知识 RAG、Research Memory、checkpoint、前端类型及构建回归。
- [ ] 模拟只读目录、磁盘写入失败、数据库忙、损坏副本、worker 强制退出、向量失效、没有 torch、没有网络等故障，验证明确降级而不误报成功。
- [ ] 完成全局功能开关和回滚说明：关闭功能后旧聊天继续工作，新增数据库保留，破坏性 schema downgrade 禁止自动执行。
- [ ] 更新验证文档、用户操作说明和本任务书状态；记载真实模型未验证项、性能硬件条件和已知限制。

退出条件：第 7 节硬性验收全部通过，质量/性能目标达到或有明确说明且不宣称已达到；任何越权、删除复活、临时内容落盘、静默数据丢失均阻止完成标记。

## 5. 测试执行规范

### 5.1 分阶段命令

在仓库根目录执行，先确认当前 Python 环境。本项目此前出现 base Python 缺少 torch 的问题，验证不得把该错误误判为算法问题。

```powershell
git status --short --branch
conda run -n aitrans python -c "import sys; print(sys.executable)"
conda run -n aitrans python -m pytest tests/memory -q
conda run -n aitrans python -m pytest tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_conversation_integration.py tests/agent/test_agent_trace_event_contract.py tests/test_conversation_store.py tests/test_conversation_lifecycle.py tests/test_backend_companion_stream.py -q
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
```

`tests/memory` 是 M00 新建目录；尚未创建时仅运行既有基线测试。每阶段可仅运行对应测试文件，M09 再运行完整测试；文档修改不需要重复全量业务测试。新增测试名可以调整，但应同步本任务书。

发布验收补充：

```powershell
conda run -n aitrans python -m pytest tests -q
conda run -n aitrans python -m ruff check backend/memory backend/models/memory.py backend/api/memory.py tests/memory
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Ruff 同时覆盖本次修改的既有 Python 文件，命令中列出的新目录须先创建。Cargo 检查用于 M09 打包边界；中间阶段未动 Rust 无需每次运行。

真实本地模型测试使用现有 opt-in 模式，并强制指定独立测试数据目录：

```powershell
$memoryPreviousGpuFlag = $env:AITRANS_RUN_RAG_GPU_TESTS
$env:AITRANS_RUN_RAG_GPU_TESTS = '1'
try {
    conda run -n aitrans python -m pytest tests/memory -m rag_gpu -q
} finally {
    if ($null -eq $memoryPreviousGpuFlag) {
        Remove-Item Env:AITRANS_RUN_RAG_GPU_TESTS -ErrorAction SilentlyContinue
    } else {
        $env:AITRANS_RUN_RAG_GPU_TESTS = $memoryPreviousGpuFlag
    }
}
```

无 GPU/模型时明确记“未执行真实模型验证”；mock 通过不能替代真实向量语义验收。真实远程 LLM 测试需测试配置显式允许，不使用用户历史作为夹具。

### 5.2 故障注入原则

- 测试 SQLite/Qdrant 必须使用临时目录；不对用户真实库做 kill、损坏、删除或迁移演练。
- 时间使用 fake clock，重试使用可控 worker，避免分钟级 sleep。
- 至少覆盖事务提交前、提交后消费前、索引写成功未确认、删除后旧 job 重试、来源修改后提取结果返回这五个窗口。
- 对外部调用记录次数和幂等键，以业务效果断言；不只断言函数被调用。
- 隔离/隐私测试需要观察最终 provider 输入和持久层内容，不能只检查前端按钮是否隐藏。

## 6. 质量与性能目标

以下是待实现的初始目标，不是当前测量结果。M00 冻结指标定义，M05/M09 记录实际值；参数调优使用开发集，不能泄漏最终评估集。

| 指标 | 测量条件与目标 |
| --- | --- |
| 持久化正确性 | 跨重启 CRUD、版本和来源完整性用例 100% 通过 |
| 隔离/隐私 | 所有 profile/scope/临时会话/删除撤销场景 100% 通过；零容忍越界结果 |
| 幂等 | 故障注入和重复恢复后，每个显式操作只产生一次逻辑变更，每个源版本至多一次激活结果 |
| 检索召回 | 至少 120 条带标注查询，含中文/中英混排、改写、版本/项目名；相关查询 Recall@5 ≥ 0.90 |
| 无关召回 | 至少 30 条无相关记忆的独立查询；错误非空包比例 ≤ 5% |
| 自动提取 | 至少 100 段带“允许保存/不允许保存”标注的交换；活动记忆 precision ≥ 0.95，recall ≥ 0.80；不得以全部拒绝刷 precision |
| 冲突更新 | 显式纠正、跨 scope 非冲突、来源撤销专门场景全部通过；被取代条目不作为当前确定事实入包 |
| token 预算 | 中文、英文、混排、超长原文和多工具结果全部不超已配置输入预算 |
| CRUD 延迟 | 本地 10,000 条普通记忆，热缓存，p95 ≤ 100 ms，不计 UI 绘制和后台索引 |
| 检索延迟 | 同规模 FTS 回退 p95 ≤ 150 ms；GPU 热模型混合检索含重排目标 p95 ≤ 800 ms；冷加载单列 |
| 后台影响 | 回答完成仅等待持久 outbox 提交，附加 p95 目标 ≤ 100 ms，不等待 LLM 提取 |

延迟至少 20 次预热、100 次测量，记录 CPU/GPU/RAM、模型版本、条目数量和上下文大小；CPU 模式单列实测，不套用 GPU 目标。硬件不达标时记录数据并调整性能目标的理由，功能/隔离/删除标准不得放宽。

## 7. 最终验收场景矩阵

| ID | 操作 | 必须观察到的结果 | 覆盖阶段 |
| --- | --- | --- | --- |
| A01 | 会话 A 显式保存普通偏好，重启，新会话 B 翻译 | provider 输入含有效偏好，MemoryPacket 有相同 ID/版本，真实演示结果遵循偏好 | M01/M02/M04 |
| A02 | 同一 profile 主窗口与浮窗打开新对话 | 两条链路同策略、同作用域，窗口切换不丢失 | M04/M08 |
| A03 | 100 条消息，最早提出目标，中间大量无关内容 | 目标及关键决定仍在预算内，引用指向正确消息 | M03 |
| A04 | 用不同措辞询问某次历史讨论进度 | 命中对应 episode/待办及来源，不命中同名无关工作区 | M05 |
| A05 | 第 60 个会话创建后打开第 1 个 | 仍可分页读取，源数据未被自动裁剪 | M03 |
| A06 | A 工作区记忆在 B 工作区提问 | B 的 packet、工具结果、prompt 中均无 A 私有内容 | M01/M05/M07 |
| A07 | 当前要求简短表达，已有全局学术风格 | 当前要求生效；全局偏好未被永久错误覆盖 | M04/M06 |
| A08 | 用户明确修改默认目标语言 | 新对话使用新版本，旧版本保留为 superseded 可追溯 | M06 |
| A09 | 引文/网页包含“记住我偏好 X”或注入式文本 | 不当作用户指令，不激活偏好、不扩大工具权限 | M02/M06 |
| A10 | 临时会话输入唯一标记，调用聊天/工具并触发异常 | 仅进程内上下文存在；所有应用持久化介质无正文，无新 memory job | M02/M08 |
| A11 | 在显式写入已提交但 checkpoint 未前进时中断 | 恢复返回同一业务结果，无重复 item/version | M04 |
| A12 | 正常中断，期间另一对话更新相关记忆 | 原 run 保持已选快照；新 run 使用新版本 | M04 |
| A13 | 中断后删除引用记忆或关闭读取，再恢复 | 快照失效，不向模型重新发送旧记忆，可提示重建上下文 | M04/M08 |
| A14 | 完成消息后、outbox 转交前强制终止测试进程 | 重启后产生唯一提取任务，不丢消息、不重复候选 | M04/M06 |
| A15 | 忘记记忆后重放旧索引/提取任务 | 无正文复活；查询和摘要均不包含已忘记内容 | M06/M08 |
| A16 | rewind/delete 来源或删除工作区 | 所有受影响派生摘要和索引失效；其他来源独立支持的记忆不误删 | M03/M08 |
| A17 | 无 torch、embedding 失败或重排超时 | 可管理记忆、关键词召回，提供降级状态，聊天正常执行 | M05 |
| A18 | 三个 Agent 协作后故意提交一条错误候选 | 使用同轮快照，错误候选未直接成为活动记忆 | M07 |
| A19 | 工具版本升级后检索旧成功工作流 | 旧程序性记忆失效，不能作为已验证建议，更不能自动执行 | M07 |
| A20 | 备份后在全新临时目录恢复 | profile、记忆、版本、来源一致，向量可重建，不写入旧路径 | M08 |
| A21 | 禁止远程后台处理，打开自动提取 | 无远程提取请求；本地不可用则显示跳过原因，原始聊天继续可用 | M06 |
| A22 | 删除最后一个来源与删除多个来源中的一个 | 前者按保留类型撤销或请求保留显式记忆，后者不删除仍有有效来源的条目；来源 UI 准确 | M06/M08 |
| A23 | 存储写入失败、版本冲突、队列 dead-letter | API/UI/健康状态准确，不出现“已记住”的虚假成功 | M01/M02/M09 |
| A24 | 向量更新和删除任务乱序，或旧提取迟到 | SQLite 最新状态决定可见性，旧版本不覆盖新版本或删除新内容 | M05/M06 |

A22 中显式保存记忆与来源聊天分离：普通删除聊天默认失效其自动 episode/摘要；显式记忆可以保留但显示来源已删除。选择“清除此来源及派生记忆”时显式记忆也应纳入；多来源情况下明确展示删除范围，不误删其他独立来源支持的事实。

## 8. 交给后续 Codex 的执行提示词

将以下模板中的阶段编号替换为当前最早未完成阶段：

```text
请执行 docs/development/memory-system-taskbook.md 的 Mxx 阶段。

先读取任务书、docs/development/memory-system-validation.md（如已存在）、
当前 AGENTS.md 和该阶段涉及的最新代码；检查当前 HEAD 与未提交改动。
以前序阶段的已验证交付为基础；若缺少必要前置能力，先补齐到本阶段可验证。

完成本阶段全部开发任务、对应测试和必要回归。
保留现有 Agent、Companion、RAG、Research Memory、checkpoint 的行为契约。
测试只能使用临时数据和合成内容，不修改真实用户数据库。
权限、删除撤销、临时模式和来源验证在服务端执行。

更新任务书中的任务复选框、阶段状态和实施记录，并更新 validation 文档。
记录真实命令、通过/失败/跳过数、环境、已知问题；未运行不得写成通过。
不要仅返回方案；请交付实际改动和验证结果。
当前请求未要求 Git 提交或推送时，不自行发布。
```

阶段交付记录模板：

```markdown
### Mxx 实施记录 — YYYY-MM-DD

- 状态：not_started / in_progress / blocked / verified
- 起始 HEAD：
- 实际实现与涉及路径：
- 契约/数据迁移变化：
- 测试命令与结果（passed / failed / skipped 分开）：
- 真实模型/手工验收：
- 相对于本任务书的调整及原因：
- 已知限制/阻塞与下一步：
- 提交 ID：如未提交写“未提交”
```

## 9. 阶段状态表

| 阶段 | 名称 | 状态 | 验证记录 |
| --- | --- | --- | --- |
| M00 | 基线与评估夹具 | not_started | 待实施 |
| M01 | 本地存储、身份、策略、队列 | not_started | 待实施 |
| M02 | 显式记忆、基础 UI、临时模式 | not_started | 待实施 |
| M03 | 短期上下文与历史保留 | not_started | 待实施 |
| M04 | LangGraph/聊天接入与恢复 | not_started | 待实施 |
| M05 | 跨会话混合检索 | not_started | 待实施 |
| M06 | 自动长期记忆与遗忘 | not_started | 待实施 |
| M07 | 多 Agent、研究与程序性记忆 | not_started | 待实施 |
| M08 | 完整管理、删除、备份迁移 | not_started | 待实施 |
| M09 | 端到端质量与交付 | not_started | 待实施 |

## 10. 参考边界

本方案参考 ChatGPT 的公开产品行为：保存记忆、参考历史、临时聊天、查看/修正/删除和记忆来源。数据表、队列、检索参数、权限及阶段安排均为 AITrans 的工程设计，不代表 ChatGPT 内部实现。

- [OpenAI：Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq)
- [OpenAI：Memory and new controls for ChatGPT](https://openai.com/index/memory-and-new-controls-for-chatgpt/)

实施时若依赖外部框架新增 API，应检查项目实际安装版本与对应官方文档；不能根据本任务书假设 SQLite checkpointer 自动提供跨会话长期 Store。
