import { useState } from "react"
import { Box, ChevronDown, ChevronRight, Search } from "lucide-react"
import type { ToolCatalog, ToolSummary } from "../../api/tools"

interface Props {
  items: ToolSummary[]
  selected: string
  catalog?: ToolCatalog
  totals?: ToolCatalog
  search: string
  status: string
  category: string
  onFilter: (name: string, value: string) => void
  onSelect: (id: string) => void
  pending: boolean
  error: boolean
  retry: () => void
  hasMore: boolean
  loadMore: () => void
}
export function ToolLibrary(props: Props) {
  const [collapsed, setCollapsed] = useState<string[]>([])
  const groups = Array.from(new Set(props.items.map((item) => item.category)))
  return <aside className="tools-library" aria-label="Tool library">
    <div className="tools-library-toolbar">
      <h2>Tool library</h2>
      <label className="tools-search"><Search size={15} /><input aria-label="Search tools" placeholder="Search tools…" value={props.search} onChange={(event) => props.onFilter("q", event.target.value)} /></label>
      <div className="tools-filters" aria-label="Tool status">
        {(["all", "enabled", "disabled"] as const).map((status) => <button key={status} aria-pressed={status === props.status} className={status === props.status ? "is-active" : ""} onClick={() => props.onFilter("status", status)}>{status[0].toUpperCase() + status.slice(1)} <small>{props.totals?.[status === "all" ? "total" : status] ?? "—"}</small></button>)}
      </div>
      <select aria-label="Tool category" value={props.category} onChange={(event) => props.onFilter("category", event.target.value)}>
        <option value="">All categories</option>{Object.keys(props.totals?.categories ?? {}).map((category) => <option key={category}>{category}</option>)}
      </select>
    </div>
    <div className="tools-library-list">
      {props.pending && <p className="tools-note" role="status">Loading tools…</p>}
      {props.error && <div className="tools-notice" role="alert">Unable to load tools. Check the backend connection.<button onClick={props.retry}>Retry</button></div>}
      {!props.pending && !props.error && props.items.length === 0 && <p className="tools-note">No tools match these filters.</p>}
      {groups.map((category) => <section className="tools-group" key={category}>
        <button className="tools-group-label" aria-expanded={!collapsed.includes(category)} onClick={() => setCollapsed((value) => value.includes(category) ? value.filter((item) => item !== category) : [...value, category])}>
          {collapsed.includes(category) ? <ChevronRight size={13} /> : <ChevronDown size={13} />}<Box size={15} /><span>{category}</span><small>{props.catalog?.categories[category] ?? 0}</small>
        </button>
        {!collapsed.includes(category) && props.items.filter((item) => item.category === category).map((tool) => <button key={tool.tool_id} className={`tools-library-item ${props.selected === tool.tool_id ? "is-selected" : ""}`} aria-pressed={props.selected === tool.tool_id} onClick={() => props.onSelect(tool.tool_id)} title={tool.unavailable_reason || tool.description}>
          <Box size={14} /><i className={tool.enabled ? "tools-dot" : "tools-dot is-disabled"} /><span>{tool.name}</span>
        </button>)}
      </section>)}
      {props.hasMore && <button className="tools-text-button" onClick={props.loadMore}>Load more tools</button>}
    </div>
    <footer>{props.totals?.enabled ?? "—"} enabled · {props.totals?.disabled ?? "—"} disabled</footer>
  </aside>
}
