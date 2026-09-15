import { useState, type ReactNode } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowUpRight,
  BookOpenText,
  FileText,
  MessageSquareText,
  NotebookText,
  Save,
  Search,
  Trash2,
} from "lucide-react"
import { useNavigate } from "react-router-dom"

import { createCompanionHandoff } from "../../api/companion"
import {
  deleteResearchNote,
  getResearchWorkspace,
  updateResearchNote,
} from "../../api/research"
import type { ResearchNoteDetail, ResearchSourceSummary } from "../../api/types"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import { EmptyState } from "../../shared/ui/EmptyState"
import ResearchSourceProfilePanel from "./ResearchSourceProfilePanel"
import { filterResearchNotes, researchSourceKinds } from "./research-workspace"

const WORKSPACE_LIMIT = 100
type DetailMode = "none" | "source" | "note"

export default function ResearchWorkspace() {
  const navigate = useNavigate()
  const [query, setQuery] = useState("")
  const [sourceId, setSourceId] = useState("")
  const [sourceKind, setSourceKind] = useState("")
  const [sectionHeading, setSectionHeading] = useState("")
  const [selectedNoteId, setSelectedNoteId] = useState("")
  const [detailMode, setDetailMode] = useState<DetailMode>("none")

  const workspaceQuery = useQuery({
    queryKey: queryKeys.research.workspace(WORKSPACE_LIMIT),
    queryFn: () => getResearchWorkspace(WORKSPACE_LIMIT),
    refetchInterval: queryPolling.researchWorkspace,
  })

  const workspace = workspaceQuery.data
  const notes = filterResearchNotes(workspace?.notes ?? [], {
    query,
    sourceId,
    sourceKind,
    sectionHeading,
  })
  const sources = workspace?.sources ?? []
  const sourceKinds = researchSourceKinds(sources)
  const selectedNote = selectedNoteId
    ? notes.find((note) => note.note_id === selectedNoteId) ?? null
    : null

  function selectSource(nextSourceId: string) {
    setSourceId(nextSourceId)
    setSectionHeading("")
    setSelectedNoteId("")
    setDetailMode(nextSourceId ? "source" : "none")
  }

  function selectNote(noteId: string) {
    setSelectedNoteId(noteId)
    setDetailMode("note")
  }

  if (workspaceQuery.isPending) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 text-sm text-slate-400 shadow-sm">
        Loading Research Workspace…
      </div>
    )
  }

  if (workspaceQuery.isError) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-white p-8 text-sm text-rose-700 shadow-sm">
        {workspaceQuery.error instanceof Error
          ? workspaceQuery.error.message
          : "Unable to load Research Workspace."}
      </div>
    )
  }

  if (!workspace || workspace.total === 0) {
    return (
      <EmptyState
        icon={<NotebookText size={30} strokeWidth={1.5} />}
        title="No Research Notes yet"
        description="Save a reading selection from the Overlay or Reading Workspace, or link evidence from AI Chat. Sources, notes and annotations will be organized here automatically."
      />
    )
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Research Workspace</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-900">
            Sources, evidence and your annotations
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            Source profiles now separate document identity, represented sections and individual evidence notes. Captured evidence stays immutable while your annotation remains independently editable.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{workspace.total} notes</Badge>
          <Badge tone="info">{sources.length} sources</Badge>
        </div>
      </header>

      <div className="grid min-h-[620px] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm xl:h-[clamp(620px,68vh,780px)] xl:min-h-0 xl:grid-cols-[250px_330px_minmax(0,1fr)] xl:grid-rows-[minmax(0,1fr)]">
        <SourcePanel
          sources={sources}
          sourceKinds={sourceKinds}
          selectedSourceId={sourceId}
          selectedSourceKind={sourceKind}
          onSelectSource={selectSource}
          onSelectSourceKind={(kind) => {
            setSourceKind(kind)
            setSourceId("")
            setSectionHeading("")
            setSelectedNoteId("")
            setDetailMode("none")
          }}
        />

        <NoteListPanel
          notes={notes}
          query={query}
          selectedNoteId={selectedNote?.note_id ?? ""}
          selectedSourceId={sourceId}
          sectionHeading={sectionHeading}
          onQueryChange={setQuery}
          onSelectNote={selectNote}
          onOpenSourceOverview={() => {
            setSelectedNoteId("")
            setDetailMode(sourceId ? "source" : "none")
          }}
          onClearSection={() => setSectionHeading("")}
        />

        <main className="min-h-0 min-w-0 overflow-hidden bg-white">
          {detailMode === "source" && sourceId ? (
            <ResearchSourceProfilePanel
              sourceId={sourceId}
              selectedSectionHeading={sectionHeading}
              onSelectSection={(heading) => {
                setSectionHeading(heading)
                setSelectedNoteId("")
                setDetailMode("source")
              }}
            />
          ) : selectedNote ? (
            <ResearchNoteEditor
              key={selectedNote.note_id}
              note={selectedNote}
              onDeleted={() => {
                setSelectedNoteId("")
                setDetailMode(sourceId ? "source" : "none")
              }}
              onOpenConversation={() => {
                if (selectedNote.conversation_id) {
                  navigate(`/chat?conversation=${encodeURIComponent(selectedNote.conversation_id)}`)
                }
              }}
            />
          ) : (
            <div className="ait-scroll-panel h-full overflow-y-auto p-6">
              <EmptyState
                icon={<Search size={28} strokeWidth={1.5} />}
                title={notes.length === 0 ? "No notes match this filter" : "Choose a source or evidence note"}
                description={
                  notes.length === 0
                    ? "Try another source, source type, section or search term."
                    : "Open a source to inspect its profile, or choose one evidence note for full reading context and annotation."
                }
              />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

function SourcePanel({
  sources,
  sourceKinds,
  selectedSourceId,
  selectedSourceKind,
  onSelectSource,
  onSelectSourceKind,
}: {
  sources: ResearchSourceSummary[]
  sourceKinds: string[]
  selectedSourceId: string
  selectedSourceKind: string
  onSelectSource: (sourceId: string) => void
  onSelectSourceKind: (sourceKind: string) => void
}) {
  return (
    <aside className="flex min-h-0 flex-col border-b border-slate-200 bg-slate-950 p-3 text-slate-200 xl:border-b-0 xl:border-r xl:border-slate-800">
      <div className="shrink-0 px-2 py-2">
        <div className="flex items-center gap-2">
          <BookOpenText size={15} className="text-cyan-400" />
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Sources</p>
        </div>
        <select
          className="mt-3 w-full rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-2 text-xs text-slate-300 outline-none focus:border-slate-600"
          value={selectedSourceKind}
          onChange={(event) => onSelectSourceKind(event.target.value)}
        >
          <option value="">All provider types</option>
          {sourceKinds.map((kind) => (
            <option key={kind} value={kind}>{formatSourceKind(kind)}</option>
          ))}
        </select>
      </div>

      <div className="ait-scroll-dark mt-2 max-h-[520px] min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain pr-1 xl:max-h-none">
        <button
          type="button"
          className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
            !selectedSourceId
              ? "border-cyan-500/40 bg-cyan-500/10"
              : "border-transparent hover:border-slate-700 hover:bg-slate-900"
          }`}
          onClick={() => onSelectSource("")}
        >
          <p className="text-xs font-medium text-slate-200">All sources</p>
          <p className="mt-1 text-[10px] text-slate-500">Browse the complete evidence set</p>
        </button>

        {sources
          .filter((source) => !selectedSourceKind || source.source_kind === selectedSourceKind)
          .map((source) => {
            const active = source.source_id === selectedSourceId
            return (
              <button
                key={source.source_id}
                type="button"
                className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
                  active
                    ? "border-cyan-500/40 bg-cyan-500/10"
                    : "border-transparent hover:border-slate-700 hover:bg-slate-900"
                }`}
                onClick={() => onSelectSource(source.source_id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="line-clamp-2 text-xs font-medium leading-5 text-slate-200">{source.display_title}</p>
                  <span className="shrink-0 rounded-full bg-slate-800 px-1.5 py-0.5 text-[9px] uppercase text-slate-400">
                    {formatSourceFamily(source.source_family)}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-500">
                  <span>{source.note_count} evidence</span>
                  <span>·</span>
                  <span>{source.section_count} sections</span>
                  {source.linked_conversation_count > 0 && (
                    <>
                      <span>·</span>
                      <span>{source.linked_conversation_count} chats</span>
                    </>
                  )}
                </div>
              </button>
            )
          })}
      </div>
    </aside>
  )
}

