# AITrans Tools 管理界面：前后端分阶段开发任务书

日期：2026-10-07（Asia/Shanghai）
状态：任务规划；T00–T08 均未实施、未验收。本文中的新增文件和接口是开发目标，不代表已经存在。
设计参考：[Tools 重设计效果图](../design/tools-management-redesign-2026-10-07.png)。
执行要求：按阶段推进；每阶段完成实现、验证、记录、Git 提交和远端推送后，才能进入下一阶段。不得把全部阶段合并为一次提交或最后统一推送。

## 1. 目标与范围

将效果图落地为实际可用的 Tools 工作区：左侧工具目录、中间工具详情、右侧测试面板。所有工具名称、数量、结构、权限、状态和运行结果来自后端。启用策略同时影响真实 Agent/Chat 执行，测试面板复用现有执行、工作区范围及审批机制。

完整交付包含：

- 工具搜索、状态筛选、分组折叠、选择、启用/禁用。
- Overview、Parameters、Returns、Permissions、Examples 五个详情标签。
- JSON 输入、示例填充、上下文选择、输入校验、执行、结果、日志和上次运行。
- 超时、取消、能力允许时的流式输出。
- 图中的 Import、Add tool、Edit：通过受支持的执行器模板创建配置型自定义工具；支持配置导入、编辑与归档。
- 桌面启动、重启持久化、Agent/Chat 联动、布局与错误状态验收。

效果图是布局和样式依据。图中的 32、28/4、类别数量、vector_search、186 ms、5 results 均为设计示例；类别计数甚至与总数不一致，不能写进产品或作为接口事实。当前项目实际注册的搜索工具是 search_knowledge_base 等；首屏优先展示真实知识检索工具，不为复刻图片新增不存在的 vector_search 或图搜索执行器。未来已有工具可以按实际能力加入目录。

## 2. 已核实的项目基础

| 当前代码 | 已有能力 | 本任务的扩展方向 |
| --- | --- | --- |
| apps/desktop/src/features/workspace/WorkspaceSidebar.tsx、workspace-navigation.ts、WorkspaceShell.tsx | 黑色侧栏、工作区路由、固定高度容器 | 增加 /tools，沿用侧栏结构和独立滚动 |
| apps/desktop/src/features/skills/SkillWorkspace.tsx、SkillWorkspace.css | 相邻管理页、绿色选中与启用状态 | 复用视觉规则和通用组件 |
| apps/desktop/src/api/agent.ts、features/companion/components/AgentToolsControl.tsx | Chat 的工具目录与按次选择 | 与管理策略共享目录状态和缓存刷新 |
| backend/agent_tools/base.py | AgentToolSpec、TypedAgentToolDefinition、Pydantic 输入/输出模型 | 为管理页提供完整 schema 和明确执行元数据 |
| backend/services/agent_tool_registry.py | 真实注册、类型校验、上下文及执行入口 | 保持执行器唯一来源；补充管理元数据和执行前策略检查 |
| backend/api/agent.py、backend/models/agent_tools.py | GET /api/agent/tools、POST /api/agent/tools/{tool_name}/execute | 保留旧客户端响应契约，旧直接执行接口也必须服从新策略 |
| backend/services/agent_tool_execution_service.py、agent_run_store.py | 执行记录、效果类型、确认要求、安全重试与持久化 | 测试调用复用这些边界，补齐适合 Tools 页的异步任务适配 |
| backend/services/product_agent_service.py、product_agent_tool_port.py | 按次允许工具、任务授权、工作区范围 | 合并持久化管理策略，执行前再次验证 |
| backend/services/knowledge_function_calling.py、knowledge_function_recovery.py、companion_chat_service.py | Chat 原生知识函数与全文读取链路 | 检查目录、实际调用、恢复和直接读取路径，统一能力禁用 |
| backend/services/skill_function_bridge.py、skill_runtime.py | Skill 发现、激活、资源读取 | 维持 Skills 自身治理，明确依赖，不将 Skill 混同执行器 |
| backend/api/dependencies.py、llm_dependencies.py、backend/main.py | 服务工厂、注册表单例、路由与关闭生命周期 | 注入策略/管理/测试服务，处理配置更新和服务重启 |

现有 AgentToolSpec.input_schema 是参数属性映射，并非一定含 required、$defs 的完整 JSON Schema；现有目录 DTO 也不直接暴露结果 schema 和全部执行元数据。新接口需从 typed args_model / result_model 获取完整结构。Chat 原生知识函数与同名 Agent 工具可能有不同输入模型，必须核对调用入口及 schema，不能因为名字相同就强行复用参数定义。

现有直接执行 HTTP 接口调用 registry.execute；管理页不能直接沿用这条路径并假定它已具备完整审批、取消和持久化机制。现有线程超时也不等同于底层任务已经停止，必须明确执行状态。

本次规划时工作区已有大量与 Chat、RAG、启动有关的未提交修改。实施前记录基线，只提交本阶段自己的文件/变更，不将已有修改一并提交；禁止为整理工作区执行 reset --hard、自动 stash 或强制推送。

