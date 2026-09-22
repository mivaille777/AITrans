import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Database, LoaderCircle } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router-dom"

import { getKnowledgeRuntime, listKnowledgeDocuments } from "../../../api/knowledge"
import { queryKeys, queryPolling } from "../../../shared/query/query-keys"
import { KnowledgeScopeSelector } from "./KnowledgeScopeSelector"
import type { KnowledgeAccessPolicy } from "../../../api/agent"

export function KnowledgeRetrievalControl({
  policy,
  enabled,
  selectedDocumentIds,
  disabled,
  scopeLabel,
  onPolicyChange,
  onEnabledChange,
  onScopeChange,
}: {
  policy?: KnowledgeAccessPolicy
  enabled?: boolean
  selectedDocumentIds: string[]
  disabled: boolean
  scopeLabel?: string
  onPolicyChange?: (policy: KnowledgeAccessPolicy) => void
  onEnabledChange?: (enabled: boolean) => void
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
  const resolvedPolicy: KnowledgeAccessPolicy = policy
    ?? (enabled ? "always" : "auto")
  const changePolicy = (nextPolicy: KnowledgeAccessPolicy) => {
    if (onPolicyChange) {
      onPolicyChange(nextPolicy)
      return
    }
    onEnabledChange?.(nextPolicy === "always")
  }

  return (
    <section className="ait-chat-knowledge-section">
      <div className="ait-chat-section-heading">
        <p className="ait-chat-section-eyebrow">Knowledge</p>
        {busy && <LoaderCircle size={14} className="ait-chat-loading-icon" />}
      </div>

      <div className="ait-chat-knowledge-card">
        <div className="ait-chat-knowledge-toggle-row">
          <span className="ait-chat-knowledge-toggle-label">
            <span className={`ait-chat-knowledge-icon ${resolvedPolicy !== "never" ? "is-on" : ""}`}>
              <Database size={17} />
            </span>
            <span>Knowledge · {resolvedPolicy === "always" ? "Always search" : resolvedPolicy === "never" ? "Never search" : "Auto"}</span>
          </span>
          <select
            aria-label="Knowledge policy"
            className="ait-chat-knowledge-policy-select"
            value={resolvedPolicy}
            disabled={disabled}
            onChange={(event) => changePolicy(event.target.value as KnowledgeAccessPolicy)}
          >
            <option value="auto">Automatic</option>
            <option value="always" disabled={!available}>Always search</option>
            <option value="never">Never search</option>
          </select>
        </div>

        {available ? (
          <>
            <button
              type="button"
              disabled={disabled}
              className="ait-chat-knowledge-scope"
              onClick={() => setScopeOpen(true)}
            >
              <span className="ait-chat-knowledge-scope-copy">
                <span className="ait-chat-knowledge-scope-label">Scope</span>
                <span className="ait-chat-knowledge-scope-value">
                  {scopeLabel ?? (selectedCount > 0 ? `${selectedCount} selected documents` : "All documents")}
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
