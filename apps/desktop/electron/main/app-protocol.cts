import { app, net, protocol } from "electron"
import path from "node:path"
import { pathToFileURL } from "node:url"

export const APP_SCHEME = "aitrans"
export const APP_HOST = "app"
export const APP_ORIGIN = APP_SCHEME + "://" + APP_HOST

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
  await protocol.handle(APP_SCHEME, (request) => {
    const asset = resolveRendererAsset(request.url)
    if (!asset) {
      return new Response("Not Found", { status: 404 })
    }
    return net.fetch(pathToFileURL(asset).toString())
  })
}
