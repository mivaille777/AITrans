import { useState } from "react"
import { Box, FlaskConical, Menu, Plus, Upload, X } from "lucide-react"
import { Button } from "../../shared/ui/Button"
import { ToolLibrary } from "./ToolLibrary"
import { useToolsWorkspace } from "./useToolsWorkspace"
import "./ToolsWorkspace.css"

export default function ToolsWorkspace() {
  const state = useToolsWorkspace()
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const tool = state.detail.data
  return <section className="tools-workspace" aria-label="Tools management">
    <header className="tools-header">
      <div><div className="tools-eyebrow">AGENT WORKSPACE</div><h1>Tools <span>{state.totals.data?.total ?? "—"}</span></h1><p>Manage tools, inspect schemas, and test agent capabilities.</p></div>
      <div className="tools-actions"><Button className="tools-mobile-button" aria-label="Toggle tool library" onClick={() => setLibraryOpen(!libraryOpen)}><Menu size={16} /></Button><Button title="Available after tool configuration support is implemented" disabled><Upload size={14} />Import</Button><Button variant="primary" title="Available after tool configuration support is implemented" disabled><Plus size={14} />Add tool</Button></div>
    </header>
    <div className={`tools-body ${libraryOpen ? "library-open" : ""} ${inspectorOpen ? "inspector-open" : ""}`}>
      <ToolLibrary items={state.items} selected={state.selected} totals={state.totals.data} catalog={state.library.data?.pages[0]} search={state.search} status={state.status} category={state.category} onFilter={state.setParam} onSelect={(id) => { state.setParam("tool", id); setLibraryOpen(false) }} pending={state.library.isPending} error={state.library.isError} retry={() => { void state.library.refetch() }} hasMore={state.library.hasNextPage} loadMore={() => { void state.library.fetchNextPage() }} />
      <main className="tools-detail">
        {state.detail.isError && <div className="tools-notice" role="alert">Unable to load this tool.<button onClick={() => { void state.detail.refetch() }}>Retry</button></div>}
        {!tool && !state.detail.isError && <p className="tools-note">{state.selected ? "Loading tool details…" : "Select a tool to inspect its definition."}</p>}
        {tool && <><div className="tools-detail-header"><div className="tools-title"><div className="tools-tool-icon"><Box size={25} /></div><div><h2>{tool.name}<span className={`tools-badge ${tool.enabled ? "is-green" : ""}`}>{tool.enabled ? "Enabled" : "Disabled"}</span></h2><div className="tools-meta"><code>{tool.namespace}.{tool.name}</code><span>{tool.category}</span><span>{tool.origin}</span></div></div></div><p>{tool.description}</p>{tool.unavailable_reason && <p className="tools-notice">{tool.unavailable_reason}</p>}<div className="tools-meta"><span>{tool.effect}</span><span>{String(tool.limits.timeout_seconds)}s timeout</span><span>{tool.risk_level.replaceAll("_", " ")}</span></div></div><div className="tools-detail-content"><h3>Tool definition</h3><p className="tools-note">Input and output schemas are provided by the registered executor.</p><pre className="tools-code">{JSON.stringify(tool.input_schema, null, 2)}</pre></div></>}
      </main>
      <aside className="tools-inspector" aria-label="Test tool">
        <header><h2><FlaskConical size={18} />Test tool</h2><button className="tools-close-inspector" aria-label="Close test panel" onClick={() => setInspectorOpen(false)}><X size={16} /></button></header><p className="tools-note">Try a call before using it in an agent.</p><div className="tools-notice">Test execution will be available after the governed execution stage.</div>
      </aside>
      <button className="tools-open-inspector" onClick={() => setInspectorOpen(true)}><FlaskConical size={15} />Test tool</button>
    </div>
  </section>
}
