import { FileText, Network, Plus } from "lucide-react"

export default function KnowledgeHome({
  paperCount,
  conceptCount,
  relationCount,
  onOpenCanvas,
  onOpenGraph,
}: {
  paperCount: number
  conceptCount: number
  relationCount: number
  onOpenCanvas: () => void
  onOpenGraph: () => void
}) {
  return (
    <section className="ait-surface p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Knowledge overview</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">Your AI Knowledge Space</h2>
          <p className="mt-1 text-sm text-slate-500">Papers, concepts and agent memories organized as reusable knowledge objects.</p>
        </div>
        <button type="button" className="flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-medium text-white" onClick={onOpenCanvas}>
          <Plus size={15} /> Open Canvas
        </button>
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {[
          ["Papers", paperCount, FileText],
          ["Concepts", conceptCount, FileText],
          ["Relations", relationCount, Network],
        ].map(([label, value, Icon]) => (
          <button key={String(label)} type="button" className="rounded-xl border border-slate-200 p-4 text-left hover:bg-slate-50" onClick={label === "Relations" ? onOpenGraph : undefined}>
            <Icon size={16} className="text-slate-500" />
            <div className="mt-3 text-2xl font-semibold text-slate-950">{value}</div>
            <div className="text-xs text-slate-500">{label}</div>
          </button>
        ))}
      </div>
    </section>
  )
}
