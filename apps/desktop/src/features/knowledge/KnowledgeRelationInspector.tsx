import { ArrowRight, Link2, Pencil, Trash2 } from "lucide-react"

import { Button } from "../../shared/ui/Button"
import type { KnowledgeItem, KnowledgeRelation } from "./knowledge-types"

export function KnowledgeRelationInspector({
  relation,
  source,
  target,
  deleting,
  onEdit,
  onDelete,
}: {
  relation: KnowledgeRelation
  source: KnowledgeItem | null
  target: KnowledgeItem | null
  deleting: boolean
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <section className="mt-3 space-y-4" aria-label="Knowledge relation inspector">
      <div>
        <p className="flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.16em] text-cyan-600">
          <Link2 size={11} />Canonical relation
        </p>
        <h3 className="mt-2 text-sm font-semibold text-slate-900">
          {relation.label || relation.relation_type.replaceAll("_", " ")}
        </h3>
        <p className="mt-1 text-[10px] capitalize text-slate-400">
          {relation.relation_type.replaceAll("_", " ")} · {relation.origin}
        </p>
      </div>

      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-[14px] border border-slate-200 bg-slate-50 p-3">
        <div className="min-w-0">
          <p className="text-[8px] font-semibold uppercase tracking-[0.14em] text-slate-400">Source</p>
          <p className="mt-1 line-clamp-3 text-[10px] font-semibold leading-4 text-slate-700">
            {source?.title ?? relation.source_item_id}
          </p>
        </div>
        <ArrowRight size={13} className="text-slate-400" />
        <div className="min-w-0">
          <p className="text-[8px] font-semibold uppercase tracking-[0.14em] text-slate-400">Target</p>
          <p className="mt-1 line-clamp-3 text-[10px] font-semibold leading-4 text-slate-700">
            {target?.title ?? relation.target_item_id}
          </p>
        </div>
      </div>

      {relation.label ? (
        <div>
          <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">Label</p>
          <p className="mt-1.5 text-[11px] leading-5 text-slate-600">{relation.label}</p>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-2 text-[10px]">
        <div className="rounded-[11px] border border-slate-100 bg-white p-2.5">
          <p className="text-[8px] font-semibold uppercase tracking-[0.12em] text-slate-400">Origin</p>
          <p className="mt-1 capitalize font-semibold text-slate-700">{relation.origin}</p>
        </div>
        <div className="rounded-[11px] border border-slate-100 bg-white p-2.5">
          <p className="text-[8px] font-semibold uppercase tracking-[0.12em] text-slate-400">Confidence</p>
          <p className="mt-1 font-semibold text-slate-700">
            {relation.confidence == null ? "—" : Math.round(relation.confidence * 100) + "%"}
          </p>
        </div>
      </div>

      <div className="rounded-[12px] border border-amber-100 bg-amber-50 px-3 py-2 text-[9px] leading-4 text-amber-800">
        Canvas relations are organizational context for the Agent. A manual relation records your intended connection, but it is not treated as document evidence by itself.
      </div>

      <div className="flex gap-2">
        <Button variant="secondary" size="sm" onClick={onEdit}><Pencil size={12} />Edit</Button>
        <Button variant="ghost" size="sm" disabled={deleting} onClick={onDelete}><Trash2 size={12} />{deleting ? "Deleting…" : "Delete"}</Button>
      </div>
    </section>
  )
}
