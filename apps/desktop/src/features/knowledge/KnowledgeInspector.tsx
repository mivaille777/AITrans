import type { ReactNode } from "react"

import KnowledgeActionMenu, { type KnowledgeAction } from "./KnowledgeActionMenu"
import type { KnowledgeItem } from "./knowledge-types"

export default function KnowledgeInspector({
  item,
  relationCount = 0,
  relations,
  lastEventType,
  onAction,
}: {
  item: KnowledgeItem | null
  relationCount?: number
  relations?: ReactNode
  lastEventType?: string | null
  onAction?: (action: KnowledgeAction) => void
}) {
  if (!item) {
    return (
      <div className="mt-6 rounded-[14px] border border-dashed border-slate-200 bg-slate-50/40 px-4 py-5 text-center text-[10px] leading-5 text-slate-400">
        Select one card to inspect its context, relations, and AI actions.
      </div>
    )
  }

  return (
    <div className="mt-4 space-y-5">
      <div className="rounded-[14px] border border-slate-200 bg-slate-50/50 p-3">
        <p className="text-[9px] uppercase tracking-[0.13em] text-slate-400">{item.item_type}</p>
        <h3 className="mt-1 text-xs font-semibold leading-5 text-slate-900">{item.title}</h3>
        <p className="mt-2 text-[10px] leading-5 text-slate-500">
          {item.summary || "No summary yet."}
        </p>
        {item.source_uri ? (
          <p className="mt-3 truncate border-t border-slate-100 pt-2 text-[9px] text-slate-400" title={item.source_uri}>
            Source · {item.source_uri}
          </p>
        ) : null}
      </div>

      <KnowledgeActionMenu onAction={onAction} />

      {lastEventType ? (
        <div className="rounded-[10px] border border-cyan-100 bg-cyan-50/60 px-2.5 py-2 text-[9px] text-cyan-800">
          Workspace event · {lastEventType.replaceAll("_", " ").toLowerCase()}
        </div>
      ) : null}

      <div>
        <div className="flex items-center justify-between">
          <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">Relations</p>
          <span className="text-[9px] text-slate-400">{relationCount}</span>
        </div>
        <div className="ait-scroll-panel mt-2 max-h-[320px] space-y-2 overflow-y-auto">
          {relations ?? (
            <p className="rounded-[12px] border border-dashed border-slate-200 p-3 text-[10px] leading-4 text-slate-400">
              No explicit relations yet. Use the link action on a canvas card to connect knowledge objects.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
