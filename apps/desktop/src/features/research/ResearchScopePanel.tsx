import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookCopy, Database, Layers3, NotebookTabs } from "lucide-react"

import {
  attachResearchProjectMember,
  detachResearchProjectMember,
  getResearchProjectWorkspace,
  getResearchWorkspace,
} from "../../api/research"
import { listKnowledgeDocuments } from "../knowledge/knowledge-api"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { queryKeys } from "../../shared/query/query-keys"
import type { ResearchWorkspaceMemberKind } from "./research-workspace-types"

const SCOPE_SOURCE_LIMIT = 100
const WORKSPACES_KEY = ["research", "project-workspaces"] as const

function detailKey(workspaceId: string) {
  return ["research", "project-workspace", workspaceId] as const
}

export default function ResearchScopePanel({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const queryClient = useQueryClient()
  const activeWorkspaceId = workspace.activeResearchWorkspaceId
  const documentsQuery = useQuery({
    queryKey: queryKeys.knowledge.documents,
    queryFn: listKnowledgeDocuments,
  })
  const researchQuery = useQuery({
    queryKey: queryKeys.research.workspace(SCOPE_SOURCE_LIMIT),
    queryFn: () => getResearchWorkspace(SCOPE_SOURCE_LIMIT),
  })
  const activeWorkspaceQuery = useQuery({
    queryKey: detailKey(activeWorkspaceId),
    queryFn: () => getResearchProjectWorkspace(activeWorkspaceId),
    enabled: Boolean(activeWorkspaceId),
  })

  const membershipMutation = useMutation({
    mutationFn: async ({
      kind,
      resourceId,
      selected,
    }: {
      kind: ResearchWorkspaceMemberKind
      resourceId: string
      selected: boolean
    }) => {
      if (!activeWorkspaceId) return null
      return selected
        ? detachResearchProjectMember(activeWorkspaceId, kind, resourceId)
        : attachResearchProjectMember(activeWorkspaceId, kind, resourceId)
    },
    async onSuccess() {
      if (!activeWorkspaceId) return
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: detailKey(activeWorkspaceId) }),
        queryClient.invalidateQueries({ queryKey: WORKSPACES_KEY }),
      ])
    },
  })

  const manualScope = workspace.researchRetrievalScope
  const project = activeWorkspaceQuery.data
  const readyDocuments = (documentsQuery.data?.documents ?? []).filter(
    (document) => document.status === "ready",
  )
  const notes = researchQuery.data?.notes ?? []
  const sources = researchQuery.data?.sources ?? []

  function toggleDocument(documentId: string) {
    if (activeWorkspaceId && project) {
      membershipMutation.mutate({
        kind: "document",
        resourceId: documentId,
        selected: project.document_ids.includes(documentId),
      })
      return
    }

    const current = new Set(manualScope.knowledgeDocumentIds)
    if (current.has(documentId)) current.delete(documentId)
    else current.add(documentId)
    workspace.setResearchRetrievalScope({
      knowledgeDocumentIds: [...current],
      researchSourceIds: manualScope.researchSourceIds,
    })
  }

  function toggleResearchMemory(resourceId: string) {
    if (activeWorkspaceId && project) {
      membershipMutation.mutate({
        kind: "note",
        resourceId,
        selected: project.note_ids.includes(resourceId),
      })
      return
    }

    const current = new Set(manualScope.researchSourceIds)
    if (current.has(resourceId)) current.delete(resourceId)
    else current.add(resourceId)
    workspace.setResearchRetrievalScope({
      knowledgeDocumentIds: manualScope.knowledgeDocumentIds,
      researchSourceIds: [...current],
    })
  }

  function clearManualScope() {
    if (activeWorkspaceId) return
    workspace.setResearchRetrievalScope({
      knowledgeDocumentIds: [],
      researchSourceIds: [],
    })
  }

  const projectMode = Boolean(activeWorkspaceId)
  const documentCount = projectMode
    ? project?.document_ids.length ?? 0
    : manualScope.knowledgeDocumentIds.length
  const researchCount = projectMode
    ? project?.note_ids.length ?? 0
    : manualScope.researchSourceIds.length
  const manuallyScoped = manualScope.knowledgeDocumentIds.length > 0 || manualScope.researchSourceIds.length > 0

  return (
    <section className="ait-surface overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200/70 px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-slate-500">
            <Layers3 size={17} />
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-slate-400">
              Trusted research scope
            </p>
            <h2 className="mt-1 text-sm font-semibold text-slate-900">
              {projectMode ? "Manage persistent project evidence" : "Bound Agent retrieval to selected evidence sources"}
            </h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              {projectMode
                ? "Selections are persisted as Workspace membership and become the default Agent retrieval scope for this project."
                : "Global mode keeps the Stage 13 temporary scope. Select a Research Project to persist these choices."}
            </p>
          </div>
        </div>
        {!projectMode ? (
          <button
            type="button"
            onClick={clearManualScope}
            disabled={!manuallyScoped}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Use global scope
          </button>
        ) : null}
      </div>

      <div className="grid gap-0 lg:grid-cols-2">
        <ScopeColumn
          icon={<Database size={14} />}
          title="Indexed documents"
          description="Controls the document set used by search_knowledge_base and cross-document research."
          emptyText={documentsQuery.isPending ? "Loading indexed documents…" : "No ready indexed documents."}
          items={readyDocuments.map((document) => ({
            id: document.document_id,
            title: document.title || "Untitled document",
            meta: `${document.source_type} · ${document.chunk_count} chunks`,
            selected: projectMode
              ? Boolean(project?.document_ids.includes(document.document_id))
              : manualScope.knowledgeDocumentIds.includes(document.document_id),
          }))}
          onToggle={toggleDocument}
        />
        <ScopeColumn
          icon={<NotebookTabs size={14} />}
          title={projectMode ? "Research notes" : "Research memory sources"}
          description={projectMode
            ? "Adds exact saved evidence notes to the persistent Research Project."
            : "Constrains search_research_notes over saved evidence and annotations."}
          emptyText={researchQuery.isPending ? "Loading research memory…" : "No saved research memory."}
          items={(projectMode ? notes : sources).map((item) => projectMode
            ? {
                id: "note_id" in item ? item.note_id : "",
                title: "display_title" in item ? item.display_title : "Untitled note",
                meta: "section_heading" in item && item.section_heading
                  ? item.section_heading
                  : "Saved research evidence",
                selected: "note_id" in item
                  ? Boolean(project?.note_ids.includes(item.note_id))
                  : false,
              }
            : {
                id: "source_id" in item ? item.source_id : "",
                title: item.display_title,
                meta: "note_count" in item
                  ? `${item.note_count} notes · ${item.section_count} sections`
                  : "Research source",
                selected: "source_id" in item
                  ? manualScope.researchSourceIds.includes(item.source_id)
                  : false,
              })}
          onToggle={toggleResearchMemory}
          bordered
        />
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-200/70 bg-slate-50/55 px-5 py-3 text-[11px] text-slate-500">
        <BookCopy size={13} />
        <span>
          {projectMode ? "Project" : "Temporary"} document scope: {documentCount || "all"} · Research-memory scope: {researchCount || "all"}
        </span>
        {membershipMutation.isPending ? <span>Updating project…</span> : null}
      </div>
    </section>
  )
}

