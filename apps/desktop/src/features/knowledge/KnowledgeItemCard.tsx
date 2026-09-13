import {
  AlertTriangle,
  BookOpenText,
  CircleHelp,
  ExternalLink,
  FileText,
  Highlighter,
  Lightbulb,
  LoaderCircle,
  MoreHorizontal,
  Quote,
  RefreshCw,
  Sparkles,
  StickyNote,
  Trash2,
} from "lucide-react"

import { Badge } from "../../shared/ui/Badge"
import {
  knowledgeCardConfidence,
  knowledgeCardLabel,
  knowledgeCardProvenance,
  knowledgeCardSources,
} from "./knowledge-card-model"
import {
  isKnowledgeDocumentActive,
  knowledgeStatusLabel,
  knowledgeStatusTone,
} from "./knowledge-state"
import type { KnowledgeDocument, KnowledgeItem, KnowledgeItemType } from "./knowledge-types"

function ItemIcon({ type }: { type: KnowledgeItemType }) {
  const props = { size: 18, strokeWidth: 1.7 }
  if (type === "paper") return <BookOpenText {...props} />
  if (type === "note") return <StickyNote {...props} />
  if (type === "concept") return <Lightbulb {...props} />
  if (type === "highlight") return <Highlighter {...props} />
  if (type === "evidence") return <Quote {...props} />
  if (type === "insight") return <Sparkles {...props} />
  if (type === "question") return <CircleHelp {...props} />
  return <FileText {...props} />
}

export default function KnowledgeItemCard({
  item,
  document,
  deleting,
  reindexing,
  onOpen,
  onReveal,
  onRemoveSource,
  onDeleteItem,
  onReindex,
}: {
  item: KnowledgeItem
  document?: KnowledgeDocument
  deleting: boolean
  reindexing: boolean
  onOpen: () => void
  onReveal: () => void
  onRemoveSource: () => void
  onDeleteItem: () => void
  onReindex: () => void
}) {
  const active = document ? isKnowledgeDocumentActive(document.status) : false
  const detached = Boolean(item.resource_document_id && !document)
  const confidence = knowledgeCardConfidence(item)
  const provenance = knowledgeCardProvenance(item)
  const sources = knowledgeCardSources(item)

  return (
    <article className="group flex min-h-52 flex-col rounded-[18px] border border-slate-200/80 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.02)] transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-[0_16px_30px_rgba(15,23,42,0.06)]">
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[13px] bg-slate-50 text-slate-600">
          <ItemIcon type={item.item_type} />
        </span>
        <details className="relative">
          <summary className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-[9px] text-slate-400 transition hover:bg-slate-100 hover:text-slate-700" aria-label={`More actions for ${item.title}`}>
            <MoreHorizontal size={16} />
          </summary>
          <div data-placement="top-end" className="absolute bottom-full right-0 z-30 mb-1 w-44 rounded-[14px] border border-slate-200 bg-white p-1.5 text-xs shadow-xl">
            <button type="button" className="flex w-full items-center gap-2 rounded-[9px] px-2.5 py-2 text-left text-slate-700 hover:bg-slate-50" onClick={onOpen}><FileText size={13} />Open details</button>
            {document && <button type="button" className="flex w-full items-center gap-2 rounded-[9px] px-2.5 py-2 text-left text-slate-700 hover:bg-slate-50" onClick={onReveal}><ExternalLink size={13} />Reveal source</button>}
            {document && <button type="button" className="flex w-full items-center gap-2 rounded-[9px] px-2.5 py-2 text-left text-slate-700 hover:bg-slate-50" disabled={active || reindexing || deleting} onClick={onReindex}><RefreshCw size={13} />Reindex source</button>}
            {document ? (
              <button type="button" className="flex w-full items-center gap-2 rounded-[9px] px-2.5 py-2 text-left text-rose-600 hover:bg-rose-50" disabled={deleting || reindexing} onClick={onRemoveSource}><Trash2 size={13} />Remove source index</button>
            ) : (
              <button type="button" className="flex w-full items-center gap-2 rounded-[9px] px-2.5 py-2 text-left text-rose-600 hover:bg-rose-50" disabled={deleting} onClick={onDeleteItem}><Trash2 size={13} />Delete card</button>
            )}
          </div>
        </details>
      </div>

      <button type="button" className="mt-3 text-left" onClick={onOpen}>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={item.item_type === "paper" || item.item_type === "evidence" ? "info" : "neutral"}>{knowledgeCardLabel(item.item_type)}</Badge>
          {document && <Badge tone={knowledgeStatusTone(document.status)}>{active && <LoaderCircle size={10} className="mr-1 animate-spin" />}{knowledgeStatusLabel(document.status)}</Badge>}
          {detached && <Badge tone="warning">Source detached</Badge>}
          {confidence !== null && <Badge tone="neutral">{Math.round(confidence * 100)}% confidence</Badge>}
        </div>
        <h3 className="mt-3 line-clamp-2 text-sm font-semibold leading-5 text-slate-900 group-hover:text-cyan-800">{item.title}</h3>
        <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-500">
          {item.summary || (document ? `${document.source_type.toUpperCase()} · ${document.chunk_count} indexed chunks` : "No summary yet.")}
        </p>
      </button>

      <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-4 text-[10px] text-slate-400">
        {document?.status === "failed" ? (
          <span className="inline-flex items-center gap-1 text-rose-600"><AlertTriangle size={11} />Indexing failed</span>
        ) : document?.indexed_at ? <span>Indexed {new Date(document.indexed_at).toLocaleDateString()}</span> : <span>Updated {new Date(item.updated_at).toLocaleDateString()}</span>}
        {sources.length > 0 ? <span>· {sources.length} source{sources.length === 1 ? "" : "s"}</span> : null}
        {provenance ? <span>· {provenance.created_by}</span> : null}
      </div>
    </article>
  )
}