## 3. 产品和技术约定

### 3.1 界面规范

- 页面路由 /tools，侧栏顺序 Chat、Reading、Research、Knowledge、Agent、Skills、Tools；Tools 使用现有白色选中胶囊。
- 黑色侧栏 #0b0b0b，浅灰画布 #f6f8fb，白色主体，分隔线 #e6e9ed；正文 #202936，辅助文字 #7a8391。
- 选中/启用绿色 #3b7762 或 #43806a；浅绿背景 #f1f7f4 / #e8f3ed。
- Add tool 使用现有黑色主按钮；Run tool 使用页面内绿色变体，不改全站主按钮颜色。
- 外框沿用 18–22px 圆角，控件沿用现有组件；图标使用 lucide-react。
- 沿用项目英文界面文案；加载、空目录、空搜索、接口失败、后端不可用均有明确反馈和重试入口。
- 在 1680×1050 / 1920×1080 验收完整分栏。较窄窗口将测试区改为抽屉，目录可折叠；不强行挤成四个窄栏。
- 大表格、目录、日志各自滚动；页面标题、详情标签和执行按钮可访问，不让长结果撑破窗口。
- Tab 可键盘切换，图标按钮有标签，状态不只用颜色表示，焦点可见；Ctrl+Enter 仅在测试区执行且服从校验/运行中限制。

### 3.2 工具身份与可用状态

管理目录以服务端注册的真实能力为依据。用稳定 tool_id 标识管理对象，name 保留真实调用名；内置工具可采用 builtin:<name>，自定义配置采用 custom:<uuid>。namespace 和调用入口单独表示。

区分：

- enabled：本设备持久化的管理开关。
- available：当前依赖、上下文和工作区是否允许使用。
- unavailable_reason：例如缺少阅读选区、RAG 未就绪、沙箱未就绪、无可用文件工作区。
- effective_enabled：管理开关、运行时可用性和当前请求范围共同决定。
- effect / risk / confirmation：来自执行器和权限策略，不能由展示文案推断。

第一版管理开关按设备生效，跨工作区一致；工作区选择仅影响测试范围。避免界面暗示存在尚未实现的按工作区开关。禁用不卸载执行器；依赖不可用也不被记成用户禁用。

真实有效工具集合 = 注册工具 ∩ 管理启用集合 ∩ 当前可用能力 ∩ 请求/任务允许集合。保持现有 enabled_tools=[] 表示 Automatic 的语义，但 Automatic 只能使用管理允许集合；全部工具禁用时不得回退为全目录。

若已有调用入口在注册表外直接调用知识读取服务，需通过相同能力策略验证。对全文读取等复合能力检查所需底层能力；所需工具禁用时给出明确原因，不能绕过禁用或悄悄更换到另一条同能力路径。

### 3.3 内置与自定义工具

- 内置执行器代码、输入/输出 schema、效果类型和权限上限由代码定义。Edit 只修改允许的管理配置，例如显示说明、有效默认参数、示例和更短的超时；不能降低风险、关闭确认或扩展权限。
- 自定义工具第一版是受支持执行器的配置实例。Add tool 选择服务端公布的模板，例如“知识搜索预设”，填写名称、描述和参数预设，保留独立身份；调用仍走原执行器和同一策略边界。
- 模板决定可覆写参数、固定参数与参数合并顺序；运行时只能覆写明确开放的参数。必须对合并后的参数再次验证。
- Import 使用版本化 JSON 配置，先预览、验证，再原子导入。导入配置本身不执行代码、不调用网络、不安装依赖。
- 不接受任意 Python 函数、模块路径、eval、shell 命令或陌生 HTTP endpoint 作为新执行器。图片里的按钮不要求搭建一个任意执行平台。
- 自定义配置默认禁用；启用后才进入允许的 Agent/Chat 目录。其基础能力被禁用时，预设也不能成为绕过途径。
- 如实现中发现某模板需要新的真实执行器，应单独登记扩展任务，而非伪造可运行状态。

## 4. 统一数据与接口契约（T00 冻结，后续实现）

### 4.1 管理模型

| 模型 | 必要字段或语义 |
| --- | --- |
| ToolSummary | tool_id、name、title、description、category、namespace、origin、effect、enabled、available、effective_enabled、unavailable_reason、risk_level |
| ToolDetail | Summary + tool_version、revision、调用入口、input_schema、output_schema、context_requirements、permissions、limits、examples、execution_capabilities、editable_fields、updated_at |
| ToolCatalog | items、categories/counts、全目录 total/enabled/disabled、本次匹配 matched_total、分页 cursor、catalog_revision |
| ToolExample | id、title、description、arguments、所需上下文说明；不保存真实用户选区或原文 |
| ToolPolicy | tool_id、enabled、配置 revision、更新时间；默认值与后端定义明确 |
| ToolTestRequest | arguments、context_selection、timeout_seconds、stream_output、client_request_id；不接受客户端伪造审批或运行身份 |
| ToolTestRun | run_id、tool_id、tool_version、configuration_revision、status、UTC 时间、duration_ms、context_summary、result、error、result_summary、execution_state |
| ToolTestEvent | run_id、递增 seq、event_type、time、已脱敏 payload |
| CustomToolConfig | format_version、tool_id/name、template_id、description、开放/固定参数配置、examples、enabled、revision |

