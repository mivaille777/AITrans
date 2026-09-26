import { apiGet, apiPost, apiWebSocketUrl } from "./client"

export interface SandboxRuntimeHealth {
  available: boolean
  runtime: "docker"
  image: string
  daemon_ready: boolean
  os_type: string
  detail: string
  error_code: string
}

interface RawSandboxRuntimeHealth {
  available: boolean
  runtime?: string
  image?: string
  daemon_ready?: boolean
  os_type?: string
  detail?: string
  server_os?: string
  error_code?: string | null
  message?: string
}

export type SandboxRunStatus =
  | "pending"
  | "preparing"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "output_limit_exceeded"
  | "oom_killed"

export interface SandboxRunSummary {
  sandbox_id: string
  run_id: string
  tool_call_id: string
  source: "agent" | "manual"
  workspace_id: string
  workspace_name: string
  runtime: string
  image: string
  status: SandboxRunStatus
  started_at: string
  finished_at: string | null
  duration_ms: number
  exit_code: number | null
}

export type SandboxDebugStageKey =
  | "request"
  | "workspace"
  | "staging"
  | "create"
  | "start"
  | "execute"
  | "collect"
  | "cleanup"

export type SandboxDebugStageStatus =
  | "pending"
  | "running"
  | "complete"
  | "failed"
  | "skipped"

export interface SandboxDebugStage {
  key: SandboxDebugStageKey
  label: string
  status: SandboxDebugStageStatus
  elapsed_ms: number
  note: string
}

export type SandboxActivityKind =
  | "file"
  | "network"
  | "process"
  | "runtime"
  | "policy"

export type SandboxActivityDecision = "allowed" | "denied" | "observed"

export interface SandboxActivityEvent {
  sequence: number
  timestamp: string
  kind: SandboxActivityKind
  action: string
  target: string
  decision: SandboxActivityDecision
  reason: string
}

export interface SandboxResourceSample {
  timestamp_ms: number
  cpu_percent: number
  memory_bytes: number
  pids: number
  stdout_bytes: number
  stderr_bytes: number
  output_bytes: number
}

export interface SandboxEffectivePolicy {
  network: string
  root_filesystem_read_only: boolean
  user: string
  cap_drop: string[]
  no_new_privileges: boolean
  seccomp: string
  cpu_limit: number
  memory_limit_bytes: number
  pids_limit: number
  timeout_seconds: number
  stdout_limit_bytes: number
  stderr_limit_bytes: number
  docker_socket_mounted: boolean
}

export interface SandboxDebugFile {
  file_id: string
  path: string
  size_bytes: number
  sha256: string
  source: "workspace" | "generated" | "runtime"
}

export interface SandboxDebugTrace {
  run: SandboxRunSummary
  stages: SandboxDebugStage[]
  stdout: string
  stderr: string
  activities: SandboxActivityEvent[]
  resources: SandboxResourceSample[]
  policy: SandboxEffectivePolicy
  input_files: SandboxDebugFile[]
  output_files: SandboxDebugFile[]
  error: string
}

export interface StartSandboxDebugRunRequest {
  code: string
  filesystem_workspace_id?: string
}

export interface SandboxDebugRunAccepted {
  sandbox_id: string
  run_id: string
  status: SandboxRunStatus
}

export type SandboxDebugStreamEvent =
  | { type: "stage"; stage: SandboxDebugStage }
  | { type: "activity"; activity: SandboxActivityEvent }
  | { type: "resource"; sample: SandboxResourceSample }
  | { type: "trace"; trace: SandboxDebugTrace }
  | { type: "terminal"; trace: SandboxDebugTrace }
  | { type: "error"; code: string; message: string }

export interface SandboxDebugStreamHandlers {
  onEvent: (event: SandboxDebugStreamEvent) => void
  onTransportError: (error: Error) => void
}

export interface SandboxDebugStreamHandle {
  close: () => void
}

export async function getSandboxRuntimeHealth(): Promise<SandboxRuntimeHealth> {
  const raw = await apiGet<RawSandboxRuntimeHealth>("/api/sandbox/debug/health")
  return normalizeSandboxRuntimeHealth(raw)
}

export function normalizeSandboxRuntimeHealth(
  raw: RawSandboxRuntimeHealth,
): SandboxRuntimeHealth {
  return {
    available: Boolean(raw.available),
    runtime: "docker",
    image: raw.image ?? "",
    daemon_ready: raw.daemon_ready ?? Boolean(raw.available),
    os_type: raw.os_type ?? raw.server_os ?? "",
    detail: raw.detail ?? raw.message ?? "",
    error_code: raw.error_code ?? "",
  }
}

export function listSandboxDebugRuns(): Promise<SandboxRunSummary[]> {
  return apiGet<SandboxRunSummary[]>("/api/sandbox/debug/runs")
}

export function getSandboxDebugRun(sandboxId: string): Promise<SandboxDebugTrace> {
  return apiGet<SandboxDebugTrace>(
    `/api/sandbox/debug/runs/${encodeURIComponent(sandboxId)}`,
  )
}

export function startSandboxDebugRun(
  payload: StartSandboxDebugRunRequest,
): Promise<SandboxDebugRunAccepted> {
  return apiPost<SandboxDebugRunAccepted, StartSandboxDebugRunRequest>(
    "/api/sandbox/debug/runs",
    payload,
  )
}

export function cancelSandboxDebugRun(
  sandboxId: string,
): Promise<SandboxRunSummary> {
  return apiPost<SandboxRunSummary, Record<string, never>>(
    `/api/sandbox/debug/runs/${encodeURIComponent(sandboxId)}/cancel`,
    {},
  )
}

function parseSandboxDebugStreamEvent(raw: string): SandboxDebugStreamEvent {
  const parsed = JSON.parse(raw) as Partial<SandboxDebugStreamEvent>
  if (!parsed || typeof parsed !== "object" || typeof parsed.type !== "string") {
    throw new Error("Invalid Sandbox debug stream event.")
  }

  const supportedTypes = new Set([
    "stage",
    "activity",
    "resource",
    "trace",
    "terminal",
    "error",
  ])
  if (!supportedTypes.has(parsed.type)) {
    throw new Error("Unsupported Sandbox debug stream event.")
  }

  return parsed as SandboxDebugStreamEvent
}

export function streamSandboxDebugRun(
  sandboxId: string,
  handlers: SandboxDebugStreamHandlers,
): SandboxDebugStreamHandle {
  const path = `/api/sandbox/debug/runs/${encodeURIComponent(sandboxId)}/stream`
  const socket = new WebSocket(apiWebSocketUrl(path))
  let closed = false

  socket.addEventListener("message", (message) => {
    if (closed) return
    try {
      const event = parseSandboxDebugStreamEvent(String(message.data))
      handlers.onEvent(event)
      if (event.type === "terminal" || event.type === "error") {
        closed = true
        socket.close(1000, event.type)
      }
    } catch (error) {
      closed = true
      handlers.onTransportError(
        error instanceof Error ? error : new Error("Invalid Sandbox debug stream event."),
      )
      socket.close(1002, "invalid-sandbox-event")
    }
  })

  socket.addEventListener("error", () => {
    if (closed) return
    closed = true
    handlers.onTransportError(new Error("Unable to connect to the Sandbox debug stream."))
  })

  socket.addEventListener("close", (event) => {
    if (closed || event.code === 1000) return
    closed = true
    handlers.onTransportError(
      new Error(`Sandbox debug stream closed unexpectedly (${event.code}).`),
    )
  })

  return {
    close() {
      if (closed) return
      closed = true
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close(1000, "client-close")
      }
    },
  }
}
