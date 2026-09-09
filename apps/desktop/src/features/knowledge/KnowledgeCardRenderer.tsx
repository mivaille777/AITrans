import { BookOpenText, FileText, Highlighter, Lightbulb, StickyNote } from "lucide-react"

import type { KnowledgeItem } from "./knowledge-types"

function CardIcon({ type }: { type: KnowledgeItem["item_type"] }) {
  if (type === "paper") return <BookOpenText size={16} />
  if (type === "concept") return <Lightbulb size={16} />
  if (type === "note") return <StickyNote size={16} />
  if (type === "highlight") return <Highlighter size={16} />
  return <FileText size={16} />
}

export default function KnowledgeCardRenderer({ item }: { item: KnowledgeItem }) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2.5 pr-20">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-600">
          <CardIcon type={item.item_type} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-400">{item.item_type}</div>
          <div className="truncate text-xs font-semibold text-slate-900">{item.title}</div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden px-3 py-3 text-[11px] leading-5 text-slate-500">
        <p className="line-clamp-4">{item.summary || "No summary yet. Open this card from the Library to add more context."}</p>
      </div>
      <div className="border-t border-slate-100 px-3 py-2 text-[9px] font-medium text-slate-400">
        {item.item_type === "paper" ? "Research source" : "Knowledge card"}
      </div>
    </div>
  )
}