function NoteListPanel({
  notes,
  query,
  selectedNoteId,
  selectedSourceId,
  sectionHeading,
  onQueryChange,
  onSelectNote,
  onOpenSourceOverview,
  onClearSection,
}: {
  notes: ResearchNoteDetail[]
  query: string
  selectedNoteId: string
  selectedSourceId: string
  sectionHeading: string
  onQueryChange: (query: string) => void
  onSelectNote: (noteId: string) => void
  onOpenSourceOverview: () => void
  onClearSection: () => void
}) {
  return (
    <aside className="flex min-h-0 flex-col border-b border-slate-200 bg-slate-50/70 p-3 xl:border-b-0 xl:border-r">
      <div className="shrink-0">
        <label className="relative block">
          <Search size={14} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" />
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search evidence or annotations"
            className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-xs outline-none transition focus:border-slate-400"
          />
        </label>

        {(selectedSourceId || sectionHeading) && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {selectedSourceId && (
              <Button size="xs" variant="ghost" onClick={onOpenSourceOverview}>
                Source overview
              </Button>
            )}
            {sectionHeading && (
              <button
                type="button"
                className="rounded-full bg-cyan-100 px-2.5 py-1 text-[10px] font-medium text-cyan-800"
                onClick={onClearSection}
                title="Clear section filter"
              >
                {sectionHeading} ×
              </button>
            )}
          </div>
        )}
      </div>

      <div className="ait-scroll-panel mt-3 max-h-[500px] min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-1 xl:max-h-none">
        {notes.map((note) => {
          const active = note.note_id === selectedNoteId
          return (
            <button
              key={note.note_id}
              type="button"
              className={`w-full rounded-xl border p-3 text-left transition ${
                active
                  ? "border-cyan-300 bg-cyan-50"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
              onClick={() => onSelectNote(note.note_id)}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="line-clamp-1 text-xs font-semibold text-slate-800">
                  {note.section_heading || note.display_title}
                </p>
                {note.user_note && <span className="h-2 w-2 shrink-0 rounded-full bg-amber-400" title="Has annotation" />}
              </div>
              <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-500">{note.excerpt}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {note.ai_action && <Badge tone="info">{note.ai_action}</Badge>}
                {note.conversation_id && <Badge tone="success">Linked Chat</Badge>}
              </div>
            </button>
          )
        })}
      </div>
    </aside>
  )
}

function ResearchNoteEditor({
  note,
  onDeleted,
  onOpenConversation,
}: {
  note: ResearchNoteDetail
  onDeleted: () => void
  onOpenConversation: () => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [annotation, setAnnotation] = useState(note.user_note)
  const [savedAnnotation, setSavedAnnotation] = useState(note.user_note)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const updateMutation = useMutation({
    mutationFn: () => updateResearchNote(note.note_id, annotation),
    onSuccess: (updated) => {
      setSavedAnnotation(updated.user_note)
      queryClient.setQueryData(queryKeys.research.detail(note.note_id), updated)
      void queryClient.invalidateQueries({ queryKey: ["research"] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteResearchNote(note.note_id),
    onSuccess: (result) => {
      if (result.deleted) {
        void queryClient.invalidateQueries({ queryKey: ["research"] })
        onDeleted()
      }
    },
  })

  const handoffMutation = useMutation({
    mutationFn: () =>
      createCompanionHandoff({
        source_text: note.source_text,
        translated_text: note.translated_text,
        source_language: "auto",
        target_language: "zh-CN",
        resource_url: note.resource_url,
        resource_title: note.resource_title,
        section_heading: note.section_heading,
        context_before: note.context_before,
        context_after: note.context_after,
        source_kind: note.source_kind || "research_note",
        ai_content: note.ai_content,
        ai_action: note.ai_action,
        suggested_prompt: note.user_note,
      }),
    onSuccess: () => navigate("/chat"),
  })

  const dirty = annotation !== savedAnnotation

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-slate-100 px-5 py-4 lg:px-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Evidence note</p>
            <h3 className="mt-1 truncate text-base font-semibold text-slate-900">{note.display_title}</h3>
            {note.section_heading && <p className="mt-1 text-xs text-slate-500">{note.section_heading}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge>{formatSourceKind(note.source_kind)}</Badge>
            {note.conversation_id && <Badge tone="success">Linked Chat</Badge>}
          </div>
        </div>
      </header>

      <div className="ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 lg:px-6">
        <EvidenceBlock title="Selected source" icon={<FileText size={14} />}>
          <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{note.source_text}</p>
        </EvidenceBlock>

        {note.translated_text && (
          <EvidenceBlock title="Translation">
            <p className="whitespace-pre-wrap text-sm leading-6 text-slate-600">{note.translated_text}</p>
          </EvidenceBlock>
        )}

        {note.ai_content && (
          <EvidenceBlock title="AI evidence" badge={note.ai_action || "AI"}>
            <p className="whitespace-pre-wrap text-sm leading-6 text-slate-600">{note.ai_content}</p>
          </EvidenceBlock>
        )}

        {(note.context_before || note.context_after) && (
          <EvidenceBlock title="Nearby reading context">
            {note.context_before && <p className="text-xs leading-5 text-slate-500">Before · {note.context_before}</p>}
            {note.context_after && <p className="mt-2 text-xs leading-5 text-slate-500">After · {note.context_after}</p>}
          </EvidenceBlock>
        )}

        <section className="mt-4 rounded-2xl border border-amber-200 bg-amber-50/40 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold text-slate-800">My annotation</p>
              <p className="mt-1 text-[10px] text-slate-500">Your interpretation is stored separately from captured evidence.</p>
            </div>
            {dirty && <Badge tone="warning">Unsaved</Badge>}
          </div>
          <textarea
            value={annotation}
            onChange={(event) => setAnnotation(event.target.value)}
            placeholder="Write your own interpretation, question, citation reminder or synthesis…"
            className="mt-3 min-h-32 w-full resize-y rounded-xl border border-amber-200 bg-white px-3 py-2.5 text-sm leading-6 outline-none transition focus:border-amber-400"
          />
          <div className="mt-3 flex justify-end">
            <Button
              variant="primary"
              disabled={!dirty || updateMutation.isPending}
              onClick={() => updateMutation.mutate()}
            >
              <Save size={14} />
              {updateMutation.isPending ? "Saving…" : "Save annotation"}
            </Button>
          </div>
          {updateMutation.isError && (
            <p className="mt-2 text-xs text-rose-600">
              {updateMutation.error instanceof Error ? updateMutation.error.message : "Unable to save annotation."}
            </p>
          )}
        </section>

        {note.resource_url && (
          <p className="mt-4 break-all font-mono text-[10px] leading-4 text-slate-400">{note.resource_url}</p>
        )}
      </div>

      <footer className="shrink-0 border-t border-slate-100 p-4 lg:px-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            {note.conversation_id ? (
              <Button onClick={onOpenConversation}>
                <MessageSquareText size={14} />
                Continue conversation
              </Button>
            ) : (
              <Button disabled={handoffMutation.isPending} onClick={() => handoffMutation.mutate()}>
                <ArrowUpRight size={14} />
                Open in AI Chat
              </Button>
            )}
          </div>

          {!confirmDelete ? (
            <Button variant="ghost" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={14} />
              Delete
            </Button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-xs text-rose-600">Delete this evidence note?</span>
              <Button size="xs" onClick={() => setConfirmDelete(false)}>Cancel</Button>
              <Button size="xs" variant="danger" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                Delete
              </Button>
            </div>
          )}
        </div>
      </footer>
    </div>
  )
}

function EvidenceBlock({
  title,
  icon,
  badge,
  children,
}: {
  title: string
  icon?: ReactNode
  badge?: string
  children: ReactNode
}) {
  return (
    <section className="mt-4 rounded-2xl border border-slate-200 bg-slate-50/60 p-4 first:mt-0">
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-700">
        {icon}
        <span>{title}</span>
        {badge && <Badge tone="info">{badge}</Badge>}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function formatSourceKind(value: string): string {
  return value ? value.replaceAll("_", " ") : "unknown"
}

function formatSourceFamily(value: string): string {
  const labels: Record<string, string> = {
    browser: "Web",
    pdf: "PDF",
    word: "Word",
    desktop: "Desktop",
    other: "Other",
  }
  return labels[value] ?? value
}