input_schema / output_schema 返回完整 JSON Schema；context_requirements 独立于用户业务参数。UI 允许显示 args schema 的只读 JSON；未支持的复杂 schema 结构提供明确 JSON 回退，不丢弃约束后假装表单完整。

permissions 至少区分知识读取、文件读写范围、网络访问、沙箱使用、确认要求和权限来源。未知权限显示“未声明”，不能猜测“Low risk”。没有已实现的限流就不展示“60 requests/min”；没有真实结果计数就不展示固定 5 results。

列表计数采用固定语义：总数和 enabled/disabled 来自完整目录；分类计数为当前文本和状态筛选下的匹配数；matched_total 为所有匹配数。所有分类之和与 matched_total 一致，不能从当前分页数据计算全目录计数。unknown category 原样保留并提供默认图标。

### 4.2 拟新增接口

| 方法与路径 | 用途 | 所属阶段 |
| --- | --- | --- |
| GET /api/tools | 目录、搜索 q、category、status=all/enabled/disabled、limit/cursor、上下文可用性 | T01 |
| GET /api/tools/{tool_id} | 完整详情、schema、权限、示例与 capabilities | T01 |
| PATCH /api/tools/{tool_id} | 带 revision 的启用/配置更新；按 editable_fields 校验 | T04、T07 |
| POST /api/tools/{tool_id}/validate | 校验业务参数和上下文需求，不执行 | T05 |
| POST /api/tools/{tool_id}/test-runs | 创建有持久化身份的测试调用，返回 202 和 run_id | T05 |
| GET /api/tool-test-runs/{run_id} | 查询状态、结果及已确认执行状态 | T05 |
| POST /api/tool-test-runs/{run_id}/cancel | 发起取消，返回实际状态 | T05 |
| POST /api/tool-test-runs/{run_id}/approve | 与现有服务端审批记录绑定后恢复，不接受裸 confirmed=true | T05 |
| GET /api/tool-test-runs | 按工具/工作区分页查看测试历史 | T06 |
| GET /api/tool-test-runs/{run_id}/events | SSE 事件流；支持 Last-Event-ID 恢复 | T06 |
| GET /api/tools/templates | 服务端支持的配置型工具模板及字段规则 | T07 |
| POST /api/tools | 创建配置型工具 | T07 |
| POST /api/tools/import/preview | 配置验证、冲突和差异预览 | T07 |
| POST /api/tools/import | 校验当前 revision 后原子导入 | T07 |
| DELETE /api/tools/{tool_id} | 仅归档自定义工具，不删除内置执行器及历史记录 | T07 |

静态路由 templates、import 等须在动态 tool_id 路由之前定义，或使用等价的不冲突路由设计。跨端契约以 T00 固定文档和 Pydantic 模型为准，避免前端与后端分别发明响应格式。

错误统一使用机器可读 code、用户可读 message、字段路径 field_errors 和可关联 trace_id；兼容现有客户端的 HTTPException/detail 读取规则。约定：未知对象 404、禁用/范围拒绝 403、版本/命名冲突 409、参数错误 422、依赖不可用 503。已创建的异步调用失败在 run.status/error 内表示，不能把已接受的 HTTP 请求事后视为 HTTP 500。

### 4.3 执行上下文、状态和存储

- context_selection 显式区分研究/知识工作区、文件工作区、阅读上下文；My Workspace 的界面名称不能被直接当成后端 ID。
- 根据 context_requirements 显示额外输入区，阅读工具缺少选区时不能以空字符串假调用；后端再次解析和验证实际资源范围。
- run_id、trace_id、tool_call_id、授权文档集合、审批状态由服务端构建，业务 arguments 禁止覆写这些保留字段。
- JSON 有效与 schema 有效分别呈现；校验通过后可显示“Ready to run”，仅可解析时显示“Valid JSON”。
- 执行状态：queued → running → succeeded / failed / timed_out / cancelled；需要确认时进入 awaiting_approval。服务重启恢复时可进入 interrupted；execution_state 明确 stopped / running / unknown。
- 对尚在后台运行的线程，取消/超时响应不得宣称 stopped；前端显示“请求已取消/超时，底层执行尚未确认停止”。写操作处于不确定状态时不得自动重试。
- 同一 client_request_id 和相同有效输入返回同一 run；同一键配不同输入返回 409。新一次有意执行使用新键。
- 开关更新影响后续调用；已经开始的调用不被虚假撤销；queued 和 awaiting_approval 的调用在执行/恢复前检查最新策略。
- 策略和自定义配置落入可写应用数据目录中的 SQLite，沿用项目路径约定。测试结果优先扩展已有 AgentRunStore，只在生命周期或存储职责确有差异时新增关联表；不把数据存进仓库或浏览器 localStorage。
- UTC 存储、前端按用户时区显示；不得预置图片中的成功记录。
- 日志保留输入摘要/哈希和必要诊断，凭据、原文、代码按既有策略脱敏。输入和输出限额、保留策略在 T00 固定；建议测试历史保留最近 100 条或 30 天，结果正文每条最多 256 KiB，超额标记 truncated。待审批和未确认停止的调用不随普通历史清理。

