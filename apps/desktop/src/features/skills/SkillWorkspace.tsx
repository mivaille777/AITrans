import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState, type ReactNode } from "react"
import ReactMarkdown from "react-markdown"
import {
  AlertCircle,
  Check,
  Code2,
  FilePlus2,
  FileText,
  FolderOpen,
  LoaderCircle,
  Plus,
  Puzzle,
  RefreshCw,
  Save,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react"

import {
  createSkill,
  deleteSkillFile,
  getSkill,
  importSkill,
  listSkills,
  readSkillFile,
  removeSkill,
  setSkillEnabled,
  writeSkillFile,
  previewSkillRoute,
  type SkillFileContent,
  type SkillRecord,
} from "../../api/skills"
import { Button } from "../../shared/ui/Button"
import "./SkillWorkspace.css"

const libraryKey = ["skills", "library"] as const
const detailKey = (id: string) => ["skills", "detail", id] as const
const fileKey = (id: string, path: string) =>
  ["skills", "file", id, path] as const
type Filter = "all" | "enabled" | "disabled" | "invalid"
type Confirm = {
  title: string
  message: string
  label: string
  action: () => void
  danger?: boolean
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请重试。"
}

function bytes(size: number) {
  return size < 1024
    ? `${size} B`
    : size < 1024 ** 2
      ? `${(size / 1024).toFixed(1)} KB`
      : `${(size / 1024 ** 2).toFixed(1)} MB`
}

function Status({ skill }: { skill: SkillRecord }) {
  return (
    <span
      className={`skill-status ${!skill.valid ? "is-invalid" : skill.enabled ? "is-enabled" : ""}`}
    >
      <span />
      {!skill.valid ? "待修复" : skill.enabled ? "已启用" : "未启用"}
    </span>
  )
}

export default function SkillWorkspace() {
  const client = useQueryClient()
  const library = useQuery({
    queryKey: libraryKey,
    queryFn: listSkills,
    retry: false,
  })
  const [selected, setSelected] = useState<string | null>(null)
  const [path, setPath] = useState("SKILL.md")
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<Filter>("all")
  const [dialog, setDialog] = useState<"create" | "import" | "file" | null>(
    null,
  )
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [dirty, setDirty] = useState(false)
  const [editorGeneration, setEditorGeneration] = useState(0)
  const [notice, setNotice] = useState("")
  const [routeOpen, setRouteOpen] = useState(false)
  const selectedId = selected ?? library.data?.skills[0]?.id ?? null
  const detail = useQuery({
    queryKey: detailKey(selectedId ?? ""),
    queryFn: () => getSkill(selectedId!),
    enabled: !!selectedId,
    retry: false,
  })
  const file = useQuery({
    queryKey: fileKey(selectedId ?? "", path),
    queryFn: () => readSkillFile(selectedId!, path),
    enabled: !!selectedId,
    retry: false,
  })
  const operation = useMutation({
    mutationFn: (action: () => Promise<void>) => action(),
  })
  const busy = operation.isPending
  const records = library.data?.skills ?? []
  const visible = records.filter((skill) => {
    const matches = `${skill.name} ${skill.description}`
      .toLowerCase()
      .includes(search.toLowerCase())
    return (
      matches &&
      (filter === "all" ||
        (filter === "enabled" && skill.enabled) ||
        (filter === "disabled" && skill.valid && !skill.enabled) ||
        (filter === "invalid" && !skill.valid))
    )
  })
  const error = operation.error ?? library.error ?? detail.error ?? file.error

  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: libraryKey }),
      client.invalidateQueries({ queryKey: ["skills", "detail"] }),
      client.invalidateQueries({ queryKey: ["skills", "file"] }),
    ])
  }

  function run(action: () => Promise<void>) {
    setNotice("")
    operation.mutate(action)
  }

  function leave(action: () => void) {
    if (busy) return
    if (!dirty) {
      action()
      return
    }
    setConfirm({
      title: "放弃未保存的修改？",
      message: "当前文件的修改尚未保存。放弃后会重新读取磁盘内容。",
      label: "放弃修改",
      action: () => {
        setDirty(false)
        setEditorGeneration((value) => value + 1)
        action()
      },
    })
  }

  function selectFile(next: string) {
    if (next !== path) leave(() => setPath(next))
  }

  return (
    <section className="skill-workspace" aria-label="Skill 管理">
      <header className="skill-header">
        <div>
          <div className="skill-eyebrow">
            <Puzzle size={14} /> CAPABILITY LIBRARY
          </div>
          <h1>
            Skills <span>技能库</span>
          </h1>
          <p>把工作方法整理成可复用的技能，在这里管理与预览。</p>
        </div>
        <div className="skill-header-actions">
          <Button disabled={busy} onClick={() => setRouteOpen(true)}>
            <Search size={14} /> 路由检查
          </Button>
          <Button
            size="xs"
            disabled={busy}
            onClick={() => run(refresh)}
            aria-label="刷新技能库"
          >
            <RefreshCw size={14} />
          </Button>
          <Button
            disabled={busy}
            onClick={() => leave(() => setDialog("import"))}
          >
            <Upload size={14} />
            导入技能
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => leave(() => setDialog("create"))}
          >
            <Plus size={15} />
            新建技能
          </Button>
        </div>
      </header>
      {error && (
        <div className="skill-alert" role="alert">
          <AlertCircle size={16} />
          <span>{message(error)}</span>
          <Button
            size="xs"
            onClick={() => {
              operation.reset()
              run(refresh)
            }}
          >
            重试
          </Button>
        </div>
      )}
      {notice && (
        <div className="skill-notice" role="status">
          <Check size={15} />
          {notice}
          <button
            type="button"
            onClick={() => setNotice("")}
            aria-label="关闭提示"
          >
            <X size={14} />
          </button>
        </div>
      )}
      <div className="skill-body">
        <aside className="skill-library" aria-label="技能列表">
          <div className="skill-library-tools">
            <label className="skill-search">
              <Search size={15} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索名称或用途…"
                aria-label="搜索技能"
              />
            </label>
            <div className="skill-library-filter">
              <span>
                {records.length} 个技能 ·{" "}
                {records.filter((item) => item.enabled).length} 已启用
              </span>
              <select
                value={filter}
                onChange={(event) => setFilter(event.target.value as Filter)}
                aria-label="筛选技能"
              >
                <option value="all">全部状态</option>
                <option value="enabled">已启用</option>
                <option value="disabled">未启用</option>
                <option value="invalid">待修复</option>
              </select>
            </div>
          </div>
          <div className="skill-list">
            {library.isPending ? (
              <Loading label="正在读取技能库…" />
            ) : library.isError ? (
              <p className="skill-empty-small">技能库暂不可用，请重试。</p>
            ) : visible.length === 0 ? (
              <div className="skill-empty-small">
                {records.length
                  ? "没有匹配的技能。"
                  : "还没有技能。从新建或导入开始。"}
              </div>
            ) : (
              visible.map((skill) => (
                <button
                  type="button"
                  key={skill.id}
                  className={`skill-card${selectedId === skill.id ? " is-selected" : ""}`}
                  onClick={() => {
                    if (selectedId !== skill.id)
                      leave(() => {
                        setSelected(skill.id)
                        setPath("SKILL.md")
                      })
                  }}
                >
                  <div className="skill-card-top">
                    <span className="skill-card-icon">
                      <Puzzle size={17} />
                    </span>
                    <Status skill={skill} />
                  </div>
                  <h2>{skill.name}</h2>
                  <p>
                    {skill.description ||
                      "缺少用途说明，打开 SKILL.md 后补充。"}
                  </p>
                  <div className="skill-card-footer">
                    <FileText size={12} />
                    {skill.file_count} 个文件
                    <span>
                      {new Date(skill.updated_at).toLocaleDateString("zh-CN")}
                    </span>
                  </div>
                </button>
              ))
            )}
          </div>
          <footer className="skill-library-footer">
            <span className="skill-local-dot" />
            本地文件 · 修改自动校验
            <details>
              <summary>存储位置</summary>
              <code>{library.data?.storage_root ?? "读取中…"}</code>
            </details>
          </footer>
        </aside>
        <main className="skill-detail">
          {!selectedId ? (
            <div className="skill-welcome">
              <span className="skill-welcome-icon">
                <Puzzle size={32} strokeWidth={1.4} />
              </span>
              <h2>让你的工作方法成为技能</h2>
              <p>
                每个技能以 SKILL.md
                为入口，可以附带参考文档、脚本和模板。创建后即可查看和编辑文件。
              </p>
              <Button variant="primary" onClick={() => setDialog("create")}>
                <Plus size={15} />
                创建第一个技能
              </Button>
              <div className="skill-welcome-example">
                <code>my-skill/</code>
                <code>
                  ├── SKILL.md <span>技能说明</span>
                </code>
                <code>
                  ├── references/ <span>参考文档</span>
                </code>
                <code>
                  ├── scripts/ <span>辅助脚本</span>
                </code>
                <code>
                  └── assets/ <span>模板资源</span>
                </code>
              </div>
            </div>
          ) : detail.isPending ? (
            <Loading label="正在读取技能…" />
          ) : detail.data ? (
            <>
              <header className="skill-detail-header">
                <div>
                  <div className="skill-detail-title">
                    <h2>{detail.data.name}</h2>
                    <Status skill={detail.data} />
                  </div>
                  <p>
                    {detail.data.description ||
                      "请在 SKILL.md 中填写 description。"}
                  </p>
                </div>
                <div className="skill-detail-actions">
                  <button
                    className="skill-toggle"
                    type="button"
                    role="switch"
                    aria-checked={detail.data.enabled}
                    aria-label="启用技能"
                    disabled={
                      busy || (!detail.data.valid && !detail.data.enabled)
                    }
                    onClick={() =>
                      run(async () => {
                        await setSkillEnabled(selectedId, !detail.data!.enabled)
                        await refresh()
                      })
                    }
                  >
                    <span className={detail.data.enabled ? "is-on" : ""}>
                      <i />
                    </span>
                    {detail.data.enabled ? "已启用" : "启用"}
                  </button>
                  <Button
                    variant="ghost"
                    size="xs"
                    disabled={busy}
                    aria-label="移除技能"
                    onClick={() =>
                      leave(() =>
                        setConfirm({
                          title: `移除 ${detail.data!.name}？`,
                          message:
                            "该技能将从技能库移除，文件会移入本地 .trash 归档目录。",
                          label: "移除技能",
                          danger: true,
                          action: () =>
                            run(async () => {
                              await removeSkill(selectedId)
                              client.removeQueries({
                                queryKey: detailKey(selectedId),
                              })
                              client.removeQueries({
                                queryKey: ["skills", "file", selectedId],
                              })
                              setSelected(null)
                              setPath("SKILL.md")
                              setDirty(false)
                              await refresh()
                              setNotice(
                                "技能已移除，文件已保留在本地归档目录。",
                              )
                            }),
                        }),
                      )
                    }
                  >
                    <Trash2 size={15} />
                  </Button>
                </div>
              </header>
              {!detail.data.valid && (
                <div className="skill-validation" role="status">
                  <AlertCircle size={15} />
                  <div>
                    <strong>格式需要修复，暂时无法启用</strong>
                    <ul>
                      {detail.data.diagnostics.map((issue) => (
                        <li key={issue}>{issue}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              <div className="skill-runtime-note">
                启用后参与任务路由。先发现用途，再加载所选技能正文；附属文件按需读取。
              </div>
              <div className="skill-files-layout">
                <aside className="skill-files" aria-label="技能文件">
                  <header>
                    <span>
                      文件 <small>{detail.data.file_count}</small>
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      aria-label="新建文件"
                      onClick={() => leave(() => setDialog("file"))}
                    >
                      <FilePlus2 size={15} />
                    </button>
                  </header>
                  <div className="skill-file-list">
                    {detail.data.files.map((item) => (
                      <button
                        type="button"
                        key={item.path}
                        className={path === item.path ? "is-active" : ""}
                        title={item.path}
                        onClick={() => selectFile(item.path)}
                      >
                        <FileText size={14} />
                        <span>{item.path}</span>
                      </button>
                    ))}
                  </div>
                  <details className="skill-metadata">
                    <summary>元数据</summary>
                    <pre>{JSON.stringify(detail.data.metadata, null, 2)}</pre>
                  </details>
                </aside>
                <div className="skill-editor-area">
                  {file.isPending ? (
                    <Loading label="正在读取文件…" />
                  ) : file.isError && !file.data ? (
                    <div className="skill-file-error" role="alert">
                      <AlertCircle size={20} />
                      <p>{message(file.error)}</p>
                      <Button onClick={() => void file.refetch()}>
                        重新加载
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => selectFile("SKILL.md")}
                      >
                        返回 SKILL.md
                      </Button>
                    </div>
                  ) : file.data ? (
                    <FileEditor
                      key={`${selectedId}/${path}/${editorGeneration}`}
                      skillId={selectedId}
                      file={file.data}
                      files={detail.data.files.map((item) => item.path)}
                      busy={busy}
                      onDirtyChange={(value) => {
                        setDirty(value)
                        if (value) setSelected(selectedId)
                      }}
                      onSelectFile={selectFile}
                      onConfirm={setConfirm}
                      onRun={run}
                      onSaved={async (saved) => {
                        client.setQueryData(fileKey(selectedId, path), saved)
                        await refresh()
                        setNotice("文件已保存。")
                      }}
                      onDeleted={() => {
                        setPath("SKILL.md")
                        setDirty(false)
                        void refresh()
                        setNotice("文件已删除。")
                      }}
                    />
                  ) : null}
                </div>
              </div>
            </>
          ) : null}
        </main>
      </div>
      {routeOpen && <RouteInspector onClose={() => setRouteOpen(false)} />}
      {dialog && (
        <SkillDialog
          mode={dialog}
          busy={busy}
          error={operation.error}
          onClose={() => {
            setDialog(null)
            operation.reset()
          }}
          onSubmit={(values) =>
            run(async () => {
              if (dialog === "file") {
                if (!selectedId) return
                await writeSkillFile(selectedId, values.path.trim(), "", null)
                setPath(values.path.trim())
                setDirty(false)
              } else {
                const result =
                  dialog === "create"
                    ? await createSkill(
                        values.name.trim(),
                        values.description.trim(),
                      )
                    : await importSkill(
                        values.content
                          ? { content: values.content }
                          : { path: values.path.trim() },
                      )
                setSelected(result.id)
                setPath("SKILL.md")
                setDirty(false)
                client.setQueryData(detailKey(result.id), result)
              }
              await refresh()
              setDialog(null)
              setNotice(
                dialog === "file"
                  ? "文件已创建，可以开始编辑。"
                  : "技能已加入本地技能库。",
              )
            })
          }
        />
      )}
      {confirm && (
        <Modal title={confirm.title} onClose={() => setConfirm(null)}>
          <p className="skill-modal-description">{confirm.message}</p>
          <div className="skill-modal-actions">
            <Button onClick={() => setConfirm(null)}>取消</Button>
            <Button
              variant={confirm.danger ? "danger" : "primary"}
              onClick={() => {
                setConfirm(null)
                confirm.action()
              }}
            >
              {confirm.label}
            </Button>
          </div>
        </Modal>
      )}
    </section>
  )
}

function Loading({ label }: { label: string }) {
  return (
    <div className="skill-loading" role="status">
      <LoaderCircle size={17} className="animate-spin" />
      {label}
    </div>
  )
}

function FileEditor({
  skillId,
  file,
  files,
  busy,
  onDirtyChange,
  onSelectFile,
  onConfirm,
  onRun,
  onSaved,
  onDeleted,
}: {
  skillId: string
  file: SkillFileContent
  files: string[]
  busy: boolean
  onDirtyChange: (dirty: boolean) => void
  onSelectFile: (path: string) => void
  onConfirm: (confirm: Confirm) => void
  onRun: (action: () => Promise<void>) => void
  onSaved: (saved: SkillFileContent) => Promise<void>
  onDeleted: () => void
}) {
  const [draft, setDraft] = useState(file.content ?? "")
  const [baseline, setBaseline] = useState(file)
  const [tab, setTab] = useState<"preview" | "source">(
    file.content === "" ? "source" : "preview",
  )
  const dirty = draft !== (baseline.content ?? "")
  const changedOnDisk = file.revision !== baseline.revision
  const markdown = file.language === "markdown"
  useEffect(() => {
    if (!dirty) return
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", guard)
    return () => window.removeEventListener("beforeunload", guard)
  }, [dirty])

  function reload() {
    const action = () =>
      onRun(async () => {
        const latest = await readSkillFile(skillId, file.path)
        setBaseline(latest)
        setDraft(latest.content ?? "")
        onDirtyChange(false)
        await onSaved(latest)
      })
    if (dirty)
      onConfirm({
        title: "重新加载文件？",
        message: "这会放弃编辑器中的修改，并读取磁盘上的最新版本。",
        label: "放弃并加载",
        action,
      })
    else action()
  }

  async function save() {
    const saved = await writeSkillFile(
      skillId,
      file.path,
      draft,
      baseline.revision,
    )
    setBaseline(saved)
    setDraft(saved.content ?? "")
    onDirtyChange(false)
    await onSaved(saved)
  }

  const link = (href: string) => {
    try {
      if (/^[a-z][a-z0-9+.-]*:|^\/\/|^#|^\//i.test(href)) return null
      const base = new URL(file.path, "https://skill.local/")
      const target = decodeURIComponent(new URL(href, base).pathname.slice(1))
      return files.includes(target) ? target : null
    } catch {
      return null
    }
  }

  return (
    <div className="skill-editor">
      <header className="skill-editor-toolbar">
        <div className="skill-editor-path">
          <FileText size={15} />
          <span title={file.path}>{file.path}</span>
          {dirty && <small>未保存</small>}
        </div>
        <div className="skill-editor-buttons">
          <Button
            size="xs"
            variant="ghost"
            disabled={busy}
            aria-label="重新加载文件"
            onClick={reload}
          >
            <RefreshCw size={13} />
          </Button>
          {file.path !== "SKILL.md" && (
            <Button
              size="xs"
              variant="ghost"
              disabled={busy}
              aria-label="删除文件"
              onClick={() =>
                onConfirm({
                  title: `删除 ${file.path}？`,
                  message: "该文件将被删除，此操作会同时丢弃当前未保存的修改。",
                  label: "删除文件",
                  danger: true,
                  action: () =>
                    onRun(async () => {
                      await deleteSkillFile(
                        skillId,
                        file.path,
                        baseline.revision,
                      )
                      onDeleted()
                    }),
                })
              }
            >
              <Trash2 size={13} />
            </Button>
          )}
          <Button
            size="xs"
            variant="primary"
            disabled={busy || !dirty || !file.previewable}
            onClick={() => onRun(save)}
          >
            <Save size={13} />
            {busy ? "处理中…" : "保存"}
          </Button>
        </div>
      </header>
      <div className="skill-editor-tabs">
        <div role="tablist" aria-label="文件显示方式">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "preview"}
            onClick={() => setTab("preview")}
          >
            <FileText size={13} />
            预览
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "source"}
            onClick={() => setTab("source")}
          >
            <Code2 size={13} />
            源码 / 编辑
          </button>
        </div>
        <span>
          {bytes(file.size)} · {file.previewable ? "UTF-8" : "二进制文件"}
        </span>
      </div>
      {changedOnDisk && (
        <div className="skill-validation">
          <AlertCircle size={15} />
          <span>
            磁盘文件已更新。编辑器保留了当前内容，请重新加载后再保存。
          </span>
        </div>
      )}
      {!file.previewable ? (
        <div className="skill-file-error">
          <FolderOpen size={26} />
          <p>该文件是二进制或非 UTF-8 文本，暂不支持在线预览与编辑。</p>
          <small>
            {file.path} · {bytes(file.size)}
          </small>
        </div>
      ) : tab === "source" ? (
        <div className="skill-source" role="tabpanel">
          <textarea
            spellCheck={false}
            aria-label="编辑文件内容"
            value={draft}
            disabled={busy}
            onChange={(event) => {
              setDraft(event.target.value)
              onDirtyChange(event.target.value !== (baseline.content ?? ""))
            }}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "s") {
                event.preventDefault()
                if (dirty && !busy) onRun(save)
              }
            }}
          />
        </div>
      ) : markdown ? (
        <article className="skill-markdown" role="tabpanel">
          <ReactMarkdown
            skipHtml
            components={{
              a: ({ href, children }) => {
                const target = href ? link(href) : null
                return target ? (
                  <button
                    type="button"
                    className="skill-document-link"
                    onClick={() => onSelectFile(target)}
                  >
                    {children}
                  </button>
                ) : (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                )
              },
              img: ({ alt }) => (
                <span className="skill-image-placeholder">
                  [图片：{alt || "资源文件"}]
                </span>
              ),
            }}
          >
            {markdownBody(draft)}
          </ReactMarkdown>
          {!markdownBody(draft).trim() && (
            <p className="skill-empty-small">
              文件内容为空，切换到源码开始编辑。
            </p>
          )}
        </article>
      ) : (
        <pre className="skill-code-preview" role="tabpanel">
          {draft || "文件内容为空，切换到源码开始编辑。"}
        </pre>
      )}
      <footer className="skill-editor-footer">
        <span>
          {markdown && tab === "preview"
            ? "元数据见左侧 · 预览显示正文"
            : `${draft.split("\n").length} 行 · ${draft.length} 字符`}
        </span>
        <span>{dirty ? "修改尚未写入文件" : "文件已保存"}</span>
      </footer>
    </div>
  )
}

