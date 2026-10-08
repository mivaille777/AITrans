import { useEffect, useRef, useState } from "react"
import { Check, ChevronDown, Folder, LoaderCircle, Wrench } from "lucide-react"
import type { KnowledgeAccessPolicy } from "../../../api/agent"
import type { useChatConfiguration } from "../hooks/useChatConfiguration"
import { AgentToolsControl } from "./AgentToolsControl"

export function ChatSessionControls({
  config,
  disabled,
  selectedTools,
  onToolsChange,
  hasReadingContext,
  knowledgePolicy,
  onKnowledgePolicyChange,
}: {
  config: ReturnType<typeof useChatConfiguration>
  disabled: boolean
  selectedTools: string[]
  onToolsChange: (tools: string[]) => void
  hasReadingContext: boolean
  knowledgePolicy: KnowledgeAccessPolicy
  onKnowledgePolicyChange: (policy: KnowledgeAccessPolicy) => void
}) {
  const [open, setOpen] = useState<"workspace" | "mode" | "files" | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const { configuration, workspaces, mutation } = config
  const data = configuration.data
  const busy =
    disabled || mutation.isPending || !data || Boolean(data.pending_run_id)
  const selectedWorkspace = workspaces.data?.find(
    (item) => item.workspace_id === data?.filesystem_workspace_id,
  )
  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(null)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(null)
    }
    document.addEventListener("pointerdown", close)
    document.addEventListener("keydown", escape)
    return () => {
      document.removeEventListener("pointerdown", close)
      document.removeEventListener("keydown", escape)
    }
  }, [open])
  const toggle = (menu: typeof open) =>
    setOpen((value) => (value === menu ? null : menu))
  return (
    <div ref={root} className="contents">
      <div className="ait-chat-context-picker">
        <button
          type="button"
          className="ait-chat-composer-control"
          aria-label="工作区"
          aria-expanded={open === "workspace"}
          aria-haspopup="menu"
          disabled={disabled || mutation.isPending}
          onClick={() => toggle("workspace")}
        >
          <Folder size={18} />
          <span>
            {selectedWorkspace?.display_name ||
              (data?.filesystem_workspace_id ? "工作区不可用" : "选择工作区")}
          </span>
          <ChevronDown size={14} />
        </button>
        {open === "workspace" && (
          <div
            className="ait-chat-context-picker-menu"
            role="menu"
            aria-label="工作区选择"
          >
            <button
              type="button"
              role="menuitem"
              className="ait-chat-context-picker-option"
              disabled={busy}
              onClick={() => mutation.mutate({ kind: "choose" })}
            >
              <span>
                <strong>选择本地文件夹…</strong>
                <small>确定文件读取和任务执行的工作区。</small>
              </span>
            </button>
            {workspaces.data
              ?.filter((item) => item.status === "active")
              .map((item) => (
                <button
                  type="button"
                  key={item.workspace_id}
                  role="menuitem"
                  className="ait-chat-context-picker-option"
                  disabled={busy}
                  onClick={() =>
                    mutation.mutate({
                      kind: "update",
                      update: { filesystem_workspace_id: item.workspace_id },
                    })
                  }
                >
                  <span>
                    <strong>{item.display_name}</strong>
                    <small>{item.display_path || "已登记的本地工作区"}</small>
                  </span>
                  {item.workspace_id === data?.filesystem_workspace_id && (
                    <Check size={14} />
                  )}
                </button>
              ))}
            {data?.filesystem_workspace_id && (
              <button
                type="button"
                role="menuitem"
                className="ait-chat-context-picker-option"
                disabled={busy}
                onClick={() =>
                  mutation.mutate({
                    kind: "update",
                    update: { filesystem_workspace_id: "" },
                  })
                }
              >
                清除当前工作区
              </button>
            )}
            <p className="ait-chat-model-menu-message">
              切换工作区会移除当前会话的文件引用，已保存的副本保留。
            </p>
            {workspaces.isError && (
              <p role="alert" className="ait-chat-model-menu-message is-error">
                工作区列表加载失败。
              </p>
            )}
          </div>
        )}
      </div>
      <div className="ait-chat-tools-picker">
        <button
          type="button"
          className="ait-chat-composer-control"
          aria-label="执行模式"
          aria-expanded={open === "mode"}
          aria-haspopup="menu"
          disabled={disabled || mutation.isPending}
          onClick={() => toggle("mode")}
        >
          <Wrench size={14} />
          <span>
            {data?.execution_mode === "plan_execute"
              ? "Plan–Execute"
              : "常规（ReAct）"}
          </span>
          <ChevronDown size={14} />
        </button>
        {open === "mode" && (
          <div
            className="ait-chat-tools-menu"
            role="menu"
            aria-label="执行模式选择"
          >
            {(
              [
                {
                  id: "react",
                  label: "常规（ReAct）",
                  description: "逐步选择动作，根据工具结果继续处理。",
                },
                {
                  id: "plan_execute",
                  label: "Plan–Execute",
                  description: "先显示计划，确认后按计划执行。",
                },
              ] as const
            ).map((mode) => (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={data?.execution_mode === mode.id}
                key={mode.id}
                className="ait-chat-tools-auto"
                disabled={busy}
                onClick={() =>
                  mutation.mutate({
                    kind: "update",
                    update: { execution_mode: mode.id },
                  })
                }
              >
                <span>
                  <strong>{mode.label}</strong>
                  <small>{mode.description}</small>
                </span>
                {data?.execution_mode === mode.id && <Check size={15} />}
              </button>
            ))}
            <AgentToolsControl
              selectedTools={selectedTools}
              disabled={busy}
              onChange={onToolsChange}
              hasReadingContext={hasReadingContext}
              workspaceId={data?.filesystem_workspace_id ?? ""}
              knowledgePolicy={knowledgePolicy}
            />
            <label className="ait-chat-composer-knowledge">
              <span>知识库检索</span>
              <select
                aria-label="Knowledge policy"
                disabled={busy}
                value={knowledgePolicy}
                onChange={(event) =>
                  onKnowledgePolicyChange(
                    event.target.value as KnowledgeAccessPolicy,
                  )
                }
              >
                <option value="auto">自动</option>
                <option value="always">总是检索</option>
                <option value="never">不检索</option>
              </select>
            </label>
          </div>
        )}
      </div>
      <div className="ait-chat-context-picker ait-chat-composer-knowledge">
        <button
          type="button"
          className="ait-chat-composer-control"
          aria-label="导入文件"
          aria-expanded={open === "files"}
          aria-haspopup="menu"
          disabled={disabled || mutation.isPending}
          onClick={() => toggle("files")}
        >
          <span className="ait-chat-composer-knowledge-dot" />
          <span>
            导入文件
            {data?.attachments.length ? `（${data.attachments.length}）` : ""}
          </span>
          <ChevronDown size={14} />
        </button>
        {open === "files" && (
          <div
            className="ait-chat-context-picker-menu"
            role="menu"
            aria-label="会话文件"
          >
            <button
              type="button"
              role="menuitem"
              className="ait-chat-context-picker-option"
              disabled={busy || !data?.filesystem_workspace_id}
              onClick={() => mutation.mutate({ kind: "import" })}
            >
              <span>
                <strong>从电脑导入…</strong>
                <small>
                  PDF、DOCX、TXT、Markdown、HTML；单个文件最大 16 MB。
                </small>
              </span>
            </button>
            {!data?.filesystem_workspace_id && (
              <p className="ait-chat-model-menu-message">请先选择工作区。</p>
            )}
            {data?.attachments.map((file) => (
              <div
                key={file.attachment_id}
                className="ait-chat-context-picker-option"
              >
                <span>
                  <strong>{file.name}</strong>
                  <small>
                    {file.relative_path} · {file.text_chars} 字
                  </small>
                </span>
                <button
                  type="button"
                  className="ait-chat-message-action shrink-0 whitespace-nowrap"
                  disabled={busy}
                  aria-label={`移除 ${file.name}`}
                  onClick={() =>
                    mutation.mutate({ kind: "detach", id: file.attachment_id })
                  }
                >
                  移除
                </button>
              </div>
            ))}
            <p className="ait-chat-model-menu-message">
              保存副本至工作区，仅用于当前会话。文件内的指令作为资料处理。
            </p>
          </div>
        )}
      </div>
      {mutation.isPending && (
        <LoaderCircle size={14} aria-label="正在更新会话配置" />
      )}
    </div>
  )
}
