// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import ReadingSelectionActionBar from "./ReadingSelectionActionBar"

afterEach(cleanup)

describe("ReadingSelectionActionBar", () => {
  it("renders at the selection anchor and exposes every contextual action", () => {
    const handlers = {
      onEvidence: vi.fn(),
      onHighlight: vi.fn(),
      onNote: vi.fn(),
      onConcept: vi.fn(),
      onTranslate: vi.fn(),
      onAskAi: vi.fn(),
    }

    render(
      <ReadingSelectionActionBar
        left={420}
        top={180}
        {...handlers}
      />,
    )

    const toolbar = screen.getByRole("toolbar", { name: "Reading selection actions" })
    expect(toolbar).toHaveStyle({ left: "420px", top: "180px" })

    for (const [label, key] of [
      ["Evidence", "onEvidence"],
      ["Highlight", "onHighlight"],
      ["Note", "onNote"],
      ["Concept", "onConcept"],
      ["Translate", "onTranslate"],
      ["Ask AI", "onAskAi"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }))
      expect(handlers[key]).toHaveBeenCalledTimes(1)
    }
  })

  it("preserves the browser text selection while pressing the toolbar", () => {
    render(
      <ReadingSelectionActionBar
        left={320}
        top={140}
        onEvidence={vi.fn()}
        onHighlight={vi.fn()}
        onNote={vi.fn()}
        onConcept={vi.fn()}
        onTranslate={vi.fn()}
        onAskAi={vi.fn()}
      />,
    )

    const event = new MouseEvent("mousedown", { bubbles: true, cancelable: true })
    screen.getByRole("toolbar", { name: "Reading selection actions" }).dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })
})
