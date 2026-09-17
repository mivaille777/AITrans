import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Clipboard, Download, FilePenLine, Plus, Save, X } from "lucide-react"

import { ApiError } from "../../api/client"
import {
  applyWritingRevision,
  createWritingProject,
  exportWritingProject,
  listWritingProjects,
  previewWritingRevision,
  saveWritingArtifact,
  type WritingRevisionPreview,
} from "../../api/writing"
import { Button } from "../../shared/ui/Button"

export default function WritingDraftPanel({ workspaceId }: { workspaceId: string }) {
  const queryClient = useQueryClient()
  const [projectId, setProjectId] = useState("")
  const [title, setTitle] = useState("")
  const [goal, setGoal] = useState("")
  const [artifactKind, setArtifactKind] = useState<"outline" | "sections">("sections")
  const [artifactId, setArtifactId] = useState("")
  const [artifactVersion, setArtifactVersion] = useState(1)
  const [expectedArtifactVersion, setExpectedArtifactVersion] = useState(0)
  const [sectionId, setSectionId] = useState("")
  const [paragraphId, setParagraphId] = useState("")
  const [replacement, setReplacement] = useState<string | null>(null)
  const [preview, setPreview] = useState<WritingRevisionPreview | null>(null)
  const [operationId, setOperationId] = useState("")
  const [message, setMessage] = useState("")

  const projectsQuery = useQuery({
    queryKey: ["writing", "projects", workspaceId],
    queryFn: () => listWritingProjects(workspaceId),
    enabled: Boolean(workspaceId),
  })
  const projects = projectsQuery.data?.projects ?? []
  const project = projects.find((item) => item.project_id === projectId) ?? projects[0] ?? null
  const section = project?.sections.find((item) => item.section_id === sectionId) ?? project?.sections[0] ?? null
  const paragraph = section?.paragraphs.find((item) => item.paragraph_id === paragraphId) ?? section?.paragraphs[0] ?? null
  const revisionText = replacement ?? paragraph?.markdown ?? ""

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["writing", "projects", workspaceId] })
  }
  const createMutation = useMutation({
    mutationFn: () => createWritingProject({ workspace_id: workspaceId, title: title.trim(), writing_goal: goal.trim() }),
    onSuccess: async (created) => {
      setProjectId(created.project_id)
      setTitle("")
      setGoal("")
      setMessage("Writing project created locally.")
      await refresh()
    },
  })
  const attachMutation = useMutation({
    mutationFn: () => saveWritingArtifact(project!.project_id, artifactKind, {
      artifact_id: artifactId.trim(),
      artifact_version: artifactVersion,
      expected_version: artifactKind === "outline" ? project!.outline_version : expectedArtifactVersion,
    }),
    onSuccess: async () => {
      setArtifactId("")
      setMessage("Agent draft attached. It remains a local writing-project version.")
      await refresh()
    },
  })
  const previewMutation = useMutation({
    mutationFn: () => previewWritingRevision(project!.project_id, section!.section_id, {
      expected_version: section!.version,
      changes: [{
        paragraph_id: paragraph!.paragraph_id,
        replacement_markdown: revisionText,
        rationale: "User-reviewed local revision",
        evidence_ids: paragraph!.evidence_ids,
        category: paragraph!.evidence_ids.length ? "fact" : "suggestion",
      }],
    }),
    onSuccess: (draft) => {
      setPreview(draft)
      setOperationId(newOperationId())
      setMessage("Revision draft generated. It has not been applied.")
    },
  })
  const applyMutation = useMutation({
    mutationFn: () => applyWritingRevision(project!.project_id, {
      artifact_id: preview!.revision_ref.artifact_id,
      artifact_version: preview!.revision_ref.version,
      expected_version: preview!.base_version,
      operation_id: operationId,
    }),
    onSuccess: async (receipt) => {
      setPreview(null)
      setMessage(`Revision applied as version ${receipt.result_version}.`)
      await refresh()
    },
    onError: (error) => {
      setMessage(error instanceof ApiError && error.status === 409
        ? "Version conflict: reload the latest section before applying."
        : error instanceof Error ? error.message : "Unable to apply revision.")
    },
  })
  const exportMutation = useMutation({
    mutationFn: () => exportWritingProject(project!.project_id),
    onSuccess: (result) => downloadMarkdown(`${safeName(project!.title)}.md`, result.markdown),
  })
  const copyMutation = useMutation({
    mutationFn: async () => {
      const result = await exportWritingProject(project!.project_id)
      await navigator.clipboard.writeText(result.markdown)
    },
    onSuccess: () => setMessage("Markdown copied."),
  })

  const diff = useMemo(() => preview ? preview.before.map((before, index) => ({ before, after: preview.after[index] })) : [], [preview])

  if (!workspaceId) {
    return <section className="ait-surface px-5 py-4 text-xs text-slate-500">Select a Research Project to start a versioned writing draft.</section>
  }

  return (
    <section className="ait-surface overflow-hidden">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200/70 px-5 py-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-slate-400">Academic Writer</p>
          <h2 className="mt-1 text-sm font-semibold text-slate-900">Versioned outline and section drafts</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">Drafts stay local and are never written back to an original paper. Revisions require an explicit preview and apply action.</p>
        </div>
        {project ? <div className="flex gap-2"><Button onClick={() => copyMutation.mutate()}><Clipboard size={13} />Copy</Button><Button onClick={() => exportMutation.mutate()}><Download size={13} />Export</Button></div> : null}
      </header>

      <div className="grid gap-4 p-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="space-y-3">
          <label className="block text-xs font-medium text-slate-600">Writing project
            <select aria-label="Writing project" value={project?.project_id ?? ""} onChange={(event) => { setProjectId(event.target.value); setPreview(null) }} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
              {projects.length === 0 ? <option value="">No writing projects</option> : null}
              {projects.map((item) => <option key={item.project_id} value={item.project_id}>{item.title}</option>)}
            </select>
          </label>
          <input aria-label="New project title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="New manuscript title" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs" />
          <textarea aria-label="Writing goal" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="Writing goal" className="min-h-20 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs" />
          <Button disabled={!title.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}><Plus size={13} />Create project</Button>

          {project ? <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <p className="text-[11px] font-semibold text-slate-700">Attach an Agent artifact</p>
            <select aria-label="Artifact kind" value={artifactKind} onChange={(event) => setArtifactKind(event.target.value as "outline" | "sections")} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"><option value="outline">Outline</option><option value="sections">Section</option></select>
            <input aria-label="Artifact ID" value={artifactId} onChange={(event) => setArtifactId(event.target.value)} placeholder="Artifact ID" className="mt-2 w-full rounded-lg border border-slate-200 px-2 py-2 text-xs" />
            <input aria-label="Artifact version" type="number" min={1} value={artifactVersion} onChange={(event) => setArtifactVersion(Number(event.target.value))} className="mt-2 w-full rounded-lg border border-slate-200 px-2 py-2 text-xs" />
            {artifactKind === "sections" ? <input aria-label="Expected section version" type="number" min={0} value={expectedArtifactVersion} onChange={(event) => setExpectedArtifactVersion(Number(event.target.value))} className="mt-2 w-full rounded-lg border border-slate-200 px-2 py-2 text-xs" title="Use 0 for a new section" /> : null}
            <Button className="mt-2" disabled={!artifactId.trim() || attachMutation.isPending} onClick={() => attachMutation.mutate()}><Save size={13} />Attach draft</Button>
            <p className="mt-2 text-[10px] text-slate-400">Outline v{project.outline_version} · {project.sections.length} sections</p>
          </div> : null}
        </aside>

        <main className="min-w-0">
          {!section ? <div className="rounded-xl border border-dashed border-slate-200 p-6 text-xs text-slate-500">Create a writing project, then attach an Outline or Manuscript Section artifact produced by Academic Writer.</div> : <>
            <div className="flex flex-wrap gap-2">
              {project!.sections.map((item) => <button key={item.section_id} type="button" onClick={() => { setSectionId(item.section_id); setParagraphId(""); setReplacement(null); setPreview(null) }} className={`rounded-full border px-3 py-1 text-[11px] ${item.section_id === section.section_id ? "border-cyan-300 bg-cyan-50 text-cyan-800" : "border-slate-200 text-slate-500"}`}>{item.title || item.section_id} · v{item.version}</button>)}
            </div>
            <label className="mt-4 block text-xs font-medium text-slate-600">Paragraph to revise
              <select aria-label="Paragraph to revise" value={paragraph?.paragraph_id ?? ""} onChange={(event) => { setParagraphId(event.target.value); setReplacement(null); setPreview(null) }} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">{section.paragraphs.map((item) => <option key={item.paragraph_id} value={item.paragraph_id}>{item.paragraph_id}</option>)}</select>
            </label>
            <textarea aria-label="Revision text" value={revisionText} onChange={(event) => { setReplacement(event.target.value); setPreview(null) }} className="mt-3 min-h-32 w-full rounded-xl border border-slate-200 p-3 text-sm leading-6" />
            <div className="mt-2 flex flex-wrap items-center gap-1 text-[10px] text-slate-500" aria-label="Paragraph evidence">
              <span>已保存 v{section.version} · 段落来源：</span>
              {paragraph?.evidence_ids.length
                ? paragraph.evidence_ids.map((id) => <a key={id} href={`#evidence-${encodeURIComponent(id)}`} className="rounded bg-cyan-50 px-1.5 py-0.5 text-cyan-800">{id}</a>)
                : <span className="text-amber-700">无来源，应用前需复核</span>}
            </div>
            <Button disabled={!paragraph || revisionText === paragraph.markdown || previewMutation.isPending} onClick={() => previewMutation.mutate()}><FilePenLine size={13} />Preview revision</Button>

            {preview ? <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/50 p-4" aria-label="Revision diff">
              <p className="text-xs font-semibold text-amber-900">Pending draft — not applied</p>
              {diff.map((item) => <div key={item.before.paragraph_id} className="mt-3 grid gap-3 md:grid-cols-2"><div><p className="text-[10px] font-semibold uppercase text-rose-600">Before</p><pre className="mt-1 whitespace-pre-wrap rounded-lg bg-white p-3 font-sans text-xs text-slate-600">{item.before.markdown}</pre></div><div><p className="text-[10px] font-semibold uppercase text-emerald-700">After</p><pre className="mt-1 whitespace-pre-wrap rounded-lg bg-white p-3 font-sans text-xs text-slate-600">{item.after.markdown}</pre></div></div>)}
              <div className="mt-3 flex gap-2"><Button onClick={() => applyMutation.mutate()} disabled={applyMutation.isPending}><Save size={13} />Apply revision</Button><Button variant="ghost" onClick={() => { setPreview(null); setMessage("Revision cancelled. The stored section is unchanged.") }}><X size={13} />Cancel draft</Button></div>
            </div> : null}
          </>}
          {message ? <p role="status" className="mt-3 text-xs text-slate-600">{message}</p> : null}
          {(projectsQuery.isError || createMutation.isError || attachMutation.isError || previewMutation.isError || exportMutation.isError || copyMutation.isError) ? <p className="mt-3 text-xs text-rose-600">Unable to complete the writing action.</p> : null}
        </main>
      </div>
    </section>
  )
}

function newOperationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `writing-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function safeName(value: string): string {
  return value.replace(/[<>:"/\\|?*]+/g, "-").trim() || "manuscript"
}

function downloadMarkdown(filename: string, markdown: string): void {
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }))
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
