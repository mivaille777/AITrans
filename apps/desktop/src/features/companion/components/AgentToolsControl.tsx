import { useEffect, useRef, useState } from "react"
import { BookOpen, Check, ChevronDown, LoaderCircle, ShieldCheck, Wrench } from "lucide-react"
import { useQuery } from "@tanstack/react-query"

import { getAgentTools, type AgentToolDefinition } from "../../../api/agent"
import { queryKeys } from "../../../shared/query/query-keys"

function effectLabel(tool: AgentToolDefinition): string {
  if (tool.effect === "write") return "Writes data"
  if (tool.effect === "compute") return "Computes"
  return "Reads data"
}

export function AgentToolsControl({
  selectedTools,
  disabled,
  hasReadingContext,
  onChange,
}: {
  selectedTools: string[]
  disabled: boolean
  hasReadingContext: boolean
  onChange: (toolNames: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const toolsQuery = useQuery({
    queryKey: queryKeys.agent.tools,
    queryFn: getAgentTools,
    enabled: open,
    staleTime: 60_000,
    retry: 0,
  })

  useEffect(() => {
    if (!open) return undefined
    const closeOnPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("pointerdown", closeOnPointerDown)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [open])

  const tools = toolsQuery.data?.tools ?? []

  function toggleTool(tool: AgentToolDefinition) {
    if (tool.requires_reading_context && !hasReadingContext) return
    if (selectedTools.includes(tool.name)) {
      onChange(selectedTools.filter((name) => name !== tool.name))
    } else {
      onChange([...selectedTools, tool.name])
    }
  }

  return (
    <div className="ait-chat-tools-picker" ref={rootRef}>
      <button
        type="button"
        className={`ait-chat-composer-control ait-chat-tools-button ${selectedTools.length > 0 ? "is-selected" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <Wrench size={14} />
        <span>Tools{selectedTools.length > 0 ? ` (${selectedTools.length})` : ""}</span>
        <ChevronDown size={14} />
      </button>

      {open && (
        <div className="ait-chat-tools-menu" role="menu" aria-label="Agent tools">
          <div className="ait-chat-tools-menu-heading">
            <span>Agent tools</span>
            {toolsQuery.isFetching && <LoaderCircle size={13} className="ait-chat-model-menu-spinner" />}
          </div>
          <button
            type="button"
            role="menuitem"
            className={`ait-chat-tools-auto ${selectedTools.length === 0 ? "is-active" : ""}`}
            onClick={() => {
              onChange([])
              setOpen(false)
            }}
          >
            <span>
              <strong>Automatic</strong>
              <small>Use the allowed catalog for this request.</small>
            </span>
            {selectedTools.length === 0 && <Check size={15} />}
          </button>

          {toolsQuery.isPending ? (
            <p className="ait-chat-tools-message">Loading the tool catalog…</p>
          ) : toolsQuery.isError ? (
            <p className="ait-chat-tools-message is-error">Unable to load Agent tools.</p>
          ) : tools.length === 0 ? (
            <p className="ait-chat-tools-message">No Agent tools are available.</p>
          ) : (
            <div className="ait-chat-tools-options">
              {tools.map((tool) => {
                const unavailable = tool.requires_reading_context && !hasReadingContext
                const checked = selectedTools.includes(tool.name)
                return (
                  <button
                    key={tool.name}
                    type="button"
                    role="menuitemcheckbox"
                    aria-checked={checked}
                    disabled={unavailable}
                    className={`ait-chat-tool-option ${checked ? "is-selected" : ""}`}
                    onClick={() => toggleTool(tool)}
                  >
                    <span className="ait-chat-tool-option-check">{checked && <Check size={13} />}</span>
                    <span className="ait-chat-tool-option-copy">
                      <strong>{tool.title || tool.name}</strong>
                      <small>{tool.description}</small>
                      <span className="ait-chat-tool-option-meta">
                        <span>{tool.category}</span>
                        <span>{effectLabel(tool)}</span>
                        {tool.requires_confirmation && (
                          <span><ShieldCheck size={11} /> Confirmation</span>
                        )}
                        {tool.requires_reading_context && (
                          <span><BookOpen size={11} /> Reading context</span>
                        )}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          )}
          <p className="ait-chat-tools-footnote">
            Selecting a tool routes the next message through Agent WebSocket execution.
          </p>
        </div>
      )}
    </div>
  )
}
