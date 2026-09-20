import { Plus, Search } from "lucide-react"

import type { KnowledgePrimaryView } from "./knowledge-workspace-navigation"

const primaryViews = [
  ["canvas", "Canvas"],
  ["graph", "Graph"],
  ["library", "Library"],
] as const

export default function KnowledgeWorkspaceHeader({
  view,
  onSelectView,
  onSearch,
  onNew,
}: {
  view: KnowledgePrimaryView
  onSelectView: (view: KnowledgePrimaryView) => void
  onSearch?: () => void
  onNew?: () => void
}) {
  return (
    <header className="knowledge-workspace-header">
      <div className="knowledge-workspace-header-copy">
        <h1 className="knowledge-workspace-title">AI Knowledge Space</h1>
        <p className="knowledge-workspace-subtitle">Connect ideas. Ground in sources. Think deeper.</p>
      </div>
      <nav className="knowledge-workspace-tabs" aria-label="Knowledge workspace view">
        {primaryViews.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={`knowledge-workspace-tab${view === value ? " is-active" : ""}`}
            onClick={() => onSelectView(value)}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="knowledge-workspace-actions">
        <button type="button" className="knowledge-workspace-search" aria-label="Search knowledge objects" onClick={onSearch}>
          <Search size={17} strokeWidth={1.8} />
        </button>
        <button type="button" className="knowledge-workspace-new" onClick={onNew}>
          <Plus size={16} strokeWidth={1.8} />
          New
        </button>
      </div>
    </header>
  )
}
