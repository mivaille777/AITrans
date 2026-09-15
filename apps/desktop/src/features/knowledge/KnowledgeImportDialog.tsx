import { FilePlus2, ShieldCheck, X } from "lucide-react"

import { Button } from "../../shared/ui/Button"

export function KnowledgeImportDialog({ open, adding, onBrowse, onClose }: { open: boolean; adding: boolean; onBrowse: () => void; onClose: () => void }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/25 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={onClose}>
      <section className="ait-scroll-panel max-h-[calc(100vh-2rem)] w-full max-w-lg overflow-y-auto overscroll-contain rounded-[22px] border border-white/70 bg-white/95 p-5 shadow-[0_24px_70px_rgba(15,23,42,0.2)]" role="dialog" aria-modal="true" aria-label="Add to Knowledge Base" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4">
          <div><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Local import</p><h3 className="mt-1.5 text-lg font-semibold text-slate-950">Add to Knowledge Base</h3></div>
          <Button variant="ghost" size="xs" aria-label="Close document import" onClick={onClose}><X size={15} /></Button>
        </header>
        <div className="mt-5 rounded-[18px] border border-dashed border-slate-300 bg-slate-50/70 px-6 py-10 text-center">
          <FilePlus2 size={27} className="mx-auto text-slate-400" />
          <p className="mt-3 text-sm font-semibold text-slate-800">Choose a document to index</p>
          <p className="mt-1 text-xs text-slate-500">PDF · DOCX · TXT · MD · HTML</p>
          <Button className="mt-5" variant="primary" disabled={adding} onClick={onBrowse}>{adding ? "Indexing…" : "Browse files"}</Button>
        </div>
        <p className="mt-4 flex items-center justify-center gap-2 text-xs text-slate-500"><ShieldCheck size={14} className="text-emerald-600" />Files are indexed locally. The source stays in place.</p>
      </section>
    </div>
  )
}
