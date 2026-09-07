import { Highlighter, Lightbulb, Plus, StickyNote, X } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "../../shared/ui/Button"
import type { KnowledgeItemCreateInput } from "./knowledge-types"

type CreatableType = KnowledgeItemCreateInput["item_type"]

const choices: Array<{ type: CreatableType; label: string; icon: typeof StickyNote; description: string }> = [
  { type: "note", label: "Note", icon: StickyNote, description: "Capture your own interpretation or reading note." },
  { type: "concept", label: "Concept", icon: Lightbulb, description: "Create a reusable idea that papers and notes can connect to." },
  { type: "highlight", label: "Highlight", icon: Highlighter, description: "Save a concise quote, finding, or important passage." },
  { type: "paper", label: "Paper", icon: Plus, description: "Create a manual paper card without attaching a local file." },
]

export function KnowledgeCreateCardDialog({ open, creating, onClose, onCreate }: { open: boolean; creating: boolean; onClose: () => void; onCreate: (payload: KnowledgeItemCreateInput) => void }) {
  const [type, setType] = useState<CreatableType>("note")
  const [title, setTitle] = useState("")
  const [summary, setSummary] = useState("")

  useEffect(() => {
    if (!open) return
    setType("note")
    setTitle("")
    setSummary("")
  }, [open])

  if (!open) return null
  const canCreate = title.trim().length > 0 && !creating

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/25 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={onClose}>
      <section className="w-full max-w-xl rounded-[22px] border border-white/60 bg-white p-5 shadow-2xl" role="dialog" aria-modal="true" aria-label="Create knowledge card" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4"><div><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Knowledge card</p><h3 className="mt-1.5 text-lg font-semibold text-slate-950">Create a new card</h3></div><Button variant="ghost" size="xs" aria-label="Close create card dialog" onClick={onClose}><X size={16} /></Button></header>
        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          {choices.map(({ type: value, label, icon: Icon, description }) => <button key={value} type="button" className={`rounded-[15px] border p-3 text-left transition ${type === value ? "border-cyan-200 bg-cyan-50/70" : "border-slate-200 hover:bg-slate-50"}`} onClick={() => setType(value)}><span className="flex items-center gap-2 text-xs font-semibold text-slate-800"><Icon size={14} />{label}</span><span className="mt-1.5 block text-[11px] leading-4 text-slate-500">{description}</span></button>)}
        </div>
        <label className="mt-5 block text-xs font-semibold text-slate-700">Title<input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} className="mt-2 w-full rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300" placeholder="Name this card" /></label>
        <label className="mt-4 block text-xs font-semibold text-slate-700">Summary<textarea value={summary} onChange={(event) => setSummary(event.target.value)} className="mt-2 min-h-28 w-full resize-y rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal leading-6 outline-none transition focus:border-cyan-300" placeholder="Add the content or context you want to keep…" /></label>
        <footer className="mt-5 flex justify-end gap-2"><Button variant="ghost" disabled={creating} onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!canCreate} onClick={() => onCreate({ item_type: type, title: title.trim(), summary: summary.trim() })}>{creating ? "Creating…" : "Create card"}</Button></footer>
      </section>
    </div>
  )
}
