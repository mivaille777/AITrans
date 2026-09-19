import {
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
  FileText,
  HelpCircle,
  LoaderCircle,
  MoreHorizontal,
  Play,
  Plus,
  Save,
  Search,
  Target,
  Trash2,
  Upload,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"

type RagTab = "trace" | "chunks" | "evaluation" | "compare" | "datasets"
type StageKey = "query" | "rewrite" | "dense" | "bm25" | "fusion" | "rerank" | "context" | "answer"
type Candidate = {
  id: string
  source: string
  section: string
  page: number
  tokens: number
  dense: number
  bm25: number
  fusion: number
  rerank: number
  before: number
  after: number
  text: string
}

type ChunkRecord = {
  id: string
  title: string
  preview: string
  section: string
  page: number
  tokens: number
  overlap: number
  start: number
  end: number
  type: string
  embedding: string
  text: string
}

type EvaluationCase = {
  id: number
  query: string
  type: string
  pass: boolean
  recall: number
  firstGoldRank: number | null
}

type CompareCase = {
  id: number
  query: string
  aRank: number
  bRank: number
}

type DatasetCase = {
  id: number
  query: string
  type: "Factual" | "Analytical" | "Comparative" | "Creative"
  goldChunks: string[]
  answer: string
  answerable: boolean
  tags: string[]
  updated: string
  notes: string
}

const TABS: Array<{ id: RagTab; label: string }> = [
  { id: "trace", label: "Trace" },
  { id: "chunks", label: "Chunks" },
  { id: "evaluation", label: "Evaluation" },
  { id: "compare", label: "Compare" },
  { id: "datasets", label: "Datasets" },
]

const STAGES: Array<{ key: StageKey; label: string; short: string; ms: number; note: string }> = [
  { key: "query", label: "Query", short: "Query", ms: 12, note: "Parse query and intent" },
  { key: "rewrite", label: "Rewrite", short: "Rewrite", ms: 48, note: "Generate sub-queries" },
  { key: "dense", label: "Dense Retrieval", short: "Dense", ms: 142, note: "Top 30 results" },
  { key: "bm25", label: "BM25 Retrieval", short: "BM25", ms: 87, note: "Top 30 results" },
  { key: "fusion", label: "Fusion", short: "Fusion", ms: 12, note: "RRF merge to 20" },
  { key: "rerank", label: "Rerank", short: "Rerank", ms: 95, note: "Qwen3 reranker" },
  { key: "context", label: "Context Building", short: "Context", ms: 36, note: "Build final context" },
  { key: "answer", label: "Answer Generation", short: "Answer", ms: 312, note: "Generate response" },
]

const ROWS: Candidate[] = [
  { id: "chunk_3f2a1c", source: "unep_2023.pdf", section: "4.2 Coastal Adaptation Strategies", page: 42, tokens: 362, dense: .862, bm25: 8.42, fusion: .043, rerank: .892, before: 13, after: 1, text: "Coastal cities face compounded risks from sea-level rise, more frequent and intense storm surges, and chronic flooding. Effective adaptation requires integrated approaches including resilient infrastructure, nature-based solutions such as mangrove restoration, and improved early warning systems. Governance, financing, and community engagement are critical enablers for long-term resilience." },
  { id: "chunk_7e9d4b", source: "ipcc_ar6.pdf", section: "12.3 Adaptation Pathways", page: 118, tokens: 318, dense: .841, bm25: 7.96, fusion: .041, rerank: .845, before: 10, after: 2, text: "Adaptation pathways help decision makers sequence near-term actions while keeping longer-term options open under uncertainty. Flexible pathways combine risk reduction, land-use planning, ecosystem restoration, and staged infrastructure investment." },
  { id: "chunk_a1d9f8", source: "worldbank_2022.pdf", section: "3.1 Financing resilience", page: 27, tokens: 295, dense: .826, bm25: 7.35, fusion: .038, rerank: .781, before: 8, after: 3, text: "Long-lived coastal resilience programs depend on predictable financing, credible project pipelines, and institutions capable of coordinating public and private investment." },
  { id: "chunk_c4b2e6", source: "nature_2021.pdf", section: "2.4 Nature-based adaptation", page: 9, tokens: 342, dense: .804, bm25: 6.81, fusion: .035, rerank: .742, before: 4, after: 4, text: "Nature-based solutions can reduce flood exposure while delivering habitat, cooling, and social co-benefits. Their effectiveness depends on local conditions and integration with engineered protection." },
  { id: "chunk_9f7d3a", source: "unhabitat_2022.pdf", section: "5.1 Inclusive planning", page: 64, tokens: 276, dense: .792, bm25: 6.44, fusion: .033, rerank: .698, before: 3, after: 5, text: "Inclusive adaptation planning improves implementation quality by incorporating neighborhood-scale vulnerability, informal settlement conditions, and local knowledge." },
  { id: "chunk_d8e3c1", source: "ipcc_ar6.pdf", section: "12.5 Residual risk", page: 126, tokens: 301, dense: .775, bm25: 5.98, fusion: .031, rerank: .665, before: 9, after: 6, text: "Even with substantial adaptation, residual coastal risk persists because extreme events can exceed design assumptions and socioeconomic exposure continues to change." },
]

const CHUNKS: ChunkRecord[] = [
  {
    id: "chunk_3f2a1c",
    title: "Coastal cities face compounded risks from sea-level rise…",
    preview: "Coastal cities face compounded risks from sea-level rise, more frequent and intense storm surges, and chronic flooding…",
    section: "2. Coastal Adaptation Strategies",
    page: 42,
    tokens: 362,
    overlap: 200,
    start: 0,
    end: 2847,
    type: "Text",
    embedding: "Qwen3-Embedding-0.6B",
    text: "Coastal cities face compounded risks from sea-level rise, more frequent and intense storm surges, and chronic flooding. Effective adaptation requires integrated approaches including resilient infrastructure, nature-based solutions such as mangrove restoration, and improved early warning systems. Governance, financing, and community engagement are critical enablers for long-term resilience, especially in vulnerable regions where socioeconomic factors increase exposure and limit adaptive capacity.",
  },
  {
    id: "chunk_7e9d4b",
    title: "Nature-based solutions offer multiple co-benefits…",
    preview: "Nature-based solutions offer multiple co-benefits, including flood risk reduction, biodiversity conservation, and improved…",
    section: "2.1 Nature-based Solutions",
    page: 43,
    tokens: 318,
    overlap: 200,
    start: 2648,
    end: 5231,
    type: "Text",
    embedding: "Qwen3-Embedding-0.6B",
    text: "Nature-based solutions offer multiple co-benefits, including flood risk reduction, biodiversity conservation, improved public space, and lower urban heat exposure. Their effectiveness depends on local hydrology, maintenance capacity, and long-term governance arrangements.",
  },
  {
    id: "chunk_a1d9f8",
    title: "Integrated coastal zone management (ICZM)…",
    preview: "Integrated coastal zone management (ICZM) provides a holistic framework for balancing development and ecosystem…",
    section: "2.3 Policy Frameworks",
    page: 46,
    tokens: 295,
    overlap: 200,
    start: 5032,
    end: 7491,
    type: "Text",
    embedding: "Qwen3-Embedding-0.6B",
    text: "Integrated coastal zone management provides a holistic framework for balancing development and ecosystem protection. It coordinates land use, infrastructure planning, environmental protection, and public participation across administrative boundaries.",
  },
  {
    id: "chunk_c4b2e6",
    title: "Hard infrastructure remains important in high-risk areas…",
    preview: "Hard infrastructure remains important in high-risk areas, particularly where immediate protection is required for…",
    section: "2.2 Infrastructure Approaches",
    page: 49,
    tokens: 342,
    overlap: 200,
    start: 7292,
    end: 10156,
    type: "Text",
    embedding: "Qwen3-Embedding-0.6B",
    text: "Hard infrastructure remains important in high-risk areas, particularly where immediate protection is required for dense settlements and critical assets. Seawalls, surge barriers, drainage upgrades, and elevated infrastructure are most effective when paired with adaptive design and periodic reassessment.",
  },
  {
    id: "chunk_9f7d3a",
    title: "Policy and governance enable long-term resilience…",
    preview: "Policy and governance enable long-term resilience by aligning incentives, setting clear regulations, and fostering multi-level…",
    section: "2.3 Policy Frameworks",
    page: 52,
    tokens: 276,
    overlap: 200,
    start: 9956,
    end: 12331,
    type: "Text",
    embedding: "Qwen3-Embedding-0.6B",
    text: "Policy and governance enable long-term resilience by aligning incentives, setting clear regulations, and fostering multi-level coordination. Durable institutions help cities sustain adaptation investments across political and budget cycles.",
  },
]

const EVALUATION_CASES: EvaluationCase[] = [
  { id: 1, query: "What are the key challenges of climate change adaptation in coastal cities?", type: "Factual", pass: true, recall: 1.00, firstGoldRank: 1 },
  { id: 2, query: "How do coastal cities manage sea-level rise risks?", type: "Factual", pass: true, recall: .90, firstGoldRank: 2 },
  { id: 3, query: "What infrastructure solutions are most effective?", type: "Comparative", pass: true, recall: .80, firstGoldRank: 3 },
  { id: 4, query: "Summarize the IPCC findings on coastal adaptation.", type: "Summary", pass: true, recall: 1.00, firstGoldRank: 1 },
  { id: 5, query: "What are the economic impacts of coastal flooding?", type: "Factual", pass: false, recall: .20, firstGoldRank: null },
  { id: 6, query: "Which nature-based solutions are recommended?", type: "Factual", pass: true, recall: .80, firstGoldRank: 4 },
  { id: 7, query: "How does mangrove restoration reduce risk?", type: "Causal", pass: true, recall: .90, firstGoldRank: 2 },
  { id: 8, query: "What policies support resilient coastal infrastructure?", type: "Factual", pass: false, recall: .30, firstGoldRank: null },
  { id: 9, query: "Compare hard vs. soft infrastructure approaches.", type: "Comparative", pass: true, recall: .70, firstGoldRank: 5 },
  { id: 10, query: "What are early warning system best practices?", type: "Factual", pass: true, recall: .80, firstGoldRank: 3 },
]

const COMPARE_CASES: CompareCase[] = [
  { id: 1, query: "What are the key challenges of climate change adaptation in coastal cities?", aRank: 13, bRank: 4 },
  { id: 2, query: "How effective are nature-based solutions for coastal flood risk?", aRank: 8, bRank: 3 },
  { id: 3, query: "What financing mechanisms support coastal resilience projects?", aRank: 5, bRank: 7 },
  { id: 4, query: "How do sea-level rise projections affect urban planning?", aRank: 12, bRank: 12 },
  { id: 5, query: "What are the social impacts of coastal adaptation strategies?", aRank: 20, bRank: 6 },
]

const DATASET_CASES: DatasetCase[] = [
  { id: 1, query: "What are the key challenges of climate change adaptation in coastal cities?", type: "Analytical", goldChunks: ["chunk_3f2a1c", "chunk_7e9d4b", "chunk_a1d9f8"], answer: "Coastal cities face compounded risks from sea-level rise, more frequent and intense storm surges, and chronic flooding. Effective adaptation requires integrated approaches including resilient infrastructure, nature-based solutions, and early warning systems.", answerable: true, tags: ["adaptation", "coastal-cities", "challenges"], updated: "Mar 1, 2024", notes: "" },
  { id: 2, query: "How does sea-level rise affect coastal planning?", type: "Factual", goldChunks: ["chunk_3f2a1c", "chunk_c4b2e6"], answer: "Sea-level rise increases chronic flood exposure and raises design requirements for infrastructure and land-use planning.", answerable: true, tags: ["sea-level"], updated: "Feb 28, 2024", notes: "" },
  { id: 3, query: "What infrastructure solutions are most effective?", type: "Analytical", goldChunks: ["chunk_c4b2e6", "chunk_7e9d4b", "chunk_a1d9f8", "chunk_9f7d3a"], answer: "The strongest portfolios combine engineered protection, nature-based solutions, adaptive pathways, and supporting governance.", answerable: true, tags: ["infrastructure"], updated: "Feb 27, 2024", notes: "" },
  { id: 4, query: "Are nature-based solutions enough on their own?", type: "Comparative", goldChunks: ["chunk_7e9d4b", "chunk_c4b2e6", "chunk_3f2a1c"], answer: "Not always. Nature-based solutions work best as part of an integrated portfolio with engineered measures where risk is high.", answerable: true, tags: ["nature-based"], updated: "Feb 26, 2024", notes: "" },
  { id: 5, query: "What are the economic impacts of coastal flooding?", type: "Analytical", goldChunks: ["chunk_a1d9f8", "chunk_3f2a1c", "chunk_9f7d3a", "chunk_c4b2e6"], answer: "Impacts include direct asset losses, service disruption, reduced investment confidence, and higher adaptation expenditure.", answerable: true, tags: ["economics"], updated: "Feb 25, 2024", notes: "" },
  { id: 6, query: "Which coastal cities are highlighted as examples?", type: "Factual", goldChunks: ["chunk_3f2a1c", "chunk_a1d9f8"], answer: "The source set highlights multiple coastal city contexts rather than one universal case.", answerable: true, tags: ["examples"], updated: "Feb 24, 2024", notes: "" },
  { id: 7, query: "How effective are early warning systems?", type: "Analytical", goldChunks: ["chunk_3f2a1c", "chunk_7e9d4b", "chunk_a1d9f8", "chunk_9f7d3a"], answer: "They reduce loss of life and disruption when paired with reliable forecasts, communication channels, and response capacity.", answerable: true, tags: ["early-warning"], updated: "Feb 22, 2024", notes: "" },
  { id: 8, query: "What policies support coastal resilience?", type: "Factual", goldChunks: ["chunk_9f7d3a", "chunk_a1d9f8", "chunk_c4b2e6"], answer: "Clear land-use rules, coordinated planning, financing mechanisms, and long-term institutional accountability support resilience.", answerable: true, tags: ["policy"], updated: "Feb 20, 2024", notes: "" },
  { id: 9, query: "What are the trade-offs between hard and soft adaptation?", type: "Comparative", goldChunks: ["chunk_c4b2e6", "chunk_7e9d4b", "chunk_3f2a1c"], answer: "Hard measures can deliver immediate protection but are capital intensive; softer and nature-based measures provide co-benefits but may need more space and time.", answerable: true, tags: ["trade-offs"], updated: "Feb 18, 2024", notes: "" },
  { id: 10, query: "How does mangrove restoration contribute to resilience?", type: "Factual", goldChunks: ["chunk_7e9d4b", "chunk_3f2a1c"], answer: "Mangroves reduce wave energy, stabilize shorelines, and provide ecological co-benefits.", answerable: true, tags: ["ecosystems"], updated: "Feb 16, 2024", notes: "" },
]

const scoreFor = (row: Candidate, stage: StageKey) => stage === "dense" ? row.dense : stage === "bm25" ? row.bm25 : stage === "fusion" ? row.fusion : row.rerank
const retrievalStage = (stage: StageKey) => ["dense", "bm25", "fusion", "rerank"].includes(stage)

export default function RagDebugStudioTrace() {
  const [activeTab, setActiveTab] = useState<RagTab>("trace")

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <header className="shrink-0 border-b border-slate-200 px-8 pt-7">
        <h1 className="text-[27px] font-semibold tracking-[-0.035em] text-slate-950">RAG Debug Studio</h1>
        <p className="mt-1 text-[13px] text-slate-500">Inspect and debug your RAG pipeline. Trace retrieval, ranking, and generation step by step.</p>
        <nav className="mt-5 flex gap-8" aria-label="RAG Debug Studio tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`relative px-1 pb-4 text-[13px] font-medium transition-colors duration-150 ${activeTab === tab.id ? "text-slate-950" : "text-slate-500 hover:text-slate-800"}`}
            >
              {tab.label}
              <span className={`absolute inset-x-0 bottom-0 h-[2px] origin-center bg-slate-950 transition-transform duration-200 ${activeTab === tab.id ? "scale-x-100" : "scale-x-0"}`} />
            </button>
          ))}
        </nav>
      </header>

      <div key={activeTab} className="min-h-0 flex-1 animate-[ragFadeIn_.18s_ease-out]">
        {activeTab === "trace" && <TraceTab />}
        {activeTab === "chunks" && <ChunksTab />}
        {activeTab === "evaluation" && <EvaluationTab />}
        {activeTab === "compare" && <CompareTab />}
        {activeTab === "datasets" && <DatasetsTab />}
      </div>
    </section>
  )
}

