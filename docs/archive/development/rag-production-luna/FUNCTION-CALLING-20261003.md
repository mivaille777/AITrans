# 本地资料 Function Calling 实施与验收

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../../start.ps1)；最新检索修复见 [语义排序报告](../../../development/rag-semantic-ranking-2026-10-05.md)。

## 实施范围

生产 Companion HTTP/WS 和 Reading Agent 已接入原生 Chat Completions Function Calling。Auto 由模型选择工具并填写参数，Never 不暴露本地工具，Always 要求先执行本地访问；参数修复期间仍保持 required。

复用现有 `search_knowledge_base`、`read_knowledge_chunk`、`read_knowledge_section`，新增 `list_knowledge_documents` 薄封装。目录读取 manifest；搜索只提供导航片段；读取正文后才生成可引用证据。GraphRAG、融合、重排和索引算法未修改。

服务端保留最大资料范围，模型只能在已知且允许的文档 ID 中缩小搜索范围。空数组继承服务端范围；读取锚点必须由本轮搜索定位，现有 generation/来源校验继续执行。旧 `document_scope` 调用保留。

Companion 上限为 2 次搜索、4 次读取、7 次总工具调用，串行执行；总执行期限 240 秒，单工具 120 秒，支持取消。真实文本模型冷加载超过一分钟，因此未使用会导致首次检索失败的 60 秒工具期限。Agent 继续受现有 Runtime 更严格的预算约束，同时模型可见搜索/读取次数分别最多 2/4。

原生流式参数按 index 完整组装后才解析、执行。assistant/tool 消息保留相同 tool_call_id；工具阶段的介绍文字会清除，最终回答复用现有引用 guard、WS 替换草稿及会话持久化。非法参数允许一次修复；越界、超时、服务故障、无匹配分别返回明确状态。Trace 保存调用 ID、参数哈希、状态和耗时，不保存新引入的原始工具参数；HTTP/WS 随执行状态更新记录，后续模型失败或工具取消时仍保留已发生的调用。

## 修改文件与必要性

| 文件 | 必须修改的原因 |
|---|---|
| `app/ai/tool_calling.py`（新增） | 共用原生工具请求、响应及流式组装，保留现有 SDK 异常分类。 |
| `app/ai/client.py` | DeepSeek 客户端接入共用工具 API，原 complete 接口保留。 |
| `app/ai/openai_compatible.py` | 兼容客户端接入同一工具 API。 |
| `backend/agent_tools/knowledge.py` | 增加目录工具和模型可填写的有界搜索参数，复用已有搜索/读取执行器。 |
| `backend/services/knowledge_function_calling.py`（新增） | HTTP/WS 共用有界循环、范围/定位校验、错误回传及累计引用标签。 |
| `backend/services/companion_chat_service.py` | 接入共享循环和真实模型决策；复用回答、引用校验及返回结构。 |
| `backend/api/companion_stream.py` | 让 WS 接入同一循环，最终状态使用实际检索结果并持久化。 |
| `backend/api/dependencies.py` | 启用生产聊天入口，延迟绑定现有 RAG/正文存储及目录。 |
| `backend/services/agent_tool_registry.py` | 给现有工具注册表提供可选目录依赖。 |
| `backend/services/agent_react_decision_service.py` | 原生工具决策映射现有 Tool/Final 合同，回放真实工具消息并验证参数。 |
| `backend/models/agent_react.py` | 持久化原生调用 ID，使 Agent 后续轮次可正确回放。 |
| `backend/agent_core/product_adapter.py` | 移除生产 Auto 的规则提前关闭；保留范围/工具白名单，并修复数组、整数被转成字符串的问题。 |
| `backend/agent_graph/reading_agent_graph.py` | 传递调用历史，记录实际检索决策；失败检索没有正文时拦截模型虚构引用。 |
| `backend/services/product_agent_service.py` | 保留模型在服务端范围内的缩小选择，传递根 Trace；证据汇总阶段禁止重复检索。 |
| `backend/api/llm_dependencies.py` | 启用生产 Agent 原生决策，继续使用现有配置的 planner 模型。 |
| `tests/test_knowledge_function_calling.py`（新增） | 验证原生协议、意图入口、范围、错误、预算、HTTP/WS 持久化及完整 Agent 搜索/读取/校验流程。 |
| 本报告、`OPEN-ISSUES.md` | 记录当前验收证据与未解决风险，避免把功能验收表述成生产效果达标。 |

## 验证证据

本机证据目录：`data/benchmarks/knowledge-function-calling-20261003/`，包含修改前副本、增量 diff、测试报告、模型协议和实际接口报告。

- 相关回归 163 项通过（`targeted-tests.xml`）；其后补充 Always 参数修复、循环期限错误分类、取消及模型失败时 Trace 保留，最终局部复验 **69 项通过**，见 `final-focused-tests.xml`。两轮测试有重叠，不相加为独立用例总数。
- 新模块 Ruff 通过；对修改前副本比较，既有文件无新增 Ruff 诊断。Python 编译检查通过。未删除或跳过测试，未升级依赖。
- 真实 `deepseek-v4-flash` 原生协议通过：模型返回 `list_knowledge_documents` 与结构化参数，不依赖 JSON 决策文本。
- 真实模型意图冒烟 7/7：闲聊、通用知识、翻译不访问资料；目录走 manifest；单文档、双文档比较、上下文追问执行搜索和读取。使用合成文档测试意图，不作为召回质量评测；文档问题允许为了名称解析先读取目录。见 `live-intent-smoke.json`。
- 真实原资料、Qdrant、BM25、GraphRAG、Qwen3 embedding/reranker、DeepSeek：Auto 的 HTTP 和 WS 都执行一次搜索、两次读取，调用均成功；只返回指定水箱论文证据，HTTP 3 条、WS 4 条正文证据，引用 guard 严格通过。目录准确返回 3 份资料且没有搜索。见 `text-function-smoke.json`。
- 完整编译 Agent 图通过搜索→读取→已有证据汇总→引用校验；检索失败后即使模型输出虚构 `[1]`，也不释放该回答。普通问题直接完成且不执行工具。
- 保留修改前已有失败：`test_companion_capability_routing_matrix.py` 有 4 项 fixture 未接受 `trace_id` 的 TypeError。加载本轮修改前的 Companion 源码后同样复现 4 项失败；按最小修改原则未顺手修改。

## 尚未解决

1. **视觉复验失败**：本轮原生视觉预检出现 CUDA 显存分配失败，未满足无视觉回退的断言。测试子进程已退出；用户启用配置与已发布索引未改。随后实际接口测试明确采用文本/GraphRAG 配置，不能替代视觉验收。见 `visual-preflight-failure.json`。初次测试进程也未继承用户环境路径；已修正测试环境，并恢复已停止的本机 Docker/Qdrant。
2. **整体效果与容量仍未达标**：既有 Recall/MRR、并发和视觉语义验收结论保持；7 条意图冒烟不能证明生产精确率/漏检率。独立大样本意图集、真实业务资料、持续负载及打包入口仍待验收。
3. **Agent 冷加载预算**：保留现有 Runtime 时限；首次模型加载可能超过它的严格工具时限。实际资料 API 测试进行了模型预热，不声称完成了冷启动容量验收。
4. **应用生效**：代码生产入口已启用，但未启动常驻后端或重启桌面应用；需下一次正常启动读取本轮代码。现有后台启动自动审批拒绝的问题保持记录。

本轮没有提交或推送。整体生产结论继续 NO-GO；本轮通过的是 Function Calling 功能接入和上述限定验证。