function ScopeColumn({
  icon,
  title,
  description,
  emptyText,
  items,
  onToggle,
  bordered = false,
}: {
  icon: React.ReactNode
  title: string
  description: string
  emptyText: string
  items: Array<{ id: string; title: string; meta: string; selected: boolean }>
  onToggle: (id: string) => void
  bordered?: boolean
}) {
  const visibleItems = items.filter((item) => item.id)
  return (
    <div className={`p-4 ${bordered ? "border-t border-slate-200/70 lg:border-l lg:border-t-0" : ""}`}>
      <div className="flex items-center gap-2 text-slate-600">
        {icon}
        <p className="text-xs font-semibold">{title}</p>
      </div>
      <p className="mt-1 text-[11px] leading-5 text-slate-400">{description}</p>
      <div className="ait-scroll-panel mt-3 max-h-48 space-y-1.5 overflow-y-auto overscroll-contain pr-1">
        {visibleItems.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-[11px] text-slate-400">
            {emptyText}
          </p>
        ) : (
          visibleItems.map((item) => (
            <label
              key={item.id}
              className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 transition ${
                item.selected
                  ? "border-cyan-200 bg-cyan-50/70"
                  : "border-slate-200/70 bg-white hover:border-slate-300"
              }`}
            >
              <input
                type="checkbox"
                checked={item.selected}
                onChange={() => onToggle(item.id)}
                className="mt-0.5"
              />
              <span className="min-w-0">
                <span className="block truncate text-[11px] font-medium text-slate-700">{item.title}</span>
                <span className="mt-0.5 block text-[10px] text-slate-400">{item.meta}</span>
              </span>
            </label>
          ))
        )}
      </div>
    </div>
  )
}
