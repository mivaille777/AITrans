# Tools 本地启动目录接入记录

2026-10-07。原启动方式为 `cd D:\AITrans` 后执行 `.\start.ps1`。

此前 Tools 的阶段提交只在 `codex/tools-management` 独立工作区，主目录 maindev 仍是 `56675625`，因此原启动目录没有新界面/接口。接入时发现旧 Electron/Vite/后台仍运行，旧 `/api/tools` 返回 404；重复启动还会遇到 5173 端口占用。

## 接入与保存

- 接入前用 include-untracked stash 保存全部未提交内容，保留恢复快照 `49c5dca092e8911207fb3b61c553ce5a4d65a191`，未删除或 pop。该快照仅保存在本机，不推送用户草稿。
- 本地 maindev 快进到已推送的 Tools 提交 `9edbbf6e`，再应用原工作内容。29 个原已修改文件保留；6 个重叠文件自动合并，无未解决冲突。其他原修改文件的 Git 内容哈希与快照一致。
- 原 36 个未跟踪文件均存在；35 个内容哈希一致，Tools 任务书使用分支中的新版本，其旧版本仍在恢复快照中。Git 的“untracked files could not restore”仅对应已被分支追踪的 3 个设计/任务书路径，没有丢失源代码。
- 未将本地 Chat/RAG/startup 改动提交、覆盖或推送。这些改动仍以原来的未提交状态保留。本地 maindev 的快进没有推送到 origin/maindev。

## 验证

`.\start.ps1 -CheckOnly -SkipRagProbe` 通过；`npm run desktop:check` 的 Electron 编译、17 文件/74 测试和测试类型检查通过；7 文件/36 项 Tools/启动/Chat 前端回归通过；后端全文读取、阅读规划、知识函数/恢复、Tools/策略/审批和启动共 183 项回归通过（3 条已有 SWIG 警告）；生产构建和 PDF.js 离线守卫通过。

用户明确授权重启当前 AITrans 后，关闭旧后台并用原 `.\start.ps1` 启动新 Electron。实际 Electron 主进程启动，新后台 `/health` 返回 ok，`/api/tools` 正常返回 23 个工具。浏览器直接检查由主目录 Vite 提供的 `http://127.0.0.1:5173/#/tools`，目录/数量/真实搜索工具参数加载成功；截图见 `../design/acceptance/tools-local-main-2026-10-07.jpg`。该截图来自浏览器，不能代替原生窗口交互的全部验收。

现有 Windows 运行窗口保持打开；用户后续仍使用原命令，无需切换独立工作区。启动失败时先关闭已有 AITrans 窗口，并停止上一次启动终端的运行，避免旧 Vite 占用 5173；不要按进程名批量终止其他 Python/Node 程序。
