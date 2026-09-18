import { ArrowDown, ArrowUp, Check, ChevronLeft, ChevronRight, Copy, LoaderCircle, Play } from "lucide-react"
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"

type StageKey = "query" | "rewrite" | "dense" | "bm25" | "fusion" | "rerank" | "context" | "answer"
type Candidate = {
  id: string; source: string; section: string; page: number; tokens: number
  dense: number; bm25: number; fusion: number; rerank: number
  before: number; after: number; text: string
}

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

const scoreFor = (row: Candidate, stage: StageKey) => stage === "dense" ? row.dense : stage === "bm25" ? row.bm25 : stage === "fusion" ? row.fusion : row.rerank
const retrievalStage = (stage: StageKey) => ["dense", "bm25", "fusion", "rerank"].includes(stage)

export default function RagDebugStudioTrace() {
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
    setRunning(true); setDone(0); setStage("query")
    let next = 0
    timer.current = window.setInterval(() => {
      next += 1; setDone(next); setStage(STAGES[Math.min(next - 1, STAGES.length - 1)].key)
      if (next >= STAGES.length) {
        if (timer.current !== null) window.clearInterval(timer.current)
        timer.current = null; setRunning(false); setStage("rerank")
      }
    }, 220)
  }

  const move = (offset: number) => {
    const index = (selectedIndex + offset + rows.length) % rows.length
    setSelectedId(rows[index].id)
  }

  return (
    <section className="flex min-h-[760px] flex-col overflow-hidden bg-white">
      <header className="border-b border-slate-200 px-8 pt-7">
        <h1 className="text-[27px] font-semibold tracking-[-0.035em] text-slate-950">RAG Debug Studio</h1>
        <p className="mt-1 text-[13px] text-slate-500">Inspect and debug your RAG pipeline. Trace retrieval, ranking, and generation step by step.</p>
        <nav className="mt-5 flex gap-8" aria-label="RAG Debug Studio tabs">
          {["Trace", "Chunks", "Evaluation", "Compare", "Datasets"].map((tab) => (
            <button key={tab} type="button" disabled={tab !== "Trace"} title={tab === "Trace" ? "Trace" : "Coming next"} className={`relative px-1 pb-4 text-[13px] font-medium ${tab === "Trace" ? "text-slate-950" : "text-slate-400"}`}>
              {tab}{tab === "Trace" && <span className="absolute inset-x-0 bottom-0 h-[2px] bg-slate-950" />}
            </button>
          ))}
        </nav>
      </header>

      <div className="ait-scroll-page flex-1 overflow-y-auto px-8 py-5">
        <div className="mx-auto max-w-[1240px] space-y-4">
          <section className="rounded-[10px] border border-slate-200 p-4">
            <label className="text-[12px] font-semibold text-slate-800">Query</label>
            <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={2} className="mt-2 w-full resize-none rounded-[8px] border border-slate-200 px-3 py-2.5 text-[13px] outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-900/5" />
            <div className="mt-4 grid items-end gap-3 lg:grid-cols-[1fr_1fr_120px_148px]">
              <Field label="Workspace"><select className="h-10 w-full rounded-[8px] border border-slate-200 bg-white px-3 text-[12px]"><option>My Workspace</option><option>All sources</option></select></Field>
              <Field label="RAG Config"><select className="h-10 w-full rounded-[8px] border border-slate-200 bg-white px-3 text-[12px]"><option>Default (v1)</option><option>Hybrid + Rerank</option></select></Field>
              <Field label="Top K"><select value={topK} onChange={(e) => setTopK(Number(e.target.value))} className="h-10 w-full rounded-[8px] border border-slate-200 bg-white px-3 text-[12px]"><option value={5}>5</option><option value={6}>6</option></select></Field>
              <button type="button" onClick={run} disabled={running || !query.trim()} className="flex h-10 items-center justify-center gap-2 rounded-[8px] bg-slate-950 text-[12px] font-semibold text-white transition hover:bg-slate-800 active:scale-[.985] disabled:bg-slate-300">{running ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}{running ? "Running" : "Run"}</button>
            </div>
          </section>

          <section className="rounded-[10px] border border-slate-200 px-4 py-4">
            <div className="grid grid-cols-[repeat(8,minmax(70px,1fr))_92px]">
              {STAGES.map((item, index) => {
                const complete = index < done; const active = index === stageIndex; const current = running && index === done
                return <button key={item.key} type="button" onClick={() => setStage(item.key)} className="group text-left">
                  <div className="flex items-center"><span className={`z-10 flex h-5 w-5 items-center justify-center rounded-full border transition ${complete ? "border-slate-950 bg-slate-950 text-white" : current ? "border-slate-950 bg-white ring-4 ring-slate-900/10" : "border-slate-300 bg-slate-100"} ${active ? "scale-110" : ""}`}>{complete ? <Check size={12} /> : <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />}</span>{index < 7 && <span className={`h-px flex-1 ${index < done - 1 ? "bg-slate-950" : "bg-slate-300"}`} />}</div>
                  <p className={`mt-2 truncate text-[11px] font-semibold ${active ? "text-slate-950" : "text-slate-700"}`}>{item.short}</p><p className="text-[10px] text-slate-500">{item.ms} ms</p>
                </button>
              })}
              <div className="border-l border-slate-200 pl-4"><p className="text-[10px] text-slate-500">Total time</p><p className="mt-1 text-lg font-semibold">{totalMs} ms</p></div>
            </div>
          </section>

          <div className="grid min-h-[410px] gap-3 xl:grid-cols-[190px_minmax(0,1fr)_330px]">
            <aside className="rounded-[10px] border border-slate-200 p-3">
              <h2 className="px-1 text-[13px] font-semibold">Pipeline stages</h2>
              <div className="mt-2 space-y-1">{STAGES.map((item, index) => <button key={item.key} type="button" onClick={() => setStage(item.key)} className={`flex w-full items-center gap-2 rounded-[8px] px-2.5 py-2 text-left transition ${stage === item.key ? "bg-slate-100" : "hover:bg-slate-50"}`}><span className={`flex h-4 w-4 items-center justify-center rounded-full border ${index < done ? "border-slate-950 bg-slate-950 text-white" : "border-slate-300"}`}>{index < done && <Check size={10} />}</span><span className="min-w-0 flex-1"><span className="block truncate text-[11px] font-semibold">{item.label}</span><span className="block truncate text-[9px] text-slate-500">{item.note}</span></span><span className="text-[9px] text-slate-400">{item.ms} ms</span></button>)}</div>
            </aside>

            <main className="min-w-0 rounded-[10px] border border-slate-200 p-3">
              {retrievalStage(stage) ? <ResultTable stage={stage} rows={rows} selectedId={selected?.id ?? ""} onSelect={setSelectedId} /> : <StageSummary stage={stage} query={query} />}
            </main>

            <aside className="rounded-[10px] border border-slate-200 p-3">{selected && <ChunkDetail row={selected} index={selectedIndex} total={rows.length} previous={() => move(-1)} next={() => move(1)} />}</aside>
          </div>
        </div>
      </div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="block"><span className="mb-1.5 block text-[11px] font-semibold text-slate-700">{label}</span>{children}</label> }

