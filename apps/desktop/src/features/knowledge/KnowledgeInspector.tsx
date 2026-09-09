import KnowledgeActionMenu, { type KnowledgeAction } from "./KnowledgeActionMenu"
import type { KnowledgeItem } from "./knowledge-types"

export default function KnowledgeInspector({
  item,
  onAction,
}: {
  item: KnowledgeItem | null
  onAction?: (action: KnowledgeAction) => void
}) {
  if (!item) {
    return (
      <div className="mt-6 text-center text-[10px] leading-5 text-slate-400">
        Select one card to inspect its knowledge context.
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
      </div>
      <KnowledgeActionMenu onAction={onAction} />
    </div>
  )
}
