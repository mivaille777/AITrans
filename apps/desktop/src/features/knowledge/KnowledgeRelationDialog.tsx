import { ArrowRight, Link2, X } from "lucide-react"
import { useState } from "react"

import { Button } from "../../shared/ui/Button"
import type { KnowledgeItem, KnowledgeRelationCreateInput } from "./knowledge-types"

const relationTypes = [
  { value: "related_to", label: "Related to" },
  { value: "supports", label: "Supports" },
  { value: "contradicts", label: "Contradicts" },
  { value: "explains", label: "Explains" },
  { value: "extends", label: "Extends" },
  { value: "uses", label: "Uses" },
  { value: "derived_from", label: "Derived from" },
] as const

export function KnowledgeRelationDialog({
  source,
  target,
  creating,
  onClose,
  onCreate,
}: {
  source: KnowledgeItem | null
  target: KnowledgeItem | null
  creating: boolean
  onClose: () => void
  onCreate: (payload: KnowledgeRelationCreateInput) => void
}) {
  if (!source || !target) return null

  return (
    <KnowledgeRelationDialogContent
      key={`${source.item_id}:${target.item_id}`}
      source={source}
      target={target}
      creating={creating}
      onClose={onClose}
      onCreate={onCreate}
    />
  )
}

function KnowledgeRelationDialogContent({
  source,
  target,
  creating,
  onClose,
  onCreate,
}: {
  source: KnowledgeItem
  target: KnowledgeItem
  creating: boolean
  onClose: () => void
  onCreate: (payload: KnowledgeRelationCreateInput) => void
}) {
  const [relationType, setRelationType] = useState("related_to")
  const [label, setLabel] = useState("")

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/25 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={onClose}>
      <section className="w-full max-w-lg rounded-[22px] border border-white/60 bg-white p-5 shadow-2xl" role="dialog" aria-modal="true" aria-label="Create knowledge relation" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4">
          <div><p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400"><Link2 size={12} />Manual relation</p><h3 className="mt-1.5 text-lg font-semibold text-slate-950">Connect two cards</h3></div>
          <Button variant="ghost" size="xs" aria-label="Close relation dialog" onClick={onClose}><X size={16} /></Button>
        </header>
        <div className="mt-5 grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-[16px] bg-slate-50 p-3">
          <div className="min-w-0"><p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">Source</p><p className="mt-1 truncate text-xs font-semibold text-slate-800">{source.title}</p></div>
          <ArrowRight size={15} className="text-slate-400" />
          <div className="min-w-0"><p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">Target</p><p className="mt-1 truncate text-xs font-semibold text-slate-800">{target.title}</p></div>
        </div>
        <label className="mt-5 block text-xs font-semibold text-slate-700">Relation<select value={relationType} onChange={(event) => setRelationType(event.target.value)} className="mt-2 w-full rounded-[13px] border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300">{relationTypes.map((relation) => <option key={relation.value} value={relation.value}>{relation.label}</option>)}</select></label>
        <label className="mt-4 block text-xs font-semibold text-slate-700">Optional label<input value={label} onChange={(event) => setLabel(event.target.value)} className="mt-2 w-full rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300" placeholder="Add context to this edge" /></label>
        <footer className="mt-5 flex justify-end gap-2"><Button variant="ghost" disabled={creating} onClick={onClose}>Cancel</Button><Button variant="primary" disabled={creating} onClick={() => onCreate({ source_item_id: source.item_id, target_item_id: target.item_id, relation_type: relationType, label: label.trim(), origin: "manual" })}>{creating ? "Connecting…" : "Create relation"}</Button></footer>
      </section>
    </div>
  )
}
