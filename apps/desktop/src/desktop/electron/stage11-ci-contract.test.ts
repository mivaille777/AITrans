import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 11 CI contract", () => {
  it("keeps a dedicated deliverable workflow on electronrebuild", () => {
    const workflow = read("../../../../../.github/workflows/electron-package.yml")

    expect(workflow).toContain("name: Electron Deliverable CI")
    expect(workflow).toContain("branches:\n      - electronrebuild")
    expect(workflow).toContain("build_installer:")
    expect(workflow).toContain("cancel-in-progress: true")
  })

  it("builds the verified unpacked package on relevant push and pull requests", () => {
    const workflow = read("../../../../../.github/workflows/electron-package.yml")

    expect(workflow).toContain("npm run electron:package")
    expect(workflow).toContain("aitrans-electron-win32-x64-")
    expect(workflow).toContain("apps/desktop/out/*-win32-x64/")
    expect(workflow).toContain('python -m pip install -e ".[build]" -r aitranslator-rag-requirements.txt')
  })

  it("reserves installer creation for an explicit manual workflow run", () => {
    const workflow = read("../../../../../.github/workflows/electron-package.yml")

    expect(workflow).toContain("github.event_name == 'workflow_dispatch'")
    expect(workflow).toContain("inputs.build_installer == true")
    expect(workflow).toContain("npm run electron:make")
    expect(workflow).toContain("apps/desktop/out/make/squirrel.windows/x64/")
  })

  it("uploads deliverables with bounded retention instead of committing binaries", () => {
    const workflow = read("../../../../../.github/workflows/electron-package.yml")

    expect(workflow.match(/actions\/upload-artifact@v7/g)?.length).toBe(2)
    expect(workflow.match(/retention-days: 14/g)?.length).toBe(2)
    expect(workflow.match(/if-no-files-found: error/g)?.length).toBe(2)
  })
})
