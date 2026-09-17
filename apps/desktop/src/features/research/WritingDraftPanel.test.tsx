// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "../../api/client"
import type { WritingProjectSnapshot } from "../../api/writing"
import WritingDraftPanel from "./WritingDraftPanel"

const api = vi.hoisted(() => ({
  applyWritingRevision: vi.fn(),
  createWritingProject: vi.fn(),
  exportWritingProject: vi.fn(),
  listWritingProjects: vi.fn(),
  previewWritingRevision: vi.fn(),
  saveWritingArtifact: vi.fn(),
}))

vi.mock("../../api/writing", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/writing")>(),
  ...api,
}))

function project(): WritingProjectSnapshot {
  return {
    project_id: "project-1",
    workspace_id: "workspace-1",
    title: "Grounded manuscript",
    writing_goal: "Revise only selected paragraphs",
    outline_ref: null,
    outline_version: 0,
    sections: [{
      section_id: "introduction",
      version: 1,
      title: "Introduction",
      markdown: "Original paragraph.",
      paragraphs: [{ paragraph_id: "p1", markdown: "Original paragraph.", content_hash: "before-hash", evidence_ids: [] }],
      artifact_ref: { artifact_id: "section-1", version: 1, kind: "manuscript_section", content_hash: "section-hash" },
      references: [],
      verification_status: "passed",
      created_at: "2026-09-16T00:00:00Z",
    }],
    created_at: "2026-09-16T00:00:00Z",
    updated_at: "2026-09-16T00:00:00Z",
  }
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><WritingDraftPanel workspaceId="workspace-1" /></QueryClientProvider>)
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe("WritingDraftPanel", () => {
  it("shows a generated revision as an unapplied diff and cancel preserves the stored draft", async () => {
    api.listWritingProjects.mockResolvedValue({ total: 1, projects: [project()] })
    api.previewWritingRevision.mockResolvedValue({
      project_id: "project-1",
      section_id: "introduction",
      base_version: 1,
      revision_ref: { artifact_id: "revision-1", version: 1, kind: "revision", content_hash: "revision-hash" },
      before: [{ paragraph_id: "p1", markdown: "Original paragraph.", content_hash: "before-hash", evidence_ids: [] }],
      after: [{ paragraph_id: "p1", markdown: "Revised paragraph.", content_hash: "after-hash", evidence_ids: [] }],
    })
    renderPanel()
    const input = await screen.findByRole("textbox", { name: "Revision text" })
    await userEvent.clear(input)
    await userEvent.type(input, "Revised paragraph.")
    await userEvent.click(screen.getByRole("button", { name: "Preview revision" }))

    expect(await screen.findByText("Pending draft — not applied")).not.toBeNull()
    expect(screen.getByLabelText("Revision diff").textContent).toContain("Original paragraph.")
    expect(screen.getByLabelText("Revision diff").textContent).toContain("Revised paragraph.")
    expect(api.applyWritingRevision).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole("button", { name: "Cancel draft" }))
    expect(screen.queryByLabelText("Revision diff")).toBeNull()
    expect(screen.getByRole("status").textContent).toContain("stored section is unchanged")
    expect(api.applyWritingRevision).not.toHaveBeenCalled()
  })

  it("applies the approved revision once with a stable operation id", async () => {
    api.listWritingProjects.mockResolvedValue({ total: 1, projects: [project()] })
    api.previewWritingRevision.mockResolvedValue({
      project_id: "project-1",
      section_id: "introduction",
      base_version: 1,
      revision_ref: { artifact_id: "revision-1", version: 1, kind: "revision", content_hash: "revision-hash" },
      before: [{ paragraph_id: "p1", markdown: "Original paragraph.", content_hash: "before-hash", evidence_ids: [] }],
      after: [{ paragraph_id: "p1", markdown: "Approved paragraph.", content_hash: "after-hash", evidence_ids: [] }],
    })
    api.applyWritingRevision.mockResolvedValue({
      operation_id: "operation-1",
      project_id: "project-1",
      section_id: "introduction",
      result_version: 2,
      artifact_ref: { artifact_id: "section-1", version: 2, kind: "manuscript_section", content_hash: "new-hash" },
      replayed: false,
    })
    renderPanel()
    const input = await screen.findByRole("textbox", { name: "Revision text" })
    await userEvent.clear(input)
    await userEvent.type(input, "Approved paragraph.")
    await userEvent.click(screen.getByRole("button", { name: "Preview revision" }))
    await userEvent.click(await screen.findByRole("button", { name: "Apply revision" }))

    await waitFor(() => expect(api.applyWritingRevision).toHaveBeenCalledTimes(1))
    const [, payload] = api.applyWritingRevision.mock.calls[0]
    expect(payload).toMatchObject({ artifact_id: "revision-1", artifact_version: 1, expected_version: 1 })
    expect(payload.operation_id).toBeTruthy()
  })

  it("reports an optimistic-version conflict instead of hiding it", async () => {
    api.listWritingProjects.mockResolvedValue({ total: 1, projects: [project()] })
    api.previewWritingRevision.mockResolvedValue({
      project_id: "project-1",
      section_id: "introduction",
      base_version: 1,
      revision_ref: { artifact_id: "revision-1", version: 1, kind: "revision", content_hash: "revision-hash" },
      before: [{ paragraph_id: "p1", markdown: "Original paragraph.", content_hash: "before-hash", evidence_ids: [] }],
      after: [{ paragraph_id: "p1", markdown: "Conflicting paragraph.", content_hash: "after-hash", evidence_ids: [] }],
    })
    api.applyWritingRevision.mockRejectedValue(new ApiError("section version conflict", 409))
    renderPanel()
    const input = await screen.findByRole("textbox", { name: "Revision text" })
    await userEvent.clear(input)
    await userEvent.type(input, "Conflicting paragraph.")
    await userEvent.click(screen.getByRole("button", { name: "Preview revision" }))
    await userEvent.click(await screen.findByRole("button", { name: "Apply revision" }))

    expect(await screen.findByText("Version conflict: reload the latest section before applying.")).not.toBeNull()
    expect(screen.getByLabelText("Revision diff")).not.toBeNull()
  })

  it("shows the stored version and paragraph-level source state", async () => {
    const sourced = project()
    sourced.sections[0].paragraphs[0].evidence_ids = ["ev-writing-1"]
    api.listWritingProjects.mockResolvedValue({ total: 1, projects: [sourced] })
    renderPanel()
    const evidence = await screen.findByLabelText("Paragraph evidence")
    expect(evidence.textContent).toContain("已保存 v1")
    expect(screen.getByRole("link", { name: "ev-writing-1" }).getAttribute("href")).toContain("evidence-ev-writing-1")
  })

  it("warns when an exported draft uses a stale source", async () => {
    api.listWritingProjects.mockResolvedValue({ total: 1, projects: [project()] })
    api.exportWritingProject.mockResolvedValue({
      project_id: "project-1",
      markdown: "# Grounded manuscript\n",
      references: [],
      outline_version: 0,
      section_versions: { introduction: 1 },
      source_statuses: { "paper-a": "stale" },
      verification_status: "requires_revalidation",
      warnings: ["Source paper-a is stale; revalidate affected claims before reuse."],
    })
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:writing-export")
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined)
    renderPanel()

    await userEvent.click(await screen.findByRole("button", { name: "Export" }))

    expect(await screen.findByText(/Exported with 1 stale or unavailable source warning/)).not.toBeNull()
  })
})
