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

type RawSandboxRunStatus = SandboxRunStatus | "succeeded" | string

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
  output_limit_bytes?: number
  docker_socket_mounted: boolean | null
}

type RawSandboxEffectivePolicy = Partial<SandboxEffectivePolicy> & {
  network_mode?: string
  read_only_rootfs?: boolean
  nano_cpus?: number
  max_total_output_bytes?: number
}

export interface SandboxDebugFile {
  file_id: string
  path: string
  size_bytes: number
  sha256: string
  source: "workspace" | "generated" | "runtime"
}

type RawSandboxDebugFile = Partial<SandboxDebugFile> & {
  relative_path?: string
}

type RawSandboxRunSummary = Omit<SandboxRunSummary, "status"> & {
  status: RawSandboxRunStatus
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

type RawSandboxDebugTrace = Omit<
  SandboxDebugTrace,
  "run" | "policy" | "input_files" | "output_files"
> & {
  run: RawSandboxRunSummary
  policy: RawSandboxEffectivePolicy
  input_files: RawSandboxDebugFile[]
  output_files: RawSandboxDebugFile[]
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

export async function listSandboxDebugRuns(): Promise<SandboxRunSummary[]> {
  const runs = await apiGet<RawSandboxRunSummary[]>("/api/sandbox/debug/runs")
  return runs.map(normalizeSandboxRunSummary)
}

export async function getSandboxDebugRun(sandboxId: string): Promise<SandboxDebugTrace> {
  const trace = await apiGet<RawSandboxDebugTrace>(
    `/api/sandbox/debug/runs/${encodeURIComponent(sandboxId)}`,
  )
  return normalizeSandboxDebugTrace(trace)
}

export async function startSandboxDebugRun(
  payload: StartSandboxDebugRunRequest,
): Promise<SandboxDebugRunAccepted> {
  const accepted = await apiPost<
    Omit<SandboxDebugRunAccepted, "status"> & { status: RawSandboxRunStatus },
    StartSandboxDebugRunRequest
  >(
    "/api/sandbox/debug/runs",
    payload,
  )
  return { ...accepted, status: normalizeSandboxRunStatus(accepted.status) }
}

export async function cancelSandboxDebugRun(
  sandboxId: string,
): Promise<SandboxRunSummary> {
  const run = await apiPost<RawSandboxRunSummary, Record<string, never>>(
    `/api/sandbox/debug/runs/${encodeURIComponent(sandboxId)}/cancel`,
    {},
  )
  return normalizeSandboxRunSummary(run)
}

export function normalizeSandboxRunStatus(status: RawSandboxRunStatus): SandboxRunStatus {
  if (status === "succeeded") return "completed"
  if (
    status === "pending"
    || status === "preparing"
    || status === "running"
    || status === "completed"
    || status === "failed"
    || status === "cancelled"
    || status === "timed_out"
    || status === "output_limit_exceeded"
    || status === "oom_killed"
  ) {
    return status
  }
  return "failed"
}

function normalizeSandboxRunSummary(run: RawSandboxRunSummary): SandboxRunSummary {
  return { ...run, status: normalizeSandboxRunStatus(run.status) }
}

function normalizeSandboxDebugTrace(trace: RawSandboxDebugTrace): SandboxDebugTrace {
  return {
    ...trace,
    run: normalizeSandboxRunSummary(trace.run),
    policy: normalizeSandboxEffectivePolicy(trace.policy),
    input_files: trace.input_files.map((file) => normalizeSandboxDebugFile(file, "workspace")),
    output_files: trace.output_files.map((file) => normalizeSandboxDebugFile(file, "generated")),
  }
}

function normalizeSandboxDebugFile(
  file: RawSandboxDebugFile,
  fallbackSource: SandboxDebugFile["source"],
): SandboxDebugFile {
  return {
    file_id: file.file_id ?? "",
    path: file.path ?? file.relative_path ?? "",
    size_bytes: file.size_bytes ?? 0,
    sha256: file.sha256 ?? "",
    source: file.source ?? fallbackSource,
  }
}

export function normalizeSandboxEffectivePolicy(
  policy: RawSandboxEffectivePolicy,
): SandboxEffectivePolicy {
  return {
    network: policy.network ?? policy.network_mode ?? "",
    root_filesystem_read_only:
      policy.root_filesystem_read_only ?? policy.read_only_rootfs ?? false,
    user: policy.user ?? "",
    cap_drop: Array.isArray(policy.cap_drop) ? policy.cap_drop : [],
    no_new_privileges: policy.no_new_privileges ?? false,
    seccomp: policy.seccomp ?? "",
    cpu_limit:
      policy.cpu_limit
      ?? (typeof policy.nano_cpus === "number" ? policy.nano_cpus / 1_000_000_000 : 0),
    memory_limit_bytes: policy.memory_limit_bytes ?? 0,
    pids_limit: policy.pids_limit ?? 0,
    timeout_seconds: policy.timeout_seconds ?? 0,
    stdout_limit_bytes: policy.stdout_limit_bytes ?? 0,
    stderr_limit_bytes: policy.stderr_limit_bytes ?? 0,
    output_limit_bytes:
      policy.output_limit_bytes ?? policy.max_total_output_bytes ?? 0,
    docker_socket_mounted:
      typeof policy.docker_socket_mounted === "boolean"
        ? policy.docker_socket_mounted
        : null,
  }
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

  const event = parsed as SandboxDebugStreamEvent
  if (event.type === "trace" || event.type === "terminal") {
    return {
      ...event,
      trace: normalizeSandboxDebugTrace(event.trace as RawSandboxDebugTrace),
    }
  }
  return event
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
