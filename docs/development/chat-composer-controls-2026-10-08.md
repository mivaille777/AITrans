# Chat 输入栏功能重设计（2026-10-08）

本次按用户确认实现四个入口，沿用现有图标、组件和样式：模型、工作区、执行模式、导入文件。

- 工作区使用已有的本地文件夹登记后端，绑定到会话的 session。Agent 文件读取和 Python 执行接收此工作区 ID。
- 导入支持 PDF、DOCX、TXT、Markdown、HTML。文件副本保存到工作区的 `AITrans Chat Imports`，解析内容用于当前会话，不进入全局知识库。单文件上限 16 MB，每会话最多 16 个引用。移除引用、切换工作区均保留文件副本。
- 默认常规 ReAct，经现有 Agent 运行时处理。Plan–Execute 使用现有计划器生成步骤，持久化中断并显示计划；确认后执行相同计划，取消不调用工具。服务端核对会话、运行 ID 和计划摘要，等待确认期间冻结文件与工作区配置。
- 大文件通过 `read_workspace_file` 分段读取，限制路径位于所选工作区内。导入内容明确标注为参考资料，文件内指令不视为用户指令。
- 模型菜单连接已有模型目录和 LLM 设置接口，切换后更新后端模型配置。原工具选择和知识库策略保留在执行模式菜单内；Reading 上下文仍在右侧面板中选择。

验证：

- 前端 companion 目录：15 个测试文件，71 项通过；最终相关两文件 15 项通过；测试类型检查、定向 oxlint、生产构建、Electron 编译通过。
- 后端：32 项通过，覆盖会话导入隔离、文件副本、分页读取和路径边界，计划确认、取消、摘要校验、刷新恢复、ReAct 默认行为及现有 Agent API/计划器回归。使用 `conda run -n aitrans` 环境。
- 最终端到端检查在独立后端 8767、前端 5174 和 `.cache/chat-functional-qa/runtime` 数据目录完成，使用合成的 `qa.md`。确认前工具调用数为 0；刷新仍能确认；确认后调用一次 `read_workspace_file` 并回答三个样本。切回 ReAct 后下一条消息直接回答 `4`。模型从 `deepseek-v4-flash` 切换到 `deepseek-v4-pro`，仅影响独立测试配置。
- 系统文件选择弹窗在内置浏览器不可用。桌面适配层以集成测试验证选择路径传入导入接口，复制和解析由真实接口检查。未声称已自动操作原生系统弹窗。
- 实际移除测试文件引用后，会话附件数量为 0，工作区副本仍存在。结束后关闭独立测试页面和进程，移除临时设置副本；原后端模型仍为 `deepseek-v4-flash`。原环境的合成测试工作区已撤销登记，待确认测试记录已清理。
- 证据：`D:/AITrans/.cache/chat-ui/chat-toolbar-plan.jpg`、`D:/AITrans/.cache/chat-ui/chat-toolbar-result.jpg`；计划前后快照位于 `.cache/chat-functional-qa/plan-before-approval.json`、`plan-after-approval.json`。

当前桌面进程成功重新加载了初版新增接口，但最终桌面重启动作被自动审批拒绝，返回 `blocked by policy`，没有附带具体理由。最终计划保存修复需退出应用后重新运行 `D:/AITrans/start.ps1` 加载。独立测试进程验证了最终代码。
