# 目录元数据与 Function Calling 风险复验

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../../start.ps1)；最新检索修复见 [语义排序报告](../../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-10-03（Asia/Shanghai）。基线为本轮开始时的工作区，HEAD `4b0d802c`、分支 `electronrebuild`；不把此前未提交的开发计入本轮增量。未提交、未推送。

## 已完成

- 目录工具返回 `file_format`、`modified_at`、`metadata_status`。格式来自登记源文件的受支持扩展名；修改时间读取允许范围内源文件的 `st_mtime`，返回 ISO 8601 UTC。API 复用既有 `source_type` 表示格式，新增时间与可用状态。没有用导入/索引时间替代源文件修改时间，没有根据标题或正文猜格式。
- 对缺失、不可访问或无法读取的来源，时间为 null，并明确区分 `source_missing`、`source_denied`、`source_unavailable`；未提供可信格式时为 unknown。目录仍按服务端 scope 过滤，工具不返回本地源路径。已有文件不需要重建索引即可查询这些元数据。
- 修复普通 Agent Auto 问答被旧文档分析编排接管、直接返回分析 JSON 的问题。compat/native 两种 Root 拓扑的默认问答都进入原生 Function Calling；明确的 `workflow_action` 和非 Auto 编排模式仍沿原入口执行。
- 搜索找到候选且尚未尝试正文读取时，Companion/Agent 下一轮只提供 Read 工具并要求调用。空检索、工具故障及预算耗尽保留诚实失败路径；模型违背 required 合同明确报错，正文/引用校验保持。比较请求要求分别读取各文档并引用。
- 启动时对已有 READY 资料库复用现有健康探测准备 embedding、reranker 和已启用视觉模型，将首次加载移出 Agent 的 20 秒工具/45 秒总预算。预热失败记录模型状态和异常，不伪报模型就绪；其他应用服务仍可启动。视觉包装器的 reranker 探测改为访问其已有文本底座。
- Electron 就绪等待从约30秒延长到约6分钟，容纳本机模型准备。修复 PowerShell 启动脚本将依赖探测代码传给 Python 时丢失引号的问题：仅将 `python -c` 改为标准输入执行，未跳过探测。

修改时间是源文件状态；它不表示索引已自动重建。索引/来源版本仍由既有发布和校验逻辑处理。

## 每个文件的修改必要性

| 文件（相对仓库根目录） | 必须修改的原因 |
|---|---|
| `backend/services/knowledge_library_service.py` | 复用源文件权限边界，集中读取格式、修改时间与缺失状态。 |
| `backend/agent_tools/knowledge.py` | 将元数据传入模型实际使用的目录工具结果。 |
| `backend/models/knowledge_api.py` | 为目录、详情、导入及重建响应声明新增字段，兼容旧响应。 |
| `backend/api/knowledge.py` | 将同一来源元数据接入四类文档响应。 |
| `backend/services/knowledge_function_calling.py` | 让模型正确解释和展示元数据；修复搜索后未 Read 的工具约束。 |
| `backend/services/agent_react_decision_service.py` | Agent 使用同样的搜索后 Read 约束。 |
| `backend/agent_graph/reading_agent_graph.py` | 修复 compat/native 的默认 Auto 问答被旧编排抢占。 |
| `backend/api/rag_models.py` | 复用模型探测实现启动准备，并修复视觉包装器探测接线。 |
| `backend/main.py` | 在服务接受请求前执行模型准备并记录失败。 |
| `apps/desktop/electron/main/services/backend-process-manager.cts` | 原30秒启动等待小于真实模型准备时间，会误判后端失败。 |
| `start-electronrebuild.ps1` | 实际启动复现 Python SyntaxError；标准输入避免 PowerShell 原生参数丢引号。 |
| `tests/rag/test_knowledge_api.py` | 验证 PDF/DOCX/Markdown、中文/空格路径、时间刷新、来源异常及 API 一致性。 |
| `tests/rag/test_model_manager.py` | 验证视觉包装探测、启动准备顺序、空库跳过和失败状态。 |
| `tests/test_knowledge_function_calling.py` | 验证搜索后必须 Read、拒绝未读事实、两种 Root 拓扑及实际编排桥接存在时的搜索/Read/guard 链路。搜索预算测试改用无候选场景，继续检查第三次搜索不可用。 |
| `tests/test_companion_capability_routing_matrix.py` | 上轮4项 fixture 未接受生产调用的 trace_id；仅补兼容参数，保留全部业务断言。 |
| `docs/development/rag-production-luna/OPEN-ISSUES.md` | 更新最新闭环与未解决问题，保留历史失败结论。 |
| 本文件 | 保存逐文件原因、真实验证和剩余风险，便于后续决策。 |

生产/测试/启动代码本轮15个文件，333行新增、21行删除；文档另计。没有升级依赖、替换模型、调检索权重或修改用户资料/索引。桌面测试新增一条目录测试对话，未删除用户会话。

## 验证与证据

本机证据目录：`D:/AITrans/data/benchmarks/metadata-risk-20261003/`（Git 忽略）。保留修改前备份、失败报告、完整响应、测试 XML、本轮 diff 和哈希，未覆盖原失败结论。

| 验证 | 结果与范围 |
|---|---|
| 最终局部 Python 回归 | **83通过，0失败/跳过**，34.01秒；覆盖元数据/API、模型管理、后端健康、能力矩阵、原生 Function Calling。`final-local-tests.xml`。 |
| 编排与工具首轮定向回归 | **51通过**，其中含12项 Root/路由相关回归；随后 compat/native 桥接强化验证 **42通过**。与最终83存在重叠，不累计为独立用例数。 |
| Electron | 类型编译通过；后端进程合同 **4通过**；PowerShell 语法解析通过。真实启动再次执行依赖探测与 Electron 编译，日志见 `desktop-launch.log`。 |
| 静态与增量审查 | 对本轮 Python 增量与开工备份比较，**无新增 Ruff 诊断、无新增行末空白**；修改文件字节码编译通过。保留原有诊断，没有全库格式化。`changes.json`、`current-turn.diff`。 |
| 真实模型意图80题 | `deepseek-v4-flash`，中英文闲聊/通识/所选文本转换/目录/文档检索/比较/追问/Never/Always，**80/80**。工具资料为受控两文档，不能充当生产检索质量评测。 |
| 意图标注纠正 | 原报告78/80中，一例比较未 Read 为真实缺陷；另一追问“核实这个数值”在历史中没有数值，正确答案应要求澄清。保留原80个问题和原报告，单独记录标注纠正，未改问题或伪造前文。`intent-label-corrections.json`、`intent-acceptance-after.json`。 |
| 原生视觉 | 原模型、SDPA+NF4/256 token 配置完成真实查询与两张页图编码；embedding、reranker、ColQwen 共存的完整检索无视觉回退，真实候选包含6项视觉结果。不是持续容量/复杂图表语义验收。 |
| 冷启动首条真实 Agent | 启动准备 **64.55秒**；准备后首条请求 **9.23秒**，返回所问单句与 **2条正文证据/2条引用**，guard通过（1条声明支持，0无效引用）。根 Trace/检索 Trace 保留。`cold-agent-smoke.json`。 |
| 真实 API 全入口冒烟 | Companion HTTP 200、WS done，搜索→Read→引用 guard；目录输出 PDF/Markdown 与源修改时间；Debug Trace、Agent scoped evidence（8包）通过。隔离 manifest/BM25/图数据库，Qdrant/视觉资产只读，退出后无测试模型子进程。 |
| 桌面启动与前端 | 常规 `start-electronrebuild.ps1 -RefreshRagEnvironment` 成功启动开发版 Electron、Vite 与8766后端，已核验监听及进程。通过浏览器访问相同 Vite 前端，发送目录问题，实际页面表格展示3份文档的格式与 UTC 时间，标记为 Knowledge directory，无引用失败回退。测试对话 ID `35d674165f254576ae4adf4a24c31b24`。未声称打包版或原生桌面窗口全部 UI 已验收。 |

真实前端显示的格式/时间：Computers and Chemical Engineering → PDF / 2026-05-06 08:02 UTC；科研多 Agent 任务书 → Markdown / 2026-09-16 08:36 UTC；Measurement → PDF / 2026-09-14 05:53 UTC。

## 保留的问题与可执行后续

1. **公开效果与并发容量仍未过生产门。** 本轮未改检索算法，也未把意图冒烟算入 Recall/MRR。沿用原冻结评测：Medical100999/dev100 Recall@5=0.63、MRR=0.5278，暖单并发P95=638ms、4并发P95=1465ms；SciFact/test300 Recall@5=0.7821、MRR=0.7209、P95=667ms。后续在冻结开发集上按坏例分析选择检索/重排方案，配对复验后再决定推广；不降低0.80/0.70/800ms门槛。
2. **独立引用语义质量仍阻塞。** 本轮 guard 通过证明当前来源与引用合同成立，不证明独立 Citation Accuracy≥0.90。既有独立 judge 校准仍不合格；需有代表性的人工双人复核金标或合格独立裁判后，再做盲评，不能用生成模型自评替代。
3. **视觉高负载/图表语义尚未通过。** 多模型共存成功说明本次功能可用，不能排除其他程序占用GPU/RAM时再发生分配失败。继续用本机冻结复杂页图集验证公式/小字/图表语义，做持续负载与内存峰值评测，再决定资源配置；本轮未改变模型精度或全局系统设置。
4. **完整部署验收仍缺。** 本轮解除了开发版启动阻塞，但未验收安装包、长期运行、所有外部请求硬取消和精确 token/cost。中断后复查开发端口已无监听，未反复启动应用；这不撤销已完成的启动/前端功能验证。正常重开仍使用上述启动脚本。
5. **桌面主题 IPC 日志另列。** 本轮启动出现 `aitrans:overlay:set-visual-theme` 的 Unauthorized desktop IPC sender，目录问答未受阻；未改IPC身份校验或扩大白名单。需在桌面维护任务中核对发送窗口与时序，当前RAG任务保留该问题。

结论：目录字段、原生工具问答接线、本机模型首次准备及开发版启动功能验证通过；**整体生产结论仍为 NO-GO**，效果/独立引用/容量缺口继续保留。
