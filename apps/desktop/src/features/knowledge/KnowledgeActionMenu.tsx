import { Sparkles } from "lucide-react"

export type KnowledgeAction =
  | "summarize"
  | "explain"
  | "translate"
  | "generate_notes"
  | "ask_agent"

const actions: Array<{ id: KnowledgeAction; label: string }> = [
  { id: "summarize", label: "Summarize" },
  { id: "explain", label: "Explain" },
  { id: "translate", label: "Translate" },
  { id: "generate_notes", label: "Generate Notes" },
  { id: "ask_agent", label: "Ask Agent" },
]

export default function KnowledgeActionMenu({
  disabled = false,
  onAction,
}: {
  disabled?: boolean
  onAction?: (action: KnowledgeAction) => void
}) {
  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">
        <Sparkles size={11} /> AI Actions
      </p>
      <div className="grid gap-1.5">
        {actions.map((action) => (
          <button
            key={action.id}
            type="button"
            disabled={disabled}
            onClick={() => onAction?.(action.id)}
            className="rounded-[10px] border border-slate-200 bg-white px-2.5 py-2 text-left text-[10px] text-slate-700 hover:border-slate-300 disabled:opacity-50"
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  )
}
