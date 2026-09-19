// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import RagDebugStudioTrace from "./RagDebugStudioTrace"

afterEach(cleanup)

describe("RagDebugStudio", () => {
  it("renders all five interactive tabs", () => {
    render(<RagDebugStudioTrace />)

    expect(screen.getByText("RAG Debug Studio")).toBeTruthy()
    for (const label of ["Trace", "Chunks", "Evaluation", "Compare", "Datasets"]) {
      expect((screen.getByRole("button", { name: label }) as HTMLButtonElement).disabled).toBe(false)
    }
  })

  it("switches to the chunk explorer and selects a chunk", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Chunks" }))
    expect(screen.getByText("Document Structure")).toBeTruthy()
    expect(screen.getByText("Chunks", { selector: "h2" })).toBeTruthy()
    fireEvent.click(screen.getByText("Nature-based solutions offer multiple co-benefits…"))
    expect(screen.getByText("2.1 Nature-based Solutions")).toBeTruthy()
  })

  it("shows evaluation metrics", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Evaluation" }))
    expect(screen.getByText("Recall@10")).toBeTruthy()
    expect(screen.getByText("Case Results")).toBeTruthy()
  })

  it("updates compare details when a different case is selected", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Compare" }))
    fireEvent.click(screen.getByText("What financing mechanisms support coastal resilience projects?"))
    expect(screen.getByText("Query Comparison")).toBeTruthy()
  })

  it("opens the dataset case editor", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Datasets" }))
    expect(screen.getByText("Evaluation Cases")).toBeTruthy()
    expect(screen.getByText("Case Details")).toBeTruthy()
    expect(screen.getByDisplayValue("What are the key challenges of climate change adaptation in coastal cities?")).toBeTruthy()
  })
})