function TraceTab() {
  const [query, setQuery] = useState("What are the key challenges of climate change adaptation in coastal cities?")
  const [stage, setStage] = useState<StageKey>("rerank")
  const [selectedId, setSelectedId] = useState(ROWS[0].id)
  const [topK, setTopK] = useState(6)
  const [done, setDone] = useState(STAGES.length)
  const [running, setRunning] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(() => () => { if (timer.current !== null) window.clearInterval(timer.current) }, [])

  const rows = useMemo(() => ROWS.slice(0, topK), [topK])
  const selectedIndex = Math.max(0, rows.findIndex((row) => row.id === selectedId))
  const selected = rows[selectedIndex] ?? rows[0]
  const stageIndex = STAGES.findIndex((item) => item.key === stage)
  const totalMs = STAGES.reduce((sum, item) => sum + item.ms, 0)

  function run() {
    if (timer.current !== null) window.clearInterval(timer.current)
    setRunning(true)
    setDone(0)
    setStage("query")
    let next = 0
    timer.current = window.setInterval(() => {
      next += 1
      setDone(next)
      setStage(STAGES[Math.min(next - 1, STAGES.length - 1)].key)
      if (next >= STAGES.length) {
        if (timer.current !== null) window.clearInterval(timer.current)
        timer.current = null
        setRunning(false)
        setStage("rerank")
      }
    }, 220)
  }

  const move = (offset: number) => {
    const index = (selectedIndex + offset + rows.length) % rows.length
    setSelectedId(rows[index].id)
  }

  return (
    <ScrollSurface>
      <div className="mx-auto max-w-[1240px] space-y-4">
        <section className="rounded-[10px] border border-slate-200 p-4">
          <label className="text-[12px] font-semibold text-slate-800">Query</label>
          <textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={2} className={inputClass("mt-2 w-full resize-none py-2.5")} />
          <div className="mt-4 grid items-end gap-3 lg:grid-cols-[1fr_1fr_120px_148px]">
            <Field label="Workspace"><select className={selectClass}><option>My Workspace</option><option>All sources</option></select></Field>
            <Field label="RAG Config"><select className={selectClass}><option>Default (v1)</option><option>Hybrid + Rerank</option></select></Field>
            <Field label="Top K"><select value={topK} onChange={(event) => setTopK(Number(event.target.value))} className={selectClass}><option value={5}>5</option><option value={6}>6</option></select></Field>
            <PrimaryButton onClick={run} disabled={running || !query.trim()}>{running ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}{running ? "Running" : "Run"}</PrimaryButton>
          </div>
        </section>

        <section className="rounded-[10px] border border-slate-200 px-4 py-4">
          <div className="grid grid-cols-[repeat(8,minmax(70px,1fr))_92px]">
            {STAGES.map((item, index) => {
              const complete = index < done
              const active = index === stageIndex
              const current = running && index === done
              return (
                <button key={item.key} type="button" onClick={() => setStage(item.key)} className="group text-left">
                  <div className="flex items-center">
                    <span className={`z-10 flex h-5 w-5 items-center justify-center rounded-full border transition ${complete ? "border-slate-950 bg-slate-950 text-white" : current ? "border-slate-950 bg-white ring-4 ring-slate-900/10" : "border-slate-300 bg-slate-100"} ${active ? "scale-110" : ""}`}>{complete ? <Check size={12} /> : <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />}</span>
                    {index < 7 && <span className={`h-px flex-1 transition-colors ${index < done - 1 ? "bg-slate-950" : "bg-slate-300"}`} />}
                  </div>
                  <p className={`mt-2 truncate text-[11px] font-semibold ${active ? "text-slate-950" : "text-slate-700"}`}>{item.short}</p>
                  <p className="text-[10px] text-slate-500">{item.ms} ms</p>
                </button>
              )
            })}
            <div className="border-l border-slate-200 pl-4"><p className="text-[10px] text-slate-500">Total time</p><p className="mt-1 text-lg font-semibold">{totalMs} ms</p></div>
          </div>
        </section>

        <div className="grid min-h-[410px] gap-3 xl:grid-cols-[190px_minmax(0,1fr)_330px]">
          <aside className="rounded-[10px] border border-slate-200 p-3">
            <h2 className="px-1 text-[13px] font-semibold">Pipeline stages</h2>
            <div className="mt-2 space-y-1">
              {STAGES.map((item, index) => (
                <button key={item.key} type="button" onClick={() => setStage(item.key)} className={`flex w-full items-center gap-2 rounded-[8px] px-2.5 py-2 text-left transition ${stage === item.key ? "bg-slate-100" : "hover:bg-slate-50"}`}>
                  <span className={`flex h-4 w-4 items-center justify-center rounded-full border ${index < done ? "border-slate-950 bg-slate-950 text-white" : "border-slate-300"}`}>{index < done && <Check size={10} />}</span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-[11px] font-semibold">{item.label}</span><span className="block truncate text-[9px] text-slate-500">{item.note}</span></span>
                  <span className="text-[9px] text-slate-400">{item.ms} ms</span>
                </button>
              ))}
            </div>
          </aside>

          <main className="min-w-0 rounded-[10px] border border-slate-200 p-3">
            {retrievalStage(stage) ? <ResultTable stage={stage} rows={rows} selectedId={selected?.id ?? ""} onSelect={setSelectedId} /> : <StageSummary stage={stage} query={query} />}
          </main>

          <aside className="rounded-[10px] border border-slate-200 p-3">{selected && <ChunkDetail row={selected} index={selectedIndex} total={rows.length} previous={() => move(-1)} next={() => move(1)} />}</aside>
        </div>
      </div>
    </ScrollSurface>
  )
}

