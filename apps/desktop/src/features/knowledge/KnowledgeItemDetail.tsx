import { Trash2, X } from "lucide-react"

import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import type { KnowledgeItem } from "./knowledge-types"

export function KnowledgeItemDetail({ item, deleting, onClose, onDelete }: { item: KnowledgeItem; deleting: boolean; onClose: () => void; onDelete: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/25 backdrop-blur-[2px]" role="presentation" onMouseDown={onClose}>
      <aside className="ait-scroll-panel h-full w-full max-w-md overflow-y-auto overscroll-contain border-l border-white/60 bg-white/95 p-5 shadow-[-24px_0_70px_rgba(15,23,42,0.18)]" role="dialog" aria-modal="true" aria-label={`Knowledge card details ${item.title}`} onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 pb-4"><div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Knowledge card</p><h3 className="mt-1.5 text-lg font-semibold text-slate-950">{item.title}</h3></div><Button variant="ghost" size="xs" aria-label="Close knowledge card details" onClick={onClose}><X size={16} /></Button></header>
        <div className="mt-5"><Badge tone={item.item_type === "concept" ? "info" : "neutral"}>{item.item_type}</Badge></div>
        <section className="mt-6"><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Content</p><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{item.summary || "No summary has been added yet."}</p></section>
        {item.source_uri && <section className="mt-6"><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Source</p><p className="mt-2 break-words font-mono text-[11px] leading-5 text-slate-500">{item.source_uri}</p></section>}
        <section className="mt-6"><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Updated</p><p className="mt-2 text-sm text-slate-600">{new Date(item.updated_at).toLocaleString()}</p></section>
        <div className="mt-8"><Button variant="ghost" size="sm" className="text-rose-600" disabled={deleting} onClick={onDelete}><Trash2 size={14} />{deleting ? "Deleting…" : "Delete card"}</Button></div>
      </aside>
    </div>
  )
}
