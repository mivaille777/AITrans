import { LayoutDashboard, Network, LibraryBig } from "lucide-react"
import { useState, type ReactNode } from "react"

export type KnowledgeViewMode = "graph" | "canvas" | "library"

export default function KnowledgeWorkspace({
  graph,
  canvas,
  library,
}: {
  graph: ReactNode
  canvas: ReactNode
  library: ReactNode
}) {
  const [mode, setMode] = useState<KnowledgeViewMode>("canvas")

  const views = {
    graph,
    canvas,
    library,
  }

  return (
    <section className="ait-surface overflow-hidden">
      <header className="flex flex-col gap-4 border-b border-slate-100 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Knowledge workspace</p>
          <h1 className="mt-1 text-lg font-semibold text-slate-950">AI Knowledge Space</h1>
          <p className="mt-1 text-xs text-slate-500">Organize papers, concepts, agents and workflows in one workspace.</p>
        </div>
        <nav className="flex rounded-xl border border-slate-200 bg-white p-1">
          {([
            ["graph", Network, "Graph"],
            ["canvas", LayoutDashboard, "Canvas"],
            ["library", LibraryBig, "Library"],
          ] as const).map(([value, Icon, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${mode === value ? "bg-slate-950 text-white" : "text-slate-500 hover:bg-slate-50"}`}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </nav>
      </header>
      <div>{views[mode]}</div>
    </section>
  )
}
