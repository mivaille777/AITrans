import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Copy,
  Database,
  Download,
  FilePlus2,
  FileText,
  HelpCircle,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  SlidersHorizontal,
  Target,
  Trash2,
  Upload,
  X,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"

import { desktop } from "../../desktop"
import { addKnowledgeDocument, deleteKnowledgeDocument, listKnowledgeDocuments, reindexKnowledgeDocument } from "../../api/knowledge"
import type { KnowledgeDocument } from "../knowledge/knowledge-types"

import {
  activateRagDebugConfig,
  cancelRagDebugRun,
  compareRagDebugDataset,
  createRagDebugConfig,
  createRagDebugDataset,
  deleteRagDebugCase,
  deleteRagDebugDataset,
  evaluateRagDebugDataset,
  exportRagDebugDataset,
  getRagDebugRun,
  importRagDebugDataset,
  listRagDebugCases,
  listRagDebugChunks,
  listRagDebugCompanionTraces,
  listRagDebugConfigs,
  listRagDebugDatasets,
  getQasperDebugCase,
  listQasperDebugCases,
  listQasperDebugChunks,
  listQasperDebugRuns,
  startQasperDebugRun,
  type RagConfig,
  type RagDebugCase,
  type RagDebugCandidate,
  type RagDebugChunk,
  type RagDebugCompanionTrace,
  type RagDebugCompareResponse,
  type RagDebugConfigProfile,
  type RagDebugDataset,
  type RagDebugEvaluationResponse,
  type RagDebugStage,
  type RagDebugTraceResponse,
  type QasperDebugCase,
  type QasperDebugCaseIndex,
  type QasperDebugChunk,
  type QasperDebugRunSummary,
  saveRagDebugCase,
  startRagDebugRun,
  updateRagDebugCase,
  updateRagDebugConfig,
} from "../../api/rag-debug"

type RagTab = "trace" | "retrieval" | "chunks" | "evaluation" | "compare" | "datasets"

const TABS: Array<{ id: RagTab; label: string }> = [
  { id: "trace", label: "Trace" },
  { id: "retrieval", label: "Retrieval" },
  { id: "chunks", label: "Chunks" },
  { id: "evaluation", label: "Evaluation" },
  { id: "compare", label: "Compare" },
  { id: "datasets", label: "Datasets" },
]

const INITIAL_STAGES: RagDebugStage[] = [
  { key: "query", label: "Query", status: "pending", elapsed_ms: 0, note: "Parse query and intent", summary: {}, candidate_count: 0 },
  { key: "rewrite", label: "Rewrite", status: "pending", elapsed_ms: 0, note: "Generate standalone retrieval queries", summary: {}, candidate_count: 0 },
  { key: "dense", label: "Dense Retrieval", status: "pending", elapsed_ms: 0, note: "Vector search from the active index", summary: {}, candidate_count: 0 },
  { key: "bm25", label: "BM25 Retrieval", status: "pending", elapsed_ms: 0, note: "Sparse lexical search from the active index", summary: {}, candidate_count: 0 },
  { key: "structural", label: "Structural Retrieval", status: "pending", elapsed_ms: 0, note: "Section-aware retrieval from the active index", summary: {}, candidate_count: 0 },
  { key: "fusion", label: "Fusion", status: "pending", elapsed_ms: 0, note: "Merge retrieval lists with the configured strategy", summary: {}, candidate_count: 0 },
  { key: "rerank", label: "Rerank", status: "pending", elapsed_ms: 0, note: "Apply the configured reranker when available", summary: {}, candidate_count: 0 },
  { key: "final", label: "Final Results", status: "pending", elapsed_ms: 0, note: "Final ranked evidence candidates", summary: {}, candidate_count: 0 },
  { key: "context", label: "Context Building", status: "pending", elapsed_ms: 0, note: "Build bounded grounded context", summary: {}, candidate_count: 0 },
  { key: "answer", label: "Answer Generation", status: "pending", elapsed_ms: 0, note: "Optional answer generation from context", summary: {}, candidate_count: 0 },
]