## 5. 分阶段实施任务

阶段编号固定为 T00–T08，依赖严格顺序。阶段内可分前后端子任务，但阶段退出时必须有一个可验证的整体结果。

| 阶段 | 目标 | 主要交付 | 阶段提交标题 |
| --- | --- | --- | --- |
| T00 | 基线与契约冻结 | 真实目录、调用路径、API 和验收基线 | docs(tools): T00 freeze contracts and implementation baseline |
| T01 | 后端只读管理目录 | 管理 DTO、目录/详情 API、旧接口兼容 | feat(tools): T01 expose typed management catalog |
| T02 | 前端工作区与目录 | 路由、样式、真实列表、搜索筛选 | feat(tools): T02 add management workspace and library |
| T03 | 五个详情标签 | schema、输出结构、权限、示例 | feat(tools): T03 add schemas permissions and examples |
| T04 | 持久化开关与全链路策略 | 启用持久化、运行时禁用、Chat 联动 | feat(tools): T04 enforce persistent tool policy |
| T05 | 真实测试调用 | 输入、上下文、审批、超时取消、结果 | feat(tools): T05 add governed tool test runs |
| T06 | 日志、历史与流式体验 | SSE、恢复、上次运行、分页历史 | feat(tools): T06 add test history and event streaming |
| T07 | 新增、导入与编辑 | 配置型自定义工具完整管理 | feat(tools): T07 add template based custom tools |
| T08 | 联调与桌面验收 | 真实链路、视觉/桌面证据、交接文档 | test(tools): T08 verify desktop and runtime integration |

### T00：基线与契约冻结

前端任务：

- 记录现有 Shell、Skills、Chat 工具选择器的布局/路由/Query key；明确 Tools 的路由挂载方式，避免双标题。
- 冻结 1680×1050、1920×1080、1280×800 和更窄窗口布局规则。
- 制定目录、详情、编辑、测试的状态矩阵以及错误文案；标出阶段性不可用按钮。

后端任务：

- 盘点真实注册工具、输入/输出模型、effect、上下文与依赖；不初始化大型模型只为获取目录。
- 盘点旧 HTTP 直接调用、Product Agent、任务 ToolPort、ReAct/原生 Chat、知识全文读取/恢复等所有调用入口。
- 将同能力的入口建立明确映射，说明哪些执行 schema 不同；区分内部辅助操作、Skill 函数和可管理工具。
- 固定数据模型、过滤/计数、开关范围、执行状态、保留上限、审批和超时语义。
- 记录当前 commit、分支、未提交改动和相关测试现有失败；不得为本任务提交此前其他功能。

交付与验收：

- [ ] docs/development/tools-management-contract.md：字段、请求/响应样例、错误和状态机。
- [ ] docs/development/tools-management-baseline.md：真实能力表、调用路径、入口与 schema 映射、已有失败。
- [ ] 前后端均能依据契约实现；图示名称与真实工具差异已标注。
- [ ] 本阶段文档检查通过，完成独立提交并推送。

### T01：后端只读管理目录

后端任务：

- 新建 backend/models/tool_management.py、backend/api/tools.py、backend/services/tool_management_service.py；服务从注册定义生成管理视图。
- 添加必要的元数据声明与完整 args/result schema 导出，复用定义来源，不写第二份硬编码工具目录。
- 提供 /api/tools 和详情接口；实现稳定排序、过滤、分页、全目录/匹配计数、revision、未找到与依赖状态。
- 补齐真实权限信息；未声明的能力显示 unknown。调用入口差异使用明确的 profile/entrypoint 记录。
- 在 backend/main.py 注册，沿用依赖工厂与生命周期；目录操作避免新触发推理或模型下载。
- 保留 /api/agent/tools 既有字段语义和前端旧选择器兼容性。

前端任务：

- 新建 apps/desktop/src/api/tools.ts，定义 TypeScript DTO 和查询方法。
- 在 shared/query/query-keys.ts 加入目录、详情、策略和测试 query key，确定失效范围。

验收：

- [ ] API 测试覆盖真实/空目录、未知 ID、关键字、筛选、分页和计数一致性。
- [ ] schema 与实际 typed 输入/输出模型一致，含 required、默认值、数组、嵌套引用。
- [ ] 旧工具目录相关测试通过；没有为了查目录调用模型。
- [ ] 本阶段允许真实依赖显示不可用，不能用假工具替代；完成提交与推送。

