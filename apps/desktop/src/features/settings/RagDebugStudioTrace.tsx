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
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"

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
  listRagDebugConfigs,
  listRagDebugDatasets,
  listRagDebugDocuments,
  type RagConfig,
  type RagDebugCase,
  type RagDebugCandidate,
  type RagDebugChunk,
  type RagDebugCompareResponse,
  type RagDebugConfigProfile,
  type RagDebugDataset,
  type RagDebugEvaluationResponse,
  type RagDebugStage,
  type RagDebugTraceResponse,
  saveRagDebugCase,
  startRagDebugRun,
  updateRagDebugCase,
  updateRagDebugConfig,
} from "../../api/rag-debug"

type RagTab = "trace" | "chunks" | "evaluation" | "compare" | "datasets"

const TABS: Array<{ id: RagTab; label: string }> = [
  { id: "trace", label: "Trace" },
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
  { key: "fusion", label: "Fusion", status: "pending", elapsed_ms: 0, note: "Merge retrieval lists with the configured strategy", summary: {}, candidate_count: 0 },
  { key: "rerank", label: "Rerank", status: "pending", elapsed_ms: 0, note: "Apply the configured reranker when available", summary: {}, candidate_count: 0 },
  { key: "context", label: "Context Building", status: "pending", elapsed_ms: 0, note: "Build bounded grounded context", summary: {}, candidate_count: 0 },
  { key: "answer", label: "Answer Generation", status: "pending", elapsed_ms: 0, note: "Optional answer generation from context", summary: {}, candidate_count: 0 },
]

export default function RagDebugStudioTrace() {
  const [activeTab, setActiveTab] = useState<RagTab>("trace")
  const [configs, setConfigs] = useState<RagDebugConfigProfile[]>([])
  const [datasets, setDatasets] = useState<RagDebugDataset[]>([])
  const [baseError, setBaseError] = useState("")

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

      <div key={activeTab} className="min-h-0 flex-1 animate-[ragFadeIn_.18s_ease-out]">
        {activeTab === "trace" && <TraceTab configs={configs} onConfigsChanged={refreshBaseData} />}
        {activeTab === "chunks" && <ChunksTab />}
        {activeTab === "evaluation" && <EvaluationTab configs={configs} datasets={datasets} />}
        {activeTab === "compare" && <CompareTab configs={configs} datasets={datasets} />}
        {activeTab === "datasets" && <DatasetsTab datasets={datasets} onDatasetsChanged={refreshBaseData} />}
      </div>
    </section>
  )
}

