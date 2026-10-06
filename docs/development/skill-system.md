# Skill 文件管理系统

## 范围与界面

本次新增独立的 `/skills` 工作区，侧栏入口为 Skills。功能覆盖本地技能文件管理：搜索、状态筛选、新建、导入、启用/停用、移除，以及附属文件创建、读取、编辑与删除。

桌面界面分为技能列表、文件列表和内容区。内容区提供 Markdown 正文预览、文本/脚本源码预览和 UTF-8 编辑器。元数据在文件列表底部查看。支持 `Ctrl/Cmd + S` 保存；有未保存修改时切换技能/文件或打开创建、导入、移除操作，会先提示放弃修改或取消操作。切换其他工作区时，沿用项目的路由缓存保留编辑状态。浏览器关闭/刷新通过 `beforeunload` 提示。

采用 [Agent Skills 文件规范](https://agentskills.io/specification) 的基本结构：目录名与 `name` 一致，入口文件为 `SKILL.md`，以 YAML frontmatter 保存名称、用途和可选元数据，其后是 Markdown 说明。附属文件可以位于 `references/`、`scripts/`、`assets/` 或其他普通目录。

文件管理已接入 Companion 原生工具调用和 Agent ReAct 决策/回答链路。运行时按任务范围、领域、候选元数据、已激活正文和附属资源逐层披露；模型决定激活自动候选，用户可用 `$skill-name` 或首行 `/skill-name` 显式指定。格式无效或未启用的技能不会参与运行。`allowed-tools` 仅作为元数据展示，不授权工具；脚本仍只作为文本读取。完整流程、缓存、预算和边界见 [Skill 架构](skill-architecture.md)。

## 文件与状态存储

数据根路径沿用 `app.infrastructure.paths.data_root()`，技能保存在 `<data_root>/data/skills/`。开发环境默认为仓库内 `data/skills/`；打包环境使用用户数据目录；`AITRANSLATOR_DATA_DIR` 可覆盖数据根目录。

```text
data/skills/
├── .state.json                  # 启用状态，原子写入
├── .trash/                      # 移除后的技能归档
├── paper-review/
│   ├── SKILL.md
│   ├── references/guide.md
│   └── scripts/analyze.py
└── research-synthesis/
    └── SKILL.md
```

新建和导入的技能默认停用。导入目录采用复制方式，不修改原始目录；单文件导入只复制上传的 `SKILL.md`，不自动读取该文件所在目录的其他内容。同名技能返回 409，不隐式覆盖。技能移除后整个目录移入 `.trash/<id>-<uuid>/`，状态记录被清除。恢复需手动从归档目录移回原名称的技能目录；本次未提供前端恢复操作。删除附属文件直接删除，需通过页面确认；入口文件禁止删除。

文件保存通过同目录临时文件和 `os.replace` 原子替换。单进程内使用可重入锁序列化服务操作；当前设计适用于桌面端的单后端进程，未提供多个后端写进程间的锁。

## API 契约

所有响应和请求使用 JSON。FastAPI 注册到主应用，可从运行中的 `/docs` 查阅完整的 Pydantic schema。

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| GET | `/api/skills` | — | `{skills: SkillRecord[], storage_root: string}` |
| POST | `/api/skills` | `{name, description}` | 201 `SkillDetail`，生成入口说明模板 |
| POST | `/api/skills/import` | `{path}` 或 `{content}`，二选一 | 201 `SkillDetail` |
| GET | `/api/skills/catalog` | query: `context_mode=general/reading` | `SkillCatalog`，领域摘要与版本 |
| POST | `/api/skills/route` | `{query, context_mode, category?}` | `SkillRoutePreview`，领域、候选、原因；不读正文 |
| GET | `/api/skills/{id}` | — | `SkillDetail`，含元数据、校验结果和文件列表 |
| PATCH | `/api/skills/{id}` | `{enabled: boolean}` | 更新后的 `SkillDetail` |
| DELETE | `/api/skills/{id}` | — | `{removed: true, archived_path: string}` |
| GET | `/api/skills/{id}/file` | query: `path` | `SkillFileContent` |
| PUT | `/api/skills/{id}/file` | `{path, content, revision}` | 写入后的 `SkillFileContent` |
| DELETE | `/api/skills/{id}/file` | query: `path`, `revision` | `{removed: true}` |

`SkillRecord` 字段：`id`、`name`、`description`、`enabled`、`valid`、`diagnostics: string[]`、`metadata: object`、`file_count`、`updated_at`（UTC ISO 8601）。目录名称作为稳定 ID，修改 frontmatter 的 name 不会重命名目录，而会触发校验错误。

`SkillDetail` 追加 `files: {path, size}[]`，入口文件优先，其余按路径排序。列表接口只返回摘要，不加载正文到前端。

`SkillFileContent` 字段：`path`、`size`（UTF-8 文件字节数）、`content: string | null`、`revision`（原文件字节 SHA-256）、`language`、`previewable`。二进制或非 UTF-8 文件返回 `content: null`、`previewable: false`，保留大小信息。脚本仅作为文本预览，不执行。

更新现有文件时，必须提供上次读取的 `revision`。新建文件时使用 `revision: null` 或省略该字段，表示只允许创建。文件不存在但请求含旧版本、文件已存在但缺少版本、或者磁盘内容与旧版本不一致，均返回 409。前端在冲突和刷新失败时保留草稿；重新加载前会提示丢弃未保存修改。

```json
{
  "path": "references/guide.md",
  "content": "# 阅读指南\n\n先确认研究问题。\n",
  "revision": null
}
```

| HTTP 状态 | 含义 |
| --- | --- |
| 400 | 无效名称/路径、导入入口缺失、链接目录、删除入口文件等 |
| 404 | 技能或文件不存在 |
| 409 | 同名冲突、文件版本冲突、无效技能启用、状态文件损坏 |
| 413 | 文件或技能包超过限额 |
| 422 | 请求字段与 schema 不符 |
| 500 | 文件系统读写失败，后端记录详细日志，界面提示检查权限 |

## 校验与资源约束

校验 YAML 安全解析、名称格式、名称与目录一致、非空 description（最多 1024 字符），以及可选字段类型。compatibility 最多 500 字符，metadata 为字符串键值映射。Frontmatter 原始字节和展开后的字符串总量最多 64 KiB；元数据树最多 2048 个节点、深度 12，防止 YAML 别名循环或过量展开。格式错误保留为可编辑草稿，`diagnostics` 提供原因；通过 API 保存无效入口时会清除启用状态，修复后需显式再次启用。

普通包最多 200 个文件、单文件 2 MiB、总计 20 MiB。导入忽略点号开头的隐藏项；其他文件完整复制，包括限额内的二进制资源。文件访问拒绝目录越界、绝对路径、Windows ADS、系统保留名称、符号链接和目录联接。不同大小写的重复文件名不允许导入，以保持 Windows 行为一致。

Markdown 预览不渲染原始 HTML，也不自动加载图片；包内相对文件链接在文件区打开，外部链接通过安全的新窗口链接打开。二进制资源不提供在线编辑。

## 实现位置与验证

- 后端 schema：`backend/models/skills.py`
- 文件服务：`backend/services/skill_service.py`
- 分层路由与加载：`backend/services/skill_runtime.py`
- 原生调用适配：`backend/services/skill_function_bridge.py`
- 运行时依赖：`backend/services/skill_dependencies.py`
- 路由与依赖：`backend/api/skills.py`
- 前端 API：`apps/desktop/src/api/skills.ts`
- 工作区：`apps/desktop/src/features/skills/SkillWorkspace.tsx`
- 后端测试：`tests/test_skills.py`
- 加载与集成测试：`tests/test_skill_runtime.py`
- 前端交互测试：`apps/desktop/src/features/skills/SkillWorkspace.test.tsx`

```powershell
python -m pytest tests/test_skills.py tests/test_skill_runtime.py -q
cd apps/desktop
npx vitest run src/features/skills/SkillWorkspace.test.tsx src/features/workspace/workspace-navigation.test.ts
npx tsc --noEmit -p tsconfig.app.json
npm run build
```

测试覆盖文件生命周期、导入资源、启用状态持久化、草稿校验、版本冲突、路径限制、资源限额、编辑保护和界面错误反馈。符号链接测试在无创建权限的 Windows 环境会显式跳过。
