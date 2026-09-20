import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowUpRight,
  BookOpen,
  Check,
  CircleAlert,
  CircleGauge,
  Download,
  ExternalLink,
  FileText,
  Filter,
  FolderPlus,
  MoreHorizontal,
  Plus,
  Search,
  Share2,
  Sparkles,
  SquarePen,
  Target,
  X,
} from "lucide-react"
import ReactMarkdown from "react-markdown"
import { useNavigate } from "react-router-dom"

import {
  createResearchProjectWorkspace,
  getResearchWorkspace,
  listResearchProjectWorkspaces,
} from "../../api/research"
import {
  getEvidenceReview,
  synthesizeLiteratureWithAgent,
  updateEvidenceReview,
} from "../../api/evidence-review"
import {
  createWritingProject,
  exportWritingProject,
  listWritingProjects,
} from "../../api/writing"
import type { ResearchSourceSummary } from "../../api/types"
import type { EvidenceReviewStatus, ReviewedEvidenceItem } from "./evidence-review-types"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import "./ResearchDashboard.css"
import ResearchScopePanel from "./ResearchScopePanel"
import KnowledgeResearchBridgePanel from "./KnowledgeResearchBridgePanel"
import WritingDraftPanel from "./WritingDraftPanel"

type BackendState = "checking" | "connected" | "offline"
type EvidenceFilter = "all" | "accepted" | "needs_review" | "unreviewed"
type ResearchPane = "evidence" | "sources"
type AdvancedPanel = "scope" | "writing" | null

const PROJECTS_KEY = ["research", "project-workspaces"] as const

const evidenceTabs: Array<{ id: EvidenceFilter; label: string }> = [
  { id: "all", label: "All sources" },
  { id: "accepted", label: "Accepted" },
  { id: "needs_review", label: "Needs review" },
  { id: "unreviewed", label: "Unreviewed" },
]