function TraceTab({ configs, onConfigsChanged }: { configs: RagDebugConfigProfile[]; onConfigsChanged: () => Promise<void> }) {
  const [query, setQuery] = useState("")
  const [configId, setConfigId] = useState("default")
  const [topK, setTopK] = useState(8)
  const [includeAnswer, setIncludeAnswer] = useState(false)
  const [trace, setTrace] = useState<RagDebugTraceResponse | null>(null)
  const [selectedId, setSelectedId] = useState("")
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState("")
  const mounted = useRef(true)

  useEffect(() => () => { mounted.current = false }, [])
  useEffect(() => {
    if (configs.length && !configs.some((item) => item.config_id === configId)) setConfigId(configs[0].config_id)
  }, [configs, configId])

  const selectedConfig = configs.find((item) => item.config_id === configId) ?? configs[0]
  const candidates = trace?.candidates ?? []
  const selectedIndex = Math.max(0, candidates.findIndex((item) => item.id === selectedId))
  const selected = candidates[selectedIndex]
  const activeStage = trace?.stages.find((item) => item.status === "active")?.key ?? ""

  async function run() {
    if (!query.trim() || running) return
    setRunning(true)
    setNotice("")
    try {
      const accepted = await startRagDebugRun({ query: query.trim(), config_id: configId, top_k: topK, include_answer: includeAnswer })
      let next = await getRagDebugRun(accepted.run_id)
      if (mounted.current) setTrace(next)
      while (next.status === "queued" || next.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 180))
        next = await getRagDebugRun(accepted.run_id)
        if (mounted.current) setTrace(next)
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
      setTrace(cancelled)
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
            <label className="text-[12px] font-semibold text-slate-800">Query</label>
            {selectedConfig?.requires_reindex && <span className="rounded-full bg-amber-50 px-2 py-1 text-[9px] text-amber-800">Index rebuild required for indexed config changes</span>}
          </div>
          <textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={2} placeholder="Ask a question against the indexed knowledge base…" className={inputClass("mt-2 w-full resize-none py-2.5")} />
          <div className="mt-4 grid items-end gap-3 lg:grid-cols-[1fr_1fr_120px_148px]">
            <Field label="Workspace"><select className={selectClass} defaultValue="workspace"><option value="workspace">My Workspace</option><option value="all">All indexed documents</option></select></Field>
            <Field label="RAG Config"><div className="flex gap-2"><select value={configId} onChange={(event) => setConfigId(event.target.value)} className={selectClass}>{configs.length ? configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}{item.active ? " · active" : ""}</option>) : <option value="default">Default</option>}</select><button type="button" title="Duplicate selected profile" aria-label="Duplicate selected profile" onClick={async () => { if (!selectedConfig) return; const name = window.prompt("New RAG profile name", `${selectedConfig.name} copy`); if (!name?.trim()) return; await createRagDebugConfig({ name, description: selectedConfig.description, config: selectedConfig.config }); await onConfigsChanged() }} className="rounded-[8px] border border-slate-200 px-2.5 text-slate-600 hover:bg-slate-50"><Plus size={14} /></button></div></Field>
            <Field label="Top K"><select value={topK} onChange={(event) => setTopK(Number(event.target.value))} className={selectClass}>{[5, 8, 10, 20].map((value) => <option key={value} value={value}>{value}</option>)}</select></Field>
            <PrimaryButton onClick={running ? stop : run} disabled={!running && !query.trim()}>{running ? <><X size={14} />Stop</> : <><Play size={14} fill="currentColor" />Run trace</>}</PrimaryButton>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-slate-500">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={includeAnswer} onChange={(event) => setIncludeAnswer(event.target.checked)} className="accent-slate-950" />Include optional answer generation</label>
            {selectedConfig && <><span>Embedding: {String(selectedConfig.config.embedding.model ?? "configured")}</span><span>Fusion: {selectedConfig.config.retrieval.fusion}</span><button type="button" onClick={async () => { await activateRagDebugConfig(selectedConfig.config_id); await onConfigsChanged(); setNotice(`${selectedConfig.name} is now the active profile.`) }} className="font-medium text-slate-800 underline underline-offset-2">Use this profile</button></>}
          </div>
        </section>

        <ConfigTuningPanel config={selectedConfig} onSaved={onConfigsChanged} onNotice={setNotice} />

        <section className="rounded-[10px] border border-slate-200 px-4 py-4">
          <div className="grid grid-cols-4 gap-2 md:grid-cols-8">{(trace?.stages ?? INITIAL_STAGES).map((item) => <StagePill key={item.key} stage={item} active={activeStage === item.key} />)}</div>
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

function ConfigTuningPanel({ config, onSaved, onNotice }: { config?: RagDebugConfigProfile; onSaved: () => Promise<void>; onNotice: (value: string) => void }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState({ dense_top_k: 30, sparse_top_k: 30, fusion_top_k: 20, final_top_k: 8, fusion: "rrf", small_to_big_enabled: true })
  useEffect(() => { if (config) setDraft({ dense_top_k: config.config.retrieval.dense_top_k, sparse_top_k: config.config.retrieval.sparse_top_k, fusion_top_k: config.config.retrieval.fusion_top_k, final_top_k: config.config.retrieval.final_top_k, fusion: config.config.retrieval.fusion, small_to_big_enabled: config.config.retrieval.small_to_big_enabled }) }, [config])
  if (!config) return null
  const profile = config
  async function save() { const nextConfig: RagConfig = { ...profile.config, retrieval: { ...profile.config.retrieval, ...draft } }; await updateRagDebugConfig(profile.config_id, { config: nextConfig }); await onSaved(); onNotice("RAG profile saved. Indexed-field changes are marked for reindexing.") }
  return <section className="rounded-[10px] border border-slate-200"><button type="button" onClick={() => setOpen((value) => !value)} className="flex w-full items-center justify-between px-4 py-3 text-left"><span className="inline-flex items-center gap-2 text-[12px] font-semibold"><SlidersHorizontal size={14} />Retrieval tuning · {profile.name}</span><ChevronDown size={14} className={`transition-transform ${open ? "rotate-180" : ""}`} /></button>{open && <div className="grid gap-3 border-t border-slate-100 px-4 py-4 md:grid-cols-5"><NumberField label="Dense top K" value={draft.dense_top_k} onChange={(value) => setDraft({ ...draft, dense_top_k: value })} /><NumberField label="BM25 top K" value={draft.sparse_top_k} onChange={(value) => setDraft({ ...draft, sparse_top_k: value })} /><NumberField label="Fusion top K" value={draft.fusion_top_k} onChange={(value) => setDraft({ ...draft, fusion_top_k: value })} /><NumberField label="Final top K" value={draft.final_top_k} onChange={(value) => setDraft({ ...draft, final_top_k: value })} /><label className="text-[10px] text-slate-600">Fusion<select value={draft.fusion} onChange={(event) => setDraft({ ...draft, fusion: event.target.value })} className={smallSelectClass}><option value="rrf">RRF</option></select></label><label className="inline-flex items-center gap-2 text-[10px] text-slate-600"><input type="checkbox" checked={draft.small_to_big_enabled} onChange={(event) => setDraft({ ...draft, small_to_big_enabled: event.target.checked })} className="accent-slate-950" />Small-to-big context</label><div className="md:col-span-5 flex justify-end gap-2"><SecondaryButton onClick={() => setOpen(false)}>Cancel</SecondaryButton><PrimaryButton onClick={save}><Save size={13} />Save profile</PrimaryButton></div></div>}</section>
}

