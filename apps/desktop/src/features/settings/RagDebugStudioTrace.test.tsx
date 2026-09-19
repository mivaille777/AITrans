// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import RagDebugStudioTrace from "./RagDebugStudioTrace"

afterEach(cleanup)

describe("RagDebugStudioTrace", () => {
  it("renders the Trace workspace and keeps unreleased tabs disabled", () => {
    render(<RagDebugStudioTrace />)

    expect(screen.getByText("RAG Debug Studio")).toBeTruthy()
    expect((screen.getByRole("button", { name: "Trace" }) as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByRole("button", { name: "Chunks" }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText("Reranker Results")).toBeTruthy()
  })

  it("switches retrieval stage details without rerunning the pipeline", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getAllByText("Dense Retrieval")[0])
    expect(screen.getByText("Dense Retrieval Results")).toBeTruthy()
  })

  it("updates the chunk inspector when a different result is selected", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getAllByText("chunk_7e9d4b")[0])
    expect(screen.getByText("12.3 Adaptation Pathways")).toBeTruthy()
    expect(screen.getByText("ipcc_ar6.pdf", { selector: "dd" })).toBeTruthy()
  })
})
