import { AlertCircle, Copy, LoaderCircle, Play, Square } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { listFilesystemWorkspaces, type FilesystemWorkspace } from "../../api/filesystem-workspaces"
import { sandboxDebugErrorFromCode, sandboxDebugErrorMessage } from "./sandbox-debug-errors"
import {
  cancelSandboxDebugRun,
  getSandboxDebugRun,
  exportSandboxReport,
  startSandboxDebugRun,
  streamSandboxDebugRun,
  type SandboxDebugStage,
  type SandboxDebugStreamEvent,
  type SandboxDebugStreamHandle,
  type SandboxDebugTrace,
  type SandboxRunStatus,
  type SandboxRuntimeHealth,
} from "../../api/sandbox-debug"

const INITIAL_STAGES: SandboxDebugStage[] = [
  { key: "request", label: "Request", status: "pending", elapsed_ms: 0, note: "Validate debug request" },
  { key: "permission", label: "Permission", status: "pending", elapsed_ms: 0, note: "Evaluate requested access" },
  { key: "approval", label: "Approval", status: "pending", elapsed_ms: 0, note: "Wait for user approval when required" },
  { key: "workspace", label: "Workspace", status: "pending", elapsed_ms: 0, note: "Resolve filesystem scope" },
  { key: "staging", label: "Staging", status: "pending", elapsed_ms: 0, note: "Stage bounded inputs" },
  { key: "create", label: "Container", status: "pending", elapsed_ms: 0, note: "Create isolated container" },
  { key: "start", label: "Start", status: "pending", elapsed_ms: 0, note: "Start runtime" },
  { key: "execute", label: "Execute", status: "pending", elapsed_ms: 0, note: "Execute Python" },
  { key: "network", label: "Network", status: "pending", elapsed_ms: 0, note: "Apply network policy" },
  { key: "changes", label: "Changes", status: "pending", elapsed_ms: 0, note: "Collect workspace changes" },
  { key: "apply", label: "Apply", status: "pending", elapsed_ms: 0, note: "Apply approved host changes" },
  { key: "collect", label: "Collect", status: "pending", elapsed_ms: 0, note: "Collect outputs" },
  { key: "cleanup", label: "Cleanup", status: "pending", elapsed_ms: 0, note: "Remove runtime resources" },
]