export default function ResearchDashboard({
  backendState,
  workspace,
}: {
  backendState: BackendState
  workspace: TranslationWorkspaceController
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const evidenceRef = useRef<HTMLDivElement>(null)
  const draftRef = useRef<HTMLDivElement>(null)
  const advancedRef = useRef<HTMLDivElement>(null)

  const [projectPickerOpen, setProjectPickerOpen] = useState(false)
  const [projectName, setProjectName] = useState("")
  const [projectGoal, setProjectGoal] = useState("")
  const [projectDescription, setProjectDescription] = useState("")
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>("all")
  const [evidenceSearch, setEvidenceSearch] = useState("")
  const [researchPane, setResearchPane] = useState<ResearchPane>("evidence")
  const [sourceSearch, setSourceSearch] = useState("")
  const [synthesisFocus, setSynthesisFocus] = useState("")
  const [synthesisResult, setSynthesisResult] = useState<Awaited<ReturnType<typeof synthesizeLiteratureWithAgent>> | null>(null)
  const [draftTitle, setDraftTitle] = useState("")
  const [draftGoal, setDraftGoal] = useState("")
  const [draftTab, setDraftTab] = useState<"document" | "outline">("document")
  const [advancedPanel, setAdvancedPanel] = useState<AdvancedPanel>(null)
  const [command, setCommand] = useState("")
  const [statusMessage, setStatusMessage] = useState("")

  const projectsQuery = useQuery({
    queryKey: PROJECTS_KEY,
    queryFn: () => listResearchProjectWorkspaces(100),
  })
  const researchQuery = useQuery({
    queryKey: ["research", "workspace", 100],
    queryFn: () => getResearchWorkspace(100),
  })
  const workspaceId = workspace.activeResearchWorkspaceId
  const evidenceQuery = useQuery({
    queryKey: ["research", "dashboard-evidence-review", workspaceId, evidenceSearch],
    queryFn: () => getEvidenceReview(workspaceId, evidenceSearch, 100),
    enabled: Boolean(workspaceId),
  })
  const writingQuery = useQuery({
    queryKey: ["writing", "projects", workspaceId],
    queryFn: () => listWritingProjects(workspaceId),
    enabled: Boolean(workspaceId),
  })

  const projects = projectsQuery.data?.workspaces ?? []
  const activeProject = projects.find((item) => item.workspace_id === workspaceId) ?? null
  const evidenceSnapshot = evidenceQuery.data ?? null
  const writingProject = writingQuery.data?.projects?.[0] ?? null
  const firstSection = writingProject?.sections?.[0] ?? null
  const firstParagraph = firstSection?.paragraphs?.[0] ?? null

  useEffect(() => {
    if (!workspaceId && projects.length > 0) {
      workspace.setActiveResearchWorkspaceId(projects[0].workspace_id)
    }
  }, [projects, workspace, workspaceId])

  const createProjectMutation = useMutation({
    mutationFn: () => createResearchProjectWorkspace({
      name: projectName.trim(),
      research_goal: projectGoal.trim(),
      description: projectDescription.trim(),
    }),
    onSuccess: async (created) => {
      workspace.setActiveResearchWorkspaceId(created.workspace_id)
      workspace.setResearchRetrievalScope({
        knowledgeDocumentIds: created.document_ids,
        researchSourceIds: [],
      })
      setProjectName("")
      setProjectGoal("")
      setProjectDescription("")
      setProjectPickerOpen(false)
      setStatusMessage("Research project created locally.")
      await queryClient.invalidateQueries({ queryKey: PROJECTS_KEY })
    },
  })

  const reviewMutation = useMutation({
    mutationFn: ({ entryId, status }: { entryId: string; status: EvidenceReviewStatus }) =>
      updateEvidenceReview(workspaceId, entryId, status),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["research", "dashboard-evidence-review", workspaceId] }),
        queryClient.invalidateQueries({ queryKey: ["research", "evidence-review", workspaceId] }),
      ])
    },
  })

  const synthesisMutation = useMutation({
    mutationFn: () => synthesizeLiteratureWithAgent(workspaceId, synthesisFocus.trim()),
    onSuccess: (result) => {
      setSynthesisResult(result)
      setStatusMessage("Grounded synthesis generated from the reviewed evidence.")
    },
  })

  const createWritingMutation = useMutation({
    mutationFn: () => createWritingProject({
      workspace_id: workspaceId,
      title: draftTitle.trim(),
      writing_goal: draftGoal.trim(),
    }),
    onSuccess: async () => {
      setDraftTitle("")
      setDraftGoal("")
      setStatusMessage("Writing draft created locally.")
      await queryClient.invalidateQueries({ queryKey: ["writing", "projects", workspaceId] })
    },
  })

  const exportMutation = useMutation({
    mutationFn: () => exportWritingProject(writingProject!.project_id),
    onSuccess: (result) => {
      downloadMarkdown(`${safeName(writingProject?.title ?? "research-draft")}.md`, result.markdown)
      setStatusMessage(exportStatusMessage(result.verification_status, result.warnings))
    },
  })

  const evidenceItems = useMemo(() => {
    const items = evidenceSnapshot?.items ?? []
    if (evidenceFilter === "all") return items
    return items.filter((item) => item.review.status === evidenceFilter)
  }, [evidenceFilter, evidenceSnapshot?.items])

  const sources = researchQuery.data?.sources ?? []
  const sourceCount = activeProject?.document_count ?? sources.length
  const evidenceCount = evidenceSnapshot?.entry_count ?? (activeProject ? 0 : researchQuery.data?.notes.length ?? 0)
  const draftPercent = getDraftProgress(writingProject)
  const wordCount = countWords(firstSection?.markdown ?? "")
  const planSteps = useMemo(() => [
    {
      id: "question",
      title: "Define the research question",
      description: "Clarify scope, key themes, and audience.",
      done: Boolean(activeProject?.research_goal.trim()),
      action: () => setProjectPickerOpen(true),
    },
    {
      id: "sources",
      title: "Find and select sources",
      description: "Search academic papers, reports, and credible web sources.",
      done: sourceCount > 0,
      action: () => {
        setResearchPane("sources")
        scrollTo(evidenceRef)
      },
    },
    {
      id: "evidence",
      title: "Read and extract evidence",
      description: "Summarize key points and capture quotes.",
      done: evidenceCount > 0,
      action: () => scrollTo(evidenceRef),
    },
    {
      id: "synthesis",
      title: "Analyze and synthesize",
      description: "Identify patterns, compare perspectives, and draw insights.",
      done: Boolean(synthesisResult),
      action: () => scrollTo(evidenceRef),
    },
    {
      id: "draft",
      title: "Write the draft",
      description: "Turn insights into a structured document.",
      done: Boolean(writingProject),
      action: () => scrollTo(draftRef),
    },
    {
      id: "review",
      title: "Review and refine",
      description: "Check accuracy, fill gaps, and polish.",
      done: Boolean(writingProject && (firstSection?.version ?? 0) > 1),
      action: () => openAdvanced("writing", advancedRef),
    },
  ], [
    activeProject?.research_goal,
    evidenceCount,
    firstSection?.version,
    sourceCount,
    synthesisResult,
    writingProject,
  ])
  const completedSteps = planSteps.filter((step) => step.done).length
  const currentStep = planSteps.find((step) => !step.done) ?? planSteps[planSteps.length - 1]

  function selectProject(nextId: string) {
    workspace.setActiveResearchWorkspaceId(nextId)
    setSynthesisResult(null)
    setStatusMessage("")
  }

  function openAdvanced(panel: Exclude<AdvancedPanel, null>, ref: React.RefObject<HTMLDivElement | null>) {
    setAdvancedPanel(panel)
    window.setTimeout(() => ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 40)
  }

  function runCommand() {
    const prompt = command.trim()
    if (!prompt) return
    navigate("/agent", {
      state: {
        agentDraftPrompt: prompt,
        agentWorkflowAction: "",
        autoSubmitAgentPrompt: true,
      },
    })
  }

  if (backendState !== "connected") {
    return null
  }

  return (
    <div className="research-dashboard">
      <header className="research-hero">
        <div className="research-hero-top">
          <div className="research-hero-heading">
            <div className="research-title-row">
              <h1 className="research-display research-page-title">Research</h1>
              <span className="research-status-chip"><span />Ready</span>
            </div>
            <div className="research-project-title-row">
              <select
                aria-label="Active research project"
                value={workspaceId}
                onChange={(event) => selectProject(event.target.value)}
                className="research-project-select"
              >
                <option value="">Start a research project</option>
                {projects.map((project) => (
                  <option key={project.workspace_id} value={project.workspace_id}>{project.name}</option>
                ))}
              </select>
              <button type="button" className="research-icon-button" onClick={() => setProjectPickerOpen((value) => !value)} aria-label="Create a research project" title="Create a research project">
                <Plus size={16} />
              </button>
            </div>
            <p className="research-hero-description">
              {activeProject?.research_goal || activeProject?.description || "Turn a question into a structured evidence review and a grounded draft."}
            </p>
          </div>
          <div className="research-hero-side">
            <div className="research-hero-actions">
              <button type="button" className="research-button research-button-secondary" onClick={() => { setResearchPane("sources"); scrollTo(evidenceRef) }}>
                <BookOpen size={15} />
                Open sources
              </button>
              <button type="button" className="research-button research-button-primary" disabled={!writingProject || exportMutation.isPending} onClick={() => exportMutation.mutate()}>
                <Download size={15} />
                {exportMutation.isPending ? "Exporting…" : "Export"}
              </button>
            </div>
            <div className="research-stat-grid">
              <StatCard icon={<FileText size={17} />} label="Sources" value={sourceCount} />
              <StatCard icon={<FileText size={17} />} label="Evidence" value={evidenceCount} />
              <StatCard icon={<CircleGauge size={19} />} label="Draft" value={writingProject ? `${draftPercent}%` : "—"} detail={writingProject ? `${wordCount.toLocaleString()} words` : "Not started"} />
            </div>
          </div>
        </div>
      </header>

      {projectPickerOpen ? (
        <section className="research-project-create" aria-label="Create research project">
          <div className="research-create-icon"><FolderPlus size={17} /></div>
          <div className="research-create-copy">
            <p className="research-eyebrow">New research project</p>
            <h2 className="research-display">Give your investigation a clear direction.</h2>
          </div>
          <div className="research-create-fields">
            <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Project name" maxLength={200} aria-label="Project name" />
            <input value={projectGoal} onChange={(event) => setProjectGoal(event.target.value)} placeholder="Research question or goal" maxLength={8000} aria-label="Research goal" />
            <textarea value={projectDescription} onChange={(event) => setProjectDescription(event.target.value)} placeholder="Optional context" maxLength={4000} rows={2} aria-label="Project description" />
            <div className="research-create-actions">
              <button type="button" className="research-button research-button-quiet" onClick={() => setProjectPickerOpen(false)}>Cancel</button>
              <button type="button" className="research-button research-button-primary" disabled={!projectName.trim() || createProjectMutation.isPending} onClick={() => createProjectMutation.mutate()}>
                <Plus size={14} />
                {createProjectMutation.isPending ? "Creating…" : "Create project"}
              </button>
            </div>
          </div>
          {createProjectMutation.isError ? <p className="research-inline-error">Unable to create the research project.</p> : null}
        </section>
      ) : null}

      <div className="research-main-grid">
        <ResearchPlanCard
          steps={planSteps}
          completedSteps={completedSteps}
          currentStep={currentStep}
          onOpenScope={() => openAdvanced("scope", advancedRef)}
        />

        <div ref={evidenceRef} className="research-column-anchor">
          <EvidenceReviewColumn
            active={Boolean(workspaceId)}
            pane={researchPane}
            snapshot={evidenceSnapshot}
            items={evidenceItems}
            sources={sources}
            filter={evidenceFilter}
            search={evidenceSearch}
            sourceSearch={sourceSearch}
            synthesisFocus={synthesisFocus}
            synthesisResult={synthesisResult}
            isLoading={evidenceQuery.isPending}
            isError={evidenceQuery.isError}
            isReviewing={reviewMutation.isPending}
            isSynthesizing={synthesisMutation.isPending}
            onFilterChange={setEvidenceFilter}
            onSearchChange={setEvidenceSearch}
            onPaneChange={setResearchPane}
            onSourceSearchChange={setSourceSearch}
            onOpenScope={() => openAdvanced("scope", advancedRef)}
            onFocusChange={setSynthesisFocus}
            onReview={(entryId, status) => reviewMutation.mutate({ entryId, status })}
            onSynthesize={() => synthesisMutation.mutate()}
          />
        </div>

        <div ref={draftRef} className="research-right-column">
          <WritingDraftColumn
            active={Boolean(workspaceId)}
            project={writingProject}
            firstSection={firstSection}
            firstParagraph={firstParagraph}
            tab={draftTab}
            title={draftTitle}
            goal={draftGoal}
            progress={draftPercent}
            onTabChange={setDraftTab}
            onTitleChange={setDraftTitle}
            onGoalChange={setDraftGoal}
            onCreate={() => createWritingMutation.mutate()}
            isCreating={createWritingMutation.isPending}
            onOpenFullEditor={() => openAdvanced("writing", advancedRef)}
            onExport={() => exportMutation.mutate()}
          />
          <AgentActivityCard
            evidenceCount={evidenceCount}
            acceptedCount={evidenceSnapshot?.accepted_count ?? 0}
            writingProject={Boolean(writingProject)}
            synthesisReady={Boolean(synthesisResult)}
          />
        </div>
      </div>

      <div className="research-command-bar">
        <Sparkles size={16} />
        <input
          value={command}
          onChange={(event) => setCommand(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") runCommand() }}
          placeholder="Ask a question, request research, or give an instruction…"
          aria-label="Ask Research Agent"
        />
        <button type="button" className="research-command-pill" onClick={runCommand}>Ask AI</button>
        <button type="button" className="research-command-pill research-command-pill-active" onClick={() => scrollTo(evidenceRef)}>Research</button>
        <button type="button" className="research-command-pill" onClick={() => navigate("/knowledge?view=library")}>Knowledge</button>
        <button type="button" className="research-command-send" aria-label="Send research request" onClick={runCommand}><ArrowUpRight size={17} /></button>
      </div>

      {statusMessage ? <p role="status" className="research-status-message">{statusMessage}</p> : null}

      <div ref={advancedRef} className="research-advanced-stack">
        <div className="research-advanced-links" aria-label="More research tools">
          <button type="button" onClick={() => openAdvanced("scope", advancedRef)}><Target size={14} />Project scope</button>
          <button type="button" onClick={() => openAdvanced("writing", advancedRef)}><SquarePen size={14} />Full writing controls</button>
        </div>

        {advancedPanel === "scope" ? (
          <section className="research-advanced-panel">
            <AdvancedHeader title="Project scope & grounded knowledge" onClose={() => setAdvancedPanel(null)} />
            <div className="research-advanced-grid">
              <ResearchScopePanel workspace={workspace} />
              <KnowledgeResearchBridgePanel workspace={workspace} previewLimit={3} />
            </div>
          </section>
        ) : null}
        {advancedPanel === "writing" ? (
          <section className="research-advanced-panel">
            <AdvancedHeader title="Full writing controls" onClose={() => setAdvancedPanel(null)} />
            <WritingDraftPanel workspaceId={workspaceId} />
          </section>
        ) : null}
      </div>
    </div>
  )
}

function ResearchPlanCard({
  steps,
  completedSteps,
  currentStep,
  onOpenScope,
}: {
  steps: Array<{ id: string; title: string; description: string; done: boolean; action: () => void }>
  completedSteps: number
  currentStep: { id: string; title: string; description: string; done: boolean; action: () => void }
  onOpenScope: () => void
}) {
  return (
    <section className="research-card research-plan-card">
      <CardHeading title="Research plan" description="Turn your research question into a structured plan. The agent will search, read, extract evidence, and help you write." />
      <ol className="research-steps">
        {steps.map((step, index) => (
          <li key={step.id} className={`research-step${step.done ? " is-done" : step.id === currentStep.id ? " is-current" : ""}`}>
            <button type="button" className="research-step-button" onClick={step.action}>
              <span className="research-step-marker">{step.done ? <Check size={13} strokeWidth={2.5} /> : index + 1}</span>
              <span className="research-step-copy"><strong>{step.title}</strong><span>{step.description}</span></span>
              {step.done ? <Check size={15} className="research-step-check" /> : null}
            </button>
          </li>
        ))}
      </ol>
      <div className="research-progress-box">
        <div className="research-progress-heading"><span>Overall progress</span><strong>{Math.round((completedSteps / steps.length) * 100)}%</strong></div>
        <p>{completedSteps} of {steps.length} steps completed</p>
        <div className="research-progress-track"><span style={{ width: `${(completedSteps / steps.length) * 100}%` }} /></div>
      </div>
      <div className="research-current-step">
        <div className="research-current-icon"><CircleGauge size={16} /></div>
        <div className="research-current-copy"><p>Current step</p><strong>{currentStep.title}</strong><span>{currentStep.id === "synthesis" ? "Review accepted claims and build a coherent narrative." : currentStep.description}</span></div>
        <button type="button" onClick={currentStep.action} aria-label={`Open ${currentStep.title}`}><ArrowUpRight size={16} /></button>
      </div>
      <button type="button" className="research-plan-scope-link" onClick={onOpenScope}><Target size={13} />Manage project scope</button>
    </section>
  )
}

function EvidenceReviewColumn({
  active,
  pane,
  snapshot,
  items,
  sources,
  filter,
  search,
  sourceSearch,
  synthesisFocus,
  synthesisResult,
  isLoading,
  isError,
  isReviewing,
  isSynthesizing,
  onFilterChange,
  onSearchChange,
  onPaneChange,
  onSourceSearchChange,
  onOpenScope,
  onFocusChange,
  onReview,
  onSynthesize,
}: {
  active: boolean
  pane: ResearchPane
  snapshot: Awaited<ReturnType<typeof getEvidenceReview>> | null
  items: ReviewedEvidenceItem[]
  sources: ResearchSourceSummary[]
  filter: EvidenceFilter
  search: string
  sourceSearch: string
  synthesisFocus: string
  synthesisResult: Awaited<ReturnType<typeof synthesizeLiteratureWithAgent>> | null
  isLoading: boolean
  isError: boolean
  isReviewing: boolean
  isSynthesizing: boolean
  onFilterChange: (filter: EvidenceFilter) => void
  onSearchChange: (search: string) => void
  onPaneChange: (pane: ResearchPane) => void
  onSourceSearchChange: (search: string) => void
  onOpenScope: () => void
  onFocusChange: (focus: string) => void
  onReview: (entryId: string, status: EvidenceReviewStatus) => void
  onSynthesize: () => void
}) {
  const showingSources = pane === "sources"

  return (
    <section className="research-card research-evidence-card">
      <CardHeading
        title={showingSources ? "Sources" : "Evidence review"}
        description={showingSources ? "Browse the source context that feeds this research workspace." : "Sources, key evidence, and AI summaries. Select and organize the most relevant content."}
      />
      {showingSources ? (
        <>
          <div className="research-source-toolbar">
            <button type="button" className="research-source-back" onClick={() => onPaneChange("evidence")}><BookOpen size={14} />Evidence review</button>
            <label className="research-search-box"><Search size={14} /><input value={sourceSearch} onChange={(event) => onSourceSearchChange(event.target.value)} placeholder="Search sources…" aria-label="Search sources" /></label>
          </div>
          <SourceInventory sources={sources} query={sourceSearch} onOpenScope={onOpenScope} />
        </>
      ) : (
        <>
      <div className="research-evidence-toolbar">
        <div className="research-tabs" role="tablist" aria-label="Evidence filters">
          {evidenceTabs.map((tab) => {
            const count = tab.id === "all" ? snapshot?.entry_count : snapshot?.[`${tab.id}_count` as "accepted_count" | "needs_review_count" | "unreviewed_count"]
            return <button key={tab.id} type="button" role="tab" aria-selected={filter === tab.id} className={filter === tab.id ? "is-active" : ""} onClick={() => onFilterChange(tab.id)}>{tab.label}{typeof count === "number" ? ` (${count})` : ""}</button>
          })}
        </div>
        <div className="research-evidence-search-row">
          <label className="research-search-box"><Search size={14} /><input value={search} onChange={(event) => onSearchChange(event.target.value)} placeholder="Search evidence…" aria-label="Search evidence" /></label>
          <button type="button" className="research-filter-button" aria-label="Evidence filter" title="Evidence filters"><Filter size={15} /></button>
        </div>
      </div>

      {!active ? <EmptyPanel icon={<Target size={17} />} title="Select a Research Project" description="A project keeps evidence review and writing drafts connected." /> : null}
      {active && isLoading ? <LoadingPanel label="Loading evidence…" /> : null}
      {active && isError ? <EmptyPanel icon={<CircleAlert size={17} />} title="Unable to load evidence" description="The Evidence Ledger could not be read. Try again in a moment." tone="error" /> : null}
      {active && !isLoading && !isError && items.length === 0 ? <EvidenceEmptyState sources={sources} onOpenSources={() => onPaneChange("sources")} /> : null}

      <div className="research-evidence-list">
        {items.map((item) => <EvidenceItem key={item.ledger.entry.entry_id} item={item} isReviewing={isReviewing} onReview={onReview} />)}
      </div>

      {active ? (
        <section className="research-synthesis-card">
          <div className="research-synthesis-heading"><div className="research-synthesis-icon"><Share2 size={17} /></div><div><h3>{synthesisResult ? "Synthesis ready" : "Synthesis in progress"}</h3><p>{synthesisResult ? "The latest synthesis is grounded in the reviewed evidence." : "AI is analyzing evidence, identifying themes, and building a coherent narrative."}</p></div></div>
          <div className="research-synthesis-steps"><SynthesisStep label="Extract key themes" done={Boolean(evidenceCountFor(snapshot))} /><SynthesisStep label="Find connections" done={Boolean(snapshot?.accepted_count)} /><SynthesisStep label="Build synthesis" done={Boolean(synthesisResult)} /><SynthesisStep label="Generate insights" done={Boolean(synthesisResult?.verification?.passed)} /></div>
          <div className="research-synthesis-controls"><input value={synthesisFocus} onChange={(event) => onFocusChange(event.target.value)} placeholder="Optional synthesis focus" aria-label="Synthesis focus" /><button type="button" className="research-button research-button-primary" onClick={onSynthesize} disabled={isSynthesizing || !snapshot?.entry_count}><Sparkles size={14} />{isSynthesizing ? "Generating…" : "Generate synthesis"}</button></div>
          {synthesisResult ? <div className="research-synthesis-result"><div className="research-chip-row"><StatusChip tone="success">{synthesisResult.status.replaceAll("_", " ")}</StatusChip><StatusChip>{synthesisResult.included_count} included</StatusChip><StatusChip>{synthesisResult.evidence_count} evidence</StatusChip></div><ReactMarkdown>{synthesisResult.output_text}</ReactMarkdown></div> : null}
        </section>
      ) : null}
        </>
      )}
    </section>
  )
}

function SourceInventory({
  sources,
  query,
  onOpenScope,
}: {
  sources: ResearchSourceSummary[]
  query: string
  onOpenScope: () => void
}) {
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visibleSources = sources.filter((source) => !normalizedQuery || [source.display_title, source.source_kind, source.resource_url].join(" ").toLocaleLowerCase().includes(normalizedQuery))

  return (
    <div className="research-source-inventory">
      {visibleSources.length === 0 ? <EmptyPanel icon={<BookOpen size={17} />} title={sources.length ? "No sources match this search" : "No saved sources yet"} description={sources.length ? "Try a title, provider type, or source URL." : "Capture a passage in Reading to make it available to this research workspace."} /> : null}
      {visibleSources.map((source) => (
        <article key={source.source_id} className="research-source-item">
          <div className="research-source-item-heading">
            <span className="research-source-icon"><FileText size={16} /></span>
            <div><h3>{source.display_title || "Untitled source"}</h3><p>{formatSourceFamily(source.source_family)} · {source.source_kind || "research source"}</p></div>
            {source.resource_url ? <a href={source.resource_url} target="_blank" rel="noreferrer" className="research-source-open">Open <ArrowUpRight size={13} /></a> : null}
          </div>
          <div className="research-source-metrics"><span>{source.note_count} evidence</span><span>{source.section_count} sections</span><span>{source.annotation_count} annotations</span><span>{source.linked_conversation_count} chats</span></div>
        </article>
      ))}
      <button type="button" className="research-source-scope" onClick={onOpenScope}><Target size={14} />Manage project scope</button>
    </div>
  )
}

function EvidenceEmptyState({
  sources,
  onOpenSources,
}: {
  sources: ResearchSourceSummary[]
  onOpenSources: () => void
}) {
  const source = sources[0] ?? null
  return (
    <div className="research-evidence-empty-state">
      <EmptyPanel icon={<FileText size={17} />} title="No evidence matches this view" description="Capture evidence from Reading or adjust the search and review filter." />
      {source ? (
        <button type="button" className="research-evidence-source-prompt" onClick={onOpenSources}>
          <span className="research-source-icon"><FileText size={15} /></span>
          <span><strong>{source.display_title || "Saved source"}</strong><small>{source.note_count} saved evidence · {formatSourceFamily(source.source_family)}</small></span>
          <span className="research-evidence-source-action">Browse sources <ArrowUpRight size={13} /></span>
        </button>
      ) : null}
    </div>
  )
}

function EvidenceItem({
  item,
  isReviewing,
  onReview,
}: {
  item: ReviewedEvidenceItem
  isReviewing: boolean
  onReview: (entryId: string, status: EvidenceReviewStatus) => void
}) {
  const entry = item.ledger.entry
  const machine = item.ledger.validation.status
  const confidenceTone = machine === "supported" ? "success" : machine === "contested" ? "warning" : "muted"
  return (
    <article className="research-evidence-item">
      <div className="research-evidence-item-heading"><div className="research-evidence-icon"><FileText size={16} /></div><div className="research-evidence-item-copy"><h3>{entry.statement}</h3><p>{entry.links.length} provenance link{entry.links.length === 1 ? "" : "s"} · Evidence Ledger</p></div><StatusChip tone={confidenceTone}>{machine === "supported" ? "High confidence" : machine.replaceAll("_", " ")}</StatusChip><button type="button" className="research-more-button" aria-label="Evidence actions"><MoreHorizontal size={17} /></button></div>
      <blockquote>“{entry.statement}”<span>{entry.links.length ? ` ${entry.links.length} linked source${entry.links.length === 1 ? "" : "s"}` : "No linked source"}</span></blockquote>
      <div className="research-evidence-item-footer"><span>{formatReviewStatus(item.review.status)}</span><span>·</span><span>{item.review.reviewed_at ? formatDate(item.review.reviewed_at) : "Not reviewed"}</span><select aria-label={`Review status for ${entry.statement}`} value={item.review.status} disabled={isReviewing} onChange={(event) => onReview(entry.entry_id, event.target.value as EvidenceReviewStatus)}><option value="unreviewed">Unreviewed</option><option value="accepted">Accepted</option><option value="needs_review">Needs review</option><option value="rejected">Rejected</option></select></div>
    </article>
  )
}

function WritingDraftColumn({
  active,
  project,
  firstSection,
  firstParagraph,
  tab,
  title,
  goal,
  progress,
  onTabChange,
  onTitleChange,
  onGoalChange,
  onCreate,
  isCreating,
  onOpenFullEditor,
  onExport,
}: {
  active: boolean
  project: Awaited<ReturnType<typeof listWritingProjects>>["projects"][number] | null
  firstSection: Awaited<ReturnType<typeof listWritingProjects>>["projects"][number]["sections"][number] | null
  firstParagraph: Awaited<ReturnType<typeof listWritingProjects>>["projects"][number]["sections"][number]["paragraphs"][number] | null
  tab: "document" | "outline"
  title: string
  goal: string
  progress: number
  onTabChange: (tab: "document" | "outline") => void
  onTitleChange: (value: string) => void
  onGoalChange: (value: string) => void
  onCreate: () => void
  isCreating: boolean
  onOpenFullEditor: () => void
  onExport: () => void
}) {
  return (
    <section className="research-card research-draft-card">
      <CardHeading title="Writing draft" description="Turn your research into a well-structured document. You can edit, refine, or ask for changes." />
      <div className="research-draft-toolbar"><div className="research-tabs"><button type="button" className={tab === "document" ? "is-active" : ""} onClick={() => onTabChange("document")}>Document</button><button type="button" className={tab === "outline" ? "is-active" : ""} onClick={() => onTabChange("outline")}>Outline</button></div><button type="button" className="research-full-view-button" onClick={onOpenFullEditor}><ExternalLink size={13} />Full view</button></div>
      {!active ? <EmptyPanel icon={<SquarePen size={17} />} title="Choose a project first" description="Your draft will stay attached to the active Research Project." /> : null}
      {active && !project ? <div className="research-draft-create"><div className="research-draft-create-icon"><SquarePen size={18} /></div><h3>Start a local draft</h3><p>Create a versioned writing project to turn reviewed evidence into a manuscript.</p><input value={title} onChange={(event) => onTitleChange(event.target.value)} placeholder="Draft title" aria-label="Draft title" /><textarea value={goal} onChange={(event) => onGoalChange(event.target.value)} placeholder="What should this draft explain?" rows={3} aria-label="Draft goal" /><button type="button" className="research-button research-button-primary" disabled={!title.trim() || isCreating} onClick={onCreate}><Plus size={14} />{isCreating ? "Creating…" : "Create draft"}</button></div> : null}
      {active && project ? <>
        <div className="research-document-sheet">
          <div className="research-document-meta"><span><FileText size={13} />{project.title}</span><span>v{firstSection?.version ?? (project.outline_version || 1)}</span></div>
          {tab === "document" ? <div className="research-document-content"><h3 className="research-display">{project.title}</h3><p className="research-document-subtitle">{project.writing_goal || "A grounded research draft"}</p>{firstSection ? <><h4>{firstSection.title || "Research findings"}</h4><ReactMarkdown>{firstSection.markdown}</ReactMarkdown></> : <p className="research-document-empty">Attach an outline or manuscript section from Academic Writer to preview it here.</p>}</div> : <div className="research-outline-list">{project.sections.length ? project.sections.map((section) => <button type="button" key={section.section_id} onClick={onOpenFullEditor}><span>{section.title || section.section_id}</span><small>v{section.version} · {section.paragraphs.length} paragraphs</small></button>) : <p className="research-document-empty">No sections attached yet.</p>}</div>}
          <div className="research-document-footer"><span>Page 1 of {Math.max(1, project.sections.length)}</span><span>{countWords(firstParagraph?.markdown ?? firstSection?.markdown ?? "").toLocaleString()} words</span></div>
        </div>
        <div className="research-draft-actions"><span><CircleGauge size={14} />{progress}% drafted</span><button type="button" className="research-button research-button-secondary" onClick={onOpenFullEditor}><SquarePen size={14} />Edit draft</button><button type="button" className="research-button research-button-quiet" onClick={onExport}>Export</button></div>
      </> : null}
    </section>
  )
}

function AgentActivityCard({
  evidenceCount,
  acceptedCount,
  writingProject,
  synthesisReady,
}: {
  evidenceCount: number
  acceptedCount: number
  writingProject: boolean
  synthesisReady: boolean
}) {
  const activities = [
    { title: evidenceCount ? `Evidence set ready (${evidenceCount})` : "Waiting for evidence", detail: evidenceCount ? "Captured claims are available for review." : "Capture a passage from Reading to begin.", time: evidenceCount ? "Now" : "Next" },
    { title: acceptedCount ? `Reviewed ${acceptedCount} claim${acceptedCount === 1 ? "" : "s"}` : "Review the evidence", detail: acceptedCount ? "Accepted claims can enter synthesis." : "Choose Accepted or Needs review on a claim.", time: acceptedCount ? "This session" : "Next" },
    { title: synthesisReady ? "Synthesis generated" : writingProject ? "Draft is ready to refine" : "Writing draft not started", detail: synthesisReady ? "Grounded output is available above." : writingProject ? "Open the draft to review its sections." : "Create a versioned draft when the evidence is ready.", time: synthesisReady ? "Now" : "Later" },
  ]
  return <section className="research-card research-activity-card"><div className="research-activity-header"><div><h2 className="research-display">Agent activity</h2><p>Live updates from your research workspace.</p></div><span className="research-live-chip"><span />Live</span></div><ol className="research-activity-list">{activities.map((activity) => <li key={activity.title}><span className="research-activity-dot" /><div><div className="research-activity-title"><strong>{activity.title}</strong><time>{activity.time}</time></div><p>{activity.detail}</p></div></li>)}</ol></section>
}

function CardHeading({ title, description }: { title: string; description: string }) {
  return <header className="research-card-heading"><div><h2 className="research-display">{title}</h2><p>{description}</p></div><button type="button" className="research-more-button" aria-label={`${title} actions`}><MoreHorizontal size={17} /></button></header>
}

function StatCard({ icon, label, value, detail }: { icon: ReactNode; label: string; value: number | string; detail?: string }) {
  return <div className="research-stat-card"><span className="research-stat-icon">{icon}</span><div><span className="research-stat-label">{label}</span><strong>{value}</strong>{detail ? <small>{detail}</small> : null}</div></div>
}

function StatusChip({ children, tone = "muted" }: { children: ReactNode; tone?: "success" | "warning" | "muted" }) {
  return <span className={`research-status-chip research-status-chip-${tone}`}><span />{children}</span>
}

function SynthesisStep({ label, done }: { label: string; done: boolean }) {
  return <div className={`research-synthesis-step${done ? " is-done" : ""}`}><span>{done ? <Check size={11} /> : ""}</span><small>{label}</small></div>
}

function EmptyPanel({ icon, title, description, tone = "muted" }: { icon: ReactNode; title: string; description: string; tone?: "muted" | "error" }) {
  return <div className={`research-empty-panel${tone === "error" ? " is-error" : ""}`}><span>{icon}</span><div><strong>{title}</strong><p>{description}</p></div></div>
}

function LoadingPanel({ label }: { label: string }) {
  return <div className="research-loading-panel"><span className="research-loading-dot" />{label}</div>
}

function AdvancedHeader({ title, onClose }: { title: string; onClose: () => void }) {
  return <header className="research-advanced-header"><div><p className="research-eyebrow">Research workspace</p><h2 className="research-display">{title}</h2></div><button type="button" className="research-icon-button" onClick={onClose} aria-label="Close panel"><X size={16} /></button></header>
}

function evidenceCountFor(snapshot: Awaited<ReturnType<typeof getEvidenceReview>> | null): number {
  return snapshot?.entry_count ?? 0
}

function scrollTo(ref: React.RefObject<HTMLDivElement | null>) {
  ref.current?.scrollIntoView({ behavior: "smooth", block: "start" })
}

function formatReviewStatus(status: EvidenceReviewStatus): string {
  return status === "needs_review" ? "Needs review" : status.charAt(0).toUpperCase() + status.slice(1)
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "Recently"
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date)
}

function formatSourceFamily(value: ResearchSourceSummary["source_family"]): string {
  const labels: Record<ResearchSourceSummary["source_family"], string> = {
    browser: "Web",
    pdf: "PDF",
    word: "Word",
    desktop: "Desktop",
    other: "Other",
  }
  return labels[value] ?? value
}

function getDraftProgress(project: Awaited<ReturnType<typeof listWritingProjects>>["projects"][number] | null): number {
  if (!project) return 0
  const sectionProgress = Math.min(55, project.sections.length * 18)
  return Math.min(100, 17 + (project.outline_ref ? 28 : 0) + sectionProgress)
}

function countWords(value: string): number {
  return value.trim() ? value.trim().split(/\s+/u).length : 0
}

function safeName(value: string): string {
  return value.replace(/[<>:"/\\|?*]+/g, "-").trim() || "research-draft"
}

function exportStatusMessage(status: string, warnings: string[]): string {
  return status === "requires_revalidation"
    ? `Exported with ${warnings.length} source warning${warnings.length === 1 ? "" : "s"}. Revalidate before reuse.`
    : status === "current"
      ? "Exported with current source verification."
      : "Exported; review source verification before reuse."
}

function downloadMarkdown(filename: string, markdown: string): void {
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }))
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
