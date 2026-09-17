import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Database, LoaderCircle } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router-dom"

import { getKnowledgeRuntime, listKnowledgeDocuments } from "../../../api/knowledge"
import { queryKeys, queryPolling } from "../../../shared/query/query-keys"
import { KnowledgeScopeSelector } from "./KnowledgeScopeSelector"

export function KnowledgeRetrievalControl({
  enabled,
  selectedDocumentIds,
  disabled,
  onEnabledChange,
  onScopeChange,
}: {
  enabled: boolean
  selectedDocumentIds: string[]
  disabled: boolean
  onEnabledChange: (enabled: boolean) => void
  onScopeChange: (documentIds: string[]) => void
}) {
  const [scopeOpen, setScopeOpen] = useState(false)
  const documentsQuery = useQuery({
    queryKey: queryKeys.knowledge.documents,
    queryFn: listKnowledgeDocuments,
    refetchInterval: queryPolling.knowledgeDocuments,
  })
  const runtimeQuery = useQuery({
    queryKey: queryKeys.knowledge.runtime,
    queryFn: getKnowledgeRuntime,
    refetchInterval: queryPolling.knowledgeDocuments,
  })
  const readyDocuments = (documentsQuery.data?.documents ?? []).filter((document) => document.status === "ready")
  const available = readyDocuments.length > 0 && runtimeQuery.data?.enabled !== false
  const selectedCount = selectedDocumentIds.filter((id) => readyDocuments.some((document) => document.document_id === id)).length
  const busy = documentsQuery.isPending || runtimeQuery.isPending

  return (
    <section className="ait-chat-knowledge-section">
      <div className="ait-chat-section-heading">
        <p className="ait-chat-section-eyebrow">Knowledge</p>
        {busy && <LoaderCircle size={14} className="ait-chat-loading-icon" />}
      </div>

      <div className="ait-chat-knowledge-card">
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          disabled={disabled || !available}
          className="ait-chat-knowledge-toggle-row"
          onClick={() => onEnabledChange(!enabled)}
        >
          <span className="ait-chat-knowledge-toggle-label">
            <span className={`ait-chat-knowledge-icon ${enabled ? "is-on" : ""}`}>
              <Database size={17} />
            </span>
            <span>Search knowledge base</span>
          </span>
          <span className={`ait-chat-switch ${enabled ? "is-on" : ""}`} aria-hidden="true">
            <span />
          </span>
        </button>

        {available ? (
          <>
            <button
              type="button"
              disabled={!enabled || disabled}
              className="ait-chat-knowledge-scope"
              onClick={() => setScopeOpen(true)}
            >
              <span className="ait-chat-knowledge-scope-copy">
                <span className="ait-chat-knowledge-scope-label">Scope</span>
                <span className="ait-chat-knowledge-scope-value">
                  {selectedCount > 0 ? `${selectedCount} selected documents` : "All documents"}
                </span>
              </span>
              <ChevronRight size={16} />
            </button>
            <p className="ait-chat-knowledge-count">{readyDocuments.length} documents available</p>
          </>
        ) : !busy ? (
          <div className="ait-chat-knowledge-empty">
            <p>Knowledge base is empty</p>
            <span>Add documents before enabling retrieval.</span>
            <Link to="/knowledge">Open Knowledge Base</Link>
          </div>
        ) : null}

        {runtimeQuery.data && (
          <div className="ait-chat-knowledge-status">
            <span className="ait-chat-knowledge-pill">
              {runtimeQuery.data.embedding_status || "Runtime unavailable"}
            </span>
            <span className="ait-chat-knowledge-pill">{runtimeQuery.data.device}</span>
          </div>
        )}
      </div>

      <KnowledgeScopeSelector
        open={scopeOpen}
        documents={readyDocuments}
        selectedDocumentIds={selectedDocumentIds}
        onApply={onScopeChange}
        onClose={() => setScopeOpen(false)}
      />
    </section>
  )
}
