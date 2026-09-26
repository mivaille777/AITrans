import { AlertCircle, LoaderCircle, Play, Square } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { listFilesystemWorkspaces, type FilesystemWorkspace } from "../../api/filesystem-workspaces"
import {
  cancelSandboxDebugRun,
  getSandboxDebugRun,
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
  { key: "workspace", label: "Workspace", status: "pending", elapsed_ms: 0, note: "Resolve filesystem scope" },
  { key: "staging", label: "Staging", status: "pending", elapsed_ms: 0, note: "Stage bounded inputs" },
  { key: "create", label: "Container", status: "pending", elapsed_ms: 0, note: "Create isolated container" },
  { key: "start", label: "Start", status: "pending", elapsed_ms: 0, note: "Start runtime" },
  { key: "execute", label: "Execute", status: "pending", elapsed_ms: 0, note: "Execute Python" },
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
  const streamRef = useRef<SandboxDebugStreamHandle | null>(null)

  const runtimeReady = Boolean(health?.available && health.daemon_ready)
  const stages = trace?.stages.length ? trace.stages : INITIAL_STAGES
  const run = trace?.run ?? null

  useEffect(() => () => {
    streamRef.current?.close()
    streamRef.current = null
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
    if (selectedTrace.run.sandbox_id === trace?.run.sandbox_id) return
    setTrace(selectedTrace)
    setRunning(false)
    setError("")
  }, [selectedTrace, trace?.run.sandbox_id])
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
    if (!runtimeReady || !code.trim() || running) return

    setRunning(true)
    setError("")
    setTrace(null)
    streamRef.current?.close()
    streamRef.current = null

    try {
      const accepted = await startSandboxDebugRun({
        code: code.trim(),
        ...(filesystemWorkspaceId ? { filesystem_workspace_id: filesystemWorkspaceId } : {}),
      })
      setTrace(createPendingTrace(accepted.sandbox_id, accepted.run_id, health))

      streamRef.current = streamSandboxDebugRun(accepted.sandbox_id, {
        onEvent: handleStreamEvent,
        onTransportError: (streamError) => {
          setError(streamError.message)
          setRunning(false)
        },
      })

      try {
        const initial = await getSandboxDebugRun(accepted.sandbox_id)
        setTrace(initial)
        if (isTerminal(initial.run.status)) setRunning(false)
      } catch {
        // Streaming remains authoritative while the run record is still being created.
      }
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Unable to start Sandbox run.")
      setRunning(false)
    }
  }

  async function stopTrace() {
    const sandboxId = trace?.run.sandbox_id
    if (!sandboxId || !running) return

    try {
      const cancelled = await cancelSandboxDebugRun(sandboxId)
      setTrace((current) => current ? { ...current, run: cancelled } : current)
      try {
        const finalTrace = await getSandboxDebugRun(sandboxId)
        setTrace(finalTrace)
      } catch {
        // The cancellation summary is sufficient to leave running state safely.
      }
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : "Unable to cancel Sandbox run.")
    } finally {
      streamRef.current?.close()
      streamRef.current = null
      setRunning(false)
    }
  }

  function handleStreamEvent(event: SandboxDebugStreamEvent) {
    if (event.type === "trace" || event.type === "terminal") {
      setTrace(event.trace)
      if (event.type === "terminal") {
        setRunning(false)
        streamRef.current = null
      }
      return
    }
    if (event.type === "error") {
      setError(event.message)
      setRunning(false)
      streamRef.current = null
      return
    }

    setTrace((current) => {
      if (!current) return current
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
      return { ...current, resources: [...current.resources, event.sample] }
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
          <textarea
            id="sandbox-python-code"
            aria-label="Python Code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            spellCheck={false}
            className="mt-2 min-h-36 w-full resize-y rounded-[9px] border border-slate-200 bg-slate-950 px-3.5 py-3 font-mono text-[11px] leading-5 text-slate-100 outline-none transition focus:border-slate-400"
          />

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
                className="inline-flex items-center gap-2 rounded-[8px] border border-slate-300 bg-white px-3.5 py-2 text-[12px] font-medium text-slate-800 hover:bg-slate-50"
              >
                <Square size={13} />
                Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void runTrace()}
                disabled={!runtimeReady || !code.trim()}
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
              <p className="mt-1 truncate text-[12px] font-medium text-slate-800" title={value}>{value}</p>
            </div>
          ))}
        </section>

        <section className="grid min-h-56 gap-4 lg:grid-cols-2">
          <OutputPanel title="stdout" value={trace?.stdout ?? ""} />
          <OutputPanel title="stderr" value={trace?.stderr ?? ""} error />
        </section>

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
  return ["completed", "failed", "cancelled", "timed_out", "output_limit_exceeded", "oom_killed"].includes(status)
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
      root_filesystem_read_only: true,
      user: "",
      cap_drop: [],
      no_new_privileges: true,
      seccomp: "",
      cpu_limit: 0,
      memory_limit_bytes: 0,
      pids_limit: 0,
      timeout_seconds: 30,
      stdout_limit_bytes: 0,
      stderr_limit_bytes: 0,
      docker_socket_mounted: false,
    },
    input_files: [],
    output_files: [],
    error: "",
  }
}
