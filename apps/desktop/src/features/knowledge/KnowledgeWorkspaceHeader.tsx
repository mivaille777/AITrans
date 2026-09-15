import { LayoutDashboard, LibraryBig, Network } from "lucide-react"

import type { KnowledgePrimaryView } from "./knowledge-workspace-navigation"

const primaryViews = [
  ["canvas", LayoutDashboard, "Canvas"],
  ["graph", Network, "Graph"],
  ["library", LibraryBig, "Library"],
] as const

export default function KnowledgeWorkspaceHeader({
  view,
  onSelectView,
}: {
  view: KnowledgePrimaryView
  onSelectView: (view: KnowledgePrimaryView) => void
}) {
  return (
    <header className="ait-surface flex flex-col gap-4 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Knowledge workspace</p>
        <h1 className="mt-1 text-lg font-semibold text-slate-950">AI Knowledge Space</h1>
        <p className="mt-1 text-xs text-slate-500">Organize papers, concepts, notes, evidence, relations, and agent-ready knowledge. Open papers in Reading for focused reading actions.</p>
      </div>
      <nav className="flex items-center gap-1 rounded-[14px] border border-slate-200 bg-white p-1 shadow-sm" aria-label="Knowledge workspace view">
        {primaryViews.map(([value, Icon, label]) => (
          <button
            key={value}
            type="button"
            className={`flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs font-semibold transition ${view === value ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`}
            onClick={() => onSelectView(value)}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </nav>
    </header>
  )
}
