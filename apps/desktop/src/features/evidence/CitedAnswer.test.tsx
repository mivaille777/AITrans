// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { desktop } from "../../desktop"
import { AnswerMarkdown } from "./AnswerMarkdown"
import { CitedAnswer } from "./CitedAnswer"
import { citationSegments, isSafeEvidenceResource } from "./citation-model"
import type { AgentCitationRef, AgentEvidenceItem } from "./evidence-types"

const citation: AgentCitationRef = {
  citation_id: "citation-1",
  evidence_ids: ["evidence:chunk-1"],
  label: "[1]",
}

const evidence: AgentEvidenceItem = {
  evidence_id: "evidence:chunk-1",
  source_type: "knowledge",
  source_id: "document-1",
  title: "Control Systems Paper",
  resource_url: "file:///C:/papers/control.pdf",
  location: "Page 8 · Section Stability",
  excerpt: "The Lyapunov condition bounds the closed-loop response.",
  score: 0.923,
  metadata: {},
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("RAG citation interaction", () => {
  it("renders headings, emphasis, lists, code and citations as markdown", () => {
    const content = [
      "# Main finding",
      "",
      "The **bounded reasoning component** stays local [1].",
      "",
      "- GP selects the anchor",
      "- LLM refines locally",
      "",
      "`Theta_useful` remains bounded.",
    ].join("\n")

    render(<CitedAnswer content={content} evidence={[evidence]} citations={[citation]} />)

    expect(screen.getByRole("heading", { level: 1, name: "Main finding" })).not.toBeNull()
    expect(screen.getByText("bounded reasoning component").tagName).toBe("STRONG")
    expect(screen.getByText("GP selects the anchor").closest("li")).not.toBeNull()
    expect(screen.getByText("Theta_useful").tagName).toBe("CODE")
    expect(screen.getByRole("button", { name: "Open citation [1]" })).not.toBeNull()
  })

  it("renders pipe tables without an extra markdown dependency", () => {
    render(
      <AnswerMarkdown
        content={[
          "| Component | Role |",
          "| :--- | ---: |",
          "| GP | Wide search |",
          "| LLM | Local refinement |",
        ].join("\n")}
      />,
    )

    expect(screen.getByRole("table")).not.toBeNull()
    expect(screen.getByText("Component").closest("th")).not.toBeNull()
    expect(screen.getByText("Local refinement").closest("td")).not.toBeNull()
  })

  it("updates incomplete streaming markdown when later content arrives", () => {
    const { rerender } = render(<AnswerMarkdown content="# Streaming" />)
    expect(screen.getByRole("heading", { level: 1, name: "Streaming" })).not.toBeNull()

    rerender(<AnswerMarkdown content="# Streaming\n\n**Complete** paragraph." />)
    expect(screen.getByText("Complete").tagName).toBe("STRONG")
  })

  it("renders verified citation labels as interactive chips", () => {
    render(<CitedAnswer content="The response is bounded [1]." evidence={[evidence]} citations={[citation]} />)

    expect(screen.getByRole("button", { name: "Open citation [1]" })).not.toBeNull()
    expect(screen.getByRole("button", { name: "Open citation [1]" }).getAttribute("title")).toContain("Control Systems Paper")
    expect(citationSegments("Unknown [9]", [citation])).toEqual([
      { text: "Unknown " },
      { text: "[9]" },
    ])
  })

  it("opens citation detail with title, page, section and excerpt", async () => {
    render(<CitedAnswer content="Supported claim [1]" evidence={[evidence]} citations={[citation]} />)

    await userEvent.click(screen.getByRole("button", { name: "Open citation [1]" }))

    expect(screen.getByRole("dialog", { name: "Citation detail [1]" })).not.toBeNull()
    expect(screen.getByText("Control Systems Paper")).not.toBeNull()
    expect(screen.getByText("Page 8")).not.toBeNull()
    expect(screen.getByText("Stability")).not.toBeNull()
    expect(screen.getByText(evidence.excerpt)).not.toBeNull()
    expect(screen.getByRole("link", { name: "Knowledge details" }).getAttribute("href")).toBe("/knowledge?document=document-1")
  })

  it("opens only a safe local URI supplied by verified evidence", async () => {
    const openSource = vi.spyOn(desktop.files, "openEvidenceSource").mockResolvedValue()
    render(<CitedAnswer content="Supported claim [1]" evidence={[evidence]} citations={[citation]} />)

    await userEvent.click(screen.getByRole("button", { name: "Open citation [1]" }))
    await userEvent.click(screen.getByRole("button", { name: "Open document" }))

    expect(openSource).toHaveBeenCalledWith(evidence.resource_url)
    expect(isSafeEvidenceResource("https://example.org/invented.pdf")).toBe(false)
    expect(isSafeEvidenceResource("file:///C:/papers/control.pdf")).toBe(true)
  })

  it("handles missing and unsafe source evidence without opening it", async () => {
    const openSource = vi.spyOn(desktop.files, "openEvidenceSource").mockResolvedValue()
    const { unmount } = render(
      <CitedAnswer content="Missing source [1]" evidence={[]} citations={[citation]} />,
    )
    await userEvent.click(screen.getByRole("button", { name: "Open citation [1]" }))
    expect(screen.getByText("Source unavailable")).not.toBeNull()
    unmount()

    render(
      <CitedAnswer
        content="Unsafe source [1]"
        evidence={[{ ...evidence, resource_url: "https://example.org/invented.pdf" }]}
        citations={[citation]}
      />,
    )
    await userEvent.click(screen.getByRole("button", { name: "Open citation [1]" }))
    expect((screen.getByRole("button", { name: "Open document" }) as HTMLButtonElement).disabled).toBe(true)
    expect(openSource).not.toHaveBeenCalled()
  })

  it("keeps the sources footer compact until the user expands it", async () => {
    render(<CitedAnswer content="Supported claim [1]" evidence={[evidence]} citations={[citation]} />)

    const toggle = screen.getByRole("button", { name: /Sources 1/ })
    expect(toggle.getAttribute("aria-expanded")).toBe("false")
    expect(screen.queryByRole("list", { name: "Answer sources" })).toBeNull()

    await userEvent.click(toggle)
    expect(toggle.getAttribute("aria-expanded")).toBe("true")
    expect(screen.getByRole("list", { name: "Answer sources" })).not.toBeNull()
    expect(screen.queryByText("0.923")).toBeNull()
  })
})
