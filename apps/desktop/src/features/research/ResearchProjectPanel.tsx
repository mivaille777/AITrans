import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FolderKanban, Plus, Target } from "lucide-react"

import {
  createResearchProjectWorkspace,
  listResearchProjectWorkspaces,
} from "../../api/research"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"

const WORKSPACES_KEY = ["research", "project-workspaces"] as const

export default function ResearchProjectPanel({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const [goal, setGoal] = useState("")
  const [description, setDescription] = useState("")

  const workspacesQuery = useQuery({
    queryKey: WORKSPACES_KEY,
    queryFn: () => listResearchProjectWorkspaces(100),
  })

  const createMutation = useMutation({
    mutationFn: createResearchProjectWorkspace,
    async onSuccess(created) {
      workspace.setActiveResearchWorkspaceId(created.workspace_id)
      workspace.setResearchRetrievalScope({
        knowledgeDocumentIds: created.document_ids,
        researchSourceIds: [],
      })
      setName("")
      setGoal("")
      setDescription("")
      setCreating(false)
      await queryClient.invalidateQueries({ queryKey: WORKSPACES_KEY })
    },
  })

  const projects = workspacesQuery.data?.workspaces ?? []
  const active = projects.find(
    (item) => item.workspace_id === workspace.activeResearchWorkspaceId,
  )

  function selectWorkspace(workspaceId: string) {
    workspace.setActiveResearchWorkspaceId(workspaceId)
    if (!workspaceId) {
      workspace.setResearchRetrievalScope({
        knowledgeDocumentIds: [],
        researchSourceIds: [],
      })
    }
  }

  function createProject() {
    const trimmedName = name.trim()
    if (!trimmedName || createMutation.isPending) return
    createMutation.mutate({
      name: trimmedName,
      research_goal: goal.trim(),
      description: description.trim(),
    })
  }

  return (
    <section className="ait-surface overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200/70 px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-slate-500">
            <FolderKanban size={17} />
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-slate-400">
              Research project
            </p>
            <h2 className="mt-1 text-sm font-semibold text-slate-900">
              Keep documents, notes and Agent work under one persistent goal
            </h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              A project survives individual chats and becomes the shared context for Research and Agent workspaces.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setCreating((value) => !value)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-600 transition hover:bg-slate-50"
        >
          <Plus size={13} />
          New project
        </button>
      </div>

      <div className="grid gap-4 p-5 lg:grid-cols-[minmax(240px,0.8fr)_minmax(0,1.2fr)]">
        <div>
          <label className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
            Active project
          </label>
          <select
            value={workspace.activeResearchWorkspaceId}
            onChange={(event) => selectWorkspace(event.target.value)}
            className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 outline-none transition focus:border-slate-400"
          >
            <option value="">Global research context</option>
            {projects.map((project) => (
              <option key={project.workspace_id} value={project.workspace_id}>
                {project.name}
              </option>
            ))}
          </select>
          <p className="mt-2 text-[11px] leading-5 text-slate-400">
            Global context preserves the previous Stage 13 behavior. Selecting a project makes its saved members the default Agent scope.
          </p>
        </div>

        <div className="rounded-xl border border-slate-200/70 bg-slate-50/55 p-4">
          {active ? (
            <>
              <div className="flex items-center gap-2 text-slate-600">
                <Target size={14} />
                <p className="text-xs font-semibold">{active.name}</p>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-600">
                {active.research_goal || "No research goal has been written yet."}
              </p>
              {active.description ? (
                <p className="mt-2 text-[11px] leading-5 text-slate-400">{active.description}</p>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-slate-500">
                <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
                  {active.document_count} documents
                </span>
                <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
                  {active.note_count} notes
                </span>
                <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
                  {active.conversation_count} conversations
                </span>
              </div>
            </>
          ) : (
            <p className="text-xs leading-5 text-slate-500">
              No project selected. Research Notes and Knowledge retrieval remain available globally.
            </p>
          )}
        </div>
      </div>

      {creating ? (
        <div className="border-t border-slate-200/70 bg-slate-50/45 px-5 py-4">
          <div className="grid gap-3 lg:grid-cols-2">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Project name"
              maxLength={200}
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-slate-400"
            />
            <input
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder="Research goal"
              maxLength={8000}
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-slate-400"
            />
          </div>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Optional project description"
            maxLength={4000}
            rows={2}
            className="mt-3 w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-slate-400"
          />
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={createProject}
              disabled={!name.trim() || createMutation.isPending}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {createMutation.isPending ? "Creating…" : "Create project"}
            </button>
          </div>
          {createMutation.isError ? (
            <p className="mt-2 text-[11px] text-rose-600">
              {createMutation.error instanceof Error ? createMutation.error.message : "Unable to create project."}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
