import { BookOpenText, FileText, Lightbulb, Bot, StickyNote } from "lucide-react"
import type { KnowledgeItem } from "./knowledge-types"

function CardIcon({ type }: { type: KnowledgeItem["item_type"] }) {
  if (type === "paper") return <BookOpenText size={16} />
  if (type === "concept") return <Lightbulb size={16} />
  if (type === "note") return <StickyNote size={16} />
  if (type === "agent") return <Bot size={16} />
  return <FileText size={16} />
}

export default function KnowledgeCardRenderer({ item }: { item: KnowledgeItem }) {
  return (
    <div className="flex h-full flex-col rounded-[18px] border border-slate-200 bg-white shadow-[0_10px_30px_rgba(15,23,42,0.08)]">
      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-50 text-slate-600">
          <CardIcon type={item.item_type} />
        </span>
        <div className="min-w-0">
          <div className="text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-400">{item.item_type}</div>
          <div className="truncate text-xs font-semibold text-slate-900">{item.title}</div>
        </div>
      </div>
      <div className="flex-1 px-3 py-3 text-[11px] leading-5 text-slate-500">
        {item.summary || "No summary yet"}
      </div>
    </div>
  )
}
