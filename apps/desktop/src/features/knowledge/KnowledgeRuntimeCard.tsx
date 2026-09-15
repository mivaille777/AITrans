import { ChevronDown, Database, HardDrive } from "lucide-react"
import type { KnowledgeRuntime } from "./knowledge-types"

export function KnowledgeRuntimeCard({ runtime }: { runtime: KnowledgeRuntime }) {
  const ready = runtime.enabled && runtime.embedding_status === "ready"

  return (
    <section className="grid gap-3 border-b border-slate-100 bg-slate-50/45 px-5 py-4 sm:grid-cols-3 lg:px-7">
      <Metric label="Documents" value={runtime.document_count} detail={`${runtime.ready_document_count} ready`} icon={<HardDrive size={15} />} />
      <Metric label="Indexed chunks" value={runtime.indexed_chunk_count} detail={runtime.collection_name} icon={<Database size={15} />} />
      <details className="group rounded-[16px] border border-slate-200/80 bg-white/90 p-3.5">
        <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
          <span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">RAG Runtime</span>
            <span className="mt-1.5 flex items-center gap-2 text-sm font-semibold text-slate-800">
              <span className={`h-1.5 w-1.5 rounded-full ${ready ? "bg-emerald-500" : "bg-amber-400"}`} />
              {ready ? "Local RAG Ready" : "Runtime attention needed"}
            </span>
            <span className="mt-1 block text-[10px] text-slate-400">{runtime.embedding_model} · {runtime.device}</span>
          </span>
          <ChevronDown size={14} className="mt-1 text-slate-400 transition-transform group-open:rotate-180" />
        </summary>
        <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-100 pt-3 text-xs">
          <RuntimeDetail term="Embedding" value={runtime.embedding_model || runtime.embedding_provider} />
          <RuntimeDetail term="Device" value={runtime.device} />
          <RuntimeDetail term="Dimension" value={`${runtime.dimension}-d`} />
          <RuntimeDetail term="Vector store" value={runtime.vector_store_provider} />
        </dl>
      </details>
    </section>
  )
}

function Metric({ label, value, detail, icon }: { label: string; value: number; detail: string; icon: React.ReactNode }) {
  return (
    <div className="rounded-[16px] border border-slate-200/80 bg-white/90 p-3.5">
      <div className="flex items-center justify-between text-slate-400"><span className="text-[10px] font-semibold uppercase tracking-[0.14em]">{label}</span>{icon}</div>
      <p className="mt-1.5 text-xl font-semibold tabular-nums text-slate-900">{value.toLocaleString()}</p>
      <p className="mt-1 truncate text-[10px] text-slate-400">{detail}</p>
    </div>
  )
}

function RuntimeDetail({ term, value }: { term: string; value: string }) {
  return <div><dt className="text-[10px] text-slate-400">{term}</dt><dd className="mt-0.5 truncate font-medium text-slate-700">{value || "Unavailable"}</dd></div>
}