function ChunksTab() {
  const [document, setDocument] = useState("unep_2023.pdf")
  const [query, setQuery] = useState("")
  const [display, setDisplay] = useState("50")
  const [selectedId, setSelectedId] = useState(CHUNKS[0].id)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ intro: true, adaptation: true, risk: true })
  const [page, setPage] = useState(1)

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return CHUNKS
    return CHUNKS.filter((chunk) => `${chunk.id} ${chunk.title} ${chunk.preview} ${chunk.section}`.toLowerCase().includes(needle))
  }, [query])
  const selected = filtered.find((chunk) => chunk.id === selectedId) ?? filtered[0] ?? CHUNKS[0]
  const selectedIndex = Math.max(0, filtered.findIndex((chunk) => chunk.id === selected.id))

  function move(offset: number) {
    if (!filtered.length) return
    const next = (selectedIndex + offset + filtered.length) % filtered.length
    setSelectedId(filtered[next].id)
  }

  return (
    <ScrollSurface>
      <div className="mx-auto max-w-[1240px] space-y-3">
        <section className="grid gap-4 rounded-[10px] border border-slate-200 p-4 lg:grid-cols-[280px_minmax(0,1fr)_260px]">
          <Field label="Document"><select value={document} onChange={(event) => setDocument(event.target.value)} className={selectClass}><option>unep_2023.pdf</option><option>ipcc_ar6.pdf</option><option>worldbank_2022.pdf</option></select></Field>
          <Field label="Search chunks"><div className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search content, section, or chunk ID…" className={inputClass("h-10 w-full pl-9")} /></div></Field>
          <Field label="Display"><select value={display} onChange={(event) => setDisplay(event.target.value)} className={selectClass}><option value="50">50 per page</option><option value="25">25 per page</option><option value="10">10 per page</option></select></Field>
        </section>

        <div className="grid min-h-[600px] gap-3 xl:grid-cols-[300px_minmax(0,1fr)_380px]">
          <aside className="overflow-hidden rounded-[10px] border border-slate-200 bg-white">
            <PanelHeader title="Document Structure" />
            <div className="ait-scroll-page max-h-[640px] overflow-y-auto px-3 py-2 text-[11px]">
              <div className="flex items-center gap-2 px-1 py-2 font-semibold"><FileText size={15} /><span className="min-w-0 flex-1 truncate">{document}</span><span className="text-slate-400">142 chunks</span></div>
              <TreeSection label="1. Introduction" count={12} open={expanded.intro} onToggle={() => setExpanded((value) => ({ ...value, intro: !value.intro }))}>
                <TreeLeaf label="1.1 Background" count={4} /><TreeLeaf label="1.2 Problem Statement" count={4} /><TreeLeaf label="1.3 Objectives" count={4} />
              </TreeSection>
              <TreeSection label="2. Coastal Adaptation Strategies" count={42} open={expanded.adaptation} active onToggle={() => setExpanded((value) => ({ ...value, adaptation: !value.adaptation }))}>
                <TreeLeaf label="2.1 Nature-based Solutions" count={10} /><TreeLeaf label="2.2 Infrastructure Approaches" count={12} /><TreeLeaf label="2.3 Policy Frameworks" count={10} /><TreeLeaf label="2.4 Case Studies" count={10} />
              </TreeSection>
              <TreeSection label="3. Risk Assessment" count={28} open={expanded.risk} onToggle={() => setExpanded((value) => ({ ...value, risk: !value.risk }))}>
                <TreeLeaf label="3.1 Sea-level Rise Projections" count={8} /><TreeLeaf label="3.2 Extreme Weather Events" count={8} /><TreeLeaf label="3.3 Vulnerability Analysis" count={12} />
              </TreeSection>
              <TreeSection label="4. Implementation" count={20} open={false} onToggle={() => undefined} />
              <TreeSection label="5. Conclusion" count={8} open={false} onToggle={() => undefined} />
            </div>
          </aside>

          <main className="min-w-0 overflow-hidden rounded-[10px] border border-slate-200 bg-white">
            <PanelHeader title="Chunks" right={<span>{filtered.length || 0} chunks</span>} />
            <div className="ait-scroll-page max-h-[565px] space-y-2 overflow-y-auto p-2">
              {filtered.map((chunk, index) => (
                <button key={chunk.id} type="button" onClick={() => setSelectedId(chunk.id)} className={`group flex w-full gap-3 rounded-[10px] border p-3 text-left transition-all duration-150 ${selected.id === chunk.id ? "border-slate-950 bg-white shadow-[0_2px_8px_rgba(15,23,42,.06)]" : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/60"}`}>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-700">{index + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[11px] font-semibold text-slate-900">{chunk.title}</span>
                    <span className="mt-1 block line-clamp-2 text-[10px] leading-4 text-slate-500">{chunk.preview}</span>
                    <span className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[9px] text-slate-500"><span>{chunk.tokens} tokens</span><span>chars {chunk.start.toLocaleString()} – {chunk.end.toLocaleString()}</span><span className="rounded-full bg-slate-100 px-2 py-0.5">Overlap {chunk.overlap}</span></span>
                  </span>
                  <ChevronRight size={15} className="mt-1 shrink-0 text-slate-400 transition-transform group-hover:translate-x-0.5" />
                </button>
              ))}
              {filtered.length === 0 && <EmptyState title="No chunks found" description="Try a different search term." />}
            </div>
            <div className="flex items-center justify-center gap-2 border-t border-slate-100 px-3 py-3">
              <PaginationButton disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={14} /></PaginationButton>
              {[1, 2, 3, 4, 5].map((item) => <PaginationButton key={item} active={page === item} onClick={() => setPage(item)}>{item}</PaginationButton>)}
              <span className="text-[10px] text-slate-400">…</span><PaginationButton onClick={() => setPage(9)}>9</PaginationButton>
              <PaginationButton onClick={() => setPage((value) => Math.min(9, value + 1))}><ChevronRight size={14} /></PaginationButton>
            </div>
          </main>

          <aside className="overflow-hidden rounded-[10px] border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
              <h2 className="text-[13px] font-semibold">Chunk Detail</h2>
              <div className="flex items-center gap-2 text-[10px] text-slate-500"><button type="button" onClick={() => move(-1)} className="rounded p-1 hover:bg-slate-100"><ChevronLeft size={14} /></button><span>{selectedIndex + 1} of {Math.max(filtered.length, 1)}</span><button type="button" onClick={() => move(1)} className="rounded border border-slate-200 p-1.5 hover:bg-slate-50"><ChevronRight size={14} /></button></div>
            </div>
            <ChunkRecordDetail chunk={selected} />
          </aside>
        </div>
      </div>
    </ScrollSurface>
  )
}

