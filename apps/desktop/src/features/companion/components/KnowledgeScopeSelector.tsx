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
    <div className="ait-knowledge-scope-overlay" role="presentation" onMouseDown={onClose}>
      <section
        className="ait-knowledge-scope-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Knowledge scope"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4">
          <div>
            <p className="ait-chat-section-eyebrow">Retrieval</p>
            <h3 className="ait-knowledge-scope-title">Knowledge scope</h3>
          </div>
          <Button className="ait-knowledge-scope-close" variant="ghost" size="xs" aria-label="Close knowledge scope" onClick={onClose}>
            <X size={15} />
          </Button>
        </header>

        <div className="ait-knowledge-scope-content">
          <button
            type="button"
            className={`ait-knowledge-all-documents ${allDocuments ? "is-selected" : ""}`}
            onClick={() => setDraftIds([])}
          >
            All documents
            {allDocuments && <Check size={15} />}
          </button>

          <div className="pt-2">
            <p className="ait-knowledge-selected-label">Selected documents</p>
            <div className="ait-knowledge-document-list">
              {documents.map((document) => {
                const selected = draftIds.includes(document.document_id)
                return (
                  <label key={document.document_id} className="ait-knowledge-document-row">
                    <input
                      type="checkbox"
                      className="ait-knowledge-checkbox"
                      checked={selected}
                      onChange={() => setDraftIds((current) => selected
                        ? current.filter((id) => id !== document.document_id)
                        : [...current, document.document_id])}
                    />
                    <span className="ait-knowledge-document-copy">
                      <span className="ait-knowledge-document-title">{document.title}</span>
                      <span className="ait-knowledge-document-count">{document.chunk_count} chunks</span>
                    </span>
                  </label>
                )
              })}
            </div>
          </div>
        </div>

        <footer className="ait-knowledge-scope-footer">
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
