import { app, net, protocol } from "electron"
import path from "node:path"
import { pathToFileURL } from "node:url"

export const APP_SCHEME = "aitrans"
export const APP_HOST = "app"
export const APP_ORIGIN = APP_SCHEME + "://" + APP_HOST

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "base-uri 'none'",
  "object-src 'none'",
  "frame-src 'none'",
  "form-action 'none'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "worker-src 'self' blob:",
  "connect-src 'self' http://127.0.0.1:8765 http://localhost:8765 http://127.0.0.1:8766 http://localhost:8766",
].join("; ")

export function registerAppSchemePrivileges(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: APP_SCHEME,
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        corsEnabled: true,
        stream: true,
      },
    },
  ])
}

function rendererRoot(): string {
  return path.resolve(app.getAppPath(), "dist")
}

function resolveRendererAsset(requestUrl: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(requestUrl)
  } catch {
    return null
  }

  if (parsed.protocol !== APP_SCHEME + ":" || parsed.host !== APP_HOST) {
    return null
  }

  let relativePath: string
  try {
    relativePath = decodeURIComponent(parsed.pathname).replace(/^\/+/, "")
  } catch {
    return null
  }
  if (!relativePath) relativePath = "index.html"

  const root = rendererRoot()
  const candidate = path.resolve(root, relativePath)
  const relative = path.relative(root, candidate)

  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return null
  }
  return candidate
}

export async function installAppProtocol(): Promise<void> {
  await protocol.handle(APP_SCHEME, async (request) => {
    const asset = resolveRendererAsset(request.url)
    if (!asset) {
      return new Response("Not Found", { status: 404 })
    }
    const response = await net.fetch(pathToFileURL(asset).toString())
    const headers = new Headers(response.headers)
    headers.set("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    headers.set("X-Content-Type-Options", "nosniff")

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    })
  })
}