### T02：前端 Tools 工作区与目录

前端任务：

- 新建 features/tools/ToolsWorkspace.tsx、ToolsWorkspace.css、ToolLibrary.tsx、useToolsWorkspace.ts。
- 在 App.tsx 或现有路由实际挂载处添加 /tools，workspace-navigation.ts 增加 Tools，Sidebar 增加 Wrench 图标，Shell 增加固定高度策略。
- 落地顶部标题、真实计数、三栏布局和搜索/筛选/分组树；查询防抖建议 250 ms。
- 选中工具与必要的筛选状态可通过 URL 恢复；切换时取消/隔离过期详情响应。
- 目录支持滚动、未知分组、空状态、错误重试、后端未启动和窄窗口。
- Import/Add tool/启用/Test 的后续功能尚未交付时，显示明确禁用原因，禁止按钮看似可点击却无响应。

后端任务：

- 对接真实目录数据，纠正接口返回与契约不一致之处。
- 提供可复现的最小目录 fixture，供界面行为测试使用；生产不回退到 fixture。

验收：

- [ ] 页面能从真实 API 加载；所有名称和数量动态显示。
- [ ] 搜索 + 状态 + 分类组合一致，选择与筛选切换没有旧响应覆盖。
- [ ] 在目标窗口尺寸无溢出，主区域各自滚动，键盘焦点可达。
- [ ] 前端路由/关键交互测试和构建通过，截图归档，完成提交与推送。

### T03：五个详情标签和参数结构

前端任务：

- 新建 ToolDetailPanel、ToolSchemaView、ToolPermissionsView、ToolExamplesView。
- Overview 展示身份、来源、真实说明、效果类型、版本、依赖和限制。
- Parameters 支持 Visual schema / JSON；树状展示对象/数组/$ref、required、默认值、enum、范围，长说明可展开。
- Returns 展示完整结构化输出 schema；不把 output_text 等执行 envelope 与业务 data 混成一个结构。
- Permissions 展示准确的工作区/文件/网络/沙箱/确认策略；说明权限来自执行器或运行配置。
- Examples 支持 Copy、Use in test；后者可暂填充测试草稿，执行功能在 T05 开通。
- 切换 tab 保持选中工具；切换工具保留各自草稿或明确提示，避免旧参数误用于新工具。

后端任务：

- 补充已登记工具的权限、上下文、输出和可运行示例元数据。
- 校验示例符合各自入口的输入模型；需要上下文的示例标明额外要求。

验收：

- [ ] 五个标签均展示真实数据，不存在仅占位的标签。
- [ ] 嵌套对象、数组、可选/必填、默认值和未知 schema 类型可正确展示或回退。
- [ ] 所有发布的示例通过后端模型校验；跨工具复制不混入上下文保留字段。
- [ ] 关键行为测试与截图通过，完成提交与推送。

### T04：持久化启用开关与全链路执行策略

后端任务：

- 新建/扩展 ToolPolicyService 和 repository，支持事务、revision 比较、重启加载。
- 在 PATCH 接口持久化 enabled；更新时返回最新详情和 catalog_revision；并发冲突返回 409。
- 目录保留 disabled 工具供管理查看；运行时可用目录剔除 disabled 工具。
- 在真正调用执行器前统一检查策略；旧直接执行接口同样检查，并补上其所需的确认/范围边界。
- 按 T00 的入口清单覆盖 Product Agent、ToolPort、原生 Chat、恢复和直接知识操作；复合能力不可绕过策略。
- 管理禁用优先于前端 enabled_tools、任务快照与模型生成的 tool_calls；保留空数组 Automatic 语义。
- 运行中的已开始调用继续按既有语义完成；后续步骤、待执行和待审批恢复重新检查。

前端任务：

- 真实启用开关与 mutation；成功后使目录/详情/Chat tools 缓存失效，失败回滚并展示原因。
- 区分 Disabled 与 Unavailable；依赖恢复无需用户重复开关。
- Chat 工具选择器筛除或明确禁用不可用工具；已选但被管理禁用的项给出提示，不能静默扩大工具范围。
- 刷新或重启后恢复持久化状态。

验收：

- [ ] 禁用一个真实知识工具后，管理目录可见，但 Agent 自动/显式选择、HTTP 直接调用、原生 Chat 和恢复路径均不能绕过。
- [ ] 全部工具禁用不会恢复全目录；恢复启用后正常调用。
- [ ] 版本冲突、两窗口更新、进程重启、执行中禁用与审批后再禁用通过测试。
- [ ] Chat 原有按次工具选择行为保留；完成提交与推送。

### T05：受治理的真实测试调用

后端任务：