export default function RagDebugStudioTrace() {
  const [activeTab, setActiveTab] = useState<RagTab>("trace")
  const [visitedTabs, setVisitedTabs] = useState<Set<RagTab>>(() => new Set(["trace"]))
  const [configs, setConfigs] = useState<RagDebugConfigProfile[]>([])
  const [datasets, setDatasets] = useState<RagDebugDataset[]>([])
  const [latestTrace, setLatestTrace] = useState<RagDebugTraceResponse | null>(null)
  const [qasperRuns, setQasperRuns] = useState<QasperDebugRunSummary[]>([])
  const [selectedQasperRun, setSelectedQasperRun] = useState<QasperDebugRunSummary | null>(null)
  const [baseError, setBaseError] = useState("")
  const selectedQasperRunRef = useRef<QasperDebugRunSummary | null>(null)

  async function refreshBaseData() {
    const [configResult, datasetResult] = await Promise.allSettled([listRagDebugConfigs(), listRagDebugDatasets()])
    if (configResult.status === "fulfilled") setConfigs(configResult.value)
    if (datasetResult.status === "fulfilled") setDatasets(datasetResult.value)
    const error = [configResult, datasetResult]
      .filter((item): item is PromiseRejectedResult => item.status === "rejected")
      .map((item) => item.reason instanceof Error ? item.reason.message : "Unable to load RAG Debug Studio data.")
      .at(0)
    setBaseError(error ?? "")
  }

  useEffect(() => { void refreshBaseData() }, [])
  useEffect(() => { selectedQasperRunRef.current = selectedQasperRun }, [selectedQasperRun])
  useEffect(() => {
    let disposed = false
    const refresh = () => listQasperDebugRuns().then((runs) => {
      if (disposed) return
      setQasperRuns(runs)
      setSelectedQasperRun((current) => current ? runs.find((run) => run.run_id === current.run_id) ?? current : runs[0] ?? null)
    }).catch(() => undefined)
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 3000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [])
  const qasperCaseSelected = useCallback((item: QasperDebugCase) => {
    const run = selectedQasperRunRef.current
    if (run) setLatestTrace(qasperCaseToDebugTrace(run, item))
  }, [])
  /* oxlint-disable react/set-state-in-effect -- retain tab-local state after the user visits a tab */
  useEffect(() => {
    setVisitedTabs((current) => {
      if (current.has(activeTab)) return current
      return new Set(current).add(activeTab)
    })
  }, [activeTab])
  /* oxlint-enable react/set-state-in-effect */

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <header className="shrink-0 border-b border-slate-200 px-8 pt-7">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h1 className="text-[27px] font-semibold tracking-[-0.035em] text-slate-950">RAG Debug Studio</h1>
            <p className="mt-1 text-[13px] text-slate-500">Inspect and debug your RAG pipeline. Trace retrieval, ranking, and generation step by step.</p>
          </div>
          {baseError && <span className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-[10px] text-amber-800"><AlertCircle size={12} />{baseError}</span>}
        </div>
        <nav className="mt-5 flex gap-8" aria-label="RAG Debug Studio tabs">
          {TABS.map((tab) => (
            <button key={tab.id} type="button" onClick={() => setActiveTab(tab.id)} className={`relative px-1 pb-4 text-[13px] font-medium transition-colors duration-150 ${activeTab === tab.id ? "text-slate-950" : "text-slate-500 hover:text-slate-800"}`}>
              {tab.label}
              <span className={`absolute inset-x-0 bottom-0 h-[2px] origin-center bg-slate-950 transition-transform duration-200 ${activeTab === tab.id ? "scale-x-100" : "scale-x-0"}`} />
            </button>
          ))}
        </nav>
      </header>

      <div className="min-h-0 flex-1">
        {TABS.map(({ id }) => {
          const visible = activeTab === id
          if (!visible && !visitedTabs.has(id)) return null
          return (
            <div
              key={id}
              className={visible ? "min-h-0 h-full animate-[ragFadeIn_.18s_ease-out]" : "hidden"}
              aria-hidden={!visible}
            >
              {id === "trace" && <TraceTab configs={configs} onConfigsChanged={refreshBaseData} trace={latestTrace} onTraceChange={setLatestTrace} />}
              {id === "retrieval" && <RetrievalTab trace={latestTrace} />}
              {id === "chunks" && <ChunksTab qasperRunId={selectedQasperRun?.run_id ?? ""} />}
              {id === "evaluation" && <EvaluationTab configs={configs} datasets={datasets} qasperRun={selectedQasperRun} />}
              {id === "compare" && <CompareTab configs={configs} datasets={datasets} qasperRuns={qasperRuns} />}
              {id === "datasets" && <DatasetsTab datasets={datasets} configs={configs} onDatasetsChanged={refreshBaseData} qasperRuns={qasperRuns} onQasperRunSelected={setSelectedQasperRun} onQasperCaseSelected={qasperCaseSelected} />}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function TraceTab({
  configs,
  onConfigsChanged,
  trace,
  onTraceChange,
}: {
  configs: RagDebugConfigProfile[]
  onConfigsChanged: () => Promise<void>
  trace: RagDebugTraceResponse | null
  onTraceChange: (trace: RagDebugTraceResponse | null) => void
}) {
  const [query, setQuery] = useState("")
  const [configId, setConfigId] = useState("default")
  const [topK, setTopK] = useState("8")
  const [includeAnswer, setIncludeAnswer] = useState(false)
  const [selectedId, setSelectedId] = useState("")
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState("")
  const [companionTraces, setCompanionTraces] = useState<RagDebugCompanionTrace[]>([])
  const mounted = useRef(true)

  useEffect(() => () => { mounted.current = false }, [])
  useEffect(() => {
    void listRagDebugCompanionTraces(12)
      .then((items) => {
        if (mounted.current) setCompanionTraces(items)
      })
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    if (configs.length && !configs.some((item) => item.config_id === configId)) setConfigId(configs[0].config_id)
  }, [configs, configId])

  async function refreshCompanionTraces() {
    try {
      const items = await listRagDebugCompanionTraces(12)
      if (mounted.current) setCompanionTraces(items)
    } catch {
      // The standalone RAG trace remains usable when live Companion traces are unavailable.
    }
  }

  const selectedConfig = configs.find((item) => item.config_id === configId) ?? configs[0]
  const candidates = trace?.candidates ?? []
  const selectedIndex = Math.max(0, candidates.findIndex((item) => item.id === selectedId))
  const selected = candidates[selectedIndex]
  const activeStage = trace?.stages.find((item) => item.status === "active")?.key ?? ""
  const topKNumber = Number(topK)
  const topKValid = /^\d+$/.test(topK) && topKNumber >= 1 && topKNumber <= 100
  const topKError = topK && !topKValid ? "Enter a whole number from 1 to 100." : ""

  async function run() {
    if (!query.trim() || running) return
    if (!topKValid) {
      setNotice("Top K must be a whole number between 1 and 100.")
      return
    }
    setRunning(true)
    setNotice("")
    try {
      const accepted = await startRagDebugRun({ query: query.trim(), config_id: configId, top_k: topKNumber, include_answer: includeAnswer, knowledge_access_policy: "auto" })
      let next = await getRagDebugRun(accepted.run_id)
      if (mounted.current) onTraceChange(next)
      while (next.status === "queued" || next.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 180))
        next = await getRagDebugRun(accepted.run_id)
        if (mounted.current) onTraceChange(next)
      }
      if (next.status === "failed") setNotice(next.error || "Trace failed.")
      if (next.status === "cancelled") setNotice("Trace cancelled.")
      if (next.candidates[0] && mounted.current) setSelectedId(next.candidates[0].id)
    } catch (error) {
      if (mounted.current) setNotice(error instanceof Error ? error.message : "Unable to start trace.")
    } finally {
      if (mounted.current) setRunning(false)
    }
  }

  async function stop() {
    if (!trace?.run_id) return
    try {
      const cancelled = await cancelRagDebugRun(trace.run_id)
      onTraceChange(cancelled)
      setRunning(false)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to stop trace.")
    }
  }

  function move(offset: number) {
    if (!candidates.length) return
    setSelectedId(candidates[(selectedIndex + offset + candidates.length) % candidates.length].id)
  }

  return (
    <ScrollSurface>
      <div className="mx-auto max-w-[1240px] space-y-4">
        <section className="rounded-[10px] border border-slate-200 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-[13px] font-semibold text-slate-900">Live Capability Routing</h2>
              <p className="mt-1 text-[11px] text-slate-500">Recent AI Chat routes, grounding policy, retrieval, and verification decisions.</p>
            </div>
            <button type="button" onClick={() => void refreshCompanionTraces()} className="rounded-md border border-slate-200 px-2.5 py-1.5 text-[11px] font-medium text-slate-700 hover:bg-slate-50">
              Refresh routes
            </button>
          </div>
          <div className="mt-3 grid gap-2">
            {companionTraces.length === 0 ? (
              <p className="rounded-md bg-slate-50 px-3 py-2 text-[11px] text-slate-500">No live Companion route traces yet.</p>
            ) : companionTraces.slice(0, 6).map((item) => {
              const verificationPassed = item.verification.passed
              const reasonCodes = Array.isArray(item.verification.reason_codes)
                ? item.verification.reason_codes.map(String)
                : []
              const selectedChunks = Array.isArray(item.retrieval.selected_chunks)
                ? item.retrieval.selected_chunks
                : []
              const totalRagMs = Number(item.retrieval.total_rag_ms ?? 0)
              return (
                <div key={item.trace_id} className="grid gap-2 rounded-md border border-slate-100 px-3 py-2.5 lg:grid-cols-[minmax(180px,1.3fr)_150px_150px_1fr]">
                  <div className="min-w-0">
                    <p className="truncate text-[11px] font-medium text-slate-900">{item.query}</p>
                    <p className="mt-0.5 truncate text-[10px] text-slate-500">{item.route_reason}</p>
                  </div>
                  <div>
                    <p className="text-[9px] uppercase tracking-wide text-slate-400">Route</p>
                    <p className="mt-0.5 text-[11px] font-medium text-slate-800">{item.route}</p>
                  </div>
                  <div>
                    <p className="text-[9px] uppercase tracking-wide text-slate-400">Grounding</p>
                    <p className="mt-0.5 text-[11px] text-slate-700">{item.grounding_policy}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-slate-600">
                      {item.knowledge_enabled ? "Knowledge · " + item.document_scope : "Knowledge off"}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-slate-600">
                      {item.retrieval_skipped ? "Retrieval skipped" : "Retrieval used"}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-slate-600">
                      {item.verification_skipped
                        ? "Verification skipped"
                        : verificationPassed === true
                          ? "Verification passed"
                          : item.fallback_applied
                            ? "Fallback applied"
                            : "Verification failed"}
                    </span>
                    {!item.retrieval_skipped && (
                      <span className="rounded-full bg-slate-100 px-2 py-1 text-slate-600">
                        {totalRagMs.toFixed(1)} ms · {selectedChunks.length} chunks · {item.evidence?.length ?? 0} evidence · {item.citations?.length ?? 0} citations
                      </span>
                    )}
                    {reasonCodes.length > 0 && (
                      <span className="basis-full text-[9px] text-slate-500">
                        Verifier: {reasonCodes.join(", ")}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="rounded-[10px] border border-slate-200 p-4">
          <div className="flex items-center justify-between gap-3">
            <label className="text-[12px] font-semibold text-slate-800">Query</label>
            {selectedConfig?.requires_reindex && <span className="rounded-full bg-amber-50 px-2 py-1 text-[9px] text-amber-800">Index rebuild required for indexed config changes</span>}
          </div>
          <textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={2} placeholder="Ask a question against the indexed knowledge base…" className={inputClass("mt-2 w-full resize-none py-2.5")} />
          <div className="mt-4 grid items-end gap-3 lg:grid-cols-[1fr_1fr_120px_148px]">
            <Field label="Workspace"><select className={selectClass} defaultValue="workspace"><option value="workspace">My Workspace</option><option value="all">All indexed documents</option></select></Field>
            <Field label="RAG Config"><div className="flex gap-2"><select value={configId} onChange={(event) => setConfigId(event.target.value)} className={selectClass}>{configs.length ? configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}{item.active ? " · active" : ""}</option>) : <option value="default">Default</option>}</select><button type="button" title="Duplicate selected profile" aria-label="Duplicate selected profile" onClick={async () => { if (!selectedConfig) return; const name = window.prompt("New RAG profile name", `${selectedConfig.name} copy`); if (!name?.trim()) return; await createRagDebugConfig({ name, description: selectedConfig.description, config: selectedConfig.config }); await onConfigsChanged() }} className="rounded-[8px] border border-slate-200 px-2.5 text-slate-600 hover:bg-slate-50"><Plus size={14} /></button></div></Field>
            <Field label="Top K"><input aria-describedby="top-k-help" aria-label="Top K" type="number" inputMode="numeric" min={1} max={100} step={1} value={topK} onChange={(event) => { setTopK(event.target.value); setNotice("") }} disabled={running} className={inputClass("h-10 w-full text-[12px]")} />{topKError ? <span id="top-k-help" className="mt-1 block text-[9px] text-rose-600">{topKError}</span> : <span id="top-k-help" className="mt-1 block text-[9px] text-slate-400">1–100 results</span>}</Field>
            <PrimaryButton onClick={running ? stop : run} disabled={!running && (!query.trim() || !topKValid)}>{running ? <><X size={14} />Stop</> : <><Play size={14} fill="currentColor" />Run trace</>}</PrimaryButton>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-slate-500">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={includeAnswer} onChange={(event) => setIncludeAnswer(event.target.checked)} className="accent-slate-950" />Include optional answer generation</label>
            {selectedConfig && <><span>Embedding: {String(selectedConfig.config.embedding.model ?? "configured")}</span><span>Fusion: {selectedConfig.config.retrieval.fusion}</span><button type="button" onClick={async () => { await activateRagDebugConfig(selectedConfig.config_id); await onConfigsChanged(); setNotice(`${selectedConfig.name} is now the active profile.`) }} className="font-medium text-slate-800 underline underline-offset-2">Use this profile</button></>}
          </div>
        </section>

        <ConfigTuningPanel config={selectedConfig} onSaved={onConfigsChanged} onNotice={setNotice} />
        {trace && !trace.metadata.qasper_run_id ? <KnowledgeDebugCards trace={trace} /> : null}
        {trace?.metadata.qasper_case ? <QasperTraceSummary trace={trace} /> : null}

        <section className="rounded-[10px] border border-slate-200 px-4 py-4">
          <div className="grid grid-cols-5 gap-2 md:grid-cols-10">{(trace?.stages ?? INITIAL_STAGES).map((item) => <StagePill key={item.key} stage={item} active={activeStage === item.key} />)}</div>
          {trace && <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-slate-500"><span className="inline-flex items-center gap-1"><Clock3 size={12} />{formatMs(Number(trace.metadata.total_rag_ms ?? 0))}</span><span>{trace.candidates.length} final candidates</span><span>{trace.context.source_count} evidence items</span><span className="rounded-full bg-slate-100 px-2 py-1">{trace.status}</span></div>}
        </section>

        {trace?.error && <div className="rounded-[10px] border border-rose-200 bg-rose-50 px-4 py-3 text-[11px] text-rose-700"><AlertCircle className="mr-1 inline" size={13} />{trace.error}</div>}

        {trace && candidates.length > 0 ? <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]"><section className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center justify-between border-b border-slate-100 px-1 pb-3"><div><h2 className="text-[13px] font-semibold">Final Retrieval Results</h2><p className="mt-0.5 text-[10px] text-slate-500">Click a row to inspect the actual indexed chunk.</p></div><span className="text-[10px] text-slate-400">{candidates.length} results</span></div><ResultTable rows={candidates} selectedId={selectedId} onSelect={setSelectedId} /></section>{selected && <section className="rounded-[10px] border border-slate-200 p-4"><ChunkDetail row={selected} index={selectedIndex} total={candidates.length} previous={() => move(-1)} next={() => move(1)} /></section>}</div> : <EmptyState title={running ? "Tracing retrieval…" : "Run a trace to inspect retrieval"} description="The studio reads the current local index and reports real query, retrieval, fusion, rerank, context, and answer stages." loading={running} />}
        {trace?.answer && <section className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center gap-2"><CheckCircle2 size={15} className="text-emerald-600" /><h2 className="text-[13px] font-semibold">Generated answer</h2></div><p className="mt-3 whitespace-pre-wrap text-[11px] leading-5 text-slate-700">{trace.answer}</p></section>}
        {notice && <div className="rounded-[10px] bg-slate-950 px-4 py-2.5 text-[11px] text-white">{notice}</div>}
      </div>
    </ScrollSurface>
  )
}

function KnowledgeDebugCards({ trace }: { trace: RagDebugTraceResponse }) {
  const decision = trace.knowledge_decision ?? {}
  const scope = trace.knowledge_scope ?? {}
  const mode = debugText(decision.mode) || "auto"
  const shouldRetrieve = decision.should_retrieve === true
  const strategy = debugText(scope.strategy) || debugText(decision.scope_strategy) || "none"
  const documents = debugNumber(scope.document_count) || debugArrayLength(scope.document_ids)
  const sources = debugNumber(scope.research_source_count) || debugArrayLength(scope.research_source_ids)
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <section className="rounded-[10px] border border-cyan-100 bg-cyan-50/35 p-4" aria-label="Knowledge Decision">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[13px] font-semibold text-slate-900">Knowledge Decision</h2>
          <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold text-cyan-700">{mode}</span>
        </div>
        <p className="mt-3 text-sm font-semibold text-slate-800">{modeLabel(mode)} · retrieval {shouldRetrieve ? "required" : "skipped"}</p>
        <p className="mt-1 text-[10px] leading-4 text-slate-500">Reason: {debugText(decision.reason_code) || "not available"}</p>
        {debugNumber(decision.confidence) > 0 ? <p className="mt-2 text-[10px] text-slate-400">Confidence · {Number(decision.confidence).toFixed(2)}</p> : null}
      </section>
      <section className="rounded-[10px] border border-violet-100 bg-violet-50/35 p-4" aria-label="Scope Decision">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[13px] font-semibold text-slate-900">Scope Decision</h2>
          <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold text-violet-700">{scopeLabel(strategy)}</span>
        </div>
        <p className="mt-3 text-sm font-semibold text-slate-800">{documents} documents · {sources} sources</p>
        <p className="mt-1 text-[10px] leading-4 text-slate-500">{debugText(scope.reason) || "Scope resolved from the debug request."}</p>
        <p className="mt-2 text-[10px] text-slate-400">Global access · {scope.allow_global === true ? "allowed" : "restricted"}</p>
      </section>
    </div>
  )
}

function QasperTraceSummary({ trace }: { trace: RagDebugTraceResponse }) {
  const item = (trace.metadata.qasper_case ?? {}) as Record<string, unknown>
  const gold = debugStringArray(item.gold_paragraph_ids)
  const retrieved = debugStringArray(item.source_paragraph_ids)
  const hits = gold.filter((paragraphId) => retrieved.includes(paragraphId))
  const gate = (item.gate ?? {}) as Record<string, unknown>
  const reasons = debugStringArray(gate.reason_codes)
  const rounds = Array.isArray(item.retrieval_rounds) ? item.retrieval_rounds.length : debugNumber(item.retrieval_round_count)
  const evidenceCoverage = item.evidence_coverage
  return (
    <section className="rounded-[10px] border border-amber-200 bg-amber-50/40 p-4" aria-label="QASPER evidence trace">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold text-slate-900">QASPER gold evidence trace</h2>
        <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${hits.length ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}>
          {hits.length ? `Gold hit · ${hits.length}/${gold.length}` : "Gold miss"}
        </span>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <DebugDetail label="Evidence Coverage / Recall@10" value={evidenceCoverage == null ? "—" : percent(evidenceCoverage)} />
        <DebugDetail label="Retrieval rounds" value={`${rounds}${item.second_retrieval === true ? " · second retrieval" : " · one pass"}`} />
        <DebugDetail label="Gate decision" value={`${debugText(gate.action) || "not recorded"}${reasons.length ? ` · ${reasons.join(", ")}` : ""}`} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <DebugDetail label="Gold paragraph IDs" value={gold.join(", ") || "No mapped gold paragraph"} />
        <DebugDetail label="Retrieved source paragraph IDs" value={retrieved.join(", ") || "No source paragraph IDs"} />
      </div>
    </section>
  )
}

function qasperCaseToDebugTrace(run: QasperDebugRunSummary, item: QasperDebugCase): RagDebugTraceResponse {
  const rawTrace = item.trace
  const rawCandidates = Array.isArray(rawTrace.final_candidates) ? rawTrace.final_candidates as Array<Record<string, unknown>> : []
  const rawStageIds = (rawTrace.stages ?? {}) as Record<string, unknown>
  const roundRecords = Array.isArray(rawTrace.retrieval_rounds) ? rawTrace.retrieval_rounds as Array<Record<string, unknown>> : []
  const retrievalMetadata = (rawTrace.retrieval_metadata ?? {}) as Record<string, unknown>
  const candidateIds = (key: string) => debugStringArray(rawStageIds[key])
  const finalIds = rawCandidates.map((candidate) => String(candidate.chunk_id ?? "")).filter(Boolean)
  const contextSources = debugStringArray(item.prediction.predicted_evidence_paragraph_ids)
  const allSources = [...new Set(contextSources.length ? contextSources : rawCandidates.flatMap((candidate) => debugStringArray(candidate.source_paragraph_ids)))]
  const lastRound = roundRecords.at(-1) ?? {}
  const gate = (lastRound.gate ?? rawTrace.sufficiency ?? {}) as Record<string, unknown>
  const evidenceCoverage = item.metrics.gold_evidence_recall_at_10
  const stageSpecs = [
    ["query", "Query", 0, 1],
    ["rewrite", "Query Planning", 0, debugNumber(rawTrace.query_planner_invoked) ? 2 : 0],
    ["dense", "Dense", debugNumber(retrievalMetadata.dense_search_ms), candidateIds("dense_chunk_ids").length],
    ["bm25", "BM25", debugNumber(retrievalMetadata.sparse_search_ms), candidateIds("sparse_chunk_ids").length],
    ["structural", "Structural", debugNumber(retrievalMetadata.structural_search_ms), candidateIds("structural_chunk_ids").length],
    ["fusion", "Fusion", debugNumber(retrievalMetadata.fusion_ms), candidateIds("pre_rerank_chunk_ids").length],
    ["rerank", "Rerank", debugNumber(retrievalMetadata.rerank_ms), finalIds.length],
    ["final", "Final", 0, finalIds.length],
    ["context", "Evidence Context", 0, allSources.length],
    ["answer", "Answer", debugNumber((item.prediction.answer_generation as Record<string, unknown> | undefined)?.latency_ms), item.prediction.answer ? 1 : 0],
  ] as const
  const stages: RagDebugStage[] = stageSpecs.map(([key, label, elapsed, count]) => ({
    key,
    label,
    status: count > 0 ? "complete" : "skipped",
    elapsed_ms: elapsed,
    note: count > 0 ? `${count} results` : "No results recorded for this stage",
    summary: { count },
    candidate_count: count,
  }))
  const candidates: RagDebugCandidate[] = rawCandidates.map((candidate, index) => {
    const scores = (candidate.scores ?? {}) as Record<string, unknown>
    const maybeScore = (value: unknown) => value == null ? null : Number(value)
    const chunkId = String(candidate.chunk_id ?? `candidate-${index + 1}`)
    const before = candidateIds("pre_rerank_chunk_ids").indexOf(chunkId)
    return {
      id: chunkId,
      document_id: String(candidate.document_id ?? `qasper:${run.split}:${item.paper_id}`),
      source: String(candidate.title ?? "QASPER paper"),
      section: String(candidate.section_heading ?? ""),
      page: null,
      tokens: debugNumber(candidate.token_count),
      dense: maybeScore(scores.dense),
      bm25: maybeScore(scores.sparse),
      fusion: maybeScore(scores.fusion),
      rerank: maybeScore(scores.rerank),
      before: before >= 0 ? before + 1 : null,
      after: index + 1,
      text: String(candidate.text ?? ""),
      chunk_type: "qasper_paragraph_group",
      start: 0,
      end: String(candidate.text ?? "").length,
      metadata: { source_paragraph_ids: debugStringArray(candidate.source_paragraph_ids), section_path: candidate.section_path ?? [] },
    }
  })
  const contextTokens = debugNumber(item.metrics.context_token_count)
  const qasperInfo = {
    question_id: item.question_id,
    gold_paragraph_ids: item.gold_paragraph_ids,
    source_paragraph_ids: allSources,
    evidence_coverage: evidenceCoverage,
    second_retrieval: roundRecords.length > 1 || rawTrace.second_round === true,
    retrieval_round_count: roundRecords.length || 1,
    retrieval_rounds: roundRecords,
    gate,
  }
  return {
    run_id: run.run_id,
    trace_id: `qasper:${run.run_id}:${item.question_id}`,
    status: run.status,
    query: item.question,
    config_id: run.config_id,
    query_plan: (rawTrace.query_plan ?? {}) as Record<string, unknown>,
    stages,
    candidates,
    context: {
      text: candidates.map((candidate) => candidate.text).join("\n\n"),
      estimated_tokens: contextTokens || candidates.reduce((total, candidate) => total + candidate.tokens, 0),
      included_evidence_ids: finalIds,
      omitted_evidence_ids: [],
      source_count: allSources.length,
    },
    evidence: Array.isArray(item.prediction.predicted_evidence) ? (item.prediction.predicted_evidence as unknown[]).map((text) => ({ text: String(text) })) : [],
    citations: [],
    answer: String(item.prediction.answer ?? ""),
    knowledge_decision: { mode: "qasper_benchmark", should_retrieve: true, reason_code: "isolated_paper_scoped_retrieval" },
    knowledge_scope: { strategy: "single_paper", document_count: 1, document_ids: [`qasper:${run.split}:${item.paper_id}`], reason: "QASPER benchmark keeps retrieval within the question's source paper." },
    metadata: {
      qasper_run_id: run.run_id,
      qasper_case: qasperInfo,
      retrieval_queries: roundRecords.map((record) => String(record.query ?? "")).filter(Boolean),
      retrieval_round_count: roundRecords.length || 1,
      total_rag_ms: debugNumber(rawTrace.latency_ms),
      answer_f1: item.metrics["Answer F1"],
      official_evidence_f1: item.metrics["Evidence F1"],
    },
    error: String(rawTrace.error ?? ""),
  }
}

function RetrievalTab({ trace }: { trace: RagDebugTraceResponse | null }) {
  if (!trace) {
    return <ScrollSurface><EmptyState title="No retrieval trace" description="Run a trace from the Trace tab to inspect the query, scope, and retrieval rounds here." /></ScrollSurface>
  }

  const plan = trace.query_plan ?? {}
  const metadata = trace.metadata ?? {}
  const queries = debugStringArray(metadata.retrieval_queries).length > 0
    ? debugStringArray(metadata.retrieval_queries)
    : debugStringArray(plan.retrieval_queries)
  const stages = trace.stages ?? []
  const stage = (key: string) => stages.find((item) => item.key === key)
  const scope = trace.knowledge_scope ?? {}
  const scopeStrategy = debugText(scope.strategy) || "none"
  const roundCount = debugNumber(metadata.retrieval_round_count) || queries.length
  const retrievalSkipped = metadata.retrieval_skipped === true
  const pipeline = [
    { label: "Dense", key: "dense", count: stage("dense")?.candidate_count ?? debugNumber(stage("dense")?.summary.count) },
    { label: "BM25", key: "bm25", count: stage("bm25")?.candidate_count ?? debugNumber(stage("bm25")?.summary.count) },
    { label: "Structural", key: "structural", count: stage("structural")?.candidate_count ?? debugNumber(stage("structural")?.summary.count) },
    { label: "Fusion", key: "fusion", count: stage("fusion")?.candidate_count ?? debugNumber(stage("fusion")?.summary.count) },
    { label: "Rerank", key: "rerank", count: stage("rerank")?.candidate_count ?? debugNumber(stage("rerank")?.summary.count) },
    { label: "Final", key: "final", count: stage("final")?.candidate_count ?? debugNumber(stage("final")?.summary.count) },
  ]

  return (
    <ScrollSurface>
      <div className="mx-auto max-w-[1240px] space-y-4">
        <section className="rounded-[10px] border border-slate-200 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-[13px] font-semibold text-slate-900">Retrieval rounds</h2>
              <p className="mt-1 text-[10px] text-slate-500">Inspect the exact query planning, scope boundary, and local retrieval pipeline.</p>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-[10px] font-medium ${retrievalSkipped ? "bg-slate-100 text-slate-600" : "bg-emerald-50 text-emerald-700"}`}>
              {retrievalSkipped ? "Retrieval skipped" : `${roundCount} round${roundCount === 1 ? "" : "s"}`}
            </span>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <DebugDetail label="Query" value={trace.query} />
            <DebugDetail label="Query rewrite" value={debugText(plan.rewritten_query) || trace.query} />
            <DebugDetail label="Scope" value={`${scopeLabel(scopeStrategy)} · ${debugNumber(scope.document_count) || debugArrayLength(scope.document_ids)} documents`} />
          </div>
        </section>

        <section className="rounded-[10px] border border-slate-200 p-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[13px] font-semibold text-slate-900">Pipeline</h2>
            <span className="text-[10px] text-slate-400">{formatMs(Number(metadata.total_rag_ms ?? 0))}</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
            {pipeline.map((item) => {
              const current = stage(item.key)
              return (
                <div key={item.key} className="rounded-[10px] border border-slate-100 bg-slate-50/60 px-3 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <strong className="text-[11px] font-semibold text-slate-700">{item.label}</strong>
                    <span className="text-[10px] tabular-nums text-slate-400">{item.count || 0}</span>
                  </div>
                  <p className="mt-1 text-[10px] text-slate-500">{current?.status ?? "pending"} · {formatMs(current?.elapsed_ms ?? 0)}</p>
                </div>
              )
            })}
          </div>
        </section>

        <section className="rounded-[10px] border border-slate-200 p-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[13px] font-semibold text-slate-900">Round queries</h2>
            <span className="text-[10px] text-slate-400">{queries.length} planned</span>
          </div>
          {queries.length > 0 ? (
            <ol className="mt-3 space-y-2">
              {queries.map((item, index) => <li key={`${item}-${index}`} className="rounded-[9px] bg-slate-50 px-3 py-2 text-[10px] text-slate-700"><span className="mr-2 font-semibold text-slate-400">{index + 1}</span>{item}</li>)}
            </ol>
          ) : (
            <p className="mt-3 rounded-[9px] bg-slate-50 px-3 py-2 text-[10px] text-slate-500">No retrieval query was executed.</p>
          )}
        </section>
      </div>
    </ScrollSurface>
  )
}

function DebugDetail({ label, value }: { label: string; value: string }) {
  return <div className="rounded-[10px] bg-slate-50/70 px-3 py-2.5"><p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 line-clamp-3 text-[11px] leading-4 text-slate-700">{value || "—"}</p></div>
}

function modeLabel(value: string): string {
  if (value === "always") return "Always"
  if (value === "never") return "Never"
  return "Auto"
}

function scopeLabel(value: string): string {
  if (value === "attached_document") return "Current document"
  if (value === "explicit_documents") return "Selected documents"
  if (value === "research_workspace") return "Research workspace"
  if (value === "global_knowledge") return "All knowledge"
  return "No scope"
}

function debugText(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

function debugNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function debugArrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0
}

function debugStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean) : []
}

function ConfigTuningPanel({ config, onSaved, onNotice }: { config?: RagDebugConfigProfile; onSaved: () => Promise<void>; onNotice: (value: string) => void }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState({ dense_top_k: 30, sparse_top_k: 30, fusion_top_k: 20, final_top_k: 8, fusion: "rrf", small_to_big_enabled: true })
  useEffect(() => { if (config) setDraft({ dense_top_k: config.config.retrieval.dense_top_k, sparse_top_k: config.config.retrieval.sparse_top_k, fusion_top_k: config.config.retrieval.fusion_top_k, final_top_k: config.config.retrieval.final_top_k, fusion: config.config.retrieval.fusion, small_to_big_enabled: config.config.retrieval.small_to_big_enabled }) }, [config])
  if (!config) return null
  const profile = config
  async function save() { const nextConfig: RagConfig = { ...profile.config, retrieval: { ...profile.config.retrieval, ...draft } }; await updateRagDebugConfig(profile.config_id, { config: nextConfig }); await onSaved(); onNotice("RAG profile saved. Indexed-field changes are marked for reindexing.") }
  return <section className="rounded-[10px] border border-slate-200"><button type="button" onClick={() => setOpen((value) => !value)} className="flex w-full items-center justify-between px-4 py-3 text-left"><span className="inline-flex items-center gap-2 text-[12px] font-semibold"><SlidersHorizontal size={14} />Retrieval tuning · {profile.name}</span><ChevronDown size={14} className={`transition-transform ${open ? "rotate-180" : ""}`} /></button>{open && <div className="grid gap-3 border-t border-slate-100 px-4 py-4 md:grid-cols-5"><NumberField label="Dense top K" value={draft.dense_top_k} onChange={(value) => setDraft({ ...draft, dense_top_k: value })} /><NumberField label="BM25 top K" value={draft.sparse_top_k} onChange={(value) => setDraft({ ...draft, sparse_top_k: value })} /><NumberField label="Fusion top K" value={draft.fusion_top_k} onChange={(value) => setDraft({ ...draft, fusion_top_k: value })} /><NumberField label="Final top K" value={draft.final_top_k} onChange={(value) => setDraft({ ...draft, final_top_k: value })} /><label className="text-[10px] text-slate-600">Fusion<select value={draft.fusion} onChange={(event) => setDraft({ ...draft, fusion: event.target.value })} className={smallSelectClass}><option value="rrf">RRF</option></select></label><label className="inline-flex items-center gap-2 text-[10px] text-slate-600"><input type="checkbox" checked={draft.small_to_big_enabled} onChange={(event) => setDraft({ ...draft, small_to_big_enabled: event.target.checked })} className="accent-slate-950" />Small-to-big context</label><div className="md:col-span-5 flex justify-end gap-2"><SecondaryButton onClick={() => setOpen(false)}>Cancel</SecondaryButton><PrimaryButton onClick={save}><Save size={13} />Save profile</PrimaryButton></div></div>}</section>
}

function QasperChunkCatalog({ runId }: { runId: string }) {
  const [chunkPage, setChunkPage] = useState<{ key: string; chunks: QasperDebugChunk[]; total: number }>({ key: "", chunks: [], total: 0 })
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState("")
  const [query, setQuery] = useState("")
  const [error, setError] = useState("")
  const requestKey = `${runId}:${page}:${query}`
  useEffect(() => {
    let disposed = false
    if (!runId) return () => { disposed = true }
    void listQasperDebugChunks(runId, { page, pageSize: 50, query }).then((result) => {
      if (disposed) return
      setChunkPage({ key: requestKey, chunks: result.chunks, total: result.total })
      setError("")
      setSelectedId((current) => result.chunks.some((item) => item.chunk_id === current) ? current : result.chunks[0]?.chunk_id ?? "")
    }).catch((reason) => { if (!disposed) setError(errorText(reason)) })
    return () => { disposed = true }
  }, [runId, page, query, requestKey])
  const rows = chunkPage.key === requestKey ? chunkPage.chunks : []
  const total = chunkPage.key === requestKey ? chunkPage.total : 0
  const selected = rows.find((chunk) => chunk.chunk_id === selectedId) ?? rows[0]
  return (
    <section className="rounded-[10px] border border-cyan-200 p-4">
      <PanelHeader title="QASPER paragraph chunks" right={runId ? `${total} chunks · ${runId}` : "Choose a QASPER run in Datasets"} />
      {!runId ? <EmptyState title="No QASPER run selected" description="Start or choose a benchmark run in the Datasets tab to inspect its paragraph mappings." /> : <>
        <input value={query} onChange={(event) => { setPage(1); setQuery(event.target.value) }} placeholder="Filter chunk, section, or paragraph ID" className={inputClass("mt-3 h-9 w-full")} />
        {error && <p role="alert" className="mt-2 text-[10px] text-rose-700">{error}</p>}
        <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1.4fr)_minmax(260px,.8fr)]">
          <div className="ait-scroll-page max-h-[380px] overflow-auto rounded-[8px] border border-slate-100">
            <table className="w-full table-fixed text-left text-[10px]"><thead className="sticky top-0 bg-slate-50 text-slate-500"><tr><th className="w-[145px] px-2 py-2">Chunk ID</th><th className="w-[175px] px-2">Section mapping</th><th className="px-2">QASPER paragraph IDs</th><th className="w-[88px] px-2">Gold-hit Qs</th></tr></thead><tbody>{rows.map((chunk) => <tr key={chunk.chunk_id} onClick={() => setSelectedId(chunk.chunk_id)} className={`cursor-pointer border-t border-slate-100 ${selected?.chunk_id === chunk.chunk_id ? "bg-cyan-50" : "hover:bg-slate-50"}`}><td className="truncate px-2 py-2 font-medium">{chunk.chunk_id}</td><td className="truncate px-2 text-slate-600">{chunk.section_path.join(" / ") || "—"}</td><td className="truncate px-2 text-slate-600">{chunk.source_paragraph_ids.join(", ") || "—"}</td><td className="px-2 tabular-nums">{chunk.gold_question_count}</td></tr>)}</tbody></table>
            {!rows.length && <p className="p-4 text-[10px] text-slate-500">No matching chunks.</p>}
          </div>
          {selected ? <div className="rounded-[8px] border border-slate-100 p-3"><div className="flex items-start justify-between gap-2"><strong className="break-all text-[11px]">{selected.chunk_id}</strong><span className="rounded-full bg-amber-50 px-2 py-1 text-[9px] text-amber-800">{selected.gold_question_count} gold-hit questions</span></div><p className="mt-2 text-[9px] text-slate-500">{selected.section_path.join(" / ") || "No section mapping"}</p><p className="mt-2 text-[9px] text-slate-500">Paragraph IDs: {selected.source_paragraph_ids.join(", ") || "none"}</p><div className="ait-scroll-page mt-3 max-h-[260px] overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-[10px] leading-4 text-slate-700">{selected.text}</div></div> : null}
        </div>
        <div className="mt-2 flex items-center justify-end gap-2"><span className="mr-2 text-[9px] text-slate-500">Page {page} of {Math.max(1, Math.ceil(total / 50))}</span><PaginationButton disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={12} /></PaginationButton><PaginationButton disabled={page * 50 >= total} onClick={() => setPage((value) => value + 1)}><ChevronRight size={12} /></PaginationButton></div>
      </>}
    </section>
  )
}

function ChunksTab({ qasperRunId }: { qasperRunId: string }) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [documentId, setDocumentId] = useState("")
  const [query, setQuery] = useState("")
  const [page, setPage] = useState(1)
  const [chunks, setChunks] = useState<RagDebugChunk[]>([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<RagDebugChunk | null>(null)
  const [loading, setLoading] = useState(false)
  const [operation, setOperation] = useState<"idle" | "importing" | "reindexing" | "deleting">("idle")
  const [refreshKey, setRefreshKey] = useState(0)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  const selectedDocument = documents.find((document) => document.document_id === documentId) ?? null
  const operationBusy = operation !== "idle"

  useEffect(() => {
    let disposed = false
    setError("")
    listKnowledgeDocuments()
      .then((result) => {
        if (!disposed) setDocuments(result.documents)
      })
      .catch((reason) => {
        if (!disposed) setError(errorText(reason))
      })
    return () => {
      disposed = true
    }
  }, [refreshKey])

  useEffect(() => {
    let disposed = false
    setLoading(true)
    listRagDebugChunks({ documentId, query, page, pageSize: 50 })
      .then((result) => {
        if (!disposed) {
          setChunks(result.chunks)
          setTotal(result.total)
          setSelected(result.chunks[0] ?? null)
        }
      })
      .catch((reason) => {
        if (!disposed) setError(errorText(reason))
      })
      .finally(() => {
        if (!disposed) setLoading(false)
      })
    return () => {
      disposed = true
    }
  }, [documentId, query, page, refreshKey])

  useEffect(() => {
    if (documentId && !documents.some((document) => document.document_id === documentId)) {
      setDocumentId("")
    }
  }, [documents, documentId])

  const sectionCounts = useMemo(
    () =>
      chunks.reduce<Record<string, number>>((acc, chunk) => {
        const section = chunk.section || "Unsectioned"
        acc[section] = (acc[section] ?? 0) + 1
        return acc
      }, {}),
    [chunks],
  )

  async function refreshAfterOperation() {
    setRefreshKey((value) => value + 1)
  }

  async function importDocument() {
    setOperation("importing")
    setError("")
    setNotice("")
    try {
      const path = await desktop.files.pickKnowledgeDocument()
      if (!path) return
      const result = await addKnowledgeDocument(path)
      setDocumentId(result.document.document_id)
      setPage(1)
      setNotice(
        (result.document.title || "Document") +
          " indexed into " +
          result.document.chunk_count +
          " chunks.",
      )
      await refreshAfterOperation()
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setOperation("idle")
    }
  }

  async function rechunkDocument() {
    if (!selectedDocument || operationBusy) return
    if (
      !window.confirm(
        "Re-chunk and re-index this document with the current Knowledge settings?",
      )
    ) {
      return
    }
    setOperation("reindexing")
    setError("")
    setNotice("")
    try {
      const result = await reindexKnowledgeDocument(selectedDocument.document_id)
      setNotice(
        (result.document.title || "Document") +
          " re-chunked into " +
          result.document.chunk_count +
          " chunks.",
      )
      await refreshAfterOperation()
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setOperation("idle")
    }
  }

  async function removeDocument() {
    if (!selectedDocument || operationBusy) return
    if (
      !window.confirm(
        "Remove this document and its indexed chunks? The source file will be preserved.",
      )
    ) {
      return
    }
    setOperation("deleting")
    setError("")
    setNotice("")
    try {
      await deleteKnowledgeDocument(selectedDocument.document_id)
      setDocumentId("")
      setChunks([])
      setSelected(null)
      setTotal(0)
      setNotice(
        "Document removed from the local RAG index. The source file was preserved.",
      )
      await refreshAfterOperation()
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setOperation("idle")
    }
  }

  return (
    <ScrollSurface>
      <div className="mx-auto max-w-[1240px] space-y-4">
        <QasperChunkCatalog runId={qasperRunId} />
        <section className="rounded-[10px] border border-slate-200 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-[13px] font-semibold">Chunk workspace</h2>
              <p className="mt-1 max-w-[720px] text-[10px] leading-4 text-slate-500">
                Import a local document, run the existing parse → chunk → embedding → index pipeline, then inspect the persisted chunks used by retrieval.
              </p>
            </div>
            <div className="flex gap-2">
              <SecondaryButton
                onClick={() => void refreshAfterOperation()}
                disabled={operationBusy}
              >
                <RefreshCw size={13} />
                Refresh
              </SecondaryButton>
              <PrimaryButton
                onClick={() => void importDocument()}
                disabled={operationBusy}
              >
                {operation === "importing" ? (
                  <LoaderCircle size={13} className="animate-spin" />
                ) : (
                  <FilePlus2 size={13} />
                )}
                {operation === "importing" ? "Indexing…" : "Import document"}
              </PrimaryButton>
            </div>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-4">
            <ChunkStat label="Indexed documents" value={String(documents.length)} />
            <ChunkStat label="Visible chunks" value={String(total)} />
            <ChunkStat
              label="Selected status"
              value={selectedDocument?.status ?? "All documents"}
            />
            <ChunkStat
              label="Chunker"
              value={selectedDocument?.chunker_version || "Runtime default"}
            />
          </div>
          {(error || notice) && (
            <div
              className={
                "mt-3 rounded-[8px] px-3 py-2 text-[10px] " +
                (error
                  ? "border border-rose-200 bg-rose-50 text-rose-700"
                  : "bg-slate-950 text-white")
              }
            >
              {error || notice}
            </div>
          )}
        </section>

        <section className="grid min-h-[540px] gap-4 lg:grid-cols-[260px_minmax(0,1fr)_300px]">
          <div className="rounded-[10px] border border-slate-200 p-3">
            <PanelHeader
              title="Document Structure"
              right={<span>{documents.length} documents</span>}
            />
            {documents.length === 0 ? (
              <div className="flex min-h-[260px] flex-col items-center justify-center px-3 text-center">
                <FilePlus2 size={23} className="text-slate-300" />
                <p className="mt-3 text-[12px] font-semibold text-slate-700">
                  No indexed documents
                </p>
                <p className="mt-1 text-[10px] leading-4 text-slate-500">
                  Import a PDF, DOCX, TXT, MD, or HTML file to start chunk inspection.
                </p>
                <SecondaryButton
                  onClick={() => void importDocument()}
                  disabled={operationBusy}
                >
                  <FilePlus2 size={13} />
                  Import document
                </SecondaryButton>
              </div>
            ) : (
              <div className="mt-3 space-y-1">
                {documents.map((document) => (
                  <button
                    key={document.document_id}
                    type="button"
                    onClick={() => {
                      setDocumentId(document.document_id)
                      setPage(1)
                      setNotice("")
                      setError("")
                    }}
                    className={
                      "flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left text-[10px] " +
                      (documentId === document.document_id
                        ? "bg-slate-100 font-semibold"
                        : "hover:bg-slate-50")
                    }
                  >
                    <FileText size={13} className="shrink-0" />
                    <span className="min-w-0 flex-1 truncate">
                      {document.title || document.document_id}
                    </span>
                    <span className="shrink-0 text-[9px] text-slate-400">
                      {document.chunk_count}
                    </span>
                    <span
                      className={
                        "h-1.5 w-1.5 shrink-0 rounded-full " +
                        (document.status === "ready"
                          ? "bg-emerald-500"
                          : document.status === "failed"
                            ? "bg-rose-500"
                            : "bg-amber-400")
                      }
                      title={document.status}
                    />
                  </button>
                ))}
                <div className="mt-4 border-t border-slate-100 pt-3">
                  <p className="px-2 text-[9px] font-semibold uppercase tracking-[.08em] text-slate-400">
                    Sections on this page
                  </p>
                  {Object.entries(sectionCounts).map(([label, count]) => (
                    <div
                      key={label}
                      className="flex items-center justify-between px-2 py-1.5 text-[10px] text-slate-600"
                    >
                      <span className="min-w-0 truncate">{label}</span>
                      <span className="text-slate-400">{count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="rounded-[10px] border border-slate-200 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-[13px] font-semibold">Chunks</h2>
                <p className="mt-1 truncate text-[10px] text-slate-500">
                  {selectedDocument
                    ? "Inspecting " +
                      (selectedDocument.title || selectedDocument.document_id)
                    : "Inspect chunks persisted by the active Knowledge index."}
                </p>
              </div>
              <span className="shrink-0 text-[10px] text-slate-400">
                {total} total
              </span>
            </div>
            {selectedDocument && (
              <div className="mt-3 rounded-[8px] border border-slate-100 bg-slate-50/70 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2 text-[10px] text-slate-600">
                    <span
                      className={
                        "h-2 w-2 rounded-full " +
                        (selectedDocument.status === "ready"
                          ? "bg-emerald-500"
                          : selectedDocument.status === "failed"
                            ? "bg-rose-500"
                            : "bg-amber-400")
                      }
                    />
                    <span className="font-semibold">{selectedDocument.status}</span>
                    <span className="truncate text-slate-400">
                      {selectedDocument.source_type.toUpperCase()} ·{" "}
                      {selectedDocument.embedding_model || "embedding pending"}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <SecondaryButton
                      onClick={() => void rechunkDocument()}
                      disabled={operationBusy}
                    >
                      {operation === "reindexing" ? (
                        <LoaderCircle size={13} className="animate-spin" />
                      ) : (
                        <RefreshCw size={13} />
                      )}
                      {operation === "reindexing"
                        ? "Re-chunking…"
                        : "Re-chunk & reindex"}
                    </SecondaryButton>
                    <button
                      type="button"
                      onClick={() => void removeDocument()}
                      disabled={operationBusy}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-[8px] border border-rose-200 bg-white px-3 text-[11px] font-semibold text-rose-600 transition hover:bg-rose-50 disabled:opacity-40"
                    >
                      {operation === "deleting" ? (
                        <LoaderCircle size={13} className="animate-spin" />
                      ) : (
                        <Trash2 size={13} />
                      )}
                      {operation === "deleting" ? "Removing…" : "Remove"}
                    </button>
                  </div>
                </div>
                {selectedDocument.error && (
                  <p className="mt-2 break-words text-[10px] text-rose-600">
                    {selectedDocument.error}
                  </p>
                )}
              </div>
            )}
            <div className="mt-3 flex gap-2">
              <div className="relative min-w-0 flex-1">
                <Search
                  className="absolute left-3 top-2.5 text-slate-400"
                  size={14}
                />
                <input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value)
                    setPage(1)
                  }}
                  placeholder="Search chunk text…"
                  className={inputClass("h-9 w-full pl-9 text-[10px]")}
                />
              </div>
              <button
                type="button"
                onClick={() => setRefreshKey((value) => value + 1)}
                className="rounded-[8px] border border-slate-200 px-3 text-slate-500 hover:bg-slate-50"
                aria-label="Refresh chunks"
              >
                <RefreshCw size={13} />
              </button>
            </div>
            {loading ? (
              <EmptyState
                title="Loading chunks…"
                description="Reading the local chunk catalogue."
                loading
              />
            ) : chunks.length === 0 ? (
              <EmptyState
                title="No chunks found"
                description={
                  selectedDocument
                    ? "This document has no returned chunks. Check its indexing status or re-index it."
                    : "Import a document or try another search query."
                }
              />
            ) : (
              <div className="mt-3 space-y-2">
                {chunks.map((chunk) => (
                  <button
                    key={chunk.id}
                    type="button"
                    onClick={() => setSelected(chunk)}
                    className={
                      "block w-full rounded-[8px] border px-3 py-3 text-left transition " +
                      (selected?.id === chunk.id
                        ? "border-slate-950 bg-slate-50"
                        : "border-slate-100 hover:border-slate-300")
                    }
                  >
                    <div className="flex items-start gap-2">
                      <FileText
                        size={14}
                        className="mt-0.5 shrink-0 text-slate-500"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <h3 className="truncate text-[11px] font-semibold">
                            {chunk.title || chunk.id}
                          </h3>
                          <span className="shrink-0 text-[9px] text-slate-400">
                            {chunk.page ? "p. " + chunk.page : ""}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-500">
                          {chunk.preview}
                        </p>
                        <div className="mt-2 flex gap-3 text-[9px] text-slate-400">
                          <span>{chunk.tokens} tokens</span>
                          <span>{chunk.type}</span>
                          <span>{chunk.id}</span>
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
            <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-[10px] text-slate-500">
              <span>
                Page {page} · {Math.max(1, Math.ceil(total / 50))}
              </span>
              <div className="flex gap-1">
                <PaginationButton
                  disabled={page <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  <ChevronLeft size={13} />
                </PaginationButton>
                <PaginationButton
                  disabled={page >= Math.ceil(total / 50)}
                  onClick={() => setPage((value) => value + 1)}
                >
                  <ChevronRight size={13} />
                </PaginationButton>
              </div>
            </div>
          </div>

          <section className="rounded-[10px] border border-slate-200 p-4">
            {selected ? (
              <ChunkRecordDetail chunk={selected} />
            ) : (
              <EmptyState
                title="Select a chunk"
                description="Chunk metadata and full text will appear here."
              />
            )}
          </section>
        </section>

        {selectedDocument && (
          <section className="grid gap-3 rounded-[10px] border border-slate-200 p-4 md:grid-cols-4">
            <ChunkMeta
              label="Parser"
              value={selectedDocument.parser_version || "Runtime default"}
            />
            <ChunkMeta
              label="Chunker"
              value={selectedDocument.chunker_version || "Runtime default"}
            />
            <ChunkMeta
              label="Structure quality"
              value={selectedDocument.structure_quality || "unknown"}
            />
            <ChunkMeta
              label="Indexed at"
              value={
                selectedDocument.indexed_at
                  ? new Date(selectedDocument.indexed_at).toLocaleString()
                  : "Not indexed"
              }
            />
          </section>
        )}
      </div>
    </ScrollSurface>
  )
}

function ChunkStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[8px] bg-slate-50 px-3 py-2">
      <p className="text-[9px] text-slate-500">{label}</p>
      <p
        className="mt-1 truncate text-[12px] font-semibold text-slate-800"
        title={value}
      >
        {value}
      </p>
    </div>
  )
}

function ChunkMeta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[9px] uppercase tracking-[.08em] text-slate-400">
        {label}
      </p>
      <p
        className="mt-1 truncate text-[10px] font-medium text-slate-700"
        title={value}
      >
        {value}
      </p>
    </div>
  )
}

function QasperEvaluationPanel({ run }: { run: QasperDebugRunSummary | null }) {
  if (!run) return <section className="rounded-[10px] border border-cyan-100 p-4"><PanelHeader title="QASPER Evaluation" right="No benchmark run selected" /><p className="mt-3 text-[10px] text-slate-500">Start a QASPER preset from the Datasets tab to see gold evidence and official evaluation metrics here.</p></section>
  const metrics = run.metrics
  const official = (metrics.official_qasper ?? {}) as Record<string, unknown>
  const officialAll = (official.all_evidence ?? {}) as Record<string, unknown>
  const evidence = (metrics.paragraph_evidence ?? {}) as Record<string, unknown>
  const adaptive = (metrics.adaptive_retrieval ?? {}) as Record<string, unknown>
  const performance = (metrics.performance_ms ?? {}) as Record<string, unknown>
  const totalLatency = (performance.total_rag_ms ?? {}) as Record<string, unknown>
  const context = (metrics.context_metrics ?? {}) as Record<string, unknown>
  const values = [
    ["Evidence Recall@10", evidence["Gold Evidence Recall@10"], "rate"],
    ["Official Evidence F1", officialAll["Evidence F1"], "rate"],
    ["Official Answer F1", officialAll["Answer F1"], "rate"],
    ["Premature Stop Rate", adaptive["Premature Stop Rate"], "rate"],
    ["Retrieval p95", totalLatency.p95, "ms"],
    ["Avg Context Tokens", context["Context Tokens"], "number"],
  ] as const
  return <section className="rounded-[10px] border border-cyan-100 p-4"><PanelHeader title="QASPER Evaluation" right={`${run.variant} · ${run.question_count} questions`} /><div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">{values.map(([label, value, format]) => <div key={label} className="rounded-[8px] bg-slate-50 px-3 py-2"><p className="text-[9px] text-slate-500">{label}</p><p className="mt-1 text-[15px] font-semibold">{formatQasperMetric(value, format)}</p></div>)}</div><p className="mt-2 text-[9px] text-slate-500">Official answer/evidence metrics come from the bundled QASPER evaluator. Metrics that the selected variant does not record are shown as —.</p></section>
}

function EvaluationTab({ configs, datasets, qasperRun }: { configs: RagDebugConfigProfile[]; datasets: RagDebugDataset[]; qasperRun: QasperDebugRunSummary | null }) {
  const [datasetId, setDatasetId] = useState("")
  const [configId, setConfigId] = useState("default")
  const [cases, setCases] = useState<RagDebugCase[]>([])
  const [report, setReport] = useState<RagDebugEvaluationResponse["report"] | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState("")
  useEffect(() => { if (datasets.length && !datasets.some((item) => item.dataset_id === datasetId)) setDatasetId(datasets[0].dataset_id) }, [datasets, datasetId])
  useEffect(() => { if (configs.length && !configs.some((item) => item.config_id === configId)) setConfigId(configs[0].config_id) }, [configs, configId])
  useEffect(() => { if (!datasetId) { setCases([]); return } listRagDebugCases(datasetId).then(setCases).catch((reason) => setError(errorText(reason))) }, [datasetId])
  async function run() { if (!datasetId || running) return; setRunning(true); setError(""); try { const result = await evaluateRagDebugDataset({ dataset_id: datasetId, config_id: configId, top_k: 20 }); setReport(result.report) } catch (reason) { setError(errorText(reason)) } finally { setRunning(false) } }
  const retrieval = report?.retrieval ?? {}
  const rows = report?.cases ?? []
  const routingMetrics = [
    { key: "retrieval_trigger_precision", title: "Retrieval Trigger Precision", detail: "Correct retrieval decisions among triggered cases.", icon: <Target size={15} /> },
    { key: "retrieval_trigger_recall", title: "Retrieval Trigger Recall", detail: "Expected retrieval cases that were triggered.", icon: <Target size={15} /> },
    { key: "unnecessary_retrieval_rate", title: "Unnecessary Retrieval Rate", detail: "Retrieval runs for cases that should stay in context.", icon: <X size={15} /> },
    { key: "missing_retrieval_rate", title: "Missing Retrieval Rate", detail: "Cases needing knowledge access but skipped.", icon: <AlertCircle size={15} /> },
    { key: "scope_violation_rate", title: "Scope Violation Rate", detail: "Retrieved evidence outside the resolved scope.", icon: <CheckCircle2 size={15} /> },
    { key: "second_round_retrieval_rate", title: "Second-round Retrieval Rate", detail: "Runs that issued a constrained second query.", icon: <RefreshCw size={15} /> },
    { key: "evidence_sufficiency_rate", title: "Evidence Sufficiency Rate", detail: "Retrieval rounds that met the evidence gate.", icon: <BarChart3 size={15} /> },
  ]
  return <ScrollSurface><div className="mx-auto max-w-[1240px] space-y-4"><QasperEvaluationPanel run={qasperRun} /><section className="rounded-[10px] border border-slate-200 p-4"><div className="grid items-end gap-3 md:grid-cols-[1fr_1fr_140px]"><Field label="Evaluation Dataset"><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} className={selectClass}><option value="">Select a dataset</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.case_count} cases</option>)}</select></Field><Field label="RAG Config"><select value={configId} onChange={(event) => setConfigId(event.target.value)} className={selectClass}>{configs.length ? configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}</option>) : <option value="default">Default</option>}</select></Field><PrimaryButton onClick={run} disabled={!datasetId || !cases.length || running}>{running ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}{running ? "Evaluating" : "Run evaluation"}</PrimaryButton></div></section>{error && <div className="rounded-[10px] border border-rose-200 bg-rose-50 px-4 py-3 text-[11px] text-rose-700">{error}</div>}<div className="grid gap-3 md:grid-cols-4"><MetricCard title="Recall@10" value={percent(retrieval.recall_at_10)} delta={report ? `${Number(retrieval.evaluated_cases ?? 0)} cases` : "—"} detail="Relevant chunks found in the top ten." icon={<Target size={15} />} /><MetricCard title="MRR" value={percent(retrieval.mrr)} delta={report ? "measured" : "—"} detail="Mean reciprocal rank after reranking." icon={<BarChart3 size={15} />} /><MetricCard title="nDCG@10" value={percent(retrieval.ndcg_at_10)} delta={report ? "graded" : "—"} detail="Position-aware relevance quality." icon={<CheckCircle2 size={15} />} /><MetricCard title="No-answer" value={percent(retrieval.no_answer_accuracy)} delta={report ? `${Number(retrieval.no_answer_cases ?? 0)} cases` : "—"} detail="Correctly abstained cases." icon={<HelpCircle size={15} />} /></div><div className="grid gap-3 md:grid-cols-3 xl:grid-cols-7">{routingMetrics.map((metric) => { const rawValue = retrieval[metric.key] ?? report?.[metric.key]; const measured = rawValue !== undefined && rawValue !== null; return <MetricCard key={metric.key} title={metric.title} value={measured ? percent(rawValue) : "—"} delta={measured ? "measured" : "not measured"} deltaTone={measured ? "positive" : "muted"} detail={metric.detail} icon={metric.icon} /> })}</div><section className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center justify-between"><div><h2 className="text-[13px] font-semibold">Case Results</h2><p className="mt-1 text-[10px] text-slate-500">Metrics are calculated from the selected dataset and real retrieval responses.</p></div><span className="text-[10px] text-slate-400">{cases.length} cases</span></div>{!cases.length ? <EmptyState title="No evaluation cases" description="Create or import cases in Datasets before running an evaluation." /> : <div className="mt-3 overflow-hidden rounded-[8px] border border-slate-100"><table className="w-full text-left text-[10px]"><thead className="bg-slate-50 text-slate-500"><tr><th className="px-3 py-2">Query</th><th className="w-28 px-2">Type</th><th className="w-24 px-2">Recall@10</th><th className="w-20 px-2">MRR</th><th className="w-20 px-2">Status</th></tr></thead><tbody>{cases.map((item, index) => { const metric = rows[index] ?? {}; const recall = Number(metric.recall_at_10 ?? 0); return <tr key={item.case_id} className="border-t border-slate-100"><td className="max-w-[480px] truncate px-3 py-2.5 font-medium">{item.query}</td><td className="px-2 text-slate-500">{item.query_type}</td><td className="px-2">{report ? percent(recall) : "—"}</td><td className="px-2">{report ? percent(Number(metric.reciprocal_rank ?? 0)) : "—"}</td><td className="px-2">{report ? <span className="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 size={12} />Measured</span> : <span className="text-slate-400">Pending</span>}</td></tr> })}</tbody></table></div>}</section></div></ScrollSurface>
}

function QasperComparePanel({ runs }: { runs: QasperDebugRunSummary[] }) {
  const completedRuns = useMemo(() => runs.filter((run) => run.status === "completed"), [runs])
  const [baselineId, setBaselineId] = useState("")
  const [candidateId, setCandidateId] = useState("")
  const selectedBaselineId = completedRuns.some((run) => run.run_id === baselineId) ? baselineId : completedRuns[0]?.run_id ?? ""
  const selectedCandidateId = completedRuns.some((run) => run.run_id === candidateId && run.run_id !== selectedBaselineId)
    ? candidateId
    : completedRuns.find((run) => run.run_id !== selectedBaselineId)?.run_id ?? ""
  const baseline = completedRuns.find((run) => run.run_id === selectedBaselineId)
  const candidate = completedRuns.find((run) => run.run_id === selectedCandidateId)
  const metrics = [
    ["Evidence Recall@10", ["paragraph_evidence", "Gold Evidence Recall@10"], "rate"],
    ["Evidence F1@10", ["paragraph_evidence", "Evidence F1@10"], "rate"],
    ["Official Answer F1", ["official_qasper", "all_evidence", "Answer F1"], "rate"],
    ["MRR", ["ai_trans_retrieval", "MRR"], "rate"],
    ["nDCG@10", ["ai_trans_retrieval", "nDCG@10"], "rate"],
    ["Retrieval p95", ["performance_ms", "total_rag_ms", "p95"], "ms"],
    ["Avg Context Tokens", ["context_metrics", "Context Tokens"], "number"],
    ["Retrieval rounds", ["adaptive_retrieval", "Mean Retrieval Rounds"], "number"],
  ] as const
  const answerTypeValues = (run: QasperDebugRunSummary | undefined) => {
    const official = (run?.metrics.official_qasper ?? {}) as Record<string, unknown>
    const all = (official.all_evidence ?? {}) as Record<string, unknown>
    return (all["Answer F1 by type"] ?? {}) as Record<string, unknown>
  }
  const baselineTypes = answerTypeValues(baseline)
  const candidateTypes = answerTypeValues(candidate)
  return (
    <section className="rounded-[10px] border border-cyan-100 p-4">
      <PanelHeader title="QASPER paired run comparison" right="Same question IDs are evaluated from each run" />
      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr]">
        <Field label="Baseline run"><select value={selectedBaselineId} onChange={(event) => setBaselineId(event.target.value)} className={selectClass}><option value="">Choose run</option>{completedRuns.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id} · {run.variant}</option>)}</select></Field>
        <Field label="Candidate run"><select value={selectedCandidateId} onChange={(event) => setCandidateId(event.target.value)} className={selectClass}><option value="">Choose run</option>{completedRuns.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id} · {run.variant}</option>)}</select></Field>
      </div>
      {!baseline || !candidate ? <p className="mt-3 text-[10px] text-slate-500">Complete two QASPER runs to compare retrieval, official scores, latency, context size, and rounds.</p> : <>
        <div className="mt-3 overflow-x-auto rounded-[8px] border border-slate-100"><table className="w-full min-w-[650px] text-left text-[10px]"><thead className="bg-slate-50 text-slate-500"><tr><th className="px-3 py-2">Metric</th><th className="px-3">Baseline</th><th className="px-3">Candidate</th><th className="px-3">Delta</th></tr></thead><tbody>{metrics.map(([label, path, format]) => { const a = qasperMetricAt(baseline.metrics, path); const b = qasperMetricAt(candidate.metrics, path); const delta = typeof a === "number" && typeof b === "number" ? b - a : null; return <tr key={label} className="border-t border-slate-100"><td className="px-3 py-2 font-medium">{label}</td><td className="px-3">{formatQasperMetric(a, format)}</td><td className="px-3">{formatQasperMetric(b, format)}</td><td className="px-3">{delta == null ? "—" : `${delta >= 0 ? "+" : ""}${formatQasperMetric(delta, format)}`}</td></tr> })}</tbody></table></div>
        <div className="mt-3 rounded-[8px] bg-slate-50 p-3"><p className="text-[10px] font-semibold">Per-answer-type delta</p><div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">{["extractive", "abstractive", "boolean", "none"].map((type) => { const a = Number(baselineTypes[type]); const b = Number(candidateTypes[type]); const delta = Number.isFinite(a) && Number.isFinite(b) ? b - a : null; return <span key={type} className="text-[10px] text-slate-600">{type}: {delta == null ? "—" : `${delta >= 0 ? "+" : ""}${formatQasperMetric(delta, "rate")}`}</span> })}</div></div>
      </>}
    </section>
  )
}

function CompareTab({ configs, datasets, qasperRuns }: { configs: RagDebugConfigProfile[]; datasets: RagDebugDataset[]; qasperRuns: QasperDebugRunSummary[] }) {
  const [datasetId, setDatasetId] = useState("")
  const [baselineId, setBaselineId] = useState("default")
  const [candidateId, setCandidateId] = useState("")
  const [result, setResult] = useState<RagDebugCompareResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState("")
  useEffect(() => { if (datasets.length && !datasets.some((item) => item.dataset_id === datasetId)) setDatasetId(datasets[0].dataset_id) }, [datasets, datasetId])
  useEffect(() => { if (configs.length) { if (!configs.some((item) => item.config_id === baselineId)) setBaselineId(configs[0].config_id); if (!candidateId || !configs.some((item) => item.config_id === candidateId)) setCandidateId(configs.find((item) => item.config_id !== baselineId)?.config_id ?? configs[0].config_id) } }, [configs, baselineId, candidateId])
  async function run() { if (!datasetId || !candidateId || running) return; setRunning(true); setError(""); try { setResult(await compareRagDebugDataset({ dataset_id: datasetId, baseline_config_id: baselineId, candidate_config_id: candidateId, top_k: 20 })) } catch (reason) { setError(errorText(reason)) } finally { setRunning(false) } }
  const metrics = result?.metrics ?? {}
  return <ScrollSurface><div className="mx-auto max-w-[1240px] space-y-4"><QasperComparePanel runs={qasperRuns} /><section className="rounded-[10px] border border-slate-200 p-4"><div className="grid items-end gap-3 md:grid-cols-[1fr_1fr_1fr_140px]"><Field label="Dataset"><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} className={selectClass}><option value="">Select a dataset</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name}</option>)}</select></Field><Field label="Baseline"><select value={baselineId} onChange={(event) => setBaselineId(event.target.value)} className={selectClass}>{configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}</option>)}</select></Field><Field label="Candidate"><select value={candidateId} onChange={(event) => setCandidateId(event.target.value)} className={selectClass}>{configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}</option>)}</select></Field><PrimaryButton onClick={run} disabled={!datasetId || !candidateId || running}>{running ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}{running ? "Comparing" : "Compare"}</PrimaryButton></div></section>{error && <div className="rounded-[10px] border border-rose-200 bg-rose-50 px-4 py-3 text-[11px] text-rose-700">{error}</div>}<div className="grid gap-3 md:grid-cols-3"><CompareMetric title="Recall@10" a={percent(Number(metrics.baseline_recall_at_10 ?? 0))} b={percent(Number(metrics.candidate_recall_at_10 ?? 0))} delta={signedPercent(Number(metrics.recall_delta ?? 0))} percent="Candidate − baseline" /><CompareMetric title="Evaluated cases" a={String(metrics.evaluated_cases ?? "—")} b={String(metrics.evaluated_cases ?? "—")} delta="—" percent="Same dataset" /><CompareMetric title="Result" a="Baseline" b="Candidate" delta={Number(metrics.recall_delta ?? 0) >= 0 ? "Improved" : "Regressed"} percent="Top-10 recall" /></div><section className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center justify-between"><div><h2 className="text-[13px] font-semibold">Query Comparison</h2><p className="mt-1 text-[10px] text-slate-500">Each row is generated by running the same query through both profiles.</p></div><span className="text-[10px] text-slate-400">{result?.cases.length ?? 0} comparisons</span></div>{!result?.cases.length ? <EmptyState title="Run a comparison" description="Choose a dataset and two profiles to see rank and latency changes." /> : <div className="mt-3 space-y-2">{result.cases.map((item) => <div key={item.case_id} className="grid gap-2 rounded-[8px] border border-slate-100 px-3 py-3 md:grid-cols-[minmax(0,1fr)_100px_100px_100px]"><div className="min-w-0"><p className="truncate text-[11px] font-semibold">{item.query}</p><p className="mt-1 text-[9px] text-slate-500">{item.case_id} · {item.baseline_latency_ms.toFixed(0)} ms / {item.candidate_latency_ms.toFixed(0)} ms</p></div><MiniStat label="Baseline rank" value={item.baseline_rank ? String(item.baseline_rank) : "—"} /><MiniStat label="Candidate rank" value={item.candidate_rank ? String(item.candidate_rank) : "—"} /><span className={`self-center text-[10px] font-medium ${item.candidate_rank && (!item.baseline_rank || item.candidate_rank < item.baseline_rank) ? "text-emerald-600" : "text-slate-500"}`}>{item.candidate_rank && item.baseline_rank ? item.candidate_rank - item.baseline_rank : "No gold hit"}</span></div>)}</div>}</section></div></ScrollSurface>
}

function QasperBenchmarkPanel({ configs, runs, onRunSelected, onCaseSelected }: { configs: RagDebugConfigProfile[]; runs: QasperDebugRunSummary[]; onRunSelected: (run: QasperDebugRunSummary) => void; onCaseSelected: (item: QasperDebugCase) => void }) {
  const [split, setSplit] = useState<"train" | "validation">("validation")
  const [sampleSize, setSampleSize] = useState<"20" | "100" | "full">("20")
  const [seed, setSeed] = useState("42")
  const [configId, setConfigId] = useState("default")
  const [variant, setVariant] = useState("CURRENT")
  const [includeAnswer, setIncludeAnswer] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState("")
  const [selectedQuestionId, setSelectedQuestionId] = useState("")
  const [caseIndex, setCaseIndex] = useState<{ runId: string; questions: QasperDebugCaseIndex[] } | null>(null)
  const [selectedCase, setSelectedCase] = useState<QasperDebugCase | null>(null)
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState("")
  const [accepted, setAccepted] = useState<QasperDebugRunSummary | null>(null)
  const effectiveRunId = selectedRunId || runs[0]?.run_id || accepted?.run_id || ""
  const activeRun = runs.find((run) => run.run_id === effectiveRunId) ?? (accepted?.run_id === effectiveRunId ? accepted : null)
  const questions = caseIndex && caseIndex.runId === activeRun?.run_id ? caseIndex.questions : []
  const activeRunId = activeRun?.run_id ?? ""
  const activeRunStatus = activeRun?.status ?? ""
  const selectedConfigId = configs.some((item) => item.config_id === configId) ? configId : configs[0]?.config_id ?? "default"
  const activeTask = runs.some((run) => run.status === "queued" || run.status === "running")
  useEffect(() => {
    let disposed = false
    if (!activeRunId || activeRunStatus !== "completed") return () => { disposed = true }
    void listQasperDebugCases(activeRunId).then((items) => {
      if (disposed) return
      setCaseIndex({ runId: activeRunId, questions: items })
      setSelectedQuestionId((current) => current && items.some((item) => item.question_id === current) ? current : items[0]?.question_id ?? "")
    }).catch((reason) => { if (!disposed) setError(errorText(reason)) })
    return () => { disposed = true }
  }, [activeRunId, activeRunStatus])
  useEffect(() => {
    let disposed = false
    if (activeRunStatus !== "completed" || !activeRunId || !selectedQuestionId) return () => { disposed = true }
    void getQasperDebugCase(activeRunId, selectedQuestionId).then((item) => {
      if (disposed) return
      setSelectedCase(item)
      onCaseSelected(item)
    }).catch((reason) => { if (!disposed) setError(errorText(reason)) })
    return () => { disposed = true }
  }, [activeRunId, activeRunStatus, selectedQuestionId, onCaseSelected])
  async function launch() {
    const parsedSeed = Number(seed)
    if (!Number.isInteger(parsedSeed) || parsedSeed < 0 || parsedSeed > 2_147_483_647 || launching) return
    setLaunching(true)
    setError("")
    try {
      const run = await startQasperDebugRun({ split, sample_size: sampleSize, seed: parsedSeed, config_id: selectedConfigId, variant, include_answer: includeAnswer })
      setAccepted(run)
      setSelectedRunId(run.run_id)
      setSelectedQuestionId("")
      setSelectedCase(null)
      onRunSelected(run)
    } catch (reason) { setError(errorText(reason)) } finally { setLaunching(false) }
  }
  return (
    <section className="rounded-[10px] border border-cyan-200 bg-cyan-50/25 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-[13px] font-semibold">QASPER benchmark preset</h2><p className="mt-1 text-[10px] text-slate-500">Run an isolated validation or train benchmark. Gold evidence is mapped from source paragraphs automatically.</p></div>
        {activeRun && <span className="rounded-full bg-white px-2.5 py-1 text-[10px] font-medium text-slate-700">{activeRun.status} · {activeRun.question_count || activeRun.sample_size} questions</span>}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Field label="Split"><select value={split} onChange={(event) => setSplit(event.target.value as "train" | "validation")} className={selectClass}><option value="validation">Validation</option><option value="train">Train</option></select></Field>
        <Field label="Sample"><select value={sampleSize} onChange={(event) => setSampleSize(event.target.value as "20" | "100" | "full")} className={selectClass}><option value="20">20 · smoke</option><option value="100">100 · dev</option><option value="full">Full split</option></select></Field>
        <Field label="Seed"><input type="number" min={0} max={2147483647} value={seed} onChange={(event) => setSeed(event.target.value)} className={inputClass("h-10 w-full")} /></Field>
        <Field label="RAG Config"><select value={selectedConfigId} onChange={(event) => setConfigId(event.target.value)} className={selectClass}>{configs.length ? configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}</option>) : <option value="default">Default</option>}</select></Field>
        <Field label="Variant"><select value={variant} onChange={(event) => setVariant(event.target.value)} className={selectClass}><optgroup label="RAG ablation">{["CURRENT", "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "FULL"].map((item) => <option key={item} value={item}>{item}</option>)}</optgroup><optgroup label="Adaptive retrieval">{["one_shot", "multi_query", "evidence_gated", "requirement_aware"].map((item) => <option key={item} value={`adaptive:${item}`}>{item}</option>)}</optgroup><optgroup label="Evidence selection">{["raw_top_k", "rerank_top_k", "evidence_selection"].map((item) => <option key={item} value={`evidence:${item}`}>{item}</option>)}</optgroup></select></Field>
        <div className="flex items-end"><SecondaryButton onClick={launch} disabled={launching || activeTask || !/^\d+$/.test(seed)}><Play size={13} />{launching ? "Starting…" : "Run QASPER"}</SecondaryButton></div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-slate-500">
        <label className="inline-flex items-center gap-2"><input type="checkbox" checked={includeAnswer} onChange={(event) => setIncludeAnswer(event.target.checked)} className="accent-slate-950" />Generate grounded answers (uses configured provider)</label>
        <span>No QASPER paper is imported into your personal library, and Gold Chunk IDs are not entered by hand.</span>
      </div>
      {error && <p role="alert" className="mt-3 text-[10px] text-rose-700">{error}</p>}
      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,.8fr)_minmax(0,2fr)]">
        <Field label="Benchmark run"><select value={effectiveRunId} onChange={(event) => { const runId = event.target.value; setSelectedRunId(runId); setSelectedQuestionId(""); setSelectedCase(null); setError(""); const run = runs.find((item) => item.run_id === runId) ?? (accepted?.run_id === runId ? accepted : undefined); if (run) onRunSelected(run) }} className={selectClass}><option value="">Select a QASPER run</option>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id} · {run.status} · {run.sample_size}</option>)}{accepted && !runs.some((run) => run.run_id === accepted.run_id) && <option value={accepted.run_id}>{accepted.run_id} · {accepted.status}</option>}</select></Field>
        <Field label="Question Trace"><select value={selectedQuestionId} onChange={(event) => setSelectedQuestionId(event.target.value)} disabled={!questions.length} className={selectClass}><option value="">{activeRun?.status === "completed" ? "Select a question" : "Run must complete first"}</option>{questions.map((item) => <option key={item.question_id} value={item.question_id}>{item.question_id} · {item.question}</option>)}</select></Field>
      </div>
      {selectedCase && <p className="mt-2 text-[10px] text-slate-600">Gold paragraph IDs: {selectedCase.gold_paragraph_ids.join(", ") || "none annotated"} · {selectedCase.no_answer ? "unanswerable" : "answerable"}</p>}
    </section>
  )
}

function DatasetsTab({ datasets, configs, onDatasetsChanged, qasperRuns, onQasperRunSelected, onQasperCaseSelected }: { datasets: RagDebugDataset[]; configs: RagDebugConfigProfile[]; onDatasetsChanged: () => Promise<void>; qasperRuns: QasperDebugRunSummary[]; onQasperRunSelected: (run: QasperDebugRunSummary) => void; onQasperCaseSelected: (item: QasperDebugCase) => void }) {
  const [datasetId, setDatasetId] = useState("")
  const [cases, setCases] = useState<RagDebugCase[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [draft, setDraft] = useState<RagDebugCase | null>(null)
  const [notice, setNotice] = useState("")
  const [error, setError] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => { if (datasets.length && !datasets.some((item) => item.dataset_id === datasetId)) setDatasetId(datasets[0].dataset_id) }, [datasets, datasetId])
  useEffect(() => { if (!datasetId) { setCases([]); setDraft(null); return } listRagDebugCases(datasetId).then((items) => { setCases(items); setSelectedId(items[0]?.case_id ?? ""); setDraft(items[0] ?? null) }).catch((reason) => setError(errorText(reason))) }, [datasetId])
  useEffect(() => { const selected = cases.find((item) => item.case_id === selectedId); if (selected) setDraft(selected) }, [cases, selectedId])
  const dataset = datasets.find((item) => item.dataset_id === datasetId)
  async function newDataset() { const name = window.prompt("Dataset name", "RAG evaluation set"); if (!name?.trim()) return; try { const created = await createRagDebugDataset({ name }); await onDatasetsChanged(); setDatasetId(created.dataset_id); setNotice("Dataset created.") } catch (reason) { setError(errorText(reason)) } }
  async function removeDataset() { if (!datasetId || !window.confirm("Delete this dataset and its cases?")) return; try { await deleteRagDebugDataset(datasetId); await onDatasetsChanged(); setDatasetId(""); setNotice("Dataset deleted.") } catch (reason) { setError(errorText(reason)) } }
  async function save() { if (!datasetId || !draft) return; try { const saved = cases.some((item) => item.case_id === draft.case_id) ? await updateRagDebugCase(datasetId, draft.case_id, draft) : await saveRagDebugCase(datasetId, draft); setCases((items) => [...items.filter((item) => item.case_id !== saved.case_id), saved]); setSelectedId(saved.case_id); setNotice("Case saved.") } catch (reason) { setError(errorText(reason)) } }
  async function removeCase() { if (!datasetId || !draft || !window.confirm("Delete this evaluation case?")) return; try { await deleteRagDebugCase(datasetId, draft.case_id); const next = cases.filter((item) => item.case_id !== draft.case_id); setCases(next); setDraft(next[0] ?? null); setSelectedId(next[0]?.case_id ?? ""); setNotice("Case deleted.") } catch (reason) { setError(errorText(reason)) } }
  async function importFile(file: File) { const content = await file.text(); const format = file.name.toLowerCase().endsWith(".jsonl") ? "jsonl" : "json"; try { const created = await importRagDebugDataset({ name: file.name.replace(/\.(jsonl?|txt)$/i, "") || "Imported dataset", content, format }); await onDatasetsChanged(); setDatasetId(created.dataset_id); setNotice(`${created.case_count} cases imported.`) } catch (reason) { setError(errorText(reason)) } }
  async function exportFile() { if (!datasetId) return; try { const result = await exportRagDebugDataset(datasetId); const url = URL.createObjectURL(new Blob([result.content], { type: "application/json" })); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${result.dataset.name}.json`; anchor.click(); URL.revokeObjectURL(url) } catch (reason) { setError(errorText(reason)) } }
  function createCase() { setDraft({ case_id: `case-${Date.now()}`, query: "", categories: [], relevant_chunk_ids: [], relevance_grades: {}, claims: [], no_answer: false, expected_retrieval: true, expected_scope_document_ids: [], metadata: {}, query_type: "Factual", expected_answer: "", answerable: true, tags: [], notes: "", updated_at: "" }); setSelectedId("") }
  function patchDraft(update: Partial<RagDebugCase>) { setDraft((value) => value ? { ...value, ...update } : value) }
  return <ScrollSurface><div className="mx-auto max-w-[1240px] space-y-4"><QasperBenchmarkPanel configs={configs} runs={qasperRuns} onRunSelected={onQasperRunSelected} onCaseSelected={onQasperCaseSelected} /><section className="flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-slate-200 p-4"><div><h2 className="text-[13px] font-semibold">Evaluation Datasets</h2><p className="mt-1 text-[10px] text-slate-500">Persist retrieval test cases locally and reuse them for evaluation and comparison.</p></div><div className="flex gap-2"><SecondaryButton onClick={newDataset}><Plus size={13} />New dataset</SecondaryButton><SecondaryButton onClick={() => inputRef.current?.click()}><Upload size={13} />Import JSON/JSONL</SecondaryButton><input ref={inputRef} type="file" accept=".json,.jsonl,application/json" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importFile(file); event.currentTarget.value = "" }} /><SecondaryButton onClick={() => void exportFile()} disabled={!datasetId}><Download size={13} />Export</SecondaryButton></div></section><div className="grid min-h-[520px] gap-4 lg:grid-cols-[300px_minmax(0,1fr)]"><section className="rounded-[10px] border border-slate-200 p-3"><PanelHeader title="Evaluation Cases" right={dataset ? `${cases.length} cases` : undefined} />{datasets.length === 0 ? <EmptyState title="No datasets" description="Create a dataset or import JSON/JSONL cases." /> : <div className="mt-3 space-y-1">{datasets.map((item) => <button key={item.dataset_id} type="button" onClick={() => setDatasetId(item.dataset_id)} className={`flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left text-[10px] ${datasetId === item.dataset_id ? "bg-slate-100 font-semibold" : "hover:bg-slate-50"}`}><Database size={13} /><span className="min-w-0 flex-1 truncate">{item.name}</span><span className="text-slate-400">{item.case_count}</span></button>)}{dataset && <div className="mt-4 border-t border-slate-100 pt-3"><button type="button" onClick={createCase} className="flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left text-[10px] text-slate-600 hover:bg-slate-50"><Plus size={13} />New case</button><button type="button" onClick={() => void removeDataset()} className="flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left text-[10px] text-rose-600 hover:bg-rose-50"><Trash2 size={13} />Delete dataset</button></div>}{cases.map((item) => <button key={item.case_id} type="button" onClick={() => setSelectedId(item.case_id)} className={`mt-1 block w-full truncate rounded-[7px] px-2 py-2 text-left text-[10px] ${selectedId === item.case_id ? "bg-slate-50 font-semibold" : "text-slate-600 hover:bg-slate-50"}`}>{item.query || item.case_id}</button>)}</div>}</section><section className="rounded-[10px] border border-slate-200">{draft ? <><PanelHeader title="Case Details" right={<span>{draft.case_id}</span>} /><div className="ait-scroll-page max-h-[560px] space-y-3 overflow-y-auto p-4"><EditorLabel label="Query" required><textarea value={draft.query} onChange={(event) => patchDraft({ query: event.target.value })} rows={3} className={inputClass("w-full resize-none py-2.5 text-[10px]")} /></EditorLabel><EditorLabel label="Query Type"><select value={draft.query_type} onChange={(event) => patchDraft({ query_type: event.target.value })} className={selectClass}><option>Factual</option><option>Analytical</option><option>Comparative</option><option>Creative</option></select></EditorLabel><EditorLabel label="Gold Chunk IDs"><input value={draft.relevant_chunk_ids.join(", ")} onChange={(event) => patchDraft({ relevant_chunk_ids: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="chunk_id_1, chunk_id_2" className={inputClass("h-9 w-full text-[10px]")} /></EditorLabel><EditorLabel label="Expected Answer"><textarea value={draft.expected_answer} onChange={(event) => patchDraft({ expected_answer: event.target.value })} rows={5} className={inputClass("w-full resize-none py-2.5 text-[10px]")} /></EditorLabel><label className="flex items-center gap-2 text-[10px] text-slate-700"><input type="checkbox" checked={draft.answerable} onChange={(event) => patchDraft({ answerable: event.target.checked, no_answer: !event.target.checked })} className="accent-slate-950" />Answerable</label><EditorLabel label="Tags"><input value={draft.tags.join(", ")} onChange={(event) => patchDraft({ tags: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="retrieval, multilingual" className={inputClass("h-9 w-full text-[10px]")} /></EditorLabel><EditorLabel label="Notes"><textarea value={draft.notes} onChange={(event) => patchDraft({ notes: event.target.value })} rows={3} className={inputClass("w-full resize-none text-[10px]")} /></EditorLabel></div><div className="flex items-center justify-end gap-2 border-t border-slate-100 p-3"><SecondaryButton onClick={() => void removeCase()}><Trash2 size={13} />Delete</SecondaryButton><PrimaryButton onClick={() => void save()}><Save size={13} />Save Changes</PrimaryButton></div></> : <EmptyState title="Select or create a case" description="Cases are stored in the local RAG Debug Studio database." />}</section></div>{error && <div className="rounded-[10px] border border-rose-200 bg-rose-50 px-4 py-3 text-[11px] text-rose-700">{error}</div>}{notice && <div className="rounded-[10px] bg-slate-950 px-4 py-2.5 text-[11px] text-white">{notice}</div>}</div></ScrollSurface>
}

function StagePill({ stage, active }: { stage: RagDebugStage; active: boolean }) { const icon = stage.status === "complete" ? <CheckCircle2 size={13} className="text-emerald-600" /> : stage.status === "failed" ? <AlertCircle size={13} className="text-rose-600" /> : stage.status === "active" || active ? <LoaderCircle size={13} className="animate-spin text-slate-950" /> : <span className="h-2 w-2 rounded-full border border-slate-300" />; return <div className={`flex min-w-0 items-center gap-1.5 rounded-[7px] border px-2 py-2 ${active ? "border-slate-950 bg-slate-50" : "border-slate-100"}`} title={stage.note}><span className="shrink-0">{icon}</span><span className="min-w-0 truncate text-[9px] font-medium">{stage.label}</span></div> }
function ResultTable({ rows, selectedId, onSelect }: { rows: RagDebugCandidate[]; selectedId: string; onSelect: (id: string) => void }) { return <div className="mt-3 overflow-hidden rounded-[8px] border border-slate-100"><table className="w-full table-fixed text-left text-[10px]"><thead className="bg-slate-50 text-slate-500"><tr><th className="w-8 px-2 py-2">#</th><th className="w-[135px] px-2">Chunk ID</th><th className="w-[70px] px-2">Score</th><th className="w-[64px] px-2">Δ Rank</th><th className="px-2">Source</th><th className="w-[90px] px-2">Section</th></tr></thead><tbody>{rows.map((row, index) => { const delta = (row.before ?? row.after ?? index + 1) - (row.after ?? index + 1); return <tr key={row.id} onClick={() => onSelect(row.id)} className={`cursor-pointer border-t border-slate-100 transition ${selectedId === row.id ? "bg-slate-100" : "hover:bg-slate-50"}`}><td className="px-2 py-2.5 text-slate-500">{row.after ?? index + 1}</td><td className="truncate px-2 font-medium">{row.id}</td><td className="px-2 tabular-nums">{formatScore(row.rerank ?? row.fusion ?? row.dense ?? row.bm25)}</td><td className="px-2">{delta === 0 ? <span className="text-slate-400">—</span> : delta > 0 ? <span className="inline-flex items-center gap-1 text-emerald-600"><ArrowUp size={10} />{delta}</span> : <span className="inline-flex items-center gap-1 text-rose-500"><ArrowDown size={10} />{Math.abs(delta)}</span>}</td><td className="truncate px-2 text-slate-600">{row.source || row.document_id}</td><td className="truncate px-2 text-slate-600">{row.section || "—"}</td></tr> })}</tbody></table></div> }
function ChunkDetail({ row, index, total, previous, next }: { row: RagDebugCandidate; index: number; total: number; previous: () => void; next: () => void }) { const [copied, setCopied] = useState(false); function copy() { if (navigator.clipboard) void navigator.clipboard.writeText(row.id); setCopied(true); window.setTimeout(() => setCopied(false), 800) }; return <div><div className="flex items-center justify-between border-b border-slate-100 pb-3"><h2 className="text-[13px] font-semibold">Chunk Detail</h2><div className="flex items-center gap-1 text-[10px] text-slate-500"><button type="button" onClick={previous} className="rounded border border-slate-200 p-1"><ChevronLeft size={13} /></button><span>{index + 1} of {total}</span><button type="button" onClick={next} className="rounded border border-slate-200 p-1"><ChevronRight size={13} /></button></div></div><dl className="grid grid-cols-[92px_1fr] gap-x-2 gap-y-2 border-b border-slate-100 py-3 text-[10px]"><dt className="text-slate-500">Chunk ID</dt><dd className="flex items-center gap-1 font-medium"><span className="truncate">{row.id}</span><button type="button" onClick={copy} aria-label="Copy chunk ID" className="text-slate-400">{copied ? <Check size={11} /> : <Copy size={11} />}</button></dd><dt className="text-slate-500">Source</dt><dd>{row.source || row.document_id}</dd><dt className="text-slate-500">Section</dt><dd className="truncate">{row.section || "—"}</dd><dt className="text-slate-500">Page</dt><dd>{row.page ?? "—"}</dd><dt className="text-slate-500">Tokens</dt><dd>{row.tokens}</dd><dt className="text-slate-500">Score</dt><dd>{formatScore(row.rerank ?? row.fusion ?? row.dense ?? row.bm25)}</dd><dt className="text-slate-500">Original Rank</dt><dd>{row.before ?? "—"}</dd><dt className="text-slate-500">Rerank Position</dt><dd>{row.after ?? "—"}</dd></dl><h3 className="mt-3 text-[11px] font-semibold">Chunk Text</h3><div className="ait-scroll-page mt-2 max-h-[230px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-2.5 text-[10px] leading-[1.6] text-slate-700">{row.text || "No text returned by the index."}</div></div> }
function ChunkRecordDetail({ chunk }: { chunk: RagDebugChunk }) { const [copied, setCopied] = useState(false); function copy() { if (navigator.clipboard) void navigator.clipboard.writeText(chunk.id); setCopied(true); window.setTimeout(() => setCopied(false), 800) }; return <div><div className="flex items-center justify-between border-b border-slate-100 pb-3"><h2 className="text-[13px] font-semibold">Chunk Detail</h2><button type="button" aria-label="Copy chunk ID" onClick={copy} className="text-slate-400">{copied ? <Check size={13} /> : <Copy size={13} />}</button></div><dl className="grid grid-cols-[92px_1fr] gap-x-2 gap-y-2 border-b border-slate-100 py-3 text-[10px]"><dt className="text-slate-500">Chunk ID</dt><dd className="truncate font-medium">{chunk.id}</dd><dt className="text-slate-500">Document</dt><dd>{chunk.document_id}</dd><dt className="text-slate-500">Section</dt><dd>{chunk.section || "—"}</dd><dt className="text-slate-500">Page</dt><dd>{chunk.page ?? "—"}</dd><dt className="text-slate-500">Type</dt><dd>{chunk.type || "—"}</dd><dt className="text-slate-500">Tokens</dt><dd>{chunk.tokens}</dd><dt className="text-slate-500">Overlap</dt><dd>{chunk.overlap || "—"}</dd><dt className="text-slate-500">Character range</dt><dd>{chunk.start.toLocaleString()} – {chunk.end.toLocaleString()}</dd><dt className="text-slate-500">Embedding model</dt><dd className="truncate">{chunk.embedding || "—"}</dd></dl><h3 className="mt-3 text-[11px] font-semibold">Chunk Text</h3><div className="ait-scroll-page mt-2 max-h-[290px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-3 text-[10px] leading-[1.7] text-slate-700">{chunk.text}</div></div> }
function MetricCard({ title, value, delta, detail, icon, deltaTone = "positive" }: { title: string; value: string; delta: string; detail: string; icon: ReactNode; deltaTone?: "positive" | "muted" }) { return <section className="rounded-[10px] border border-slate-200 p-4 transition hover:shadow-[0_4px_16px_rgba(15,23,42,.05)]"><div className="flex items-start justify-between"><h2 className="text-[12px] font-semibold">{title}</h2><span className="text-slate-600">{icon}</span></div><div className="mt-2 flex items-end gap-3"><span className="text-[25px] font-semibold tracking-tight">{value}</span><span className={`mb-1 text-[11px] font-medium ${deltaTone === "muted" ? "text-slate-400" : "text-emerald-600"}`}>{delta}</span></div><p className="mt-1 text-[10px] text-slate-500">{detail}</p></section> }
function CompareMetric({ title, a, b, delta, percent: label }: { title: string; a: string; b: string; delta: string; percent: string }) { return <section className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center gap-1"><h2 className="text-[12px] font-semibold">{title}</h2><HelpCircle size={12} className="text-slate-400" /></div><div className="mt-3 grid grid-cols-[1fr_1fr_1.15fr] divide-x divide-slate-100"><div><p className="text-[9px] text-slate-500">A</p><p className="mt-1 text-[18px] font-semibold">{a}</p></div><div className="pl-4"><p className="text-[9px] text-slate-500">B</p><p className="mt-1 text-[18px] font-semibold">{b}</p></div><div className="pl-4"><p className="text-[9px] text-slate-500">Δ</p><p className="mt-1 text-[18px] font-semibold text-emerald-600">{delta}</p><p className="text-[10px] text-emerald-600">{label}</p></div></div></section> }
function MiniStat({ label, value }: { label: string; value: string }) { return <div className="px-3 first:pl-0"><p className="text-[9px] text-slate-500">{label}</p><p className="mt-1 text-[13px] font-semibold">{value}</p></div> }
function ScrollSurface({ children }: { children: ReactNode }) { return <div className="ait-scroll-page h-full min-h-0 overflow-y-auto px-8 py-5">{children}</div> }
const inputClass = (extra = "") => `rounded-[8px] border border-slate-200 bg-white px-3 text-[12px] text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-900/5 ${extra}`
const selectClass = "h-10 w-full rounded-[8px] border border-slate-200 bg-white px-3 text-[12px] text-slate-800 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-900/5"
const smallSelectClass = "mt-1 h-9 w-full rounded-[8px] border border-slate-200 bg-white px-2 text-[10px] text-slate-700 outline-none"
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="block min-w-0"><span className="mb-1.5 block text-[11px] font-semibold text-slate-700">{label}</span>{children}</label> }
function EditorLabel({ label, required = false, children }: { label: string; required?: boolean; children: ReactNode }) { return <label className="block"><span className="mb-1.5 block text-[10px] font-medium text-slate-800">{label}{required && <span className="text-rose-500"> *</span>}</span>{children}</label> }
function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) { return <label className="text-[10px] text-slate-600">{label}<input type="number" min={1} value={value} onChange={(event) => onChange(Math.max(1, Number(event.target.value) || 1))} className={inputClass("mt-1 h-9 w-full text-[10px]")} /></label> }
function PrimaryButton({ children, onClick, disabled = false }: { children: ReactNode; onClick?: () => void | Promise<void>; disabled?: boolean }) { return <button type="button" onClick={() => void onClick?.()} disabled={disabled} className="inline-flex h-10 items-center justify-center gap-2 rounded-[8px] bg-slate-950 px-4 text-[11px] font-semibold text-white transition hover:bg-slate-800 active:scale-[.985] disabled:bg-slate-300">{children}</button> }
function SecondaryButton({ children, onClick, disabled = false }: { children: ReactNode; onClick?: () => void | Promise<void>; disabled?: boolean }) { return <button type="button" onClick={() => void onClick?.()} disabled={disabled} className="inline-flex h-10 items-center justify-center gap-2 rounded-[8px] border border-slate-300 bg-white px-4 text-[11px] font-semibold text-slate-800 transition hover:bg-slate-50 active:scale-[.985] disabled:opacity-40">{children}</button> }
function PanelHeader({ title, right }: { title: string; right?: ReactNode }) { return <div className="flex items-center justify-between border-b border-slate-100 px-1 pb-3"><h2 className="text-[13px] font-semibold">{title}</h2><div className="text-[10px] text-slate-500">{right}</div></div> }
function PaginationButton({ children, disabled, onClick }: { children: ReactNode; disabled?: boolean; onClick?: () => void }) { return <button type="button" disabled={disabled} onClick={onClick} className="flex h-7 min-w-7 items-center justify-center rounded-[7px] px-2 text-[10px] text-slate-600 hover:bg-slate-50 disabled:opacity-30">{children}</button> }
function EmptyState({ title, description, loading = false }: { title: string; description: string; loading?: boolean }) { return <div className="flex min-h-[220px] flex-col items-center justify-center text-center"><span className="text-slate-300">{loading ? <LoaderCircle size={22} className="animate-spin" /> : <Search size={22} />}</span><p className="mt-3 text-[12px] font-semibold text-slate-700">{title}</p><p className="mt-1 max-w-[300px] text-[10px] text-slate-500">{description}</p></div> }
function formatScore(value: number | null | undefined) { return value == null || !Number.isFinite(value) ? "—" : value.toFixed(Math.abs(value) > 2 ? 2 : 3) }
function formatMs(value: number) { return Number.isFinite(value) && value > 0 ? `${value.toFixed(0)} ms` : "—" }
function qasperMetricAt(metrics: Record<string, unknown>, path: readonly string[]): number | null { let value: unknown = metrics; for (const key of path) { if (!value || typeof value !== "object") return null; value = (value as Record<string, unknown>)[key] } return typeof value === "number" && Number.isFinite(value) ? value : null }
function formatQasperMetric(value: unknown, format: "rate" | "ms" | "number"): string { if (value == null || typeof value !== "number" || !Number.isFinite(value)) return "—"; if (format === "rate") return `${(value * 100).toFixed(1)}%`; if (format === "ms") return `${value.toFixed(1)} ms`; return value.toFixed(1) }
function percent(value: unknown) { const number = Number(value ?? 0); return Number.isFinite(number) ? `${(number * 100).toFixed(0)}%` : "—" }
function signedPercent(value: number) { return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%` }
function errorText(reason: unknown) { return reason instanceof Error ? reason.message : "Request failed." }