export default function SandboxDebugTrace({
  health,
  selectedTrace = null,
  onTraceChange,
}: {
  health: SandboxRuntimeHealth | null
  selectedTrace?: SandboxDebugTrace | null
  onTraceChange?: (trace: SandboxDebugTrace | null) => void
}) {
  const [code, setCode] = useState('print("Hello from AITrans Sandbox")')
  const [trace, setTrace] = useState<SandboxDebugTrace | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState("")
  const [filesystemWorkspaces, setFilesystemWorkspaces] = useState<FilesystemWorkspace[]>([])
  const [filesystemWorkspaceId, setFilesystemWorkspaceId] = useState("")
  const [executionKind, setExecutionKind] = useState<"python" | "command">("python")
  const [command, setCommand] = useState('["python", "--version"]')
  const [cwd, setCwd] = useState(".")
  const [retainContent, setRetainContent] = useState(false)
  const streamRef = useRef<SandboxDebugStreamHandle | null>(null)
  const runGenerationRef = useRef(0)
  const streamedTerminalGenerationRef = useRef<number | null>(null)
  const streamedEventGenerationRef = useRef<number | null>(null)
  const sequenceRef = useRef(-1)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retryCountRef = useRef(0)

  const runtimeReady = Boolean(health?.available && health.daemon_ready)
  const stages = trace?.stages.length ? trace.stages : INITIAL_STAGES
  const run = trace?.run ?? null

  useEffect(() => () => {
    runGenerationRef.current += 1
    streamRef.current?.close()
    streamRef.current = null
    if (retryRef.current) clearTimeout(retryRef.current)
  }, [])

  useEffect(() => {
    let disposed = false
    void listFilesystemWorkspaces()
      .then((workspaces) => {
        if (!disposed) setFilesystemWorkspaces(workspaces.filter((item) => item.status === "active"))
      })
      .catch(() => {
        if (!disposed) setFilesystemWorkspaces([])
      })
    return () => {
      disposed = true
    }
  }, [])

  useEffect(() => {
    onTraceChange?.(trace)
  }, [onTraceChange, trace])

  /* oxlint-disable react-hooks/set-state-in-effect -- a Runs-tab selection replaces the inspected trace */
  useEffect(() => {
    if (!selectedTrace) return
    runGenerationRef.current += 1
    sequenceRef.current = selectedTrace.sequence ?? -1
    streamedTerminalGenerationRef.current = null
    streamedEventGenerationRef.current = null
    if (retryRef.current) clearTimeout(retryRef.current)
    streamRef.current?.close()
    streamRef.current = null
    setTrace(selectedTrace)
    setRunning(!isTerminal(selectedTrace.run.status))
    setError("")
    // oxlint-disable-next-line react/immutability -- This hoisted callback runs after render; reconnect recursion occurs only in timers.
    if (!isTerminal(selectedTrace.run.status)) subscribe(selectedTrace.run.sandbox_id, runGenerationRef.current)
  }, [selectedTrace])
  /* oxlint-enable react-hooks/set-state-in-effect */

  const summaryItems = useMemo(() => [
    ["Sandbox ID", run?.sandbox_id || "—"],
    ["Agent Run", run?.run_id || "—"],
    ["Tool Call", run?.tool_call_id || "—"],
    ["Runtime", run?.runtime || "Docker / Python"],
    ["Image", run?.image || health?.image || "—"],
    ["Exit Code", run?.exit_code === null || run?.exit_code === undefined ? "—" : String(run.exit_code)],
    ["Duration", run ? formatDuration(run.duration_ms) : "—"],
    ["Status", run?.status || "idle"],
  ], [health?.image, run])

  async function runTrace() {
    if (!runtimeReady || !(executionKind === "python" ? code.trim() : command.trim()) || running) return

    const generation = runGenerationRef.current + 1
    runGenerationRef.current = generation
    streamedTerminalGenerationRef.current = null
    streamedEventGenerationRef.current = null
    sequenceRef.current = -1
    retryCountRef.current = 0
    if (retryRef.current) clearTimeout(retryRef.current)
    setRunning(true)
    setError("")
    setTrace(null)
    streamRef.current?.close()
    streamRef.current = null

    try {
      let argv: string[] | undefined
      if (executionKind === "command") {
        const parsed: unknown = JSON.parse(command)
        if (!Array.isArray(parsed) || parsed.length === 0 || !parsed.every((item) => typeof item === "string")) throw new Error("Enter a JSON array of command arguments.")
        argv = parsed
      }
      const accepted = await startSandboxDebugRun({
        code: executionKind === "python" ? code.trim() : command,
        ...(retainContent ? { retain_content: true } : {}),
        ...(executionKind === "command" ? { execution_kind: executionKind } : {}),
        ...(argv ? { argv, cwd } : {}),
        ...(filesystemWorkspaceId ? { filesystem_workspace_id: filesystemWorkspaceId } : {}),
      })
      if (runGenerationRef.current !== generation) return
      setTrace(createPendingTrace(accepted.sandbox_id, accepted.run_id, health))

      subscribe(accepted.sandbox_id, generation)

      try {
        const initial = await getSandboxDebugRun(accepted.sandbox_id)
        if (runGenerationRef.current !== generation) return
        if (initial.sequence === undefined && streamedEventGenerationRef.current === generation) return
        handleStreamEvent({ type: isTerminal(initial.run.status) ? "terminal" : "trace", trace: initial, sequence: initial.sequence }, generation)
      } catch {
        // Streaming remains authoritative while the run record is still being created.
      }
    } catch (runError) {
      if (runGenerationRef.current !== generation) return
      setError(sandboxDebugErrorMessage(runError, "Sandbox execution failed."))
      setRunning(false)
    }
  }

  async function stopTrace() {
    const sandboxId = trace?.run.sandbox_id
    if (!sandboxId || !running) return

    const generation = runGenerationRef.current
    try {
      const cancelled = await cancelSandboxDebugRun(sandboxId)
      if (runGenerationRef.current !== generation) return
      setTrace((current) => current ? { ...current, run: cancelled } : current)
      try {
        const finalTrace = await getSandboxDebugRun(sandboxId)
        handleStreamEvent({type: isTerminal(finalTrace.run.status) ? "terminal" : "trace", trace: finalTrace, sequence: finalTrace.sequence}, generation)
      } catch {
        // The cancellation summary is sufficient to leave running state safely.
      }
    } catch (cancelError) {
      setError(sandboxDebugErrorMessage(cancelError, "Sandbox execution failed."))
    }
  }

  function subscribe(sandboxId: string, generation: number) {
    if (generation !== runGenerationRef.current || streamedTerminalGenerationRef.current === generation) return
    streamRef.current?.close()
    streamRef.current = streamSandboxDebugRun(sandboxId, {
      onEvent: (event) => handleStreamEvent(event, generation),
      onTransportError: () => {
        if (generation !== runGenerationRef.current || streamedTerminalGenerationRef.current === generation) return
        setError("Connection interrupted; reconnecting to the existing run…")
        streamRef.current?.close()
        streamRef.current = null
        if (retryRef.current) clearTimeout(retryRef.current)
        retryRef.current = setTimeout(() => {
          void getSandboxDebugRun(sandboxId).then((snapshot) => {
            handleStreamEvent({type: isTerminal(snapshot.run.status) ? "terminal" : "trace", trace: snapshot, sequence: snapshot.sequence}, generation)
          }).catch(() => {}).finally(() => subscribe(sandboxId, generation))
        }, Math.min(1000 * 2 ** Math.min(retryCountRef.current++, 5), 30000))
      },
    })
  }

  function handleStreamEvent(event: SandboxDebugStreamEvent, generation: number) {
    if (runGenerationRef.current !== generation) return
    if (streamedTerminalGenerationRef.current === generation) return
    setError("")
    retryCountRef.current = 0
    if (event.sequence !== undefined) {
      if (event.sequence <= sequenceRef.current) return
      sequenceRef.current = event.sequence
    }
    streamedEventGenerationRef.current = generation
    if (event.type === "trace" || event.type === "terminal") {
      if (event.type === "terminal") {
        if (retryRef.current) clearTimeout(retryRef.current)
        streamedTerminalGenerationRef.current = generation
      }
      setTrace(event.trace)
      setRunning(!isTerminal(event.trace.run.status))
      if (event.type === "terminal") {
        setRunning(false)
        streamRef.current?.close()
        streamRef.current = null
      }
      return
    }
    if (event.type === "error") {
      setError(sandboxDebugErrorFromCode(event.code, "Sandbox execution failed."))
      setRunning(false)
      streamRef.current = null
      return
    }

    setTrace((current) => {
      if (!current) return current
      if (event.type === "output") return { ...current, stdout: event.stdout, stderr: event.stderr, sequence: event.sequence }
      if (event.type === "stage") {
        const found = current.stages.some((stage) => stage.key === event.stage.key)
        return {
          ...current,
          stages: found
            ? current.stages.map((stage) => stage.key === event.stage.key ? event.stage : stage)
            : [...current.stages, event.stage],
        }
      }
      if (event.type === "activity") {
        return { ...current, activities: [...current.activities, event.activity] }
      }
      return { ...current, resources: [...current.resources.slice(-239), event.sample] }
    })
  }

  return (
    <div className="h-full overflow-auto bg-slate-50/40 px-8 py-6">
      <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-5">
        <section className="rounded-[10px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="flex items-start justify-between gap-5">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Manual trace</p>
              <h2 className="mt-1 text-[15px] font-semibold text-slate-900">Run isolated Python</h2>
              <p className="mt-1 text-[11px] text-slate-500">
                Debug execution uses the runtime policy; this page cannot enable network, mounts or privileged mode.
              </p>
            </div>
            {!runtimeReady && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-medium text-amber-800">
                <AlertCircle size={12} />
                Runtime unavailable
              </span>
            )}
          </div>

          <label className="mt-4 block text-[11px] font-medium text-slate-700" htmlFor="sandbox-python-code">Python Code</label>
          <div className="mt-3 flex gap-3 text-[11px] text-slate-600">
            <select aria-label="Execution kind" value={executionKind} disabled={running} onChange={(event) => setExecutionKind(event.target.value as "python" | "command")}>
              <option value="python">Python</option><option value="command">Command (python / pytest)</option>
            </select>
            <label><input type="checkbox" checked={retainContent} disabled={running} onChange={(event) => setRetainContent(event.target.checked)} /> Retain scrubbed code and logs in history</label>
          </div>
          <textarea
            id="sandbox-python-code"
            aria-label="Python Code"
            value={code}
            hidden={executionKind === "command"}
            onChange={(event) => setCode(event.target.value)}
            spellCheck={false}
            className="mt-2 min-h-36 w-full resize-y rounded-[9px] border border-slate-200 bg-slate-950 px-3.5 py-3 font-mono text-[11px] leading-5 text-slate-100 outline-none transition focus:border-slate-400"
          />
          {executionKind === "command" && <div className="mt-3 flex flex-col gap-2 text-[11px]">
            <label>Command argv (JSON array)<input aria-label="Command argv" value={command} onChange={(event) => setCommand(event.target.value)} className="ml-2 w-2/3 rounded border p-2 font-mono" /></label>
            <label>Workspace relative cwd<input aria-label="Command cwd" value={cwd} onChange={(event) => setCwd(event.target.value)} className="ml-2 rounded border p-2" /></label>
          </div>}

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="rounded-[8px] border border-slate-200 bg-slate-50 px-3 py-2.5">
              <span className="text-[10px] font-medium uppercase tracking-[0.1em] text-slate-400">Filesystem Workspace</span>
              <select
                aria-label="Filesystem Workspace"
                value={filesystemWorkspaceId}
                disabled={running}
                onChange={(event) => setFilesystemWorkspaceId(event.target.value)}
                className="mt-1 w-full bg-transparent text-[11px] font-medium text-slate-700 outline-none disabled:text-slate-400"
              >
                <option value="">No workspace</option>
                {filesystemWorkspaces.map((workspace) => (
                  <option key={workspace.workspace_id} value={workspace.workspace_id}>
                    {workspace.display_name}
                  </option>
                ))}
              </select>
            </label>
            <ReadOnlyField label="Runtime" value="Docker / Python" />
            <ReadOnlyField label="Timeout" value="30 s" />
          </div>

          <div className="mt-4 flex items-center justify-between gap-4">
            <div className="min-h-5 text-[11px] text-rose-700" role={error ? "alert" : undefined}>
              {error}
            </div>
            {running ? (
              <button
                type="button"
                onClick={() => void stopTrace()}
                disabled={run?.source === "agent" || run?.status === "cancelling"}
                className="inline-flex items-center gap-2 rounded-[8px] border border-slate-300 bg-white px-3.5 py-2 text-[12px] font-medium text-slate-800 hover:bg-slate-50"
              >
                <Square size={13} />
                {run?.source === "agent" ? "Agent controls this run" : run?.status === "cancelling" ? "Cancelling…" : "Stop"}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void runTrace()}
                disabled={!runtimeReady || !(executionKind === "python" ? code.trim() : command.trim())}
                className="inline-flex items-center gap-2 rounded-[8px] bg-slate-950 px-3.5 py-2 text-[12px] font-medium text-white disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                <Play size={13} />
                Run
              </button>
            )}
          </div>
        </section>

        <section className="rounded-[10px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Execution stages</p>
              <h2 className="mt-1 text-[15px] font-semibold text-slate-900">Sandbox lifecycle</h2>
            </div>
            {running && <span className="inline-flex items-center gap-1.5 text-[10px] text-slate-500"><LoaderCircle size={12} className="animate-spin" />Running</span>}
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-4 lg:grid-cols-8">
            {stages.map((stage) => <StagePill key={stage.key} stage={stage} />)}
          </div>
        </section>

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {summaryItems.map(([label, value]) => (
            <div key={label} className="rounded-[10px] border border-slate-200 bg-white px-4 py-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
              <p className="text-[10px] font-medium uppercase tracking-[0.11em] text-slate-400">{label}</p>
              <div className="mt-1 flex min-w-0 items-center gap-2">
                <p className="min-w-0 flex-1 truncate text-[12px] font-medium text-slate-800" title={value}>{value}</p>
                {value !== "—" && (label === "Agent Run" || label === "Tool Call") ? (
                  <button
                    type="button"
                    aria-label={label === "Agent Run" ? "Copy Run ID" : "Copy Tool Call ID"}
                    onClick={() => void copyText(value)}
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] border border-slate-200 text-slate-400 hover:bg-slate-50 hover:text-slate-700"
                  >
                    <Copy size={10} />
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </section>

        <section className="grid min-h-56 gap-4 lg:grid-cols-2">
          <OutputPanel title="stdout" value={trace?.stdout ?? ""} />
          <OutputPanel title="stderr" value={trace?.stderr ?? ""} error />
        </section>
        {trace && <section className="flex flex-wrap gap-3 text-[11px] text-slate-600">
          <button type="button" onClick={() => void exportSandboxReport(trace.run.sandbox_id, "markdown").catch((e) => setError(sandboxDebugErrorMessage(e, "Export failed.")))}>Export Markdown</button>
          <button type="button" onClick={() => void exportSandboxReport(trace.run.sandbox_id, "json").catch((e) => setError(sandboxDebugErrorMessage(e, "Export failed.")))}>Export JSON</button>
          {trace.code && !running && <button type="button" onClick={() => {
            setExecutionKind(trace.execution_kind ?? "python")
            if (trace.execution_kind === "command") setCommand(trace.code ?? "")
            else setCode(trace.code ?? "")
          }}>Load retained source for review</button>}
          <span>{trace.logs_retained ? "Scrubbed code and logs retained" : "History retains metadata only"}</span>
          {trace.error && <span role="alert" className="text-rose-700">{trace.error}</span>}
        </section>}

        {!trace && !running && !error && (
          <section className="rounded-[10px] border border-dashed border-slate-200 bg-white px-8 py-10 text-center">
            <h2 className="text-[15px] font-semibold text-slate-900">Run a Python sandbox trace</h2>
            <p className="mx-auto mt-2 max-w-xl text-[12px] leading-5 text-slate-500">
              Execute isolated Python code and inspect container lifecycle, output and cleanup.
            </p>
          </section>
        )}
      </div>
    </div>
  )
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[8px] border border-slate-200 bg-slate-50 px-3 py-2.5">
      <p className="text-[10px] font-medium uppercase tracking-[0.1em] text-slate-400">{label}</p>
      <p className="mt-1 text-[11px] font-medium text-slate-700">{value}</p>
    </div>
  )
}

function StagePill({ stage }: { stage: SandboxDebugStage }) {
  const classes = stage.status === "complete"
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : stage.status === "failed"
      ? "border-rose-200 bg-rose-50 text-rose-700"
      : stage.status === "running"
        ? "border-amber-200 bg-amber-50 text-amber-800"
        : stage.status === "skipped"
          ? "border-slate-200 bg-slate-50 text-slate-400"
          : "border-slate-200 bg-white text-slate-500"

  return (
    <div className={`rounded-[8px] border px-2.5 py-2 ${classes}`} title={stage.note}>
      <p className="truncate text-[10px] font-semibold">{stage.label}</p>
      <p className="mt-0.5 text-[9px] opacity-80">{stage.status}{stage.elapsed_ms ? ` · ${stage.elapsed_ms} ms` : ""}</p>
    </div>
  )
}

function OutputPanel({ title, value, error = false }: { title: string; value: string; error?: boolean }) {
  return (
    <div className="flex min-h-56 flex-col overflow-hidden rounded-[10px] border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className={`text-[11px] font-semibold ${error ? "text-rose-700" : "text-slate-700"}`}>{title}</h2>
      </div>
      <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words bg-slate-950 px-4 py-3 font-mono text-[11px] leading-5 text-slate-100">
        {value || "No output"}
      </pre>
    </div>
  )
}

function isTerminal(status: SandboxRunStatus): boolean {
  return ["completed", "failed", "cancelled", "timed_out", "output_limit_exceeded", "storage_limit_exceeded", "interrupted", "oom_killed"].includes(status)
}

function formatDuration(durationMs: number): string {
  if (durationMs < 1000) return `${durationMs} ms`
  return `${(durationMs / 1000).toFixed(2)} s`
}

function createPendingTrace(
  sandboxId: string,
  runId: string,
  health: SandboxRuntimeHealth | null,
): SandboxDebugTrace {
  return {
    run: {
      sandbox_id: sandboxId,
      run_id: runId,
      tool_call_id: "",
      source: "manual",
      workspace_id: "",
      workspace_name: "",
      runtime: "docker",
      image: health?.image ?? "",
      status: "preparing",
      started_at: new Date().toISOString(),
      finished_at: null,
      duration_ms: 0,
      exit_code: null,
    },
    stages: INITIAL_STAGES,
    stdout: "",
    stderr: "",
    activities: [],
    resources: [],
    policy: {
      network: "",
      root_filesystem_read_only: false,
      user: "",
      cap_drop: [],
      no_new_privileges: false,
      seccomp: "",
      cpu_limit: 0,
      memory_limit_bytes: 0,
      pids_limit: 0,
      timeout_seconds: 0,
      stdout_limit_bytes: 0,
      stderr_limit_bytes: 0,
      output_limit_bytes: 0,
      docker_socket_mounted: null,
    },
    input_files: [],
    output_files: [],
    workspace_changes: [],
    error: "",
  }
}

async function copyText(value: string): Promise<void> {
  if (typeof navigator === "undefined" || !navigator.clipboard) return
  await navigator.clipboard.writeText(value)
}