- 新建 ToolTestService 与必要后台任务适配，提供 validate、create/get/cancel/approve。
- 明确 arguments 与 context_selection 的输入边界；服务端解析工作区、资源/阅读上下文并校验输入。
- 通过既有 AgentToolExecutionService、AgentRunControl、审批/范围服务执行；不让新的 API 直接绕过到裸 executor。
- 遵守 min(用户超时, 工具上限, 系统预算)；写入和不确定调用不自动重试。
- 创建运行身份并持久化开始/结果/错误；绑定现有 run store，确保接受后崩溃可识别。
- 实现 client_request_id 幂等、重复按钮请求、取消和超时的真实状态。
- 对写工具及需要确认的工具复用服务端审批记录，批准后复核最新策略/范围/参数版本，拒绝不执行。
- 确认现有线程执行限制，未确定停止不得宣称任务已终止；不确定写入保持需核验状态。

前端任务：

- 新建 ToolTestPanel、ToolInputEditor、ToolResultView；先用轻量 JSON 编辑器组件，不为语法颜色引入不必要的大依赖。
- 语法校验、schema 错误字段定位、Copy example、示例填充及上下文选择。
- context_requirements 决定是否显示阅读输入、知识工作区、文件工作区等控件；并非所有工具都只有一个 Workspace 下拉框。
- Run/Running/Cancel、确认和拒绝、成功/失败/超时/取消/执行状态未知反馈。
- Result 显示 output_text、结构化 data、duration、trace；保留可复制 JSON，长结果折叠/截断提示。
- 切换工具/页面不将旧运行结果覆盖新工具；运行已创建后浏览器取消请求不视为底层任务已取消。

验收：

- [ ] 对固定测试文档执行真实知识检索，得到真实结果，非 mock 成功。
- [ ] 非法 JSON、缺少必填、错误类型、未知字段、伪造上下文、失效资源、禁用/不可用工具被明确拒绝且不产生执行副作用。
- [ ] 重复执行请求只调用一次；新请求可再次执行。
- [ ] 审批批准/拒绝、超时、取消、后台未停止和执行异常的结果正确。
- [ ] 无论前端状态如何，后端边界生效；完成提交与推送。

### T06：日志、历史和流式体验

后端任务：

- 用已有 trace/运行记录输出测试事件，加入递增 seq 和 SSE；从 run_id + seq 恢复，不重新执行。
- 事件至少包括 queued、started、approval_required、progress（有真实来源时）、completed、failed、cancel_requested。
- execution_capabilities 明确 supports_output_stream / supports_cancel；仅支持真实流式输出的执行器产生 output_delta。
- 实现分页历史、最近运行、日志/结果限额、清理与脱敏；服务重启将遗留运行转为可核验 interrupted，不直接标成功。
- SSE 连接断开不自动取消任务；查询状态/重连能恢复。

前端任务：

- Input/Result/Logs 三标签真实可用；Logs 显示时间、事件和错误，支持复制脱敏诊断。
- Stream output 仅按工具 capability 开启；普通工具的运行状态事件不被包装成内容流。
- 展示真实 Last run：状态、时长、可定义的结果数和时间，点击查看匹配的历史记录。
- 运行中切换页面后可恢复；重连去重，错误回退到状态查询。
- 在日志增长时提供受控自动滚动，用户上翻不被强拉回底部。

验收：

- [ ] SSE 重连无事件重复、结果重复或二次调用。
- [ ] 普通工具与真实流式工具各有明确能力反馈；无支持流式工具时控件禁用并解释。
- [ ] 历史刷新/重启可见，不包含其他工作区越权数据或敏感明文。
- [ ] 清理不会丢掉未决调用；最后运行没有预置成功数据。
- [ ] 故障与恢复测试通过，完成提交与推送。

### T07：新增、导入、编辑配置型工具

后端任务：

- 固定至少一个可运行模板（优先知识搜索预设），从服务端 executor/schema 映射生成字段规则。
- 实现自定义配置存储、注册适配与真实执行；基础工具策略/权限约束仍有效。
- 提供模板目录、创建、配置更新、归档、导入预览/执行；内置执行器不可被覆盖/归档。
- 格式版本、命名/ID 冲突、schema/default 校验、固定字段规则、revision 冲突和导入事务全覆盖。
- 更新后刷新注册缓存或采用受控动态装配；不要要求用户重启才能发现成功新增的工具。
- 区分 Chat 原生入口是否支持某模板：支持则接入，不支持则 capability 明示，并保证 Agent 入口真实可用。

前端任务：

- Add tool 打开模板选择与配置表单；展示模板来源、权限、参数开放范围，保存后选中新工具。
- Import 文件选择 → 预览 → 冲突处理 → 提交；失败保留可修改内容，成功刷新列表。
- Edit 按 editable_fields 显示允许修改的字段；禁止前端伪造可编辑权限。
- 自定义工具支持归档及明确反馈；相关运行中/待审批配置不可被修改到破坏其快照。
- 新建默认禁用，用户启用后可以测试并被允许的 Agent 调用。

验收：

