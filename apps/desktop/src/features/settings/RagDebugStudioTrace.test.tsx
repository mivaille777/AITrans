import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import RagDebugStudioTrace from "./RagDebugStudioTrace"

describe("RagDebugStudioTrace", () => {
  it("renders the Trace workspace and keeps unreleased tabs disabled", () => {
    render(<RagDebugStudioTrace />)

    expect(screen.getByText("RAG Debug Studio")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Trace" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "Chunks" })).toBeDisabled()
    expect(screen.getByText("Reranker Results")).toBeInTheDocument()
  })

  it("switches retrieval stage details without rerunning the pipeline", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByText("Dense Retrieval"))
    expect(screen.getByText("Dense Retrieval Results")).toBeInTheDocument()
  })

  it("updates the chunk inspector when a different result is selected", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByText("chunk_7e9d4b"))
    expect(screen.getByText("12.3 Adaptation Pathways")).toBeInTheDocument()
    expect(screen.getByText("ipcc_ar6.pdf", { selector: "dd" })).toBeInTheDocument()
  })
})
