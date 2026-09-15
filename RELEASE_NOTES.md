# AITranslator Release Notes

## Unreleased — `LLM_API_Calling`

更新日期：2026-08-20

这一阶段是 AITranslator 从“桌面划词翻译工具”向 **Context-aware Academic Companion Agent** 演进的主要开发版本。核心变化集中在可靠选区捕获、浏览器 / PDF Reading Context、AI 阅读动作、Research Notes、Chat 交互和 GUI 信息架构。

> 当前 `pyproject.toml` 的包版本仍为 `0.1.0`。以下内容属于 `LLM_API_Calling` 开发分支的未正式发布功能，不代表已经创建新的正式版本号。

### Selection Capture V2

自动鼠标划词路径完成原生化改造：

- 自动划词不再依赖 synthetic `Ctrl+C`；
- 自动路径不模拟 `Ctrl+V`；
- 自动路径不修改系统剪贴板；
- 鼠标释放时冻结 `SelectionContext`，包含 release point、foreground HWND、process 等信息；
- Word 继续优先通过 COM 直接读取 Selection；
- Windows 应用通过 UI Automation TextPattern / TextPattern2 读取原生选区；
- UIA 加强 ancestor / focused control / HWND root / bounded subtree 搜索；
- 对 Chrome、Edge、Acrobat 等 Browser / PDF 场景增加更有针对性的 accessibility 搜索；
- 保留显式兼容路径，用于 `Alt+Q` 等手动触发场景；
- 修复显式 Word / Clipboard provider chain 与默认 UIA timeout 配置之间的兼容性。

当前自动选区主链路：

```text
Browser DOM Selection Bridge
        ↓ fallback
Browser / PDF UIA retry
        ↓ fallback
Word COM / Windows UI Automation
```

### Browser Selection Bridge

新增 Chromium Manifest V3 浏览器扩展：

```text
browser_extension/aitrans_selection_bridge/
```

普通网页可以直接从 DOM 获取：

- selected text；
- URL；
- title；
- nearest heading；
- context before / after；
- frame URL。

桌面端 Bridge：

- 仅监听 `127.0.0.1`；
- 不开放局域网 listener；
- 提供受限状态快照供 Settings / Diagnostics 使用；
- 页面状态接口不暴露 selected text。

扩展后续加入 Active Tab / page context 同步，使 Reading Context 可以在切换页面、Tab 和本地 PDF 时更新，而不是一直保留上一个网页的选区。

### Browser / PDF Selection

针对 Chrome / Edge 内置 PDF Viewer 增加独立 Browser/PDF UIA retry provider：

- DOM Bridge miss 后进入 PDF accessibility fallback；
- bounded retry 读取 TextPattern / TextPattern2 selection；
- 支持较深 PDF accessibility tree；
- 成功后直接复用 Translation、Reading Context 与 Quick Actions；
- 整个自动 PDF 路径保持 zero-keyboard injection。

浏览器扩展同时增加普通 `file://` 页面支持；浏览器内置 PDF 的核心 fallback 不依赖 content script 必须能够注入 Viewer。

### Reading Context V1

新增结构化 `ReadingContext`，把“用户当前读的内容”从临时 selection 提升为正式 Agent Context。

Reading Context 可以保存：

```text
resource URL
resource title
section heading
selected source text
translated text
context before
context after
source kind
```

主要改动：

- Reading Context 注入 AI Chat prompt；
- 网页 / 文档上下文被明确视为 evidence / reference data，而不是系统指令；
- 当前 Conversation 可持久化 Reading Context；
- Chat History SQLite schema 从早期结构原地迁移，不删除旧消息；
- 切换 Conversation 时恢复该会话自己的 Reading Context；
- 页面切换时更新为新的 page context；
- 新划词会覆盖当前页面的 selection context；
- Word / UIA 新选区不会继续携带上一个网页的 URL metadata。

### Context-aware Reading Actions

新增高频 Academic Reading Actions：

- 解释这段；
- 结合上下文翻译；
- 总结这段；
- 分析段落作用。

这些操作直接使用当前 `ReadingContext`，不重新复制文本，也不经过 Workspace Tool Planner。

Context-aware translation 会显式读取当前目标语言，并保留术语、公式、符号、数字和专有名词。

### Selection Quick Actions

翻译结果下方新增高频 Quick Action Bar：

```text
[译] [解释] [总结] [笔记]
```

- 有有效 selection 时显示；
- 无 selection 时隐藏；
- 窄 Overlay 下自动缩写为 `[译] [解] [总] [记]`；
- 与原有 AI Menu 共享 semantic actions，不复制 Controller 逻辑。

### Research Notes / Research Memory V1

新增独立 Research Notes 数据层：

```text
research_notes.sqlite3
```

Research Notes 与 Chat History 分离，一条笔记可以包含：

