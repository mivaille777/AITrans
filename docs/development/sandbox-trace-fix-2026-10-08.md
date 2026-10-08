# Sandbox Debug Studio 闪烁与输出回退修复

## 结论和原因

用户截图中的运行 `sb_c29756ca5d2d48b0bae92dd4a603ef8d` 已在后端成功完成：退出码 0，stdout 为 `Hello from AITran Sandbox\n`，Collect、Cleanup 均完成。截图中的 preparing / Collect running / No output 是前端旧状态，并非 Docker 没有执行。

原来的 Studio 将 `latestTrace` 同时作为子组件的运行结果回传目标和历史记录选择输入。再次运行时，Trace 清空旧结果并设置新 sandbox ID，选择 effect 又恢复父组件尚未更新的旧记录，同时清除 running 状态。父子组件相互回传这些状态，导致闪烁、Run 提前恢复、最终输出被覆盖。另一个竞争条件是初始 HTTP 请求晚于 WebSocket 事件返回，旧快照可能覆盖流式进度。

## 修复内容

- `SandboxDebugStudio.tsx` 分开历史选择意图与实时结果观察。导航和 Runs 点击更新 selectedTrace；执行事件只更新 latestTrace，继续供 Filesystem、Resources、Policy 使用。
- `SandboxDebugTrace.tsx` 只在选择意图变化时切换记录；切换时关闭旧连接并使旧回调失效。启动请求返回后也检查所属运行是否仍然有效。
- 已收到流式事件时不再应用较旧的初始 HTTP 快照。HTTP 已取得终态时关闭连接，阻止重放的准备阶段覆盖最终输出；终态后的迟到事件被忽略。
- 保留代码编辑器、图标、组件样式及 Docker 安全策略。本次没有修改后端执行协议。

## 验证

- 新增 Studio + 真实 Trace 组合回归，覆盖连续运行、打开历史记录后重新运行、旧运行迟到事件和跨页签结果共享。在独立的修复前代码副本上，两项组合测试均失败，体现为运行途中 Stop 消失；在修复后均通过。
- Trace 新增延迟 HTTP 快照、HTTP 终态后流式重放，以及历史选择后旧事件隔离测试。
- 真实页面 `http://127.0.0.1:5173/#/settings`，使用现有 Docker Desktop Linux 引擎和 `aitrans-python-sandbox:v1`，输入用户的 `print("Hello from AITran Sandbox")`。
- 第一次运行 `sb_260902a7f95f4e958b39c31757ace3c1`：退出码 0，耗时 672 ms，输出正确，Collect / Cleanup 完成。
- 连续第二次 `sb_715ae7e69d954d1a9334485b9f0aeaa7`：退出码 0，耗时 655 ms，输出正确，运行期间 Stop 保持，结果稳定。
- 从 Runs 打开用户截图中的旧记录后第三次执行 `sb_12ebd8c11e454738bb34a81d318392fe`：退出码 0，耗时 500 ms，stdout 正确，Collect / Cleanup 完成。页面无 React 状态循环报错。
- 主工作区和独立修复快照的前端沙箱相关测试均为 10 个文件、58 项通过；后端 debug service 的 5 项测试通过。定向 lint 通过。
- 主工作区在验证初期测试类型检查、生产构建和 PDF 离线资源检查通过。期间出现额外未提交的文件定位改动，后续全量测试类型检查在 browser-adapter.ts:60 和 electron-adapter.ts:71 报错：revealWorkspaceLocation 放在 window 实现中，而声明位于 DesktopFilesAdapter，另有参数隐式 any。它们不属于本次修改，未纳入提交。
- 本次修改复制到上一轮提交的独立快照后，测试类型检查、生产 TypeScript 编译及 Vite 构建均通过，避免混入上述桌面适配器改动。快照复用 node_modules junction，构建仅使用既有 vite.qa.config.ts 的 preserveSymlinks 配置，不修改生产配置。
- Docker 容器检查只发现测试前已存在、11 天前停止的容器 `02c08de3d154`，本次测试没有新增残留容器。

## 功能完善建议

以下是根据现有实现检查出的后续工作，尚未在本次修复中实现。当前已有 Docker 隔离、非 root、资源上限、超时/取消、输入快照、输出收集以及 Agent 工作区变更审批基础，不应重复另建这些执行机制。

| 优先级 | 当前缺口 | 建议与验收条件 |
| --- | --- | --- |
| P0 | stdout / stderr 只在终态写入 Debug Trace，长任务期间一直 No output | 给运行时、服务和前端接入有大小上限、带序号的日志增量。`print(..., flush=True)` 后继续 sleep 的任务必须在结束前显示输出，并保留既有脱敏和输出限制。 |
| P0 | 断线时当前界面退出 running，缺少自动重新同步；重新查看活跃历史记录也没有订阅其后续事件 | 按同一 sandbox ID 恢复订阅或有限轮询，最后用服务端快照对齐。不得自动重复 POST 执行；取消后显示 cancelling，确认终态及清理后再显示 cancelled。 |
| P0 | resources 数据模型与图表存在，但运行时和 debug service 尚未产生真实 CPU / 内存 / PID 样本 | 使用 Docker stats 有界采样，记录峰值和采样时间。未采集时显示“未采集”，避免把空数组呈现为实际 0 使用量。 |
| P1 | Debug 运行历史在内存中，默认保留 100 条；后端重启后无法追溯 | 持久化运行、阶段、日志摘要和产物索引，保存事件游标与保留期限；重启后协调中断状态、容器和临时目录清理，明确 interrupted 状态。 |
| P1 | Filesystem 的 Collected Outputs 只有元信息和 Copy file id | 连接受控产物预览、下载/另存为；通过 file ID 校验来源、大小与保留期限。手动调试页的工作区输入应明确只读，编辑副本及回写复用已有审批流程。 |
| P1 | Approval / Network / Changes / Apply 不适用时直到终态才变 skipped，备注统一“未到达”；队列准备与执行准备没有区分 | 明确 queued、preparing、running、cancelling 和终态；阶段区分“不需要审批”“禁用网络”“只读运行无需回写”与“失败未到达”，状态以服务端为准。 |
| P2 | 健康检查以进入页面时为主，Python 依赖环境对用户不够可见 | 增加主动刷新 Docker / 镜像状态、Python 和预装库版本信息、受控依赖环境选择；依赖安装继续遵循网络和权限策略。 |

建议实施顺序：日志与断线恢复 → 真实资源采样 → 历史持久化与产物操作 → 阶段说明与依赖环境。