function ResultTable({ stage, rows, selectedId, onSelect }: { stage: StageKey; rows: Candidate[]; selectedId: string; onSelect: (id: string) => void }) {
  const title = stage === "dense" ? "Dense Retrieval Results" : stage === "bm25" ? "BM25 Retrieval Results" : stage === "fusion" ? "Fusion Results" : "Reranker Results"
  return <><div className="flex items-center justify-between border-b border-slate-100 px-1 pb-3"><div><h2 className="text-[13px] font-semibold">{title}</h2><p className="mt-0.5 text-[10px] text-slate-500">Click a row to inspect the chunk.</p></div><span className="text-[10px] text-slate-400">{rows.length} results</span></div><div className="mt-2 overflow-hidden rounded-[8px] border border-slate-100"><table className="w-full table-fixed text-left text-[10px]"><thead className="bg-slate-50 text-slate-500"><tr><th className="w-8 px-2 py-2">#</th><th className="w-[135px] px-2">Chunk ID</th><th className="w-[70px] px-2">Score</th><th className="w-[64px] px-2">Δ Rank</th><th className="px-2">Source</th><th className="w-[70px] px-2">Section</th></tr></thead><tbody>{rows.map((row, i) => { const delta = row.before - row.after; return <tr key={row.id} onClick={() => onSelect(row.id)} className={`cursor-pointer border-t border-slate-100 transition ${selectedId === row.id ? "bg-slate-100" : "hover:bg-slate-50"}`}><td className="px-2 py-2.5 text-slate-500">{i + 1}</td><td className="truncate px-2 font-medium">{row.id}</td><td className="px-2 tabular-nums">{scoreFor(row, stage).toFixed(stage === "bm25" ? 2 : 3)}</td><td className="px-2">{stage !== "rerank" || delta === 0 ? <span className="text-slate-400">–</span> : delta > 0 ? <span className="inline-flex items-center gap-1 text-emerald-600"><ArrowUp size={10} />{delta}</span> : <span className="inline-flex items-center gap-1 text-rose-500"><ArrowDown size={10} />{Math.abs(delta)}</span>}</td><td className="truncate px-2 text-slate-600">{row.source}</td><td className="truncate px-2 text-slate-600">{row.section.split(" ")[0]}</td></tr> })}</tbody></table></div></>
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
  const [copied, setCopied] = useState(false); const delta = row.before - row.after
  const copy = () => { if (navigator.clipboard) void navigator.clipboard.writeText(row.id); setCopied(true); window.setTimeout(() => setCopied(false), 800) }
  return <div><div className="flex items-center justify-between border-b border-slate-100 pb-3"><h2 className="text-[13px] font-semibold">Chunk Detail</h2><div className="flex items-center gap-1 text-[10px] text-slate-500"><button onClick={previous} className="rounded border border-slate-200 p-1"><ChevronLeft size={13} /></button><span>{index + 1} of {total}</span><button onClick={next} className="rounded border border-slate-200 p-1"><ChevronRight size={13} /></button></div></div><dl className="grid grid-cols-[92px_1fr] gap-x-2 gap-y-2 border-b border-slate-100 py-3 text-[10px]"><dt className="text-slate-500">Chunk ID</dt><dd className="flex items-center gap-1 font-medium"><span className="truncate">{row.id}</span><button onClick={copy} aria-label="Copy chunk ID" className="text-slate-400">{copied ? <Check size={11} /> : <Copy size={11} />}</button></dd><dt className="text-slate-500">Source</dt><dd>{row.source}</dd><dt className="text-slate-500">Section</dt><dd className="truncate">{row.section}</dd><dt className="text-slate-500">Page</dt><dd>{row.page}</dd><dt className="text-slate-500">Tokens</dt><dd>{row.tokens}</dd><dt className="text-slate-500">Score</dt><dd>{row.rerank.toFixed(3)}</dd><dt className="text-slate-500">Original Rank</dt><dd>{row.before}</dd><dt className="text-slate-500">Rerank Position</dt><dd className="flex items-center gap-1">{row.after}{delta > 0 && <span className="inline-flex items-center text-emerald-600">(<ArrowUp size={9} />{delta})</span>}</dd></dl><h3 className="mt-3 text-[11px] font-semibold">Chunk Text</h3><div className="ait-scroll-page mt-2 max-h-[180px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-2.5 text-[10px] leading-[1.6] text-slate-700">{row.text}</div></div>
}
