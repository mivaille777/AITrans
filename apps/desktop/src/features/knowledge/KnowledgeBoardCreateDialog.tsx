import { LayoutDashboard, X } from "lucide-react"
import { useState } from "react"

import { Button } from "../../shared/ui/Button"
import type { KnowledgeBoardCreateInput } from "./knowledge-types"

export function KnowledgeBoardCreateDialog({
  open,
  creating,
  onClose,
  onCreate,
}: {
  open: boolean
  creating: boolean
  onClose: () => void
  onCreate: (payload: KnowledgeBoardCreateInput) => void
}) {
  if (!open) return null

  return (
    <KnowledgeBoardCreateDialogContent
      creating={creating}
      onClose={onClose}
      onCreate={onCreate}
    />
  )
}

function KnowledgeBoardCreateDialogContent({
  creating,
  onClose,
  onCreate,
}: {
  creating: boolean
  onClose: () => void
  onCreate: (payload: KnowledgeBoardCreateInput) => void
}) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/25 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={onClose}>
      <section className="w-full max-w-lg rounded-[22px] border border-white/60 bg-white p-5 shadow-2xl" role="dialog" aria-modal="true" aria-label="Create knowledge board" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4">
          <div>
            <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400"><LayoutDashboard size={12} />Visual knowledge</p>
            <h3 className="mt-1.5 text-lg font-semibold text-slate-950">Create a new board</h3>
          </div>
          <Button variant="ghost" size="xs" aria-label="Close create board dialog" onClick={onClose}><X size={16} /></Button>
        </header>
        <label className="mt-5 block text-xs font-semibold text-slate-700">Name<input autoFocus value={name} onChange={(event) => setName(event.target.value)} className="mt-2 w-full rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300" placeholder="e.g. Bayesian Optimization" /></label>
        <label className="mt-4 block text-xs font-semibold text-slate-700">Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} className="mt-2 min-h-24 w-full resize-y rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal leading-6 outline-none transition focus:border-cyan-300" placeholder="What will this board help you understand?" /></label>
        <footer className="mt-5 flex justify-end gap-2"><Button variant="ghost" disabled={creating} onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!name.trim() || creating} onClick={() => onCreate({ name: name.trim(), description: description.trim() })}>{creating ? "Creating…" : "Create board"}</Button></footer>
      </section>
    </div>
  )
}