- [ ] 新建一个搜索预设，启用后完成真实测试和 Agent 调用。
- [ ] 复制配置到独立测试数据目录导入后，行为符合预设；重启仍可用。
- [ ] 固定字段不能被调用时参数覆盖，基础工具禁用后预设同样拒绝执行。
- [ ] 导入无代码执行、无请求安装行为；冲突/错误不造成半导入。
- [ ] 内置 schema/权限不能被修改；归档保留历史身份。
- [ ] 完成提交与推送。

### T08：整体联调、视觉和 Windows 桌面验收

前端任务：

- 对照效果图完成间距、字重、侧栏、色彩、表格与分栏细节；对真实更长名称/schema 调整布局。
- 验证键盘、焦点、错误重试、窄窗口、不同缩放和长日志。
- 在实际 Electron 主窗口完成 Tools → Chat → Tools 联动，以及刷新/重启后的状态验证。
- 产出完整窗口、Parameters、Returns、Permissions、测试成功/失败、导入流程截图。

后端任务：

- 用独立临时数据目录运行端到端场景，不改写用户的真实知识库。
- 测试真实知识检索、阅读上下文、写入审批及文件/沙箱范围；有真实可用沙箱时运行隔离工作区验证。
- 无对应环境的验收项保持未完成，不能用 mock 当作真实集成证据。
- 验证重启、未决运行恢复、策略迁移/回滚、旧 API 与 Agent/Chat 行为兼容。
- 补充 API、开发使用和问题排查说明。

验收：

- [ ] Tools 页所有公开操作可用；最终没有“下一阶段开放”的死按钮。
- [ ] 管理开关与真实运行边界一致，测试与正式 Agent 不存在权限差异。
- [ ] 真实文档检索与已有 Chat 全文读取相关回归通过或明确解释已有失败。
- [ ] 样式、响应式、键盘及实际 Windows 桌面验收证据齐全。
- [ ] 交付 docs/development/tools-management-acceptance.md 和用户说明，完成最终提交与推送。

## 6. 建议文件组织

新增模块根据阶段建立，避免一次提前生成大量占位文件：

~~~text
apps/desktop/src/
  api/tools.ts
  api/tools.test.ts
  features/tools/
    ToolsWorkspace.tsx
    ToolsWorkspace.css
    ToolLibrary.tsx
    ToolDetailPanel.tsx
    ToolSchemaView.tsx
    ToolPermissionsView.tsx
    ToolExamplesView.tsx
    ToolTestPanel.tsx
    ToolInputEditor.tsx
    ToolResultView.tsx
    ToolRunHistory.tsx
    ToolConfigDialog.tsx
    ToolImportDialog.tsx
    useToolsWorkspace.ts
    ...必要的行为测试

backend/
  models/tool_management.py
  api/tools.py
  services/tool_management_service.py
  services/tool_policy_service.py
  services/tool_management_repository.py
  services/tool_test_service.py

tests/
  api/test_tool_management_api.py
  test_tool_management_service.py
  test_tool_policy_service.py
  test_tool_test_service.py
  agent/test_tool_management_policy_integration.py

docs/development/
  tools-management-taskbook-2026-10-07.md
  tools-management-contract.md
  tools-management-baseline.md
  tools-management-progress.md
  tools-management-acceptance.md
~~~

这些路径是建议职责边界。已有模块可满足需求时直接扩展；不为文件数量创建薄转发服务，也不把数百行页面与运行逻辑塞进一个 ToolsWorkspace。

## 7. 测试和阶段退出规则

### 7.1 按影响执行的检查

在现有项目 Python 环境运行，先确认解释器可用及依赖匹配；不盲目全量更新依赖。新增工具测试在其阶段建立后加入命令。

后端相关既有基线（从仓库根目录）：

~~~powershell
python -m pytest tests/test_backend_agent_tools.py tests/agent/test_typed_tool_registry.py tests/agent/test_agent_tool_execution.py tests/agent/test_product_runtime_adapter.py tests/agent/test_product_agent_routing.py -q
~~~

策略/原生知识调用阶段追加：

~~~powershell
python -m pytest tests/test_knowledge_function_calling.py tests/test_knowledge_function_recovery.py tests/test_knowledge_full_read_regression.py tests/agent/test_product_agent_context_mode.py tests/agent/test_native_tool_boundary.py -q
~~~

涉及沙箱或审批时，追加对应 tests/sandbox 和 tests/api 的相关回归。新代码用 Ruff 检查实际修改文件，已有失败按 T00 基线对比，不通过更改原测试期望来隐藏回归。

前端从 apps/desktop 执行：

~~~powershell
npx vitest run src/features/tools src/api/tools.test.ts src/features/workspace/workspace-navigation.test.ts
npm run typecheck:test
npm run lint
npm run build
~~~

前端影响 Chat 工具选择器时追加对应组件/Agent 测试。T08 执行完整 npm run test、npm run desktop:check 和实际 Electron 运行验收。不必每阶段重复所有桌面发布包流程；只有实际影响打包资源或发布构建时才扩展构建验证。

