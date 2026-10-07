import { useEffect, useRef, useState } from "react"
import { X } from "lucide-react"
import { applyToolImport, archiveTool, createCustomTool, editToolConfiguration, previewToolImport, type ToolDetail, type ToolImportPreview } from "../../api/tools"
import { Button } from "../../shared/ui/Button"

export type ToolDialogMode = "add" | "edit" | "import" | "archive"
const preset = { name: "custom_research_search", template_id: "builtin:search_knowledge_base", title: "Research search", description: "Search selected research documents", fixed_arguments: { top_k: 5 }, exposed_fields: ["query", "document_ids", "document_scope"], defaults: {}, examples: [{ id: "basic", title: "Basic search", description: "Select knowledge documents in the test panel", arguments: { query: "AI agent framework" } }], timeout_seconds: 20 }
export function ToolConfigurationDialog({ mode, tool, close, saved }: { mode: ToolDialogMode; tool?: ToolDetail; close: () => void; saved: (id?: string) => void }) {
  const [draft, setDraft] = useState(JSON.stringify(mode === "import" ? { schema_version: 1, tools: [] } : mode === "add" ? preset : tool?.origin === "custom" ? tool.configuration : { title: tool?.title, description: tool?.description, defaults: tool?.configuration?.defaults ?? {}, examples: tool?.examples ?? [], timeout_seconds: tool?.limits.timeout_seconds }, null, 2))
  const [preview, setPreview] = useState<ToolImportPreview | null>(null)
  const [replace, setReplace] = useState(false)
  const [error, setError] = useState("")
  const [pending, setPending] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; root.current?.querySelector<HTMLButtonElement>("button")?.focus(); return () => previous?.focus() }, [])
  function parse(): Record<string, unknown> {
    const value: unknown = JSON.parse(draft)
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Configuration must be a JSON object.")
    return value as Record<string, unknown>
  }
  async function act(operation: () => Promise<void>) {
    setPending(true); setError("")
    try { await operation() } catch (e) { setError(e instanceof Error ? e.message : "Configuration failed") } finally { setPending(false) }
  }
  return <div className="tools-dialog-backdrop"><div ref={root} className="tools-dialog" role="dialog" aria-modal="true" aria-label={`${mode} tool configuration`} onKeyDown={(e) => {
    if (e.key === "Escape" && !pending) close()
    if (e.key === "Tab") { const elements = [...root.current!.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled)')]; const first = elements[0], last = elements.at(-1); if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() } }
  }}><header><h2>{mode === "add" ? "Add tool preset" : mode === "edit" ? "Edit tool configuration" : mode === "archive" ? "Archive tool" : "Import tool presets"}</h2><button aria-label="Close configuration" disabled={pending} onClick={close}><X size={18} /></button></header>
    {mode === "archive" ? <p>Archive <strong>{tool?.name}</strong>? This disables future calls. Existing history remains available through this tool’s link.</p> : <><p className="tools-note">{mode === "edit" && tool?.origin === "builtin" ? "Edit display information, validated examples, parameter defaults and a shorter timeout." : "Data-only presets use the existing knowledge search executor. Fixed fields cannot be exposed or overridden. Imported and new tools start disabled; native Chat does not support these presets."}</p>{mode === "import" && <label className="tools-input-label">Load JSON file<input type="file" accept=".json,application/json" disabled={pending} onChange={(event) => void act(async () => { const file = event.target.files?.[0]; if (!file) return; if (file.size > 1024 * 1024) throw new Error("Import is limited to 1 MiB."); setDraft(await file.text()); setPreview(null) })} /></label>}<label className="tools-input-label">Configuration (JSON)<textarea className="tools-config-editor" aria-label="Tool configuration JSON" value={draft} disabled={pending} onChange={(e) => { setDraft(e.target.value); setPreview(null) }} /></label></>}
    {error && <p role="alert" className="tools-notice">{error}</p>}
    {preview && <div className="tools-import-preview"><p>{preview.message}</p><ul>{preview.items.map((item) => <li key={item.name}>{item.name} · disabled</li>)}</ul>{preview.conflicts.length > 0 && <><p className="tools-notice">Conflicts: {preview.conflicts.map((x) => x.name + (x.archived ? " (archived)" : "")).join(", ")}</p><label><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />Replace existing configurations and disable them</label></>}</div>}
    <footer><Button disabled={pending} onClick={close}>Cancel</Button>{mode === "import" && <Button disabled={pending} onClick={() => void act(async () => { setPreview(await previewToolImport(parse())); setReplace(false) })}>Preview import</Button>}<Button variant="primary" disabled={pending || (mode === "import" && (!preview || preview.conflicts.some((x) => x.archived) || (preview.conflicts.length > 0 && !replace)))} onClick={() => void act(async () => {
      if (mode === "import") { const result = await applyToolImport(parse(), preview!, replace); saved(result.items[0]?.tool_id) }
      else if (mode === "archive") { await archiveTool(tool!); saved(tool!.tool_id) }
      else { const result = mode === "add" ? await createCustomTool(parse()) : await editToolConfiguration(tool!, parse()); saved(result.tool_id) }
    })}>{pending ? "Saving…" : mode === "import" ? "Apply import" : mode === "archive" ? "Archive tool" : "Save tool"}</Button></footer>
  </div></div>
}
