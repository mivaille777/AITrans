import { Check, X } from "lucide-react"
import { useState } from "react"

import { Button } from "../../../shared/ui/Button"
import type { KnowledgeDocument } from "../../knowledge/knowledge-types"

export function KnowledgeScopeSelector({
  open,
  documents,
  selectedDocumentIds,
  onApply,
  onClose,
}: {
  open: boolean
  documents: KnowledgeDocument[]
  selectedDocumentIds: string[]
  onApply: (documentIds: string[]) => void
  onClose: () => void
}) {
  if (!open) return null
  return (
    <KnowledgeScopeDialog
      key={selectedDocumentIds.join("\u001f")}
      documents={documents}
      selectedDocumentIds={selectedDocumentIds}
      onApply={onApply}
      onClose={onClose}
    />
  )
}

function KnowledgeScopeDialog({
  documents,
  selectedDocumentIds,
  onApply,
  onClose,
}: Omit<Parameters<typeof KnowledgeScopeSelector>[0], "open">) {
  const [draftIds, setDraftIds] = useState(selectedDocumentIds)
  const allDocuments = draftIds.length === 0

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/25 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={onClose}>
      <section
        className="w-full max-w-md rounded-[22px] border border-white/70 bg-white/95 p-5 shadow-[0_24px_70px_rgba(15,23,42,0.2)]"
        role="dialog"
        aria-modal="true"
        aria-label="Knowledge scope"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Retrieval</p>
            <h3 className="mt-1.5 text-lg font-semibold text-slate-950">Knowledge scope</h3>
          </div>
          <Button variant="ghost" size="xs" aria-label="Close knowledge scope" onClick={onClose}>
            <X size={15} />
          </Button>
        </header>

        <div className="mt-5 space-y-2">
          <button
            type="button"
            className={`flex w-full items-center justify-between rounded-[14px] border px-3.5 py-3 text-left text-sm ${allDocuments ? "border-cyan-200 bg-cyan-50/70 text-cyan-900" : "border-slate-200 bg-white text-slate-700"}`}
            onClick={() => setDraftIds([])}
          >
            All documents
            {allDocuments && <Check size={15} />}
          </button>

          <div className="pt-2">
            <p className="px-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Selected documents</p>
            <div className="mt-2 max-h-64 space-y-1 overflow-y-auto">
              {documents.map((document) => {
                const selected = draftIds.includes(document.document_id)
                return (
                  <label key={document.document_id} className="flex cursor-pointer items-start gap-3 rounded-[13px] px-3 py-2.5 hover:bg-slate-50">
                    <input
                      type="checkbox"
                      className="mt-0.5 accent-cyan-700"
                      checked={selected}
                      onChange={() => setDraftIds((current) => selected
                        ? current.filter((id) => id !== document.document_id)
                        : [...current, document.document_id])}
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-medium text-slate-800">{document.title}</span>
                      <span className="mt-0.5 block text-[10px] text-slate-400">{document.chunk_count} chunks</span>
                    </span>
                  </label>
                )
              })}
            </div>
          </div>
        </div>

        <footer className="mt-5 flex justify-end gap-2 border-t border-slate-100 pt-4">
          <Button size="sm" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!allDocuments && draftIds.length === 0}
            onClick={() => {
              onApply(draftIds)
              onClose()
            }}
          >
            Apply
          </Button>
        </footer>
      </section>
    </div>
  )
}
