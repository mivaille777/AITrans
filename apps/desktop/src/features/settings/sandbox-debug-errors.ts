const ERROR_BY_CODE: Record<string, string> = {
  docker_unavailable: "Docker is unavailable.",
  docker_daemon_unavailable: "Docker is unavailable.",
  docker_not_linux: "Sandbox requires a Linux Docker runtime.",
  sandbox_image_missing: "Sandbox image is missing.",
  image_missing: "Sandbox image is missing.",
  filesystem_workspace_unavailable: "Filesystem workspace is unavailable.",
  workspace_unavailable: "Filesystem workspace is unavailable.",
  sandbox_timeout: "Sandbox run timed out.",
  timed_out: "Sandbox run timed out.",
  sandbox_create_failed: "Sandbox runtime could not be prepared.",
  sandbox_start_failed: "Sandbox runtime could not be started.",
  sandbox_execution_failed: "Sandbox execution failed.",
  sandbox_cleanup_failed: "Sandbox cleanup failed.",
  sandbox_file_limit: "Sandbox output limit exceeded.",
  sandbox_invalid_input: "Sandbox request is invalid.",
  output_limit_exceeded: "Sandbox output limit exceeded.",
  sandbox_output_limit_exceeded: "Sandbox output limit exceeded.",
  oom_killed: "Sandbox was terminated for memory use.",
  sandbox_oom: "Sandbox was terminated for memory use.",
  sandbox_trace_unavailable: "Sandbox trace is unavailable.",
}

export function sandboxDebugErrorFromCode(code: string, fallback: string): string {
  const normalized = code.trim().toLowerCase()
  return ERROR_BY_CODE[normalized] ?? fallback
}

export function sandboxDebugErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== "object") return fallback
  const candidate = error as { code?: unknown }
  if (typeof candidate.code === "string") {
    const mapped = sandboxDebugErrorFromCode(candidate.code, "")
    if (mapped) return mapped
  }
  return fallback
}
