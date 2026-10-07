import { useEffect, useRef, useState } from "react"
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query"
import { Play, Square } from "lucide-react"
import { ApiError, API_BASE_URL } from "../../api/client"
import { approveToolTest, cancelToolTest, createToolTest, getToolTest, getToolTestHistory, getToolTestEvents, validateToolTest, type ToolDetail, type ToolTestRequest, type ToolTestRun, type ToolTestEvent } from "../../api/tools"
import { Button } from "../../shared/ui/Button"

export function ToolInspector({ tool, draft, onDraft }: { tool: ToolDetail; draft: string; onDraft: (value: string) => void }) {
  const [tab, setTab] = useState("Input")
  const [source, setSource] = useState("")
  const [reading, setReading] = useState("{}")
  const [documents, setDocuments] = useState("")
  const [workspace, setWorkspace] = useState("")
  const [filesystem, setFilesystem] = useState("")
  const [timeout, setTimeoutValue] = useState(30)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState("")
  const [run, setRun] = useState<ToolTestRun | null>(null)
  const [events, setEvents] = useState<ToolTestEvent[]>([])
  const [connection, setConnection] = useState({ id: "", value: false })
  const cache = useQueryClient()
  const history = useInfiniteQuery({ queryKey: ["tools", "history", tool.tool_id], queryFn: ({ pageParam }) => getToolTestHistory(tool.tool_id, pageParam), initialPageParam: undefined as string | undefined, getNextPageParam: (page) => page?.next_cursor ?? undefined, refetchInterval: 3000 })
  const recent = history.data?.pages.flatMap((page) => page?.items ?? []) ?? []
  const selectedRun = run?.test_run_id ?? recent[0]?.test_run_id
  const connected = connection.id === selectedRun && connection.value
  const retryRequest = useRef<{ body: ToolTestRequest; digest: string } | null>(null)
  const query = useQuery({ queryKey: ["tools", "test", tool.tool_id, selectedRun], queryFn: () => getToolTest(tool.tool_id, selectedRun!), enabled: Boolean(selectedRun), refetchInterval: (q) => { const value = q.state.data ?? run; return value && (!value.finished_at || ["running", "unknown"].includes(value.execution_state)) ? (connected ? 3000 : 700) : false } })
  const current = query.data ?? run
  const active = current && !current.finished_at
  const log = useQuery({ queryKey: ["tools", "events", tool.tool_id, selectedRun], queryFn: () => getToolTestEvents(tool.tool_id, selectedRun!), enabled: Boolean(selectedRun), refetchInterval: active && !connected ? 2000 : false })
  const combinedEvents = [...new Map([...(log.data?.items ?? []), ...events.filter((event) => event.test_run_id === selectedRun)].map((event) => [event.seq, event])).values()].sort((a, b) => a.seq - b.seq)
  useEffect(() => { if (current?.finished_at) void cache.invalidateQueries({ queryKey: ["tools", "events", tool.tool_id, selectedRun] }) }, [current?.finished_at, current?.updated_at, cache, tool.tool_id, selectedRun])
  useEffect(() => {
    if (!selectedRun || typeof EventSource === "undefined") return
    const setConnected = (value: boolean) => setConnection({ id: selectedRun, value })
    let highest = 0
    const source = new EventSource(`${API_BASE_URL}/api/tools/${encodeURIComponent(tool.tool_id)}/test-runs/${encodeURIComponent(selectedRun)}/events`)
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as ToolTestEvent
        if (event.test_run_id !== selectedRun || event.seq <= highest) return
        highest = event.seq
        setEvents((previous) => [...(previous[0]?.test_run_id === selectedRun ? previous : []), event].slice(-200))
        void cache.invalidateQueries({ queryKey: ["tools", "test", tool.tool_id, selectedRun] })
        void cache.invalidateQueries({ queryKey: ["tools", "events", tool.tool_id, selectedRun] })
      } catch { setConnected(false) }
    }
    source.addEventListener("closed", () => { source.close(); setConnected(false) })
    return () => source.close()
  }, [tool.tool_id, selectedRun, cache])
  async function action(operation: () => Promise<void>) {
    setPending(true); setError("")
    try { await operation() } catch (e) { setError(e instanceof ApiError ? [e.message, ...e.fieldErrors.map((f) => `${f.path}: ${f.message}`)].join("\n") : e instanceof Error ? e.message : "Request failed") } finally { setPending(false) }
  }
  function input() {
    let argumentsValue: unknown, readingValue: unknown
    try { argumentsValue = JSON.parse(draft); readingValue = JSON.parse(reading) } catch { throw new Error("Invalid JSON. Fix the input before running.") }
    if (!argumentsValue || typeof argumentsValue !== "object" || Array.isArray(argumentsValue) || !readingValue || typeof readingValue !== "object" || Array.isArray(readingValue)) throw new Error("Parameters and reading context must be JSON objects.")
    const body = { arguments: argumentsValue as Record<string, unknown>, context_selection: { research_workspace_id: workspace, filesystem_workspace_id: filesystem, knowledge_document_ids: documents.split(/[,\n]/).map((x) => x.trim()).filter(Boolean), reading_context: { ...readingValue, ...(source ? { source_text: source } : {}) } }, timeout_seconds: timeout, stream_output: false, client_request_id: "" }
    const digest = JSON.stringify(body)
    if (retryRequest.current?.digest === digest) return retryRequest.current.body
    body.client_request_id = crypto.randomUUID()
    retryRequest.current = { body, digest }
    return body
  }
  return <>
    <div className="tools-tabs" role="tablist" aria-label="Test views">{["Input", "Result", "Logs"].map((name) => <button key={name} role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>{name}</button>)}</div>
    {recent.length > 0 && <label className="tools-input-label">Last runs<select aria-label="Test history" value={selectedRun} onChange={(event) => { const found = recent.find((item) => item.test_run_id === event.target.value); if (found) { setRun(found); setTab("Result") } }}>{recent.map((item) => <option key={item.test_run_id} value={item.test_run_id}>{item.status} · {new Date(item.created_at).toLocaleString()}</option>)}</select>{history.hasNextPage && <button onClick={() => void history.fetchNextPage()}>Load older runs</button>}</label>}
    {history.isError && <p className="tools-notice">History unavailable.<button onClick={() => void history.refetch()}>Retry history</button></p>}
    {error && <p className="tools-notice" role="alert" style={{ whiteSpace: "pre-wrap" }}>{error}</p>}
    {tab === "Logs" ? <div className="tools-test-result"><p className="tools-note">{connected ? "Live lifecycle events" : "Stored lifecycle events · polling fallback"}</p>{combinedEvents.length ? combinedEvents.map((event) => <p key={event.seq}><code>#{event.seq}</code> {event.type.replaceAll("_", " ")} · {event.execution_state} · {event.elapsed_ms} ms</p>) : <p className="tools-note">No events yet.</p>}{log.isError && <p role="alert">Event log unavailable.<button onClick={() => void log.refetch()}>Retry logs</button></p>}</div> : tab === "Input" ? <>
      <label className="tools-input-label">Input parameters (JSON)<textarea className="tools-input-editor" aria-label="Input parameters JSON" value={draft} onChange={(e) => onDraft(e.target.value)} /></label>
      {tool.context_requirements.includes("knowledge_scope") && <label className="tools-input-label">Knowledge document IDs<textarea aria-label="Knowledge document IDs" placeholder="Explicit IDs, separated by commas" value={documents} onChange={(e) => setDocuments(e.target.value)} /></label>}
      {tool.context_requirements.includes("reading_context") && <label className="tools-input-label">Source text<textarea aria-label="Source text" value={source} onChange={(e) => setSource(e.target.value)} /></label>}
      <details className="tools-context"><summary>Context & options</summary><label className="tools-input-label">Research workspace ID<input value={workspace} onChange={(e) => setWorkspace(e.target.value)} /></label><label className="tools-input-label">Filesystem workspace ID<input value={filesystem} onChange={(e) => setFilesystem(e.target.value)} /></label><label className="tools-input-label">Reading context (JSON)<textarea value={reading} onChange={(e) => setReading(e.target.value)} /></label><label className="tools-input-label">Timeout (seconds)<input type="number" min="1" max="120" value={timeout} onChange={(e) => setTimeoutValue(Number(e.target.value))} /></label><p className="tools-note">Lifecycle updates are live. This executor does not stream output.</p></details>
      <div className="tools-test-actions"><Button disabled={pending || !tool.effective_enabled} onClick={() => void action(async () => { await validateToolTest(tool.tool_id, input()); setError("Input validated.") })}>Validate</Button><Button variant="primary" disabled={pending || Boolean(active) || !tool.effective_enabled || ["running", "unknown"].includes(current?.execution_state ?? "")} onClick={() => void action(async () => { const created = await createToolTest(tool.tool_id, input()); setRun(created); setTab("Result"); retryRequest.current = null })}><Play size={14} />Run tool</Button></div>
    </> : <div className="tools-test-result">{current ? <><strong>{current.status.replaceAll("_", " ")}</strong><p className="tools-note">Executor: {current.execution_state} · {current.elapsed_ms} ms</p><code>{current.test_run_id}</code><p className="tools-note">Trace: {current.trace_id}</p>{current.error && <p className="tools-notice">{current.error.message}</p>}{current.result_truncated && <p className="tools-notice">Result exceeded 256 KiB. Showing a truncated preview.</p>}{current.result && <pre>{JSON.stringify(current.result, null, 2)}</pre>}{current.approval_summary && current.status === "awaiting_approval" && <><p className="tools-notice">This write requires your approval for this exact call.</p><pre>{JSON.stringify(current.approval_summary, null, 2)}</pre><Button variant="primary" disabled={pending} onClick={() => void action(async () => { setRun(await approveToolTest(tool.tool_id, current.test_run_id, current.approval_id!)); await query.refetch() })}>Approve this call</Button></>}{active && <Button disabled={pending} onClick={() => void action(async () => { setRun(await cancelToolTest(tool.tool_id, current.test_run_id)); await query.refetch() })}><Square size={14} />{current.status === "awaiting_approval" ? "Reject call" : "Cancel response"}</Button>}{query.isError && <p className="tools-notice">Connection lost. Reconnecting without replaying the call.</p>}</> : <p className="tools-note">Run a tool to inspect the real result.</p>}</div>}
  </>
}
