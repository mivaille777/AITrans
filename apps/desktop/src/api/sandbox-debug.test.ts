import { afterEach, describe, expect, it, vi } from "vitest"

import {
  cancelSandboxDebugRun,
  getSandboxDebugRun,
  getSandboxRuntimeHealth,
  listSandboxDebugRuns,
  startSandboxDebugRun,
  streamSandboxDebugRun,
  normalizeSandboxRuntimeHealth,
  type SandboxDebugTrace,
  type SandboxRunSummary,
} from "./sandbox-debug"

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const run: SandboxRunSummary = {
  sandbox_id: "sb-1",
  run_id: "run-1",
  tool_call_id: "tool-1",
  source: "manual",
  workspace_id: "fsw-1",
  workspace_name: "AITrans",
  runtime: "docker",
  image: "aitrans-sandbox:latest",
  status: "completed",
  started_at: "2026-09-26T12:00:00Z",
  finished_at: "2026-09-26T12:00:01Z",
  duration_ms: 1000,
  exit_code: 0,
}

const trace: SandboxDebugTrace = {
  run,
  stages: [
    { key: "request", label: "Request", status: "complete", elapsed_ms: 2, note: "" },
  ],
  stdout: "285",
  stderr: "",
  activities: [],
  resources: [],
  policy: {
    network: "none",
    root_filesystem_read_only: true,
    user: "10001:10001",
    cap_drop: ["ALL"],
    no_new_privileges: true,
    seccomp: "default",
    cpu_limit: 1,
    memory_limit_bytes: 536870912,
    pids_limit: 64,
    timeout_seconds: 30,
    stdout_limit_bytes: 1048576,
    stderr_limit_bytes: 1048576,
    docker_socket_mounted: false,
  },
  input_files: [],
  output_files: [],
  error: "",
}

describe("sandbox debug api", () => {
  it("reads health, lists runs and gets one trace", async () => {
    const responses = [
      {
        available: true,
        runtime: "docker",
        image: "aitrans-sandbox:latest",
        daemon_ready: true,
        os_type: "linux",
        detail: "",
      },
      [run],
      trace,
    ]

    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(responses.shift()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const health = await getSandboxRuntimeHealth()
    expect(health.daemon_ready).toBe(true)
    expect(health.error_code).toBe("")

    const runs = await listSandboxDebugRuns()
    expect(runs[0]?.sandbox_id).toBe("sb-1")

    const loaded = await getSandboxDebugRun("sb-1")
    expect(loaded.stdout).toBe("285")

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/sandbox/debug/health")
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/sandbox/debug/runs")
    expect(String(fetchMock.mock.calls[2]?.[0])).toContain("/api/sandbox/debug/runs/sb-1")
  })

  it("normalizes the backend sandbox health model into the UI contract", () => {
    expect(normalizeSandboxRuntimeHealth({
      available: true,
      runtime: "docker",
      image: "aitrans-sandbox:latest",
      server_os: "linux",
      error_code: null,
      message: "ready",
    })).toEqual({
      available: true,
      runtime: "docker",
      image: "aitrans-sandbox:latest",
      daemon_ready: true,
      os_type: "linux",
      detail: "ready",
      error_code: "",
    })
  })

  it("starts and cancels a manual run using the bounded request contract", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(
        JSON.stringify(fetchMock.mock.calls.length === 1
          ? { sandbox_id: "sb-1", run_id: "run-1", status: "pending" }
          : { ...run, status: "cancelled" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    )
    vi.stubGlobal("fetch", fetchMock)

    const accepted = await startSandboxDebugRun({
      code: "print(285)",
      filesystem_workspace_id: "fsw-1",
    })
    expect(accepted.sandbox_id).toBe("sb-1")

    const cancelled = await cancelSandboxDebugRun("sb-1")
    expect(cancelled.status).toBe("cancelled")

    const startInit = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(startInit.method).toBe("POST")
    expect(JSON.parse(String(startInit.body))).toEqual({
      code: "print(285)",
      filesystem_workspace_id: "fsw-1",
    })
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/sandbox/debug/runs/sb-1/cancel")
  })

  it("parses stream events and closes on terminal", () => {
    const sockets: MockWebSocket[] = []
    vi.stubGlobal("WebSocket", createMockWebSocketConstructor(sockets))

    const onEvent = vi.fn()
    const onTransportError = vi.fn()
    streamSandboxDebugRun("sb-1", { onEvent, onTransportError })

    const socket = sockets[0]
    expect(socket).toBeTruthy()
    socket?.emit("message", { data: JSON.stringify({ type: "stage", stage: trace.stages[0] }) })
    socket?.emit("message", { data: JSON.stringify({ type: "terminal", trace }) })

    expect(onEvent).toHaveBeenCalledTimes(2)
    expect(onTransportError).not.toHaveBeenCalled()
    expect(socket?.close).toHaveBeenCalledWith(1000, "terminal")
  })

  it("reports invalid stream messages as transport errors", () => {
    const sockets: MockWebSocket[] = []
    vi.stubGlobal("WebSocket", createMockWebSocketConstructor(sockets))

    const onEvent = vi.fn()
    const onTransportError = vi.fn()
    streamSandboxDebugRun("sb-1", { onEvent, onTransportError })

    const socket = sockets[0]
    socket?.emit("message", { data: JSON.stringify({ unexpected: true }) })

    expect(onEvent).not.toHaveBeenCalled()
    expect(onTransportError).toHaveBeenCalledTimes(1)
    expect(socket?.close).toHaveBeenCalledWith(1002, "invalid-sandbox-event")
  })
})

type Listener = (event: any) => void

class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1

  readonly url: string
  readyState = MockWebSocket.OPEN
  close = vi.fn()
  private listeners = new Map<string, Listener[]>()

  constructor(url: string) {
    this.url = url
  }

  addEventListener(type: string, listener: Listener) {
    const listeners = this.listeners.get(type) ?? []
    listeners.push(listener)
    this.listeners.set(type, listeners)
  }

  emit(type: string, event: any) {
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }
}

function createMockWebSocketConstructor(sockets: MockWebSocket[]) {
  class WebSocketMock extends MockWebSocket {
    static readonly CONNECTING = MockWebSocket.CONNECTING
    static readonly OPEN = MockWebSocket.OPEN

    constructor(url: string) {
      super(url)
      sockets.push(this)
    }
  }

  return WebSocketMock
}