function markdownBody(source: string): string {
  return source.replace(/^\uFEFF?---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, "")
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string
  children: ReactNode
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const container = ref.current
    const focusable = () =>
      Array.from(
        container?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]',
        ) ?? [],
      )
    const input = container?.querySelector<HTMLElement>("input, textarea")
    ;(input ?? focusable()[0])?.focus()
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault()
        closeRef.current()
      }
      if (event.key !== "Tab") return
      const targets = focusable()
      const first = targets[0],
        last = targets[targets.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    document.addEventListener("keydown", keyboard)
    return () => {
      document.removeEventListener("keydown", keyboard)
      previous?.focus()
    }
  }, [])
  return (
    <div className="skill-modal-backdrop">
      <div
        className="skill-modal"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <button type="button" aria-label="关闭对话框" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}

function RouteInspector({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState("")
  const [mode, setMode] = useState<"general" | "reading">("general")
  const route = useMutation({ mutationFn: previewSkillRoute })
  const result = route.data
  return (
    <Modal title="技能路由检查" onClose={onClose}>
      <form
        className="skill-route-form"
        onSubmit={(event) => {
          event.preventDefault()
          route.mutate({ query: query.trim(), context_mode: mode })
        }}
      >
        <p className="skill-route-hint">
          输入任务，查看可能使用的技能。检查只读取用途元数据；实际使用时由模型选择并加载正文。使用
          $技能名 可显式指定。
        </p>
        <label>
          任务描述
          <textarea
            aria-label="路由任务描述"
            disabled={route.isPending}
            maxLength={6000}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              route.reset()
            }}
            placeholder="例如：对比两篇论文的方法并整理研究结论"
            rows={3}
          />
        </label>
        <label>
          任务范围
          <select
            aria-label="路由任务范围"
            disabled={route.isPending}
            value={mode}
            onChange={(event) => {
              setMode(event.target.value as "general" | "reading")
              route.reset()
            }}
          >
            <option value="general">通用对话</option>
            <option value="reading">阅读上下文</option>
          </select>
        </label>
        <Button
          type="submit"
          variant="primary"
          disabled={!query.trim() || route.isPending}
        >
          {route.isPending && <LoaderCircle size={14} className="skill-spin" />}{" "}
          检查路由
        </Button>
      </form>
      {route.error && <p role="alert">{message(route.error)}</p>}
      {result && (
        <section className="skill-route-result" aria-label="路由检查结果">
          <div className="skill-disclosure-steps">
            <span>1 用途与领域</span>
            <span>2 选中后加载正文</span>
            <span>3 按需读取资料</span>
          </div>
          <p className="skill-route-hint">
            适用自动路由的技能 {result.catalog.eligible_count} 个 · 本次候选{" "}
            {result.candidates.length} 个 · 未加载正文
          </p>
          <div className="skill-route-domains">
            {result.catalog.domains.map((domain) => (
              <span key={domain.id}>
                {result.selected_domains.includes(domain.id)
                  ? "候选领域 · "
                  : ""}
                {domain.description} · {domain.count}
              </span>
            ))}
          </div>
          {result.diagnostics.map((diagnostic) => (
            <p role="status" key={diagnostic}>
              {diagnostic}
            </p>
          ))}
          {result.candidates.length === 0 ? (
            <p>
              没有匹配的已启用技能。可补充任务描述，或检查技能的用途与启用状态。
            </p>
          ) : (
            <ul>
              {result.candidates.map((candidate) => (
                <li key={candidate.id}>
                  <strong>{candidate.id}</strong>
                  <span>{candidate.description}</span>
                  <small>
                    {candidate.reason} ·{" "}
                    {candidate.invocation === "manual"
                      ? "显式调用"
                      : "自动候选"}
                  </small>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </Modal>
  )
}

function SkillDialog({
  mode,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  mode: "create" | "import" | "file"
  busy: boolean
  error: unknown
  onClose: () => void
  onSubmit: (values: {
    name: string
    description: string
    path: string
    content: string
  }) => void
}) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [path, setPath] = useState("")
  const [content, setContent] = useState("")
  const [localError, setLocalError] = useState("")
  const [reading, setReading] = useState(false)
  const title =
    mode === "create" ? "新建技能" : mode === "import" ? "导入技能" : "新建文件"
  async function pickFolder() {
    try {
      const selected = await window.aiTransDesktop?.files.pickAgentWorkspace()
      if (selected) {
        setPath(selected)
        setContent("")
        setLocalError("")
      }
    } catch (exc) {
      setLocalError(message(exc))
    }
  }
  return (
    <Modal
      title={title}
      onClose={() => {
        if (!busy && !reading) onClose()
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault()
          setLocalError("")
          onSubmit({ name, description, path, content })
        }}
      >
        <p className="skill-modal-description">
          {mode === "create"
            ? "使用名称与用途生成 SKILL.md，之后可以自由编辑说明和附属文件。"
            : mode === "import"
              ? "导入本地技能目录会复制文件。也可以选择单个 SKILL.md，仅导入说明文件。"
              : "填写相对路径，例如 references/guide.md 或 scripts/analyze.py。"}
        </p>
        {(error || localError) && (
          <p className="skill-alert" role="alert">
            {localError || message(error)}
          </p>
        )}
        {mode === "create" ? (
          <>
            <label className="skill-form-label">
              技能名称
              <input
                required
                maxLength={64}
                pattern="[a-z0-9]+(-[a-z0-9]+)*"
                placeholder="例如 paper-review"
                value={name}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
              />
              <small>小写字母、数字和单连字符，与目录名称一致。</small>
            </label>
            <label className="skill-form-label">
              用途与触发场景
              <textarea
                required
                maxLength={1024}
                rows={4}
                placeholder="这个技能解决什么问题？什么时候使用？"
                value={description}
                disabled={busy}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
          </>
        ) : (
          <>
            <label className="skill-form-label">
              {mode === "file" ? "文件路径" : "本地技能目录"}
              <div className="skill-path-input">
                <input
                  required={!content}
                  value={path}
                  maxLength={mode === "file" ? 1024 : 4096}
                  disabled={busy || reading}
                  placeholder={
                    mode === "file"
                      ? "references/guide.md"
                      : "包含 SKILL.md 的完整目录路径"
                  }
                  onChange={(event) => {
                    setPath(event.target.value)
                    setContent("")
                    setLocalError("")
                  }}
                />
                {mode === "import" && window.aiTransDesktop && (
                  <Button
                    type="button"
                    size="xs"
                    disabled={busy || reading}
                    onClick={() => void pickFolder()}
                  >
                    <FolderOpen size={14} />
                    选择
                  </Button>
                )}
              </div>
            </label>
            {mode === "import" && (
              <>
                <div className="skill-import-divider">或选择说明文件</div>
                <label className="skill-upload">
                  <Upload size={20} />
                  <strong>
                    {content ? "SKILL.md 已读取" : "选择 SKILL.md"}
                  </strong>
                  <span>UTF-8 Markdown · 最大 2 MB</span>
                  <input
                    type="file"
                    accept=".md,.markdown"
                    aria-label="选择 SKILL.md 文件"
                    disabled={busy || reading}
                    onChange={(event) => {
                      const picked = event.target.files?.[0]
                      if (!picked) return
                      setLocalError("")
                      setContent("")
                      setPath("")
                      if (picked.size > 2 * 1024 ** 2) {
                        setLocalError("文件超过 2 MB。")
                        return
                      }
                      setReading(true)
                      void picked
                        .arrayBuffer()
                        .then((data) => {
                          const text = new TextDecoder("utf-8", {
                            fatal: true,
                          }).decode(data)
                          setContent(text)
                          setPath("")
                          if (!text.trim()) setLocalError("文件内容为空。")
                        })
                        .catch(() =>
                          setLocalError(
                            "无法读取文件，请确认它是 UTF-8 文本。",
                          ),
                        )
                        .finally(() => setReading(false))
                    }}
                  />
                </label>
              </>
            )}
          </>
        )}
        <div className="skill-modal-actions">
          <Button type="button" disabled={busy || reading} onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            type="submit"
            disabled={
              busy ||
              reading ||
              !!localError ||
              (mode === "create"
                ? !name.trim() || !description.trim()
                : !path.trim() && !content.trim())
            }
          >
            {busy || reading ? (
              <LoaderCircle size={14} className="animate-spin" />
            ) : (
              <Plus size={14} />
            )}
            {busy
              ? "处理中…"
              : reading
                ? "读取中…"
                : mode === "import"
                  ? "导入"
                  : "创建"}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
