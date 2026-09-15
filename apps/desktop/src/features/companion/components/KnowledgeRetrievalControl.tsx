import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Database, LoaderCircle } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router-dom"

import { getKnowledgeRuntime, listKnowledgeDocuments } from "../../../api/knowledge"
import { queryKeys, queryPolling } from "../../../shared/query/query-keys"
import { Badge } from "../../../shared/ui/Badge"
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
    <div className="mt-5 border-t border-slate-200/70 pt-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Knowledge</p>
        {busy && <LoaderCircle size={12} className="animate-spin text-slate-400" />}
      </div>

      <div className="mt-3 rounded-[16px] border border-slate-200/70 bg-white/85 p-3.5">
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          disabled={disabled || !available}
          className="flex w-full items-center justify-between gap-3 text-left disabled:opacity-50"
          onClick={() => onEnabledChange(!enabled)}
        >
          <span className="flex items-center gap-2.5">
            <Database size={15} className={enabled ? "text-cyan-700" : "text-slate-400"} />
            <span className="text-xs font-medium text-slate-700">Search knowledge base</span>
          </span>
          <span className={`relative h-5 w-9 rounded-full transition ${enabled ? "bg-cyan-700" : "bg-slate-200"}`}>
            <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition ${enabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
          </span>
        </button>

        {available ? (
          <>
            <button
              type="button"
              disabled={!enabled || disabled}
              className="mt-4 flex w-full items-center justify-between gap-3 border-t border-slate-100 pt-3 text-left disabled:opacity-45"
              onClick={() => setScopeOpen(true)}
            >
              <span>
                <span className="block text-[10px] text-slate-400">Scope</span>
                <span className="mt-0.5 block text-xs font-medium text-slate-700">
                  {selectedCount > 0 ? `${selectedCount} selected documents` : "All documents"}
                </span>
              </span>
              <ChevronRight size={14} className="text-slate-400" />
            </button>
            <p className="mt-3 text-[10px] text-slate-400">{readyDocuments.length} documents available</p>
          </>
        ) : !busy ? (
          <div className="mt-3 rounded-[12px] bg-amber-50 px-3 py-2.5">
            <p className="text-xs font-medium text-amber-800">Knowledge base is empty</p>
            <p className="mt-1 text-[10px] leading-4 text-amber-700">Add documents before enabling retrieval.</p>
            <Link to="/knowledge" className="mt-2 inline-flex text-[10px] font-semibold text-amber-800 underline underline-offset-2">
              Open Knowledge Base
            </Link>
          </div>
        ) : null}

        {runtimeQuery.data && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Badge tone={runtimeQuery.data.embedding_status === "ready" ? "success" : "warning"}>
              {runtimeQuery.data.embedding_status || "Runtime unavailable"}
            </Badge>
            <Badge>{runtimeQuery.data.device}</Badge>
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
    </div>
  )
}