T00 是文档阶段，仅检查文档/契约与基线一致性，不为了文档改动运行完整应用测试。实际执行任何命令时保留输出摘要，未运行的检查不能写为通过。

### 7.2 每阶段完成定义

以下条件全部成立才标记阶段完成：

1. 本阶段前后端目标与列出的验收条件完成。
2. 相关测试、类型检查和构建通过，或仅有已记录且未受本阶段影响的既有失败。
3. 真实集成证据与 mock/fixture 测试分开记录；有未完成的必要验收就不标整体完成。
4. docs/development/tools-management-progress.md 记录改动、测试命令/结果、证据路径、限制和下一阶段依赖。
5. 只暂存本阶段变更，检查 staged diff 无意外文件、秘密、用户数据和大型测试输出。
6. 独立 Git commit 创建成功，随后 push 到远端对应分支成功。
7. 比对本地与远端提交 SHA；完成报告说明阶段、commit、分支和验证摘要。

进度表保留三个独立字段“实现/验收/远端同步”。代码已提交但 push 失败时记录“待推送”，不得宣称阶段完成，也不得带着未同步状态继续下一阶段。

## 8. Git 提交、推送与恢复

执行阶段默认开发分支 codex/tools-management，远端 origin；规划时当前分支为 maindev。开始实施时确认基线与未提交变更来源，必要时使用独立工作区；不要在缺少当前必要基线变更的干净检出中误称完整复现。

每阶段至少一个独立提交，可以包含阶段内修复提交；提交信息使用第五节标题或同等明确格式。阶段必须按顺序推送，不自动合并到 maindev，不创建额外发布流程。

执行流程：

~~~text
实现本阶段
→ 运行对应检查
→ 更新阶段记录和验收证据
→ git diff --check
→ git add -- <本阶段明确的文件或选择性的变更>
→ git diff --cached --check
→ git diff --cached --stat
→ 审阅 git diff --cached
→ git commit -m "<本阶段标题>"
→ git push -u origin HEAD
→ git rev-parse HEAD
→ git ls-remote origin refs/heads/<实际开发分支>
→ 核对两个 SHA，报告完成
→ 下一阶段
~~~

禁止 git add . / git add -A 将当前所有无关修改混入阶段提交。对于同时含有其他工作的文件，使用选择性暂存或独立工作区，不整体提交它们。

远端 push 失败：保留本地提交，先解决网络/鉴权/远端更新，再重试普通推送；不重新编造“已推送”。远端更新需要合并时，在保护本地改动后处理冲突并重新验证，禁止强推覆盖他人提交。

已推送阶段需修正时创建新提交；撤销使用 git revert 并考虑配置迁移兼容性。不要改写已共享历史。回滚代码不等于回滚用户数据；SQLite 迁移必须明确备份与旧版本读取策略，不用删除数据目录实现回滚。

## 9. 最终验收场景

| 场景 | 预期结果 |
| --- | --- |
| 首次进入 Tools | 展示真实目录、选中真实工具、有效数量与说明 |
| 搜索 + Enabled + 分类 | 列表与匹配计数一致，清空筛选可恢复 |
| 查看复杂输入/输出 | required、默认值、嵌套/引用保留；无法视觉展开时可看完整 JSON |
| 禁用知识搜索工具 | Agent 自动/显式选择、旧直接 API、Chat 原生函数和复合恢复均服从策略 |
| 全部禁用 | 空允许集合，不恢复全目录；用户获得可理解的限制说明 |
| 重启应用 | 开关、自定义配置和已保留历史恢复 |
| 非法输入 / 缺阅读选区 | 定位错误，无执行副作用 |
| 测试真实知识检索 | 真实返回、可关联 trace 和实际耗时；不预置结果数 |
| 选择另一工作区 | 服务端校验新范围，结果与历史不越权串用 |
| 测试写工具 | 明确审批；拒绝不写，批准后仍复核策略和范围 |
| 取消/超时 | 显示实际是否停止；不确定写入不自动重试 |
| 重复请求/重连 | 相同运行不重复执行，事件按 seq 去重 |
| 自定义预设 | 真实可调用；基础能力禁用不能通过预设绕过 |
| 导入冲突/错误配置 | 预览清楚、原子失败、无执行/安装 |
| 窄窗口/长日志/键盘 | 面板可访问、独立滚动、焦点清楚、无误执行 |
| 每阶段 Git 门槛 | 阶段独立提交且远端 SHA 一致，进度记录可复查 |

## 10. 实施记录模板

每阶段在 tools-management-progress.md 追加：

~~~text
阶段：Txx
状态：实现 [ ] / 验收 [ ] / 远端同步 [ ]
变更：
验证命令与结果：
真实验收证据：
已有失败/剩余限制：
提交：<commit SHA>
远端：origin/<branch>
远端 SHA 核对：
下一阶段：
~~~

本文件交付的是开发计划。只有真实实现、验收及远端同步后，才能填写完成状态。
