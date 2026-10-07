# Tools 管理验收记录

日期：2026-10-07。工作分支：`codex/tools-management`，基线 `56675625a24f0fe209202f86b19f3cad846867bb`。

当前状态：T00–T07 已实现、验收并按阶段推送。T08 实现和自动化/浏览器验收已完成；原生 Windows Electron GUI 为必要的未完成验收，因此 T08 整体尚未标记验收完成。

## 自动化结果

| 检查 | 结果 |
| --- | --- |
| 完整前端 Vitest | 116 文件、529 项通过 |
| 前端测试类型检查 | 修正新增测试的 Testing Library 参数后通过 |
| `npm run desktop:check` | Electron 编译、16 文件/66 项桌面契约测试和类型检查通过 |
| `npm run build` | TypeScript、Vite、PDF.js 离线资源守卫、bundle report 通过 |
| `npm run lint` | 退出 0；旧 reading/settings/credentials 警告仍在 |
| `npx oxlint src/features/tools` | 通过，无 Tools 新警告 |
| 后端相关回归 | 183 项通过；3 条既有 SWIG 弃用警告 |
| 新增/修改 Tools 模块、测试、脚本 Ruff | 通过 |

后端覆盖目录和 Schema、持久化策略、Agent 自动/显式选择、Native Chat/恢复/复合读取、严格范围校验、审批、取消/超时、历史恢复/保留、SSE 游标与最后事件竞争、结果大小、自定义真实分派、原子导入及归档。回归中的替身与 fixture 测试不冒充真实模型集成。

完整 npm 测试首次扫描了用于依赖拷贝的残留 `node_modules-shared` 链接，第三方测试产生 37 个套件失败；529 项之前的 527 个项目测试本身通过。验证链接目标后仅移除该工作区的链接，原依赖目录保留，标准测试通过。最终全量运行 529 项通过，随后修正一个新增测试的类型参数并单独复核类型检查。

## 真实本地集成

证据：`evidence/tools-management-live.json`。独立 localhost 后端和 SQLite/FAISS/BM25 数据位于工作区 `test-results/tools-live`，没有使用原项目用户数据。导入两个仓库自写 Markdown 文档，一个是 Agent 工具正文，一个是范围外的对照文档。

实际模型：本机缓存 `Qwen/Qwen3-Embedding-0.6B`（1024 维）和 `Qwen/Qwen3-Reranker-0.6B`；模型离线。可选 LLM 改写关闭，无 Chat/Agent 生成模型端到端调用。首次启用改写时发生 20 秒超时，调查发现注册表忽略关闭配置；本阶段修正并用开/关两个依赖测试回归。模型冷启动与工具预算仍是实际运行约束，未提高超时掩盖问题。

真实通过的场景：

- 两文档 ready，分别生成 5 和 2 个真实块。
- 指定单文档混合检索，返回包含真实 dense/sparse/rerank 分数的片段；对照文档被排除。
- 读取检索命中的完整原文块、读取冻结阅读上下文。
- 同请求幂等复用；不同输入复用键、参数 ID 注入和范围扩大被拒绝。
- 禁用策略同时拦截管理测试和旧直接执行入口，再恢复开关。
- 写笔记等待与实际调用绑定的审批；错误审批被拒绝，正确批准后实际保存，审批重放被拒绝，拒绝调用不写入。
- 持久化自定义预设执行真实检索，固定 top_k 生效；基础搜索禁用后预设不可调用。
- 导入预览/应用、过期 token 拒绝、归档保留历史。
- 持久化生命周期序号连续，包含最终成功，生命周期事件不携带原文。

首轮本机验收观察：搜索 797 ms、读块 62 ms、批准写入 77 ms、自定义检索 547 ms。可重复启动脚本复跑报告：搜索 1375 ms、自定义检索 1108 ms；页面另一次实际审批保存笔记为 61 ms。这些是单次运行观察，不是性能承诺，具体以 JSON 的实际数值为准。

## 浏览器界面证据

浏览器使用真实 Vite 前端和上述后端，未预置响应。页面带有现有桌面框架样式，这仍是浏览器页面，不能据此认定 Electron 原生窗口已验收。

| 证据 | 观察 |
| --- | --- |
| `../design/acceptance/tools-context-result-1680.jpg` | 实际冻结阅读上下文返回、trace、状态 |
| `../design/acceptance/tools-retrieval-result-1680.jpg` | 三栏、真实知识检索结果和 trace |
| `../design/acceptance/tools-final-logs-1680.jpg` | created/running/succeeded 三条最终生命周期 |
| `../design/acceptance/tools-drawer-1366.jpg` | 测试区改为可关闭的抽屉，完整日志可读 |
| `../design/acceptance/tools-library-900.jpg` | 目录抽屉、搜索焦点和独立滚动 |
| `../design/acceptance/tools-bound-approval-1680.jpg` | 写入处于 awaiting approval，明确批准/拒绝 |
| `../design/acceptance/tools-approved-note-1680.jpg` | 批准后 succeeded、真实 note_id |
| `../design/acceptance/tools-workbench-final-1680.jpg` | 使用可重复启动器复跑后的完整工作台和真实结果 |

人工操作已验证详情 Parameters 方向键切到 Returns；测试抽屉 Escape 关闭并返回触发按钮；目录打开移入搜索焦点；配置弹窗 Shift+Tab 从关闭按钮循环到保存按钮，Escape 关闭并返回 Add tool。长 JSON 结果可在测试区独立滚动，目录和详情独立滚动。服务端重启后历史仍可恢复，停止记录不会重复执行。

## 未完成的必要验收与环境限制

原生 Windows Electron GUI 控制未开放，不能操作和记录真实窗口、拖拽/缩放、标题栏或原生焦点行为。桌面编译与契约测试通过不能替代此项，T08 验收状态保留待完成。可运行项目既有桌面启动命令，在隔离数据下复核 Tools 导航、窗口尺寸、抽屉/标签键盘行为、审批、重启历史和旧 Reading/Chat 回归，并补真实窗口截图。

Docker CLI 可用但 Docker Desktop Linux engine pipe 不存在，未执行真实 Sandbox 工具。其 API/审批回归已运行；启动 Docker 后仍需真实沙箱调用验收。

原工作目录 `D:/AITrans` 的未提交 Chat/RAG/full-read/startup 改动未纳入此独立分支；任务书提到的新 full-read 回归文件不在干净基线中。现有 Native Chat/复合读取回归已覆盖此分支的实现，不代表验证了那份未提交代码。合入前需要与那些改动集成并执行其新增回归。

既有 `desktop:verify` 中的 credential smoke 会写入/删除现有凭据，本次未运行；没有改动 Windows 凭据。未做发布安装包、生产部署或自动合并。