- 文献标题；
- URL；
- Section；
- 原文；
- 译文；
- Reading Context；
- AI 阅读结果；
- AI Action 类型；
- user note；
-关联 Conversation；
- 创建 / 更新时间。

主要能力：

- 一键加入研究笔记；
- 同一选区 Upsert；
- AI 解释 / 总结结果与当前选区安全绑定；
- 最近研究笔记；
- Research Notes Library；
- 搜索；
- 查看完整笔记；
- 编辑“我的笔记”；
- 删除；
- 打开来源。

保存、读取、编辑与删除 Research Notes 均为本地确定性操作，不调用 LLM。

### Reading Context Card

AI Chat 顶部新增可见的 Reading Context Card：

- 显示 Browser / PDF / Word / Desktop 来源；
- 显示当前文献 / 页面标题；
- 显示 Section；
- 显示当前 selection；
- 展开后显示译文、前文和后文；
- 切换页面、选区、Conversation 后同步更新。

这使 Agent 当前使用的阅读证据从“隐藏 prompt context”变成用户可见的 UI 状态。

### AI Chat GUI 改进

Chat 界面进行了多轮稳定性和可用性重构：

- AI Chat 支持独立字体大小调节；
- Chat font 与 Translation typography 解耦；
- 模型选择器增加独立宽度预算和文本省略，避免与字体按钮、清空按钮发生碰撞；
- Chat resize 不再改变翻译正文字号；
- 返回 Translation view 时清理 Chat 专属 height / resize state；
- 输入框随多行输入自动增高，超过软上限后内部滚动；
- 长 AI 回答随内容增长，超过可用区域后 transcript 内部滚动；
- 用户主动向上滚动后停止自动 follow-tail；
- 上翻后显示 `↓` 跳转到最新内容按钮；
- 点击 `↓` 后恢复自动跟随；
- Streaming 更新增加 layout debounce，减少窗口抖动；
- AI 最终 Markdown 回复增加 final transcript reflow，修复回答末尾被 QLabel height-for-width 缓存裁切的问题；
- final reflow 在 0 / 32 / 96 ms 进行短延迟稳定化 pass，确保 Markdown、scroll range 和 Overlay geometry 完成最终同步。

### AI Reply Links

AI 回复中的：

```text
http://...
https://...
```

以及 Markdown Link 现在支持 `Ctrl + 点击`。

打开流程：

```text
Ctrl + 点击 URL
        ↓
选择浏览器
        ↓
系统默认 / Edge / Chrome / Firefox / Brave / Opera / Vivaldi
        ↓
打开链接
```

安全约束：

- 普通点击不会静默启动外部程序；
- 只允许 `http://` 和 `https://`；
- 不允许 AI 回复直接启动 `file://` 或自定义协议；
- 用户必须主动确认浏览器。

### Overlay & Visual Contrast

针对真实网页和白色 PDF 背景进行了 GUI 重构：

- Translation body transparency 与 GUI Chrome layer 分离；
- 顶部语言栏、AI / Copy / Menu、Chat Toolbar、Model Picker、Reading Context、输入框等交互层保持稳定高对比度；
- 修复浅色网页背景下浅色工具按钮难以辨认的问题；
- 生产 Overlay 移除早期 `900 × 520` 固定最大尺寸；
- 窗口实际 resize 由屏幕 available geometry 作为实际边界；
- Chat resize 与 Translation view size / font state 解耦；
- 修复退出 Chat 后 Translation view 出现巨大空白或异常大字号的问题。

### Settings 信息架构

Settings 从长滚动配置表单调整为左侧导航结构：

```text
基础
AI 模型
划词与阅读
浏览器集成
外观
研究数据
高级
```

新增：

- Browser Integration 状态页；
- Selection Bridge running / extension activity 状态；
- 最近浏览页面信息；
- 扩展目录入口；
- Research Notes 数量与数据库路径；
- 从 Settings 直接打开 Research Notes Library。

工程参数，例如 endpoint、timeout、retry、request interval，被集中到 Advanced 页面。

### Research Notes Toast

保存研究笔记后新增非模态反馈：

```text
✓ 已加入研究笔记    [查看]
```

或：

```text
✓ 研究笔记已更新    [查看]
```

Toast 自动消失，不打断论文阅读；点击“查看”可直接打开 Research Notes Library。

### Agent / Tooling

继续保留并强化现有 LangGraph Agent 结构：

- Chat Execution Graph；
- Workspace Agent Graph；
- Human-in-the-loop UI capability；
- Agent Tool Registry；
- PDF / DOCX / TXT / Markdown document tools；
- `web_search` / `web_read`；
- Tool Observation 与普通 user message 分离；
- Web / Document / Reading Context 明确作为不可信 reference data。

### GitHub Manual Tests

仓库新增手动 GitHub Actions 测试基础设施：

```text
.github/workflows/manual-tests.yml
```

特点：