function ChunksTab() {
  const [documents, setDocuments] = useState<Array<{ document_id: string; title: string; chunk_count: number; status: string }>>([])
  const [documentId, setDocumentId] = useState("")
  const [query, setQuery] = useState("")
  const [page, setPage] = useState(1)
  const [chunks, setChunks] = useState<RagDebugChunk[]>([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<RagDebugChunk | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  useEffect(() => { listRagDebugDocuments().then(setDocuments).catch((reason) => setError(errorText(reason))) }, [])
  useEffect(() => { let disposed = false; setLoading(true); listRagDebugChunks({ documentId, query, page, pageSize: 50 }).then((result) => { if (!disposed) { setChunks(result.chunks); setTotal(result.total); setSelected(result.chunks[0] ?? null) } }).catch((reason) => { if (!disposed) setError(errorText(reason)) }).finally(() => { if (!disposed) setLoading(false) }); return () => { disposed = true } }, [documentId, query, page])
  const sectionCounts = useMemo(() => chunks.reduce<Record<string, number>>((acc, chunk) => { acc[chunk.section || "Unsectioned"] = (acc[chunk.section || "Unsectioned"] ?? 0) + 1; return acc }, {}), [chunks])
  return <ScrollSurface><div className="mx-auto max-w-[1240px] space-y-4"><section className="grid min-h-[540px] gap-4 lg:grid-cols-[260px_minmax(0,1fr)_300px]"><div className="rounded-[10px] border border-slate-200 p-3"><PanelHeader title="Document Structure" right={<span>{documents.length} documents</span>} />{documents.length === 0 ? <EmptyState title="No indexed documents" description="Import a document in Knowledge before exploring chunks." /> : <div className="mt-3 space-y-1">{documents.map((document) => <button key={document.document_id} type="button" onClick={() => { setDocumentId(document.document_id); setPage(1) }} className={`flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left text-[10px] ${documentId === document.document_id ? "bg-slate-100 font-semibold" : "hover:bg-slate-50"}`}><FileText size={13} /><span className="min-w-0 flex-1 truncate">{document.title || document.document_id}</span><span className="text-slate-400">{document.chunk_count}</span></button>)}<div className="mt-4 border-t border-slate-100 pt-3"><p className="px-2 text-[9px] font-semibold uppercase tracking-[.08em] text-slate-400">Sections on this page</p>{Object.entries(sectionCounts).map(([label, count]) => <div key={label} className="flex items-center justify-between px-2 py-1.5 text-[10px] text-slate-600"><span className="min-w-0 truncate">{label}</span><span className="text-slate-400">{count}</span></div>)}</div></div>}</div><div className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center justify-between"><div><h2 className="text-[13px] font-semibold">Chunks</h2><p className="mt-1 text-[10px] text-slate-500">Inspect the chunks persisted by the active index.</p></div><span className="text-[10px] text-slate-400">{total} total</span></div><div className="mt-3 flex gap-2"><div className="relative min-w-0 flex-1"><Search className="absolute left-3 top-2.5 text-slate-400" size={14} /><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1) }} placeholder="Search chunk text…" className={inputClass("h-9 w-full pl-9 text-[10px]")} /></div><button type="button" onClick={() => setPage(1)} className="rounded-[8px] border border-slate-200 px-3 text-slate-500 hover:bg-slate-50"><RefreshCw size={13} /></button></div>{error && <div className="mt-3 text-[10px] text-rose-600">{error}</div>}{loading ? <EmptyState title="Loading chunks…" description="Reading the local chunk catalogue." loading /> : chunks.length === 0 ? <EmptyState title="No chunks found" description="Try another document or search query." /> : <div className="mt-3 space-y-2">{chunks.map((chunk) => <button key={chunk.id} type="button" onClick={() => setSelected(chunk)} className={`block w-full rounded-[8px] border px-3 py-3 text-left transition ${selected?.id === chunk.id ? "border-slate-950 bg-slate-50" : "border-slate-100 hover:border-slate-300"}`}><div className="flex items-start gap-2"><FileText size={14} className="mt-0.5 shrink-0 text-slate-500" /><div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-3"><h3 className="truncate text-[11px] font-semibold">{chunk.title || chunk.id}</h3><span className="shrink-0 text-[9px] text-slate-400">{chunk.page ? `p. ${chunk.page}` : ""}</span></div><p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-500">{chunk.preview}</p><div className="mt-2 flex gap-3 text-[9px] text-slate-400"><span>{chunk.tokens} tokens</span><span>{chunk.type}</span><span>{chunk.id}</span></div></div></div></button>)}</div>}<div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-[10px] text-slate-500"><span>Page {page} · {Math.max(1, Math.ceil(total / 50))}</span><div className="flex gap-1"><PaginationButton disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={13} /></PaginationButton><PaginationButton disabled={page >= Math.ceil(total / 50)} onClick={() => setPage((value) => value + 1)}><ChevronRight size={13} /></PaginationButton></div></div></div><section className="rounded-[10px] border border-slate-200 p-4">{selected ? <ChunkRecordDetail chunk={selected} /> : <EmptyState title="Select a chunk" description="Chunk metadata and full text will appear here." />}</section></section></div></ScrollSurface>
}

function EvaluationTab({ configs, datasets }: { configs: RagDebugConfigProfile[]; datasets: RagDebugDataset[] }) {
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
  return <ScrollSurface><div className="mx-auto max-w-[1240px] space-y-4"><section className="rounded-[10px] border border-slate-200 p-4"><div className="grid items-end gap-3 md:grid-cols-[1fr_1fr_140px]"><Field label="Evaluation Dataset"><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} className={selectClass}><option value="">Select a dataset</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.case_count} cases</option>)}</select></Field><Field label="RAG Config"><select value={configId} onChange={(event) => setConfigId(event.target.value)} className={selectClass}>{configs.length ? configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}</option>) : <option value="default">Default</option>}</select></Field><PrimaryButton onClick={run} disabled={!datasetId || !cases.length || running}>{running ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}{running ? "Evaluating" : "Run evaluation"}</PrimaryButton></div></section>{error && <div className="rounded-[10px] border border-rose-200 bg-rose-50 px-4 py-3 text-[11px] text-rose-700">{error}</div>}<div className="grid gap-3 md:grid-cols-4"><MetricCard title="Recall@10" value={percent(retrieval.recall_at_10)} delta={report ? `${Number(retrieval.evaluated_cases ?? 0)} cases` : "—"} detail="Relevant chunks found in the top ten." icon={<Target size={15} />} /><MetricCard title="MRR" value={percent(retrieval.mrr)} delta={report ? "measured" : "—"} detail="Mean reciprocal rank after reranking." icon={<BarChart3 size={15} />} /><MetricCard title="nDCG@10" value={percent(retrieval.ndcg_at_10)} delta={report ? "graded" : "—"} detail="Position-aware relevance quality." icon={<CheckCircle2 size={15} />} /><MetricCard title="No-answer" value={percent(retrieval.no_answer_accuracy)} delta={report ? `${Number(retrieval.no_answer_cases ?? 0)} cases` : "—"} detail="Correctly abstained cases." icon={<HelpCircle size={15} />} /></div><section className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center justify-between"><div><h2 className="text-[13px] font-semibold">Case Results</h2><p className="mt-1 text-[10px] text-slate-500">Metrics are calculated from the selected dataset and real retrieval responses.</p></div><span className="text-[10px] text-slate-400">{cases.length} cases</span></div>{!cases.length ? <EmptyState title="No evaluation cases" description="Create or import cases in Datasets before running an evaluation." /> : <div className="mt-3 overflow-hidden rounded-[8px] border border-slate-100"><table className="w-full text-left text-[10px]"><thead className="bg-slate-50 text-slate-500"><tr><th className="px-3 py-2">Query</th><th className="w-28 px-2">Type</th><th className="w-24 px-2">Recall@10</th><th className="w-20 px-2">MRR</th><th className="w-20 px-2">Status</th></tr></thead><tbody>{cases.map((item, index) => { const metric = rows[index] ?? {}; const recall = Number(metric.recall_at_10 ?? 0); return <tr key={item.case_id} className="border-t border-slate-100"><td className="max-w-[480px] truncate px-3 py-2.5 font-medium">{item.query}</td><td className="px-2 text-slate-500">{item.query_type}</td><td className="px-2">{report ? percent(recall) : "—"}</td><td className="px-2">{report ? percent(Number(metric.reciprocal_rank ?? 0)) : "—"}</td><td className="px-2">{report ? <span className="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 size={12} />Measured</span> : <span className="text-slate-400">Pending</span>}</td></tr> })}</tbody></table></div>}</section></div></ScrollSurface>
}