function EvaluationTab() {
  const [dataset, setDataset] = useState("Coastal Adaptation Test Set")
  const [config, setConfig] = useState("Default (v1)")
  const [evaluating, setEvaluating] = useState(false)
  const [run, setRun] = useState(0)
  const [page, setPage] = useState(1)

  function startEvaluation() {
    setEvaluating(true)
    window.setTimeout(() => {
      setRun((value) => value + 1)
      setEvaluating(false)
    }, 900)
  }

  return (
    <ScrollSurface>
      <div className="mx-auto max-w-[1240px] space-y-3">
        <section className="grid items-end gap-4 rounded-[10px] border border-slate-200 p-4 lg:grid-cols-[1.1fr_1fr_140px_1fr_170px]">
          <Field label="Dataset"><select value={dataset} onChange={(event) => setDataset(event.target.value)} className={selectClass}><option>Coastal Adaptation Test Set</option><option>Academic RAG Core</option></select></Field>
          <Field label="Run Configuration"><select value={config} onChange={(event) => setConfig(event.target.value)} className={selectClass}><option>Default (v1)</option><option>Hybrid + Rerank</option></select></Field>
          <Field label="Test Cases"><div className="flex h-10 items-center rounded-[8px] border border-slate-200 px-3 text-[12px]">50</div></Field>
          <Field label="Last Evaluated"><div className="flex h-10 items-center text-[11px] text-slate-500">Apr 22, 2024, 10:24 AM</div></Field>
          <PrimaryButton onClick={startEvaluation} disabled={evaluating}>{evaluating ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}{evaluating ? "Evaluating" : "Run Evaluation"}</PrimaryButton>
        </section>

        <div className={`grid gap-3 md:grid-cols-2 xl:grid-cols-4 ${evaluating ? "opacity-60" : ""}`}>
          <MetricCard icon={<Target size={17} />} title="Recall@10" value={(0.892 + run * .001).toFixed(3)} delta="↑ 0.08" detail="vs. previous (0.812)" />
          <MetricCard icon={<BarChart3 size={17} />} title="MRR" value={(0.665 + run * .001).toFixed(3)} delta="↑ 0.05" detail="vs. previous (0.615)" />
          <MetricCard icon={<FileText size={17} />} title="Context Recall" value={(0.781 + run * .001).toFixed(3)} delta="↑ 0.06" detail="vs. previous (0.721)" />
          <MetricCard icon={<Clock3 size={17} />} title="Latency" value={`${312 - run} ms`} delta="↓ 18%" detail="vs. previous (381 ms)" />
        </div>

        <section className="overflow-hidden rounded-[10px] border border-slate-200 bg-white">
          <PanelHeader title="Case Results" right={<div className="flex items-center gap-2"><span>1–10 of 50</span><PaginationButton disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={14} /></PaginationButton><PaginationButton onClick={() => setPage((value) => value + 1)}><ChevronRight size={14} /></PaginationButton></div>} />
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[10px]">
              <thead className="border-b border-slate-200 text-slate-600"><tr><th className="w-10 px-3 py-2">#</th><th className="px-2">Query</th><th className="w-[135px] px-2">Type</th><th className="w-[110px] px-2">Status</th><th className="w-[105px] px-2">Recall@10</th><th className="w-[120px] px-2">First Gold Rank</th><th className="w-[120px] px-2">Result</th></tr></thead>
              <tbody>{EVALUATION_CASES.map((item) => <tr key={item.id} className="border-b border-slate-100 transition hover:bg-slate-50"><td className="px-3 py-2.5 text-slate-500">{item.id}</td><td className="max-w-[420px] truncate px-2">{item.query}</td><td className="px-2 text-slate-600">{item.type}</td><td className="px-2"><span className="inline-flex items-center gap-1.5">{item.pass ? <CheckCircle2 size={13} className="text-emerald-500" /> : <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full border border-rose-500 text-[8px] text-rose-500">×</span>}{item.pass ? "Pass" : "Fail"}</span></td><td className="px-2 tabular-nums">{item.recall.toFixed(2)}</td><td className="px-2">{item.firstGoldRank ?? "—"}</td><td className={`px-2 ${item.pass ? "text-emerald-600" : "text-slate-500"}`}>{item.pass ? "Relevant" : "Not relevant"}</td></tr>)}</tbody>
            </table>
          </div>
        </section>

        <div className="grid gap-3 xl:grid-cols-2">
          <section className="rounded-[10px] border border-slate-200 p-4">
            <h2 className="text-[13px] font-semibold">Failure Summary</h2>
            <div className="mt-4 space-y-3"><FailureBar label="No relevant documents" count="5 (50%)" width="50%" /><FailureBar label="Wrong context" count="3 (30%)" width="30%" /><FailureBar label="Incomplete answer" count="1 (10%)" width="10%" /><FailureBar label="Irrelevant answer" count="1 (10%)" width="10%" /></div>
          </section>
          <section className="rounded-[10px] border border-slate-200 p-4">
            <div className="flex items-center justify-between"><h2 className="text-[13px] font-semibold">Evaluation Summary</h2><Copy size={14} className="text-slate-400" /></div>
            <ul className="mt-3 list-disc space-y-1.5 pl-4 text-[10px] leading-5 text-slate-700"><li>Overall performance improved by 8% in Recall@10 compared to the previous run.</li><li>Most failures are due to no relevant documents, indicating gaps in dataset coverage.</li><li>Factual and summary queries perform well, while policy-related queries need better retrieval.</li><li>Consider expanding the dataset with more policy and economic impact documents.</li><li>Latency decreased by 18%, meeting performance targets.</li></ul>
          </section>
        </div>
      </div>
    </ScrollSurface>
  )
}

function CompareTab() {
  const [baseline, setBaseline] = useState("Default (v1)")
  const [candidate, setCandidate] = useState("Coastal RAG (v2)")
  const [dataset, setDataset] = useState("Coastal Adaptation (n=200)")
  const [comparing, setComparing] = useState(false)
  const [selectedId, setSelectedId] = useState(1)
  const [run, setRun] = useState(0)

  const selected = COMPARE_CASES.find((item) => item.id === selectedId) ?? COMPARE_CASES[0]
  const delta = selected.aRank - selected.bRank

  function compare() {
    setComparing(true)
    window.setTimeout(() => {
      setRun((value) => value + 1)
      setComparing(false)
    }, 800)
  }

  return (
    <ScrollSurface>
      <div className="mx-auto max-w-[1240px] space-y-3">
        <section className="grid items-end gap-4 rounded-[10px] border border-slate-200 p-4 lg:grid-cols-[1fr_1fr_1fr_140px]">
          <Field label="Baseline (A)"><select value={baseline} onChange={(event) => setBaseline(event.target.value)} className={selectClass}><option>Default (v1)</option><option>Dense only</option></select></Field>
          <Field label="Candidate (B)"><select value={candidate} onChange={(event) => setCandidate(event.target.value)} className={selectClass}><option>Coastal RAG (v2)</option><option>Hybrid + Rerank</option></select></Field>
          <Field label="Dataset"><select value={dataset} onChange={(event) => setDataset(event.target.value)} className={selectClass}><option>Coastal Adaptation (n=200)</option><option>Academic RAG Core (n=120)</option></select></Field>
          <PrimaryButton onClick={compare} disabled={comparing}>{comparing ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}{comparing ? "Comparing" : "Compare"}</PrimaryButton>
        </section>

        <div className={`grid gap-3 md:grid-cols-2 xl:grid-cols-4 ${comparing ? "opacity-60" : ""}`}>
          <CompareMetric title="Recall@10" a="0.612" b={(0.684 + run * .001).toFixed(3)} delta="+0.072" percent="↑ 11.8%" />
          <CompareMetric title="MRR" a="0.421" b={(0.509 + run * .001).toFixed(3)} delta="+0.088" percent="↑ 20.9%" />
          <CompareMetric title="Context Recall" a="0.708" b={(0.781 + run * .001).toFixed(3)} delta="+0.073" percent="↑ 10.3%" />
          <CompareMetric title="P95 Latency (ms)" a="412" b={`${356 - run}`} delta="−56" percent="↓ 13.6%" />
        </div>

        <section className="overflow-hidden rounded-[10px] border border-slate-200 bg-white">
          <PanelHeader title="Compared Cases" right={<div className="flex items-center gap-2"><span>5 of 200</span><PaginationButton disabled><ChevronLeft size={14} /></PaginationButton><PaginationButton><ChevronRight size={14} /></PaginationButton></div>} />
          <table className="w-full text-left text-[10px]">
            <thead className="border-b border-slate-200 text-slate-600"><tr><th className="w-10 px-3 py-2">#</th><th className="px-2">Query</th><th className="w-[100px] px-2">A Rank</th><th className="w-[100px] px-2">B Rank</th><th className="w-[110px] px-2">Delta</th><th className="w-[130px] px-2">Outcome</th></tr></thead>
            <tbody>{COMPARE_CASES.map((item) => { const itemDelta = item.aRank - item.bRank; const better = itemDelta > 0 ? "B better" : itemDelta < 0 ? "A better" : "Tie"; return <tr key={item.id} onClick={() => setSelectedId(item.id)} className={`cursor-pointer border-b border-slate-100 transition ${selectedId === item.id ? "bg-slate-50" : "hover:bg-slate-50/60"}`}><td className="px-3 py-2.5 text-slate-500">{item.id}</td><td className="px-2">{item.query}</td><td className="px-2">{item.aRank}</td><td className="px-2">{item.bRank}</td><td className={`px-2 font-medium ${itemDelta > 0 ? "text-emerald-600" : itemDelta < 0 ? "text-rose-500" : "text-slate-500"}`}>{itemDelta > 0 ? `↑ ${itemDelta}` : itemDelta < 0 ? `↓ ${Math.abs(itemDelta)}` : "0"}</td><td className="px-2"><span className={`rounded-md px-2 py-1 text-[9px] font-medium ${better === "B better" ? "bg-emerald-50 text-emerald-700" : better === "A better" ? "bg-rose-50 text-rose-700" : "bg-slate-100 text-slate-600"}`}>{better}</span></td></tr> })}</tbody>
          </table>
        </section>

        <section className="rounded-[10px] border border-slate-200 p-3">
          <div className="flex items-center justify-between"><div><h2 className="text-[13px] font-semibold">Query Comparison</h2><p className="mt-1 text-[10px] text-slate-700">{selected.query}</p></div><div className="flex items-center gap-2 text-[10px] text-slate-500"><span>1 of 200</span><PaginationButton disabled><ChevronLeft size={14} /></PaginationButton><PaginationButton><ChevronRight size={14} /></PaginationButton></div></div>
          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            <QueryComparisonCard label="Baseline (A)" config={baseline} rank={selected.aRank} latency={412} rows={ROWS.slice(2, 5)} />
            <QueryComparisonCard label="Candidate (B)" config={candidate} rank={selected.bRank} latency={356} rows={ROWS.slice(0, 3)} highlight={delta > 0} />
          </div>
        </section>
      </div>
    </ScrollSurface>
  )
}

function DatasetsTab() {
  const [dataset, setDataset] = useState("Coastal Adaptation (v1)")
  const [cases, setCases] = useState(DATASET_CASES)
  const [selectedId, setSelectedId] = useState(1)
  const [query, setQuery] = useState("")
  const [type, setType] = useState("All types")
  const [answerable, setAnswerable] = useState("All answerable")
  const [tag, setTag] = useState("All tags")
  const [draft, setDraft] = useState<DatasetCase>(() => ({ ...DATASET_CASES[0], goldChunks: [...DATASET_CASES[0].goldChunks], tags: [...DATASET_CASES[0].tags] }))
  const [dirty, setDirty] = useState(false)
  const [notice, setNotice] = useState("")
  const importRef = useRef<HTMLInputElement>(null)

  const visibleCases = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return cases.filter((item) => {
      if (needle && !`${item.query} ${item.tags.join(" ")}`.toLowerCase().includes(needle)) return false
      if (type !== "All types" && item.type !== type) return false
      if (answerable === "Answerable" && !item.answerable) return false
      if (answerable === "Not answerable" && item.answerable) return false
      if (tag !== "All tags" && !item.tags.includes(tag)) return false
      return true
    })
  }, [answerable, cases, query, tag, type])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(""), 1800)
    return () => window.clearTimeout(timer)
  }, [notice])

  function selectCase(item: DatasetCase) {
    setSelectedId(item.id)
    setDraft({ ...item, goldChunks: [...item.goldChunks], tags: [...item.tags] })
    setDirty(false)
  }

  function patch(patchValue: Partial<DatasetCase>) {
    setDraft((current) => ({ ...current, ...patchValue }))
    setDirty(true)
  }

  function save() {
    setCases((current) => current.map((item) => item.id === draft.id ? { ...draft, updated: "Just now" } : item))
    setDirty(false)
    setNotice("Case saved locally")
  }

  function removeCase() {
    const next = cases.filter((item) => item.id !== selectedId)
    setCases(next)
    const replacement = next[0]
    if (replacement) selectCase(replacement)
    setNotice("Case removed")
  }

  function createDataset() {
    setDataset("Untitled Dataset")
    setNotice("New mock dataset created")
  }

  return (
    <ScrollSurface>
      <div className="mx-auto max-w-[1240px] space-y-3">
        <section className="flex flex-wrap items-end gap-3 rounded-[10px] border border-slate-200 p-4">
          <div className="min-w-[260px] flex-1"><Field label="Dataset"><select value={dataset} onChange={(event) => setDataset(event.target.value)} className={selectClass}><option>Coastal Adaptation (v1)</option><option>Academic RAG Core</option><option>Untitled Dataset</option></select></Field></div>
          <div className="flex h-10 items-center border-l border-slate-200 pl-4 text-[12px] font-semibold">42 cases</div>
          <div className="hidden h-10 items-center gap-2 text-[9px] text-slate-500 xl:flex"><span className="rounded-full bg-slate-100 px-3 py-1">Created Feb 12, 2024</span><span>│</span><span className="rounded-full bg-slate-100 px-3 py-1">Updated Mar 1, 2024</span><span>│</span><span className="rounded-full bg-slate-100 px-3 py-1">Public</span></div>
          <div className="ml-auto flex items-center gap-2">
            <input ref={importRef} type="file" accept=".json,.csv" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) setNotice(`Imported ${file.name} locally`) }} />
            <SecondaryButton onClick={() => importRef.current?.click()}><Upload size={14} />Import</SecondaryButton>
            <PrimaryButton onClick={createDataset}><Plus size={15} />New Dataset</PrimaryButton>
            <button type="button" className="rounded-[8px] p-2 text-slate-600 hover:bg-slate-100" aria-label="More dataset actions"><MoreHorizontal size={16} /></button>
          </div>
        </section>

        <div className="grid min-h-[620px] gap-3 xl:grid-cols-[minmax(0,1fr)_430px]">
          <section className="overflow-hidden rounded-[10px] border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-4 py-3"><div className="flex items-center justify-between"><div><h2 className="text-[14px] font-semibold">Evaluation Cases</h2><p className="mt-0.5 text-[10px] text-slate-500">Manage evaluation cases for this dataset. Each case includes a query, gold references, and expected answer.</p></div><span className="text-[10px] text-slate-500">42 cases</span></div>
              <div className="mt-3 grid gap-2 md:grid-cols-[1fr_120px_150px_130px_72px]">
                <div className="relative"><Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search queries, tags…" className={inputClass("h-9 w-full pl-8 text-[10px]")} /></div>
                <select value={type} onChange={(event) => setType(event.target.value)} className={smallSelectClass}><option>All types</option><option>Factual</option><option>Analytical</option><option>Comparative</option><option>Creative</option></select>
                <select value={answerable} onChange={(event) => setAnswerable(event.target.value)} className={smallSelectClass}><option>All answerable</option><option>Answerable</option><option>Not answerable</option></select>
                <select value={tag} onChange={(event) => setTag(event.target.value)} className={smallSelectClass}><option>All tags</option><option>adaptation</option><option>policy</option><option>sea-level</option></select>
                <button type="button" onClick={() => { setQuery(""); setType("All types"); setAnswerable("All answerable"); setTag("All tags") }} className="rounded-[8px] border border-slate-200 text-[10px] hover:bg-slate-50">Reset</button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[9px]">
                <thead className="border-b border-slate-200 text-slate-600"><tr><th className="w-8 px-3 py-2"><span className="block h-3 w-3 rounded border border-slate-300" /></th><th className="px-2">Query</th><th className="w-[100px] px-2">Query Type</th><th className="w-[85px] px-2">Gold Chunks</th><th className="w-[85px] px-2">Gold Answer</th><th className="w-[90px] px-2">Answerable</th><th className="w-[110px] px-2">Tags</th><th className="w-[90px] px-2">Updated</th></tr></thead>
                <tbody>{visibleCases.map((item) => <tr key={item.id} onClick={() => selectCase(item)} className={`cursor-pointer border-b border-slate-100 transition ${selectedId === item.id ? "bg-slate-100" : "hover:bg-slate-50"}`}><td className="px-3 py-2.5"><span className={`flex h-3.5 w-3.5 items-center justify-center rounded border ${selectedId === item.id ? "border-slate-950 bg-slate-950 text-white" : "border-slate-300"}`}>{selectedId === item.id && <Check size={9} />}</span></td><td className="max-w-[260px] truncate px-2">{item.query}</td><td className="px-2">{item.type}</td><td className="px-2 text-center">{item.goldChunks.length}</td><td className="px-2">{item.answer ? "Yes" : "No"}</td><td className="px-2">{item.answerable ? <CheckCircle2 size={13} className="text-emerald-500" /> : "—"}</td><td className="px-2"><span className="rounded-full bg-slate-100 px-2 py-1">{item.tags[0]}</span></td><td className="px-2 text-slate-500">{item.updated}</td></tr>)}</tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-[10px] text-slate-500"><span>1–10 of 42 cases</span><div className="flex items-center gap-2"><ChevronLeft size={14} /><PaginationButton active>1</PaginationButton><PaginationButton>2</PaginationButton><PaginationButton>3</PaginationButton><PaginationButton>4</PaginationButton><PaginationButton>5</PaginationButton><ChevronRight size={14} /></div><div className="flex items-center gap-2"><span>Rows per page</span><select className="rounded-[7px] border border-slate-200 bg-white px-2 py-1.5"><option>10</option><option>25</option></select></div></div>
          </section>

          <aside className="overflow-hidden rounded-[10px] border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3"><h2 className="text-[13px] font-semibold">Case Details</h2><div className="flex items-center gap-2 text-[10px] text-slate-500"><ChevronLeft size={14} /><span>1 of 42</span><button type="button" className="rounded border border-slate-200 p-1.5"><ChevronRight size={14} /></button></div></div>
            <div className="ait-scroll-page max-h-[570px] space-y-3 overflow-y-auto p-4">
              <EditorLabel label="Query" required><textarea value={draft.query} onChange={(event) => patch({ query: event.target.value })} rows={2} className={inputClass("w-full resize-none py-2.5 text-[10px]")} /></EditorLabel>
              <EditorLabel label="Query Type" required><div className="flex flex-wrap gap-2">{(["Factual", "Analytical", "Comparative", "Creative"] as DatasetCase["type"][]).map((item) => <button key={item} type="button" onClick={() => patch({ type: item })} className={`rounded-full border px-3 py-1.5 text-[10px] transition ${draft.type === item ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white hover:bg-slate-50"}`}>{item}</button>)}</div></EditorLabel>
              <EditorLabel label="Gold Chunks" required><div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-[8px] border border-slate-200 px-2 py-1.5">{draft.goldChunks.map((chunk) => <span key={chunk} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-[9px]">{chunk}<button type="button" onClick={() => patch({ goldChunks: draft.goldChunks.filter((value) => value !== chunk) })} className="text-slate-400">×</button></span>)}<ChevronDown size={13} className="ml-auto text-slate-400" /></div></EditorLabel>
              <EditorLabel label="Expected Answer" required><textarea value={draft.answer} onChange={(event) => patch({ answer: event.target.value })} rows={5} className={inputClass("w-full resize-none py-2.5 text-[10px]")} /></EditorLabel>
              <div className="flex items-center gap-3"><span className="text-[10px] font-medium">Answerable <span className="text-rose-500">*</span></span><button type="button" role="switch" aria-checked={draft.answerable} onClick={() => patch({ answerable: !draft.answerable })} className={`relative h-5 w-9 rounded-full transition-colors ${draft.answerable ? "bg-slate-950" : "bg-slate-300"}`}><span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${draft.answerable ? "translate-x-[18px]" : "translate-x-0.5"}`} /></button><span className="text-[10px]">{draft.answerable ? "Yes" : "No"}</span></div>
              <EditorLabel label="Tags"><div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-[8px] border border-slate-200 px-2 py-1.5">{draft.tags.map((item) => <span key={item} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-[9px]">{item}<button type="button" onClick={() => patch({ tags: draft.tags.filter((value) => value !== item) })} className="text-slate-400">×</button></span>)}<ChevronDown size={13} className="ml-auto text-slate-400" /></div></EditorLabel>
              <EditorLabel label="Notes"><textarea value={draft.notes} onChange={(event) => patch({ notes: event.target.value })} rows={3} placeholder="Add notes about this case (optional)…" className={inputClass("w-full resize-none py-2.5 text-[10px]")} /></EditorLabel>
              <div className="grid grid-cols-3 gap-2 border-t border-slate-100 pt-3 text-[8px] text-slate-500"><div><span className="block">Created</span><strong className="mt-1 block font-medium text-slate-700">Feb 12, 2024, 10:24 AM</strong></div><div><span className="block">Updated</span><strong className="mt-1 block font-medium text-slate-700">Mar 1, 2024, 3:18 PM</strong></div><div><span className="block">Created by</span><strong className="mt-1 block font-medium text-slate-700">You</strong></div></div>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-slate-100 p-3"><SecondaryButton onClick={removeCase}><Trash2 size={13} />Delete</SecondaryButton><button type="button" disabled={!dirty} onClick={save} className="inline-flex h-9 items-center justify-center gap-2 rounded-[8px] bg-slate-950 px-4 text-[10px] font-semibold text-white transition hover:bg-slate-800 disabled:bg-slate-200 disabled:text-slate-400"><Save size={13} />Save Changes</button></div>
          </aside>
        </div>
      </div>
      {notice && <div className="fixed bottom-6 right-6 z-50 rounded-[10px] bg-slate-950 px-4 py-2.5 text-[11px] font-medium text-white shadow-xl animate-[ragToast_.2s_ease-out]">{notice}</div>}
    </ScrollSurface>
  )
}

function ScrollSurface({ children }: { children: ReactNode }) {
  return <div className="ait-scroll-page h-full min-h-0 overflow-y-auto px-8 py-5">{children}</div>
}

const inputClass = (extra = "") => `rounded-[8px] border border-slate-200 bg-white px-3 text-[12px] text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-900/5 ${extra}`
const selectClass = "h-10 w-full rounded-[8px] border border-slate-200 bg-white px-3 text-[12px] text-slate-800 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-900/5"
const smallSelectClass = "h-9 w-full rounded-[8px] border border-slate-200 bg-white px-2 text-[10px] text-slate-700 outline-none"

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-slate-700">{label}</span>{children}</label>
}

function EditorLabel({ label, required = false, children }: { label: string; required?: boolean; children: ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-[10px] font-medium text-slate-800">{label}{required && <span className="text-rose-500"> *</span>}</span>{children}</label>
}

function PrimaryButton({ children, onClick, disabled = false }: { children: ReactNode; onClick?: () => void; disabled?: boolean }) {
  return <button type="button" onClick={onClick} disabled={disabled} className="inline-flex h-10 items-center justify-center gap-2 rounded-[8px] bg-slate-950 px-4 text-[11px] font-semibold text-white transition hover:bg-slate-800 active:scale-[.985] disabled:bg-slate-300">{children}</button>
}

function SecondaryButton({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex h-10 items-center justify-center gap-2 rounded-[8px] border border-slate-300 bg-white px-4 text-[11px] font-semibold text-slate-800 transition hover:bg-slate-50 active:scale-[.985]">{children}</button>
}

function PanelHeader({ title, right }: { title: string; right?: ReactNode }) {
  return <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3"><h2 className="text-[13px] font-semibold">{title}</h2><div className="text-[10px] text-slate-500">{right}</div></div>
}

function PaginationButton({ children, active = false, disabled = false, onClick }: { children: ReactNode; active?: boolean; disabled?: boolean; onClick?: () => void }) {
  return <button type="button" onClick={onClick} disabled={disabled} className={`flex h-7 min-w-7 items-center justify-center rounded-[7px] px-2 text-[10px] transition ${active ? "bg-slate-950 text-white" : "border border-transparent text-slate-600 hover:border-slate-200 hover:bg-slate-50"} disabled:opacity-30`}>{children}</button>
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return <div className="flex min-h-[220px] flex-col items-center justify-center text-center"><Search size={22} className="text-slate-300" /><p className="mt-3 text-[12px] font-semibold text-slate-700">{title}</p><p className="mt-1 text-[10px] text-slate-500">{description}</p></div>
}

function TreeSection({ label, count, open, active = false, onToggle, children }: { label: string; count: number; open: boolean; active?: boolean; onToggle: () => void; children?: ReactNode }) {
  return <div className="mt-1"><button type="button" onClick={onToggle} className={`flex w-full items-center gap-2 rounded-[7px] px-2 py-2 text-left transition ${active ? "bg-slate-100" : "hover:bg-slate-50"}`}><ChevronRight size={12} className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`} /><span className="min-w-0 flex-1 truncate font-medium">{label}</span><span className="text-slate-400">{count}</span></button><div className={`grid transition-[grid-template-rows,opacity] duration-200 ${open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}><div className="overflow-hidden pl-7">{children}</div></div></div>
}

function TreeLeaf({ label, count }: { label: string; count: number }) {
  return <button type="button" className="flex w-full items-center gap-2 rounded-[7px] px-2 py-1.5 text-left text-slate-600 hover:bg-slate-50"><span className="min-w-0 flex-1 truncate">{label}</span><span className="text-slate-400">{count}</span></button>
}

function ChunkRecordDetail({ chunk }: { chunk: ChunkRecord }) {
  const [copied, setCopied] = useState(false)
  function copy() {
    if (navigator.clipboard) void navigator.clipboard.writeText(chunk.id)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 800)
  }
  return <div className="p-4"><dl className="grid grid-cols-[115px_minmax(0,1fr)] gap-x-3 gap-y-2 text-[10px]"><dt className="text-slate-500">Chunk ID</dt><dd className="flex items-center gap-1 font-medium"><span className="truncate">{chunk.id}</span><button type="button" onClick={copy} className="text-slate-400">{copied ? <Check size={11} /> : <Copy size={11} />}</button></dd><dt className="text-slate-500">Document</dt><dd>unep_2023.pdf</dd><dt className="text-slate-500">Section</dt><dd>{chunk.section}</dd><dt className="text-slate-500">Page</dt><dd>{chunk.page}</dd><dt className="text-slate-500">Type</dt><dd>{chunk.type}</dd><dt className="text-slate-500">Tokens</dt><dd>{chunk.tokens}</dd><dt className="text-slate-500">Overlap</dt><dd>{chunk.overlap} tokens</dd><dt className="text-slate-500">Character range</dt><dd>{chunk.start.toLocaleString()} – {chunk.end.toLocaleString()}</dd><dt className="text-slate-500">Embedding model</dt><dd className="truncate">{chunk.embedding}</dd></dl><div className="mt-4 border-t border-slate-100 pt-4"><div className="flex items-center justify-between"><h3 className="text-[12px] font-semibold">Chunk Text</h3><Copy size={14} className="text-slate-400" /></div><div className="ait-scroll-page mt-3 max-h-[290px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-3 text-[10px] leading-[1.7] text-slate-700">{chunk.text}</div></div></div>
}

function MetricCard({ title, value, delta, detail, icon }: { title: string; value: string; delta: string; detail: string; icon: ReactNode }) {
  return <section className="rounded-[10px] border border-slate-200 p-4 transition hover:shadow-[0_4px_16px_rgba(15,23,42,.05)]"><div className="flex items-start justify-between"><h2 className="text-[12px] font-semibold">{title}</h2><span className="text-slate-600">{icon}</span></div><div className="mt-2 flex items-end gap-3"><span className="text-[25px] font-semibold tracking-tight">{value}</span><span className="mb-1 text-[11px] font-medium text-emerald-600">{delta}</span></div><p className="mt-1 text-[10px] text-slate-500">{detail}</p></section>
}

function CompareMetric({ title, a, b, delta, percent }: { title: string; a: string; b: string; delta: string; percent: string }) {
  return <section className="rounded-[10px] border border-slate-200 p-4"><div className="flex items-center gap-1"><h2 className="text-[12px] font-semibold">{title}</h2><HelpCircle size={12} className="text-slate-400" /></div><div className="mt-3 grid grid-cols-[1fr_1fr_1.15fr] divide-x divide-slate-100"><div><p className="text-[9px] text-slate-500">A</p><p className="mt-1 text-[18px] font-semibold">{a}</p></div><div className="pl-4"><p className="text-[9px] text-slate-500">B</p><p className="mt-1 text-[18px] font-semibold">{b}</p></div><div className="pl-4"><p className="text-[9px] text-slate-500">Δ</p><p className="mt-1 text-[18px] font-semibold text-emerald-600">{delta}</p><p className="text-[10px] text-emerald-600">{percent}</p></div></div></section>
}

function FailureBar({ label, count, width }: { label: string; count: string; width: string }) {
  return <div className="grid grid-cols-[145px_minmax(0,1fr)_70px] items-center gap-3 text-[10px]"><span className="text-slate-600">{label}</span><div className="h-3 bg-slate-100"><div className="h-full bg-slate-950 transition-[width] duration-500" style={{ width }} /></div><span className="font-medium">{count}</span></div>
}

function QueryComparisonCard({ label, config, rank, latency, rows, highlight = false }: { label: string; config: string; rank: number; latency: number; rows: Candidate[]; highlight?: boolean }) {
  return <div className={`rounded-[9px] border p-3 ${highlight ? "border-emerald-200 bg-emerald-50/20" : "border-slate-200"}`}><div className="flex items-center gap-2 border-b border-slate-100 pb-2"><h3 className="text-[11px] font-semibold">{label}</h3><span className="text-[10px] text-slate-500">{config}</span></div><div className="grid grid-cols-4 divide-x divide-slate-100 py-3"><MiniStat label="Top Rank" value={String(rank)} /><MiniStat label="Retrieved Chunks" value="10" /><MiniStat label="Latency" value={`${latency} ms`} /><MiniStat label="Answer Status" value="Answered" check /></div><p className="mb-2 text-[10px] font-semibold">Top Retrieved Results</p><table className="w-full text-left text-[9px]"><thead className="text-slate-500"><tr><th className="w-8">#</th><th>Chunk ID</th><th className="w-20">Score</th><th>Source</th></tr></thead><tbody>{rows.map((row, index) => <tr key={row.id} className="border-t border-slate-100"><td className="py-1.5">{index + 1}</td><td>{row.id}</td><td>{row.rerank.toFixed(3)}</td><td>{row.source}</td></tr>)}</tbody></table></div>
}

function MiniStat({ label, value, check = false }: { label: string; value: string; check?: boolean }) {
  return <div className="px-3 first:pl-0"><p className="text-[9px] text-slate-500">{label}</p><p className="mt-1 flex items-center gap-1 text-[13px] font-semibold">{check && <CheckCircle2 size={13} className="text-emerald-500" />}{value}</p></div>
}

function ResultTable({ stage, rows, selectedId, onSelect }: { stage: StageKey; rows: Candidate[]; selectedId: string; onSelect: (id: string) => void }) {
  const title = stage === "dense" ? "Dense Retrieval Results" : stage === "bm25" ? "BM25 Retrieval Results" : stage === "fusion" ? "Fusion Results" : "Reranker Results"
  return <><div className="flex items-center justify-between border-b border-slate-100 px-1 pb-3"><div><h2 className="text-[13px] font-semibold">{title}</h2><p className="mt-0.5 text-[10px] text-slate-500">Click a row to inspect the chunk.</p></div><span className="text-[10px] text-slate-400">{rows.length} results</span></div><div className="mt-2 overflow-hidden rounded-[8px] border border-slate-100"><table className="w-full table-fixed text-left text-[10px]"><thead className="bg-slate-50 text-slate-500"><tr><th className="w-8 px-2 py-2">#</th><th className="w-[135px] px-2">Chunk ID</th><th className="w-[70px] px-2">Score</th><th className="w-[64px] px-2">Δ Rank</th><th className="px-2">Source</th><th className="w-[70px] px-2">Section</th></tr></thead><tbody>{rows.map((row, index) => { const delta = row.before - row.after; return <tr key={row.id} onClick={() => onSelect(row.id)} className={`cursor-pointer border-t border-slate-100 transition ${selectedId === row.id ? "bg-slate-100" : "hover:bg-slate-50"}`}><td className="px-2 py-2.5 text-slate-500">{index + 1}</td><td className="truncate px-2 font-medium">{row.id}</td><td className="px-2 tabular-nums">{scoreFor(row, stage).toFixed(stage === "bm25" ? 2 : 3)}</td><td className="px-2">{stage !== "rerank" || delta === 0 ? <span className="text-slate-400">–</span> : delta > 0 ? <span className="inline-flex items-center gap-1 text-emerald-600"><ArrowUp size={10} />{delta}</span> : <span className="inline-flex items-center gap-1 text-rose-500"><ArrowDown size={10} />{Math.abs(delta)}</span>}</td><td className="truncate px-2 text-slate-600">{row.source}</td><td className="truncate px-2 text-slate-600">{row.section.split(" ")[0]}</td></tr> })}</tbody></table></div></>
}

function StageSummary({ stage, query }: { stage: StageKey; query: string }) {
  const data: Record<string, Array<[string, string]>> = {
    query: [["Original query", query], ["Intent", "Research synthesis · coastal adaptation"]],
    rewrite: [["Standalone query", "Key challenges and adaptation strategies for climate risks in coastal cities"], ["Sub-query", "coastal city flood adaptation infrastructure nature-based solutions"]],
    context: [["Anchor chunks", "6"], ["Supplemental neighbors", "4"], ["Estimated context", "3,842 tokens"]],
    answer: [["Answer preview", "Coastal cities face compound physical, financial, governance, and equity challenges. Effective adaptation combines resilient infrastructure, nature-based solutions, flexible pathways, and sustained local capacity."], ["Citations", "4 evidence anchors"]],
  }
  return <><div className="border-b border-slate-100 pb-3"><h2 className="text-[13px] font-semibold">{STAGES.find((item) => item.key === stage)?.label}</h2></div><div className="mt-3 space-y-2">{(data[stage] ?? []).map(([label, value]) => <div key={label} className="rounded-[8px] border border-slate-100 bg-slate-50/60 px-3 py-3"><p className="text-[9px] font-semibold uppercase tracking-[.08em] text-slate-400">{label}</p><p className="mt-1.5 text-[11px] leading-5 text-slate-700">{value}</p></div>)}</div></>
}

function ChunkDetail({ row, index, total, previous, next }: { row: Candidate; index: number; total: number; previous: () => void; next: () => void }) {
  const [copied, setCopied] = useState(false)
  const delta = row.before - row.after
  const copy = () => { if (navigator.clipboard) void navigator.clipboard.writeText(row.id); setCopied(true); window.setTimeout(() => setCopied(false), 800) }
  return <div><div className="flex items-center justify-between border-b border-slate-100 pb-3"><h2 className="text-[13px] font-semibold">Chunk Detail</h2><div className="flex items-center gap-1 text-[10px] text-slate-500"><button type="button" onClick={previous} className="rounded border border-slate-200 p-1"><ChevronLeft size={13} /></button><span>{index + 1} of {total}</span><button type="button" onClick={next} className="rounded border border-slate-200 p-1"><ChevronRight size={13} /></button></div></div><dl className="grid grid-cols-[92px_1fr] gap-x-2 gap-y-2 border-b border-slate-100 py-3 text-[10px]"><dt className="text-slate-500">Chunk ID</dt><dd className="flex items-center gap-1 font-medium"><span className="truncate">{row.id}</span><button type="button" onClick={copy} aria-label="Copy chunk ID" className="text-slate-400">{copied ? <Check size={11} /> : <Copy size={11} />}</button></dd><dt className="text-slate-500">Source</dt><dd>{row.source}</dd><dt className="text-slate-500">Section</dt><dd className="truncate">{row.section}</dd><dt className="text-slate-500">Page</dt><dd>{row.page}</dd><dt className="text-slate-500">Tokens</dt><dd>{row.tokens}</dd><dt className="text-slate-500">Score</dt><dd>{row.rerank.toFixed(3)}</dd><dt className="text-slate-500">Original Rank</dt><dd>{row.before}</dd><dt className="text-slate-500">Rerank Position</dt><dd className="flex items-center gap-1">{row.after}{delta > 0 && <span className="inline-flex items-center text-emerald-600">(<ArrowUp size={9} />{delta})</span>}</dd></dl><h3 className="mt-3 text-[11px] font-semibold">Chunk Text</h3><div className="ait-scroll-page mt-2 max-h-[180px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-2.5 text-[10px] leading-[1.6] text-slate-700">{row.text}</div></div>
}