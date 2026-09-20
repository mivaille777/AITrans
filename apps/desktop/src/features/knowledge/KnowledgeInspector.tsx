import { BookOpenText, Brain, ExternalLink, FileText, Focus, Lightbulb, MoreHorizontal, StickyNote } from "lucide-react"
import { useState, type ReactNode } from "react"

import KnowledgeActionMenu, { type KnowledgeAction } from "./KnowledgeActionMenu"
import { knowledgeCardSources } from "./knowledge-card-model"
import type { KnowledgeItem } from "./knowledge-types"

type InspectorTab = "overview" | "sources" | "relations" | "notes"

function ItemIcon({ type }: { type: KnowledgeItem["item_type"] }) {
  if (type === "paper" || type === "document") return <BookOpenText size={20} strokeWidth={1.7} />
  if (type === "concept") return <Brain size={20} strokeWidth={1.7} />
  if (type === "note") return <StickyNote size={20} strokeWidth={1.7} />
  if (type === "insight") return <Lightbulb size={20} strokeWidth={1.7} />
  return <FileText size={20} strokeWidth={1.7} />
}

export default function KnowledgeInspector({
  item,
  relationCount = 0,
  relations,
  lastEventType,
  onAction,
  onOpen,
  onFocusCanvas,
}: {
  item: KnowledgeItem | null
  relationCount?: number
  relations?: ReactNode
  lastEventType?: string | null
  onAction?: (action: KnowledgeAction) => void
  onOpen?: () => void
  onFocusCanvas?: () => void
}) {
  const [activeTab, setActiveTab] = useState<InspectorTab>("overview")
  const [actionsOpen, setActionsOpen] = useState(true)

  if (!item) {
    return (
      <div className="knowledge-inspector-empty">
        Select one card to inspect its context, relations, and AI actions.
      </div>
    )
  }

  const sources = knowledgeCardSources(item)
  const sourceCount = sources.length || (item.source_uri ? 1 : 0)
  const noteCount = metadataNumber(item.metadata.notes_count)
  const tags = Array.isArray(item.metadata.tags) ? item.metadata.tags.filter((tag): tag is string => typeof tag === "string" && tag.trim().length > 0).slice(0, 6) : []
  const summary = item.summary || "No summary yet. Open this knowledge object to add more context."
  const tabs: Array<{ id: InspectorTab; label: string }> = [
    { id: "overview", label: "Overview" },
    { id: "sources", label: `Sources (${sourceCount})` },
    { id: "relations", label: `Relations (${relationCount})` },
    { id: "notes", label: `Notes (${noteCount})` },
  ]

  return (
    <div className="knowledge-inspector">
      <div className="knowledge-inspector-heading">
        <div className="flex min-w-0 items-start gap-10">
          <span className="knowledge-object-icon"><ItemIcon type={item.item_type} /></span>
          <div className="knowledge-inspector-heading-copy">
            <p className="knowledge-inspector-eyebrow">{item.item_type}</p>
            <h2 className="knowledge-inspector-title" title={item.title}>{item.title}</h2>
          </div>
        </div>
        <button type="button" className="knowledge-inspector-more" aria-label="More knowledge object actions" aria-expanded={actionsOpen} onClick={() => setActionsOpen((open) => !open)}><MoreHorizontal size={16} /></button>
      </div>

      <p className="knowledge-inspector-summary">{summary}</p>
      <div className="knowledge-inspector-meta">
        <span>{sourceCount} sources</span>
        <span><strong>{relationCount}</strong> relations</span>
        <span>{formatDate(item.updated_at)}</span>
      </div>

      <div className="knowledge-inspector-tabs" role="tablist" aria-label="Knowledge object details">
        {tabs.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={activeTab === tab.id} className={`knowledge-inspector-tab${activeTab === tab.id ? " is-active" : ""}`} onClick={() => setActiveTab(tab.id)}>{tab.label}</button>)}
      </div>

      <div className="knowledge-inspector-content">
        {activeTab === "overview" ? (
          <>
            <p className="knowledge-inspector-section-title">Summary</p>
            <p className="knowledge-inspector-section-copy">{summary}</p>
            <div className="knowledge-inspector-topics">
              {(tags.length > 0 ? tags : [item.item_type, "knowledge"]).map((tag) => <span key={tag} className="knowledge-inspector-topic">{tag}</span>)}
            </div>
            <div className="mt-4 flex gap-2">
              {onFocusCanvas ? <button type="button" className="knowledge-object-actions flex-1 !mt-0 !border-0 !p-0" onClick={onFocusCanvas}><span className="inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-[7px] border border-slate-200 text-[10px] font-semibold text-slate-600 hover:border-slate-950 hover:text-slate-950"><Focus size={12} />Focus on canvas</span></button> : null}
              {onOpen ? <button type="button" className="knowledge-object-actions flex-1 !mt-0 !border-0 !p-0" onClick={onOpen}><span className="inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-[7px] border border-slate-200 text-[10px] font-semibold text-slate-600 hover:border-slate-950 hover:text-slate-950"><ExternalLink size={12} />Open</span></button> : null}
            </div>
            <div className="knowledge-inspector-relations">
              <div className="flex items-center justify-between"><p className="knowledge-inspector-section-title">Relations ({relationCount})</p><button type="button" className="text-[10px] text-slate-500 hover:text-slate-950" onClick={() => setActiveTab("relations")}>View all</button></div>
              {relations ?? <div className="knowledge-inspector-empty">No explicit relations yet. Use the link action on a canvas card to connect knowledge objects.</div>}
            </div>
          </>
        ) : null}

        {activeTab === "sources" ? (
          <div className="space-y-3">
            <p className="knowledge-inspector-section-title">Sources ({sourceCount})</p>
            {sources.length > 0 ? sources.map((source, index) => <div key={`${source.document_id}-${source.chunk_id ?? index}`} className="rounded-[9px] border border-slate-200 p-2.5"><p className="text-[10px] font-semibold text-slate-700">{source.section || `Source ${index + 1}`}</p><p className="mt-1 line-clamp-3 text-[9px] leading-4 text-slate-500">{source.quote || source.source_uri || source.document_id}</p></div>) : item.source_uri ? <div className="knowledge-inspector-empty break-all">{item.source_uri}</div> : <div className="knowledge-inspector-empty">No source metadata is attached to this knowledge object.</div>}
          </div>
        ) : null}

        {activeTab === "relations" ? (
          <div className="space-y-3">
            <p className="knowledge-inspector-section-title">Relations ({relationCount})</p>
            <div className="knowledge-inspector-relations">{relations ?? <div className="knowledge-inspector-empty">No explicit relations yet.</div>}</div>
          </div>
        ) : null}

        {activeTab === "notes" ? <div className="space-y-3"><p className="knowledge-inspector-section-title">Notes ({noteCount})</p><div className="knowledge-inspector-empty">Notes attached to this object will appear here. Use Generate Notes from AI actions to create a draft.</div></div> : null}
      </div>

      {lastEventType ? <div className="mt-4 rounded-[8px] border border-slate-200 bg-slate-50 px-2.5 py-2 text-[9px] text-slate-600">Workspace event · {lastEventType.replaceAll("_", " ").toLowerCase()}</div> : null}

      {actionsOpen ? <div className="knowledge-inspector-actions">
        <p className="text-[10px] font-semibold text-slate-600">AI actions</p>
        <div className="knowledge-action-menu"><KnowledgeActionMenu onAction={onAction} /></div>
      </div> : null}
    </div>
  )
}

function metadataNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date)
}
