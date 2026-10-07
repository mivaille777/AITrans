# Tools 管理使用与开发说明

实现分支：`codex/tools-management`。设计参考见 `../design/tools-management-redesign-2026-10-07.png`；阶段计划见 `tools-management-taskbook-2026-10-07.md`。

## 使用界面

从左侧 Tools 进入。目录来自当前服务端注册表；搜索、状态和分类可以组合使用。总数与筛选后的数量分别计算，禁用工具仍能查看定义。大窗口显示目录、详情和测试三栏；1450 像素以下用测试抽屉，1000 像素以下增加目录抽屉。抽屉打开时移入焦点，Escape 关闭并返回触发按钮。

详情包含 Overview、Parameters、Returns、Permissions、Examples。输入、输出数据 Schema 与执行结果外层状态分开显示。Visual schema 展示可解析的嵌套结构；JSON 保留完整引用、组合类型和限制。Native Chat 使用不同参数模型时单独展示。详情标签支持方向键切换。

Enabled 是持久化开关；实际可执行还取决于依赖、上下文和基础工具策略。配置被他处修改时返回冲突，请 Reload 后重试。禁用策略覆盖 Agent 的自动/显式工具选择、执行器、Chat 原生知识函数及复合读取依赖。

## 测试工具

1. 在 Input 输入参数 JSON，也可从 Examples 的 Use in test 填入当前工具草稿。
2. 知识工具必须提供显式 Knowledge document IDs。阅读工具填写 Source text；其他阅读元数据可写入 Context & options 的 Reading context JSON。
3. Research workspace ID 与 Filesystem workspace ID 是不同上下文，服务端分别解析。工作区、文档范围不能通过普通参数扩大；不允许全库范围绕过。
4. Validate 只做模型和上下文校验。Run tool 创建真实调用；测试会使用实际执行器，写工具先停在 awaiting approval。
5. 阅读本次调用的审批摘要后 Approve this call，或 Reject call。审批绑定工具、调用 ID、输入和配置版本；不能拿旧审批批准新调用。
6. Result 展示状态、实际执行状态、trace、耗时和返回值；Logs 展示有序生命周期事件。断线时改用轮询，重连仅重放事件。

超时取请求、工具配置和基础能力限制中的最小值。Cancel response 表示停止等待；后台线程可能仍在执行，界面保留 running/unknown，直到确定停止。不自动重试可能产生副作用的调用。当前执行器不支持输出 token 流式返回，实时的是生命周期事件。

Last runs 支持恢复历史与加载更早记录。后端不保存原始输入和审批摘要；返回结果可能包含文档内容，会保存在本地历史。结果超过 256 KiB 时明确标记截断预览。保留最近 100 个已经结束且停止的记录或 30 天，待审批及执行情况未确定的记录受到保护。重启将未结束调用标为 interrupted，旧审批失效，不重新执行。

## 新增、编辑与导入

Add tool 当前支持知识搜索预设，复用 `builtin:search_knowledge_base`。它是可调用的真实预设，拥有自己的参数模型、名称和持久化配置；默认禁用。固定参数不能暴露或被调用覆盖。Agent 执行保留基础知识范围、检索预算和证据处理规则；基础工具禁用时预设也不可调用。Native Chat 暂不支持这些自定义预设。

内置工具只允许编辑展示信息、经校验的默认参数、示例和更短超时。自定义工具允许编辑预设内容，调用名称保持不变。Archive 禁止以后调用，保留身份和历史，不释放名称。

导入 JSON 示例：

```json
{
  "schema_version": 1,
  "tools": [{
    "name": "custom_research_search",
    "template_id": "builtin:search_knowledge_base",
    "title": "Research search",
    "description": "Search explicitly selected documents",
    "fixed_arguments": { "top_k": 5 },
    "exposed_fields": ["query", "document_ids", "document_scope"],
    "defaults": {},
    "examples": [],
    "timeout_seconds": 20
  }]
}
```

先 Preview import，再 Apply import。有冲突时明确选择 Replace；归档名称不能重用。预览与当前配置绑定，预览过期需重做。整个批次原子提交，导入/替换后全部禁用；不执行代码或安装依赖。文件上传限制 1 MiB，单批最多 100 项。

## 服务端契约与开发入口

