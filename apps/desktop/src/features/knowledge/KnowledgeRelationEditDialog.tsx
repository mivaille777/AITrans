import { Link2, X } from "lucide-react"
import { useState } from "react"

import { Button } from "../../shared/ui/Button"
import type { KnowledgeRelation, KnowledgeRelationUpdateInput } from "./knowledge-types"

const relationTypes = [
  { value: "related_to", label: "Related to" },
  { value: "supports", label: "Supports" },
  { value: "contradicts", label: "Contradicts" },
  { value: "explains", label: "Explains" },
  { value: "extends", label: "Extends" },
  { value: "uses", label: "Uses" },
  { value: "derived_from", label: "Derived from" },
] as const

export function KnowledgeRelationEditDialog({
  relation,
  saving,
  onClose,
  onSave,
}: {
  relation: KnowledgeRelation | null
  saving: boolean
  onClose: () => void
  onSave: (payload: KnowledgeRelationUpdateInput) => void
}) {
  if (!relation) return null
  return (
    <KnowledgeRelationEditDialogContent
      key={relation.relation_id}
      relation={relation}
      saving={saving}
      onClose={onClose}
      onSave={onSave}
    />
  )
}

function KnowledgeRelationEditDialogContent({
  relation,
  saving,
  onClose,
  onSave,
}: {
  relation: KnowledgeRelation
  saving: boolean
  onClose: () => void
  onSave: (payload: KnowledgeRelationUpdateInput) => void
}) {
  const [relationType, setRelationType] = useState(relation.relation_type)
  const [label, setLabel] = useState(relation.label)
  const [confidence, setConfidence] = useState(relation.confidence == null ? "" : String(relation.confidence))

  const parsedConfidence = confidence.trim() === "" ? null : Number(confidence)
  const confidenceValid = parsedConfidence == null || (Number.isFinite(parsedConfidence) && parsedConfidence >= 0 && parsedConfidence <= 1)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/25 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={() => !saving && onClose()}>
      <section className="w-full max-w-lg rounded-[22px] border border-white/60 bg-white p-5 shadow-2xl" role="dialog" aria-modal="true" aria-label="Edit knowledge relation" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4">
          <div><p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400"><Link2 size={12} />Relation settings</p><h3 className="mt-1.5 text-lg font-semibold text-slate-950">Edit relation</h3></div>
          <Button variant="ghost" size="xs" aria-label="Close relation editor" disabled={saving} onClick={onClose}><X size={16} /></Button>
        </header>
        <label className="mt-5 block text-xs font-semibold text-slate-700">Relation<select value={relationType} onChange={(event) => setRelationType(event.target.value)} className="mt-2 w-full rounded-[13px] border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300">{relationTypes.map((candidate) => <option key={candidate.value} value={candidate.value}>{candidate.label}</option>)}</select></label>
        <label className="mt-4 block text-xs font-semibold text-slate-700">Label<input value={label} onChange={(event) => setLabel(event.target.value)} className="mt-2 w-full rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300" placeholder="Optional context for this edge" /></label>
        <label className="mt-4 block text-xs font-semibold text-slate-700">Confidence<input value={confidence} onChange={(event) => setConfidence(event.target.value)} inputMode="decimal" className="mt-2 w-full rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300" placeholder="0–1, optional" />{!confidenceValid ? <span className="mt-1 block text-[10px] text-rose-600">Confidence must be between 0 and 1.</span> : null}</label>
        <footer className="mt-5 flex justify-end gap-2"><Button variant="ghost" disabled={saving} onClick={onClose}>Cancel</Button><Button variant="primary" disabled={saving || !confidenceValid} onClick={() => onSave({ relation_type: relationType, label: label.trim(), confidence: parsedConfidence })}>{saving ? "Saving…" : "Save relation"}</Button></footer>
      </section>
    </div>
  )
}
