import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Batch 5 desktop entry isolation", () => {
  it("keeps the main entry free of OverlayView and overlay-only CSS", () => {
    const source = read("../main.tsx")

    expect(source).toContain('import App from "./App"')
    expect(source).not.toContain("OverlayView")
    expect(source).not.toContain("overlay.css")
    expect(source).not.toContain('get("view")')
  })

  it("boots OverlayView from a dedicated entry without importing the main app router", () => {
    const source = read("../overlay-main.tsx")

    expect(source).toContain('import OverlayView from "./components/OverlayView"')
    expect(source).toContain('import "./overlay.css"')
    expect(source).toContain('import "./overlay-theme.css"')
    expect(source).not.toContain('import App from "./App"')
    expect(source).not.toContain("HashRouter")
  })

  it("builds main and overlay HTML as separate Vite inputs and routes Tauri overlay to its own document", () => {
    const viteConfig = read("../../vite.config.ts")
    const tauriConfig = JSON.parse(read("../../src-tauri/tauri.conf.json")) as {
      app: {
        windows: Array<{
          label: string
          url?: string
          decorations?: boolean
          transparent?: boolean
          shadow?: boolean
          backgroundColor?: string
        }>
      }
    }
    const overlayHtml = read("../../overlay.html")
    const overlayWindow = tauriConfig.app.windows.find((window) => window.label === "overlay")

    expect(viteConfig).toContain('main: fileURLToPath(new URL("./index.html"')
    expect(viteConfig).toContain('overlay: fileURLToPath(new URL("./overlay.html"')
    expect(overlayHtml).toContain('/src/overlay-main.tsx')
    expect(overlayWindow?.url).toBe("overlay.html")
    expect(overlayWindow).toMatchObject({
      decorations: false,
      transparent: true,
      shadow: false,
    })
    expect(overlayWindow).not.toHaveProperty("backgroundColor")
  })

  it("lazy-loads non-default main workspaces instead of importing them into translation startup", () => {
    const source = read("../App.tsx")

    for (const modulePath of [
      "./features/reading/ReadingWorkspace",
      "./features/companion/CompanionWorkspaceV2",
      "./features/research/ResearchRoute",
      "./features/settings/SettingsWorkspace",
    ]) {
      expect(source).toContain(`lazy(() => import("${modulePath}"))`)
      expect(source).not.toContain(`from "${modulePath}"`)
    }
    expect(source).toContain("<Suspense")
  })

  it("defers the heavy Compact Chat implementation until the user opens AI Chat", () => {
    const wrapper = read("../components/OverlayCompactChat.tsx")
    const content = read("../components/OverlayCompactChatContent.tsx")

    expect(wrapper).toContain('lazy(() => import("./OverlayCompactChatContent"))')
    expect(wrapper).not.toContain("react-markdown")
    expect(wrapper).not.toContain("useCompanionConversationRuntime")
    expect(content).toContain('from "react-markdown"')
    expect(content).toContain("useCompanionConversationRuntime")
  })

  it("emits a Vite manifest and reports main versus overlay payloads after every production build", () => {
    const viteConfig = read("../../vite.config.ts")
    const packageJson = JSON.parse(read("../../package.json")) as {
      scripts: Record<string, string>
    }
    const reportScript = read("../../scripts/report-bundle.mjs")

    expect(viteConfig).toContain("manifest: true")
    expect(packageJson.scripts.build).toContain("npm run bundle:report")
    expect(packageJson.scripts["bundle:report"]).toBe("node scripts/report-bundle.mjs")
    expect(reportScript).toContain("Main initial route")
    expect(reportScript).toContain("Overlay initial surface")
    expect(reportScript).toContain("Largest emitted JS chunks")
  })
})