- 仅通过 `workflow_dispatch` 手动触发；
- 普通功能代码 push 不自动执行；
- 使用 `windows-latest`；
- Python 3.11；
- 复用 `scripts/test.ps1`；
- 运行完整 pytest；
- 运行 FastAPI 应用工厂 smoke test；
- 上传 JUnit test artifact；
- workflow 权限为 `contents: read`。

这套流程用于 Stage / milestone 结束后的全新 Windows 环境验证，而日常开发测试仍以本地：

```powershell
.\scripts\test.ps1
```

为主。

### Security & Privacy

本阶段新增 / 明确以下边界：

- 自动 selection 不注入 synthetic keyboard copy/paste；
- Browser Bridge 仅监听 loopback；
- Research Notes / Chat History 为本地 SQLite；
- Web / Document / Reading Context 不被视为系统指令；
- `web_read` 保持 SSRF 防护；
- AI reply links 必须由用户 Ctrl+点击并主动选择浏览器；
- DeepSeek / OpenAI-compatible API Key 不写入普通应用配置文件。

### 当前已知限制

- Chrome / Edge 内置 PDF 的 accessibility tree 仍可能因浏览器版本、PDF Viewer 和 PDF 文本层结构而有差异；Browser/PDF UIA retry 已显著加强，但仍需要真实 Windows 场景持续验证。
- 浏览器扩展新增权限或版本后，需要用户在 `chrome://extensions` / `edge://extensions` 中重新加载扩展。
- 当前 Research Memory V1 以结构化 SQLite 笔记为主，尚未实现知识图谱或完整文献库 RAG。
- 当前正式包版本仍为 `0.1.0`，上述开发能力尚未冻结成新的正式 Release。

---

# AITranslator v0.1.0

发布日期：2026-08-18

AITranslator 的首个公开版本，定位为 Windows 桌面划词翻译工具。它可以在 Word、Chrome、记事本等应用中捕获选中文本，并通过悬浮窗快速显示中文翻译结果。

## 主要功能

- 自动划词翻译默认开启，释放鼠标后自动提交翻译。
- 保留 `Alt+Q` 全局快捷键，支持手动触发翻译。
- 支持 Word COM、Windows UI Automation 和剪贴板多级选区获取。
- 默认使用 Google Translate Web 后端，无需配置 Google Cloud 账户或凭据。
- 深色圆角悬浮窗，支持拖动、锁定、置顶和多屏安全定位。
- 支持显示 / 隐藏原文、复制译文、源语言选择和右键菜单。
- 支持背景透明度与字体透明度分别调节。
- 支持字体大小、主题、悬浮窗位置和触发模式设置。
- 支持异步翻译、最新请求优先、内存 LRU 缓存和可选 SQLite 缓存。
- 复制、加载、翻译完成和悬停状态提供轻量交互动画。
- 统一日志记录和异常保护，不记录用户原文或凭据。

## Windows EXE

发布包使用 PyInstaller GUI onedir 模式构建，不弹出控制台窗口。

启动方式：

1. 下载完整的 AITranslator 文件夹。
2. 运行其中的 `AITranslator.exe`。
3. 程序启动后会显示系统托盘图标。

请不要只复制 EXE 文件，Qt 插件和 Windows 原生依赖位于同级目录及 `_internal` 目录中。

用户配置、缓存和日志默认位于：

```text
%APPDATA%\AITranslator\
```

## v0.1.0 验证结果

- Python 3.11.7 开发环境验证通过。
- Windows 原生选区、pywin32、pynput 和 UI Automation 依赖验证通过。
- PyInstaller EXE smoke test 通过。
- EXE 启动后能够创建配置目录和日志目录。
- 退出后未发现本次构建产生的残留进程。
- 当时 pytest：143 passed。

## v0.1.0 已知限制

- 翻译服务使用 Google Translate Web 兼容接口，需要网络连接。
- Web 接口属于非官方接口，可能受到访问频率限制或接口变化影响。
- 当前版本不包含 Google Cloud Translation SDK，也不读取 Google Cloud 凭据。
- 当前发布包是 onedir 目录格式，暂未提供安装程序和代码签名。
- Word 的高级选区读取依赖本机已安装并运行 Microsoft Word。
- 不同应用对文本选区的支持能力不同，程序会自动尝试其他选区提供器。

## 反馈与改进

欢迎通过 GitHub Issue 反馈使用问题，也可以提交 Pull Request 改进 Selection、Translation、Agent、GUI、Browser Integration、Research Notes 或打包流程。

反馈问题时，如果方便，请附上：

- Windows 版本；
- 浏览器 / Word 等目标应用版本；
- 复现步骤；
- 不包含敏感原文的安全日志片段；
- 是否使用自动划词、Browser Bridge、PDF Viewer 或特定应用。

请勿在 Issue 或日志中上传原文内容、账号信息、API Key、访问令牌或其他敏感凭据。
