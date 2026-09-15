import { AlertTriangle } from "lucide-react"

import { Button } from "../../shared/ui/Button"
import type { KnowledgeDocument } from "./knowledge-types"

export function KnowledgeDeleteDialog({ document, deleting, onCancel, onConfirm }: { document: KnowledgeDocument | null; deleting: boolean; onCancel: () => void; onConfirm: () => void }) {
  if (!document) return null
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-slate-950/30 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={onCancel}>
      <section className="ait-scroll-panel max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto overscroll-contain rounded-[22px] border border-white/70 bg-white p-5 shadow-[0_24px_70px_rgba(15,23,42,0.2)]" role="alertdialog" aria-modal="true" aria-label="Remove from Knowledge Base" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[12px] bg-rose-50 text-rose-600"><AlertTriangle size={17} /></span><div><h3 className="text-base font-semibold text-slate-900">Remove from Knowledge Base?</h3><p className="mt-2 text-sm leading-6 text-slate-600">This removes chunks and vectors for <strong>{document.title}</strong>. The original file will not be deleted.</p></div></div>
        <footer className="mt-5 flex justify-end gap-2"><Button size="sm" disabled={deleting} onClick={onCancel}>Cancel</Button><Button variant="danger" size="sm" disabled={deleting} onClick={onConfirm}>{deleting ? "Removing…" : "Remove"}</Button></footer>
      </section>
    </div>
  )
}
