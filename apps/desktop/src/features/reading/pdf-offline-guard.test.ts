import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..")
const packageJson = JSON.parse(readFileSync(path.join(desktopRoot, "package.json"), "utf8"))
const runtimeSource = readFileSync(path.join(desktopRoot, "src/features/reading/pdfjs-runtime.ts"), "utf8")
const readerSource = readFileSync(path.join(desktopRoot, "src/features/reading/PdfReaderSurface.tsx"), "utf8")
const syncScript = readFileSync(path.join(desktopRoot, "scripts/sync-pdfjs-assets.mjs"), "utf8")

describe("offline PDF.js guard", () => {
  it("pins and lazy-loads the local runtime and worker", () => {
    expect(packageJson.dependencies["pdfjs-dist"]).toBe("6.3.289")
    expect(runtimeSource).toContain('import("pdfjs-dist")')
    expect(runtimeSource).toContain('pdf.worker.min.mjs?url')
    expect(runtimeSource).not.toMatch(/cdnjs|unpkg|jsdelivr/i)
    expect(readerSource).not.toMatch(/cdnjs|unpkg|jsdelivr/i)
  })

  it("configures every offline support asset directory with trailing slashes", () => {
    for (const directory of ["cmaps", "standard_fonts", "iccs", "wasm"]) {
      expect(runtimeSource).toContain(`localAssetDirectory("${directory}")`)
      expect(syncScript).toContain(`"${directory}"`)
    }
    expect(runtimeSource).toContain('`${LOCAL_ASSET_ROOT}/${name}/`')
  })

  it("runs the production asset audit after every build", () => {
    expect(packageJson.scripts.build).toContain("npm run check:pdfjs-offline")
    expect(packageJson.scripts.prebuild).toContain("sync:pdfjs-assets")
  })
})