function CompareTab({ configs, datasets }: { configs: RagDebugConfigProfile[]; datasets: RagDebugDataset[] }) {
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
  return <ScrollSurface><div className="mx-auto max-w-[1240px] space-y-4"><section className="rounded-[10px] border border-slate-200 p-4"><div className="grid items-end gap-3 md:grid-cols-[1fr_1fr_1fr_140px]"><Field label="Dataset"><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} className={selectClass}><option value="">Select a dataset</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name}</option>)}</select></Field><Field label="Baseline"><select value={baselineId} onChange={(event) => setBaselineId(event.target.value)} className={selectClass}>{configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}</option>)}</select></Field><Field label="Candidate"><select value={candidateId} onChange={(event) => setCandidateId(event.target.value)} className={selectClass}>{configs.map((item) => <option key={item.config_id} value={item.config_id}>{item.name}</option>)}</select></Field><PrimaryButton onClick={run} disabled={!datasetId || !candidateId || running}>{running ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}{running ? "Comparing" : "Compare"}</PrimaryButton></div></section>{error && <div className="rounded-[10px] border border-rose-200 bg-rose-50 px-4 py-3 text-[11px] text-rose-700">{error}</div>}<div className="grid gap-3 md:grid-cols-3"><CompareMetric title="Recall@10" a={percent(Number(metrics.baseline_recall_at_10 ?? 0))} b={percent(Number(metrics.candidate_recall_at_10 ?? 0))} delta={signedPercent(Number(metrics.recall_delta ?? 0))} percent="Candidate − baseline" /><CompareMetric title="Evaluated cases" a={String(metrics.evaluated_cases ?? "—")} b={String(metrics.evaluated_cases ?? "—")} delta="—" percent="Same dataset" /><CompareMetric title="Result" a="Baseline" b="Candidate" delta={Number(metrics.recall_delta ?? 0) >= 0 ? "Improved" : "Regressed"} percent="Top-10 recall" /></div><section className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center justify-between"><div><h2 className="text-[13px] font-semibold">Query Comparison</h2><p className="mt-1 text-[10px] text-slate-500">Each row is generated by running the same query through both profiles.</p></div><span className="text-[10px] text-slate-400">{result?.cases.length ?? 0} comparisons</span></div>{!result?.cases.length ? <EmptyState title="Run a comparison" description="Choose a dataset and two profiles to see rank and latency changes." /> : <div className="mt-3 space-y-2">{result.cases.map((item) => <div key={item.case_id} className="grid gap-2 rounded-[8px] border border-slate-100 px-3 py-3 md:grid-cols-[minmax(0,1fr)_100px_100px_100px]"><div className="min-w-0"><p className="truncate text-[11px] font-semibold">{item.query}</p><p className="mt-1 text-[9px] text-slate-500">{item.case_id} · {item.baseline_latency_ms.toFixed(0)} ms / {item.candidate_latency_ms.toFixed(0)} ms</p></div><MiniStat label="Baseline rank" value={item.baseline_rank ? String(item.baseline_rank) : "—"} /><MiniStat label="Candidate rank" value={item.candidate_rank ? String(item.candidate_rank) : "—"} /><span className={`self-center text-[10px] font-medium ${item.candidate_rank && (!item.baseline_rank || item.candidate_rank < item.baseline_rank) ? "text-emerald-600" : "text-slate-500"}`}>{item.candidate_rank && item.baseline_rank ? item.candidate_rank - item.baseline_rank : "No gold hit"}</span></div>)}</div>}</section></div></ScrollSurface>
}

