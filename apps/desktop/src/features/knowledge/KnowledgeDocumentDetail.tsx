import { RefreshCw, Trash2, X } from "lucide-react"

import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import { knowledgeStatusLabel, knowledgeStatusTone } from "./knowledge-state"
import type { KnowledgeDocument } from "./knowledge-types"

export function KnowledgeDocumentDetail({ document, reindexing, onClose, onReindex, onRemove }: { document: KnowledgeDocument; reindexing: boolean; onClose: () => void; onReindex: () => void; onRemove: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/25 backdrop-blur-[2px]" role="presentation" onMouseDown={onClose}>
      <aside className="ait-scroll-panel h-full w-full max-w-md overflow-y-auto overscroll-contain border-l border-white/60 bg-white/95 p-5 shadow-[-24px_0_70px_rgba(15,23,42,0.18)]" role="dialog" aria-modal="true" aria-label={`Document details ${document.title}`} onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 pb-4"><div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Knowledge document</p><h3 className="mt-1.5 truncate text-lg font-semibold text-slate-950">{document.title}</h3></div><Button variant="ghost" size="xs" aria-label="Close document details" onClick={onClose}><X size={16} /></Button></header>
        <div className="mt-5"><Badge tone={knowledgeStatusTone(document.status)}>{knowledgeStatusLabel(document.status)}</Badge></div>
        <dl className="mt-6 space-y-5">
          <Detail term="Document" value={`${document.source_type.toUpperCase()} · ${document.source_uri}`} />
          <Detail term="Index" value={`${document.chunk_count} chunks · 512 target tokens · 80 overlap`} />
          <Detail term="Embedding" value={`${document.embedding_model || "Unavailable"} · ${document.embedding_dimension || 0} dimensions`} />
          <Detail term="Last indexed" value={document.indexed_at ? new Date(document.indexed_at).toLocaleString() : "Not indexed yet"} />
        </dl>
        {document.reindex_recommended && <p className="mt-4 rounded-[12px] bg-amber-50 px-3 py-2 text-xs text-amber-700">This PDF was indexed without reliable section structure. Reindex it to restore section-aware retrieval.</p>}
        <details className="mt-6 rounded-[16px] border border-slate-200 bg-slate-50/70 p-4"><summary className="cursor-pointer text-xs font-semibold text-slate-700">Advanced</summary><dl className="mt-4 space-y-3"><Detail term="Parser" value={document.parser_version || "Unavailable"} /><Detail term="Structure" value={`${document.structure_quality || "unknown"} · ${document.section_count ?? 0} sections`} /><Detail term="Chunker" value={document.chunker_version || "Unavailable"} /><Detail term="Document hash" value={document.content_hash || "Unavailable"} mono /></dl></details>
        <div className="mt-6 flex flex-wrap gap-2"><Button size="sm" disabled={reindexing} onClick={onReindex}><RefreshCw size={14} className={reindexing ? "animate-spin" : ""} />{reindexing ? "Re-indexing…" : "Re-index"}</Button><Button variant="ghost" size="sm" className="text-rose-600" onClick={onRemove}><Trash2 size={14} />Remove from Knowledge</Button></div>
      </aside>
    </div>
  )
}

function Detail({ term, value, mono = false }: { term: string; value: string; mono?: boolean }) {
  return <div><dt className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">{term}</dt><dd className={`mt-1 break-words text-sm leading-6 text-slate-700 ${mono ? "font-mono text-[11px]" : ""}`}>{value}</dd></div>
}
