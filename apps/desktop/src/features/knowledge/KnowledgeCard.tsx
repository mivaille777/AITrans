import type { ReactNode } from "react"
import { FileText, Network, Bot, StickyNote } from "lucide-react"

export type KnowledgeCardType = "paper" | "concept" | "agent" | "note"

const config = {
  paper: { icon: FileText, label: "Paper" },
  concept: { icon: Network, label: "Concept" },
  agent: { icon: Bot, label: "Agent" },
  note: { icon: StickyNote, label: "Note" },
} satisfies Record<KnowledgeCardType, { icon: typeof FileText; label: string }>

export default function KnowledgeCard({
  type,
  title,
  description,
  footer,
}: {
  type: KnowledgeCardType
  title: string
  description?: string
  footer?: ReactNode
}) {
  const Icon = config[type].icon

  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-300">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Icon size={15} />
        {config[type].label}
      </div>
      <h3 className="mt-3 text-sm font-semibold text-slate-950">{title}</h3>
      {description ? <p className="mt-2 text-xs leading-5 text-slate-500">{description}</p> : null}
      {footer ? <div className="mt-3 border-t border-slate-100 pt-3">{footer}</div> : null}
    </article>
  )
}