function DatasetsTab({ datasets, onDatasetsChanged }: { datasets: RagDebugDataset[]; onDatasetsChanged: () => Promise<void> }) {
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
  function createCase() { setDraft({ case_id: `case-${Date.now()}`, query: "", categories: [], relevant_chunk_ids: [], relevance_grades: {}, claims: [], no_answer: false, metadata: {}, query_type: "Factual", expected_answer: "", answerable: true, tags: [], notes: "", updated_at: "" }); setSelectedId("") }
  function patchDraft(update: Partial<RagDebugCase>) { setDraft((value) => value ? { ...value, ...update } : value) }
  return <ScrollSurface><div className="mx-auto max-w-[1240px] space-y-4"><section className="flex flex-wrap items-center justify-between gap-3 rounded-[10px] border border-slate-200 p-4"><div><h2 className="text-[13px] font-semibold">Evaluation Datasets</h2><p className="mt-1 text-[10px] text-slate-500">Persist retrieval test cases locally and reuse them for evaluation and comparison.</p></div><div className="flex gap-2"><SecondaryButton onClick={newDataset}><Plus size={13} />New dataset</SecondaryButton><SecondaryButton onClick={() => inputRef.current?.click()}><Upload size={13} />Import JSON/JSONL</SecondaryButton><input ref={inputRef} type="file" accept=".json,.jsonl,application/json" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importFile(file); event.currentTarget.value = "" }} /><SecondaryButton onClick={() => void exportFile()} disabled={!datasetId}><Download size={13} />Export</SecondaryButton></div></section><div className="grid min-h-[520px] gap-4 lg:grid-cols-[300px_minmax(0,1fr)]"><section className="rounded-[10px] border border-slate-200 p-3"><PanelHeader title="Evaluation Cases" right={dataset ? `${cases.length} cases` : undefined} />{datasets.length === 0 ? <EmptyState title="No datasets" description="Create a dataset or import JSON/JSONL cases." /> : <div className="mt-3 space-y-1">{datasets.map((item) => <button key={item.dataset_id} type="button" onClick={() => setDatasetId(item.dataset_id)} className={`flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left text-[10px] ${datasetId === item.dataset_id ? "bg-slate-100 font-semibold" : "hover:bg-slate-50"}`}><Database size={13} /><span className="min-w-0 flex-1 truncate">{item.name}</span><span className="text-slate-400">{item.case_count}</span></button>)}{dataset && <div className="mt-4 border-t border-slate-100 pt-3"><button type="button" onClick={createCase} className="flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left text-[10px] text-slate-600 hover:bg-slate-50"><Plus size={13} />New case</button><button type="button" onClick={() => void removeDataset()} className="flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left text-[10px] text-rose-600 hover:bg-rose-50"><Trash2 size={13} />Delete dataset</button></div>}{cases.map((item) => <button key={item.case_id} type="button" onClick={() => setSelectedId(item.case_id)} className={`mt-1 block w-full truncate rounded-[7px] px-2 py-2 text-left text-[10px] ${selectedId === item.case_id ? "bg-slate-50 font-semibold" : "text-slate-600 hover:bg-slate-50"}`}>{item.query || item.case_id}</button>)}</div>}</section><section className="rounded-[10px] border border-slate-200">{draft ? <><PanelHeader title="Case Details" right={<span>{draft.case_id}</span>} /><div className="ait-scroll-page max-h-[560px] space-y-3 overflow-y-auto p-4"><EditorLabel label="Query" required><textarea value={draft.query} onChange={(event) => patchDraft({ query: event.target.value })} rows={3} className={inputClass("w-full resize-none py-2.5 text-[10px]")} /></EditorLabel><EditorLabel label="Query Type"><select value={draft.query_type} onChange={(event) => patchDraft({ query_type: event.target.value })} className={selectClass}><option>Factual</option><option>Analytical</option><option>Comparative</option><option>Creative</option></select></EditorLabel><EditorLabel label="Gold Chunk IDs"><input value={draft.relevant_chunk_ids.join(", ")} onChange={(event) => patchDraft({ relevant_chunk_ids: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="chunk_id_1, chunk_id_2" className={inputClass("h-9 w-full text-[10px]")} /></EditorLabel><EditorLabel label="Expected Answer"><textarea value={draft.expected_answer} onChange={(event) => patchDraft({ expected_answer: event.target.value })} rows={5} className={inputClass("w-full resize-none py-2.5 text-[10px]")} /></EditorLabel><label className="flex items-center gap-2 text-[10px] text-slate-700"><input type="checkbox" checked={draft.answerable} onChange={(event) => patchDraft({ answerable: event.target.checked, no_answer: !event.target.checked })} className="accent-slate-950" />Answerable</label><EditorLabel label="Tags"><input value={draft.tags.join(", ")} onChange={(event) => patchDraft({ tags: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="retrieval, multilingual" className={inputClass("h-9 w-full text-[10px]")} /></EditorLabel><EditorLabel label="Notes"><textarea value={draft.notes} onChange={(event) => patchDraft({ notes: event.target.value })} rows={3} className={inputClass("w-full resize-none text-[10px]")} /></EditorLabel></div><div className="flex items-center justify-end gap-2 border-t border-slate-100 p-3"><SecondaryButton onClick={() => void removeCase()}><Trash2 size={13} />Delete</SecondaryButton><PrimaryButton onClick={() => void save()}><Save size={13} />Save Changes</PrimaryButton></div></> : <EmptyState title="Select or create a case" description="Cases are stored in the local RAG Debug Studio database." />}</section></div>{error && <div className="rounded-[10px] border border-rose-200 bg-rose-50 px-4 py-3 text-[11px] text-rose-700">{error}</div>}{notice && <div className="rounded-[10px] bg-slate-950 px-4 py-2.5 text-[11px] text-white">{notice}</div>}</div></ScrollSurface>
}

function StagePill({ stage, active }: { stage: RagDebugStage; active: boolean }) { const icon = stage.status === "complete" ? <CheckCircle2 size={13} className="text-emerald-600" /> : stage.status === "failed" ? <AlertCircle size={13} className="text-rose-600" /> : stage.status === "active" || active ? <LoaderCircle size={13} className="animate-spin text-slate-950" /> : <span className="h-2 w-2 rounded-full border border-slate-300" />; return <div className={`flex min-w-0 items-center gap-1.5 rounded-[7px] border px-2 py-2 ${active ? "border-slate-950 bg-slate-50" : "border-slate-100"}`} title={stage.note}><span className="shrink-0">{icon}</span><span className="min-w-0 truncate text-[9px] font-medium">{stage.label}</span></div> }
function ResultTable({ rows, selectedId, onSelect }: { rows: RagDebugCandidate[]; selectedId: string; onSelect: (id: string) => void }) { return <div className="mt-3 overflow-hidden rounded-[8px] border border-slate-100"><table className="w-full table-fixed text-left text-[10px]"><thead className="bg-slate-50 text-slate-500"><tr><th className="w-8 px-2 py-2">#</th><th className="w-[135px] px-2">Chunk ID</th><th className="w-[70px] px-2">Score</th><th className="w-[64px] px-2">Δ Rank</th><th className="px-2">Source</th><th className="w-[90px] px-2">Section</th></tr></thead><tbody>{rows.map((row, index) => { const delta = (row.before ?? row.after ?? index + 1) - (row.after ?? index + 1); return <tr key={row.id} onClick={() => onSelect(row.id)} className={`cursor-pointer border-t border-slate-100 transition ${selectedId === row.id ? "bg-slate-100" : "hover:bg-slate-50"}`}><td className="px-2 py-2.5 text-slate-500">{row.after ?? index + 1}</td><td className="truncate px-2 font-medium">{row.id}</td><td className="px-2 tabular-nums">{formatScore(row.rerank ?? row.fusion ?? row.dense ?? row.bm25)}</td><td className="px-2">{delta === 0 ? <span className="text-slate-400">—</span> : delta > 0 ? <span className="inline-flex items-center gap-1 text-emerald-600"><ArrowUp size={10} />{delta}</span> : <span className="inline-flex items-center gap-1 text-rose-500"><ArrowDown size={10} />{Math.abs(delta)}</span>}</td><td className="truncate px-2 text-slate-600">{row.source || row.document_id}</td><td className="truncate px-2 text-slate-600">{row.section || "—"}</td></tr> })}</tbody></table></div> }
function ChunkDetail({ row, index, total, previous, next }: { row: RagDebugCandidate; index: number; total: number; previous: () => void; next: () => void }) { const [copied, setCopied] = useState(false); function copy() { if (navigator.clipboard) void navigator.clipboard.writeText(row.id); setCopied(true); window.setTimeout(() => setCopied(false), 800) }; return <div><div className="flex items-center justify-between border-b border-slate-100 pb-3"><h2 className="text-[13px] font-semibold">Chunk Detail</h2><div className="flex items-center gap-1 text-[10px] text-slate-500"><button type="button" onClick={previous} className="rounded border border-slate-200 p-1"><ChevronLeft size={13} /></button><span>{index + 1} of {total}</span><button type="button" onClick={next} className="rounded border border-slate-200 p-1"><ChevronRight size={13} /></button></div></div><dl className="grid grid-cols-[92px_1fr] gap-x-2 gap-y-2 border-b border-slate-100 py-3 text-[10px]"><dt className="text-slate-500">Chunk ID</dt><dd className="flex items-center gap-1 font-medium"><span className="truncate">{row.id}</span><button type="button" onClick={copy} aria-label="Copy chunk ID" className="text-slate-400">{copied ? <Check size={11} /> : <Copy size={11} />}</button></dd><dt className="text-slate-500">Source</dt><dd>{row.source || row.document_id}</dd><dt className="text-slate-500">Section</dt><dd className="truncate">{row.section || "—"}</dd><dt className="text-slate-500">Page</dt><dd>{row.page ?? "—"}</dd><dt className="text-slate-500">Tokens</dt><dd>{row.tokens}</dd><dt className="text-slate-500">Score</dt><dd>{formatScore(row.rerank ?? row.fusion ?? row.dense ?? row.bm25)}</dd><dt className="text-slate-500">Original Rank</dt><dd>{row.before ?? "—"}</dd><dt className="text-slate-500">Rerank Position</dt><dd>{row.after ?? "—"}</dd></dl><h3 className="mt-3 text-[11px] font-semibold">Chunk Text</h3><div className="ait-scroll-page mt-2 max-h-[230px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-2.5 text-[10px] leading-[1.6] text-slate-700">{row.text || "No text returned by the index."}</div></div> }
function ChunkRecordDetail({ chunk }: { chunk: RagDebugChunk }) { const [copied, setCopied] = useState(false); function copy() { if (navigator.clipboard) void navigator.clipboard.writeText(chunk.id); setCopied(true); window.setTimeout(() => setCopied(false), 800) }; return <div><div className="flex items-center justify-between border-b border-slate-100 pb-3"><h2 className="text-[13px] font-semibold">Chunk Detail</h2><button type="button" aria-label="Copy chunk ID" onClick={copy} className="text-slate-400">{copied ? <Check size={13} /> : <Copy size={13} />}</button></div><dl className="grid grid-cols-[92px_1fr] gap-x-2 gap-y-2 border-b border-slate-100 py-3 text-[10px]"><dt className="text-slate-500">Chunk ID</dt><dd className="truncate font-medium">{chunk.id}</dd><dt className="text-slate-500">Document</dt><dd>{chunk.document_id}</dd><dt className="text-slate-500">Section</dt><dd>{chunk.section || "—"}</dd><dt className="text-slate-500">Page</dt><dd>{chunk.page ?? "—"}</dd><dt className="text-slate-500">Type</dt><dd>{chunk.type || "—"}</dd><dt className="text-slate-500">Tokens</dt><dd>{chunk.tokens}</dd><dt className="text-slate-500">Overlap</dt><dd>{chunk.overlap || "—"}</dd><dt className="text-slate-500">Character range</dt><dd>{chunk.start.toLocaleString()} – {chunk.end.toLocaleString()}</dd><dt className="text-slate-500">Embedding model</dt><dd className="truncate">{chunk.embedding || "—"}</dd></dl><h3 className="mt-3 text-[11px] font-semibold">Chunk Text</h3><div className="ait-scroll-page mt-2 max-h-[290px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-3 text-[10px] leading-[1.7] text-slate-700">{chunk.text}</div></div> }
function MetricCard({ title, value, delta, detail, icon }: { title: string; value: string; delta: string; detail: string; icon: ReactNode }) { return <section className="rounded-[10px] border border-slate-200 p-4 transition hover:shadow-[0_4px_16px_rgba(15,23,42,.05)]"><div className="flex items-start justify-between"><h2 className="text-[12px] font-semibold">{title}</h2><span className="text-slate-600">{icon}</span></div><div className="mt-2 flex items-end gap-3"><span className="text-[25px] font-semibold tracking-tight">{value}</span><span className="mb-1 text-[11px] font-medium text-emerald-600">{delta}</span></div><p className="mt-1 text-[10px] text-slate-500">{detail}</p></section> }
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
function percent(value: unknown) { const number = Number(value ?? 0); return Number.isFinite(number) ? `${(number * 100).toFixed(0)}%` : "—" }
function signedPercent(value: number) { return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%` }
function errorText(reason: unknown) { return reason instanceof Error ? reason.message : "Request failed." }