沿用 FastAPI、Pydantic、React、TanStack Query 和现有 UI tokens。前端入口 `apps/desktop/src/features/tools/ToolsWorkspace.tsx`；后端路由 `backend/api/tools.py`。`tools.sqlite3` 存策略/预设；`agent_runtime.sqlite3` 中的独立扩展表存测试记录/事件，不进入 Agent 运行队列。

| 方法与路径（相对 `/api/tools`） | 作用 |
| --- | --- |
| GET `/`、GET `/{tool_id}` | 搜索/分类/状态/游标分页目录、完整定义 |
| PATCH `/{tool_id}` | revision 条件更新 enabled、config 或 preset |
| POST `/custom` | 新建默认禁用的预设 |
| POST `/imports/preview`、POST `/imports` | 校验预览、绑定 token 的原子导入 |
| POST `/{tool_id}/archive` | revision 条件归档 |
| POST `/{tool_id}/validate` | 严格输入、上下文与范围校验 |
| POST `/{tool_id}/test-runs` | 创建调用，返回 202；相同 client_request_id 和输入复用原记录 |
| GET `/{tool_id}/test-runs`、GET `/{tool_id}/test-runs/{run_id}` | 历史分页、运行快照 |
| POST `/{tool_id}/test-runs/{run_id}/approve`、`/cancel` | 绑定审批、拒绝或取消等待 |
| GET `/{tool_id}/test-runs/{run_id}/events`、`/event-log` | SSE/Last-Event-ID、持久化日志轮询 |

完整模型、OpenAPI 和 `tools-management-contract.md` 是字段定义依据。tool_id 和 run_id 在前端按路径段编码。客户端不能指定 run/trace/tool_call ID、confirmed 或全局 scope。409 表示版本、幂等键或审批绑定冲突；422 包含定位到字段的校验错误；403 表示策略/范围拒绝。旧直接执行 API 无法携带可信范围或审批，相关工具改用管理测试端点。

新增基础能力必须注册类型化定义、效果/确认要求、输入/输出模型及运行时依赖；不要把前端 JSON 当执行代码。自定义模板通过允许列表扩展，并继续使用真实注册表执行。

## 可重复的隔离验收

以下命令从本分支根目录运行，使用已配置项目 Python 环境。服务端脚本固定隔离数据目录 `test-results/tools-live`，仅监听 localhost，开启模型离线模式，关闭可选 LLM 查询改写、图抽取和视觉路径；不会修改生产配置或凭据。需要本机已经缓存 Embedding/Reranker 模型；缺模型应记录明确失败。

```powershell
conda run --no-capture-output -n aitrans python -m scripts.tools_management_acceptance_server
```

另一个终端运行：

```powershell
conda run --no-capture-output -n aitrans python -m scripts.tools_management_acceptance --acknowledge-isolated-data
```

仅对上述隔离服务执行验收脚本。它会导入仓库自写 Markdown、真实写入测试笔记、新建并归档测试预设、临时切换工具策略后还原。JSON 报告写入 `test-results/tools-management-live.json`，含真实 ID、状态和耗时，不保存完整原文或凭据。

前端另设 `$env:VITE_API_BASE_URL='http://127.0.0.1:8772'`，在 `apps/desktop` 执行 `npm run dev -- --host 127.0.0.1 --port 5187`，打开 `http://127.0.0.1:5187/#/tools`。该浏览器验收不等同原生 Electron GUI 验收。

## 排障与回滚

目录/历史连接失败：先看端口、API_BASE_URL 和后端日志，再使用页面 Retry。模型不可用：检查本地模型健康与缓存，不通过伪造结果隐藏依赖问题。查询改写关闭时 Agent 注册表不构造规划器；启用时依赖已配置的 planner 路由，其耗时仍受工具预算限制。

输入 JSON 错误：先修语法，再按 Schema 修字段和上下文。配置冲突：重新获取 detail/revision；导入冲突：重新预览，不复用旧 token。审批过期或重启：创建新测试，不复用旧审批。长结果用内部滚动查看，并注意截断标记。

回滚代码用新提交/revert，不改写已经推送的阶段历史。回滚不等于恢复数据库；停应用并备份对应 SQLite 数据后处理兼容性，不能通过删除用户目录实现回滚。
