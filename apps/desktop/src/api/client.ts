const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined

export const API_BASE_URL = (configuredBaseUrl ?? "http://127.0.0.1:8766").replace(/\/$/, "")

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(message: string, status: number, code = "") {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
  }
}

export function apiWebSocketUrl(path: string): string {
  const url = new URL(`${API_BASE_URL}${path}`)
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  return url.toString()
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set("Accept", "application/json")
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  })

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    let code = ""
    try {
      const parsed = parseApiErrorPayload(await response.json())
      if (parsed.message) detail = parsed.message
      if (parsed.code) code = parsed.code
    } catch {
      // Keep the HTTP status text when the backend did not return JSON.
    }
    throw new ApiError(detail, response.status, code)
  }

  return (await response.json()) as T
}

export function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path)
}

export function apiPost<TResponse, TBody>(path: string, body: TBody): Promise<TResponse> {
  return apiRequest<TResponse>(path, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export function apiPatch<TResponse, TBody>(path: string, body: TBody): Promise<TResponse> {
  return apiRequest<TResponse>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
}

export function apiPut<TResponse, TBody>(path: string, body: TBody): Promise<TResponse> {
  return apiRequest<TResponse>(path, {
    method: "PUT",
    body: JSON.stringify(body),
  })
}

export function apiDelete<TResponse>(path: string): Promise<TResponse> {
  return apiRequest<TResponse>(path, { method: "DELETE" })
}


function parseApiErrorPayload(payload: unknown): { message: string; code: string } {
  if (!payload || typeof payload !== "object") return { message: "", code: "" }

  const body = payload as {
    detail?: unknown
    code?: unknown
    message?: unknown
  }

  const nested = body.detail && typeof body.detail === "object"
    ? body.detail as { code?: unknown; message?: unknown }
    : null

  const message = typeof body.detail === "string"
    ? body.detail
    : typeof body.message === "string"
      ? body.message
      : typeof nested?.message === "string"
        ? nested.message
        : ""

  const code = typeof body.code === "string"
    ? body.code
    : typeof nested?.code === "string"
      ? nested.code
      : ""

  return { message, code }
}
