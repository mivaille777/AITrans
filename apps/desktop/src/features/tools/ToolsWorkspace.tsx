import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { FlaskConical, Menu, Plus, Upload, X } from "lucide-react"
import { Button } from "../../shared/ui/Button"
import { setToolEnabled } from "../../api/tools"
import { queryKeys } from "../../shared/query/query-keys"
import { ToolLibrary } from "./ToolLibrary"
import { ToolDetailPanel } from "./ToolDetailPanel"
import { useToolsWorkspace } from "./useToolsWorkspace"
import "./ToolsWorkspace.css"

export default function ToolsWorkspace() {
  const state = useToolsWorkspace()
  const queryClient = useQueryClient()
  const toggle = useMutation({ mutationFn: ({ enabled }: { enabled: boolean }) => setToolEnabled(state.detail.data!, enabled), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: queryKeys.tools.all }); await queryClient.invalidateQueries({ queryKey: queryKeys.agent.tools }) } })
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
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
        {toggle.isError && <p className="tools-notice" role="alert">{toggle.error.message}<button onClick={() => { toggle.reset(); void state.detail.refetch() }}>Reload tool</button></p>}
        {tool && <ToolDetailPanel key={tool.tool_id} tool={tool} actions={<button role="switch" aria-label="Enable tool" aria-checked={tool.enabled} className="tools-toggle" disabled={toggle.isPending || !tool.editable_fields.includes("enabled")} onClick={() => toggle.mutate({ enabled: !tool.enabled })}><i /><span>{tool.enabled ? "Enabled" : "Disabled"}</span></button>} onExample={(value) => { setDrafts((previous) => ({ ...previous, [tool.tool_id]: value })); setInspectorOpen(true) }} />}
      </main>
      <aside className="tools-inspector" aria-label="Test tool">
        <header><h2><FlaskConical size={18} />Test tool</h2><button className="tools-close-inspector" aria-label="Close test panel" onClick={() => setInspectorOpen(false)}><X size={16} /></button></header><p className="tools-note">Try a call before using it in an agent.</p><label className="tools-input-label">Input parameters (JSON)<textarea className="tools-input-editor" aria-label="Input parameters JSON" value={drafts[state.selected] ?? "{}"} onChange={(event) => setDrafts((previous) => ({ ...previous, [state.selected]: event.target.value }))} /></label><div className="tools-notice">Test execution will be available after the governed execution stage.</div>
      </aside>
      <button className="tools-open-inspector" onClick={() => setInspectorOpen(true)}><FlaskConical size={15} />Test tool</button>
    </div>
  </section>
}
