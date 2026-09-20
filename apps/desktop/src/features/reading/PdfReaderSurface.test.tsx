// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import PdfReaderSurface, { clampPdfPage } from "./PdfReaderSurface"
import { createLocalPdfDocumentSource, loadPdfJs } from "./pdfjs-runtime"

vi.mock("./pdfjs-runtime", () => ({
  createLocalPdfDocumentSource: vi.fn((url: string) => ({ url })),
  loadPdfJs: vi.fn(),
}))

const getPage = vi.fn()
const destroyDocument = vi.fn(async () => undefined)
const destroyLoadingTask = vi.fn(async () => undefined)

class FakeTextLayer {
  private readonly container: HTMLElement

  constructor({ container }: { container: HTMLElement }) {
    this.container = container
  }

  async render() {
    const span = document.createElement("span")
    span.textContent = "Selectable PDF text"
    this.container.append(span)
  }

  cancel() {}
}

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    configurable: true,
    value: vi.fn(() => ({})),
  })
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: vi.fn(),
  })
  class TestResizeObserver {
    private readonly callback: ResizeObserverCallback
    constructor(callback: ResizeObserverCallback) {
      this.callback = callback
    }
    observe(target: Element) {
      Object.defineProperty(target, "clientWidth", { configurable: true, value: 800 })
      this.callback([], this as unknown as ResizeObserver)
    }
    disconnect() {}
    unobserve() {}
  }
  vi.stubGlobal("ResizeObserver", TestResizeObserver)

  getPage.mockImplementation(async (pageNumber: number) => ({
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale, scale }),
    getTextContent: vi.fn(async () => ({ items: [{ str: `Page ${pageNumber}` }] })),
    render: vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() })),
  }))
  vi.mocked(loadPdfJs).mockResolvedValue({
    GlobalWorkerOptions: { workerSrc: "/assets/pdf.worker.mjs" },
    getDocument: vi.fn(() => ({
      promise: Promise.resolve({ numPages: 3, getPage, destroy: destroyDocument }),
      destroy: destroyLoadingTask,
    })),
    TextLayer: FakeTextLayer,
  } as never)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("PdfReaderSurface", () => {
  it("clamps requested pages to the available PDF range", () => {
    expect(clampPdfPage(0, 12)).toBe(1)
    expect(clampPdfPage(4.6, 12)).toBe(5)
    expect(clampPdfPage(99, 12)).toBe(12)
  })

  it("falls back to page one for invalid page counts or requests", () => {
    expect(clampPdfPage(Number.NaN, 12)).toBe(1)
    expect(clampPdfPage(4, 0)).toBe(1)
  })

  it("loads the local runtime and preserves selected text with its PDF page", async () => {
    const onSelection = vi.fn()
    render(<PdfReaderSurface url="http://127.0.0.1:8000/paper.pdf" title="Paper" initialPage={1} onSelection={onSelection} />)

    const canvas = await screen.findByLabelText("PDF page 1")
    await waitFor(() => expect(getPage).toHaveBeenCalledWith(1))
    expect(createLocalPdfDocumentSource).toHaveBeenCalledWith("http://127.0.0.1:8000/paper.pdf")

    const textNode = document.querySelector(".ait-pdf-text-layer span")?.firstChild
    expect(textNode).not.toBeNull()
    const removeAllRanges = vi.fn()
    vi.spyOn(window, "getSelection").mockReturnValue({
      isCollapsed: false,
      rangeCount: 1,
      removeAllRanges,
      toString: () => "  selected\n PDF   passage ",
      getRangeAt: () => ({
        commonAncestorContainer: textNode,
        getBoundingClientRect: () => ({ left: 300, top: 200, width: 100 }),
      }),
    } as unknown as Selection)

    fireEvent.mouseUp(canvas.parentElement as HTMLElement)
    await waitFor(() => expect(onSelection).toHaveBeenLastCalledWith({
      source: "pdf",
      text: "selected PDF passage",
      pageNumber: 1,
      left: 350,
      top: 188,
    }))
  })

  it("clears stale selection after page and zoom changes", async () => {
    const onSelection = vi.fn()
    render(<PdfReaderSurface url="http://127.0.0.1:8000/paper.pdf" title="Paper" initialPage={1} onSelection={onSelection} />)
    await screen.findByLabelText("PDF page 1")
    await waitFor(() => expect(getPage).toHaveBeenCalledWith(1))

    fireEvent.click(screen.getByLabelText("Next PDF page"))
    await waitFor(() => expect(getPage).toHaveBeenCalledWith(2))
    expect(onSelection).toHaveBeenCalledWith(null)
    expect(screen.getByText("Page 2 / 3")).toBeInTheDocument()

    onSelection.mockClear()
    fireEvent.click(screen.getByLabelText("Zoom PDF in"))
    await waitFor(() => expect(screen.getByText("110%")).toBeInTheDocument())
    expect(onSelection).toHaveBeenCalledWith(null)
  })

  it("zooms with ctrl plus mouse wheel over the PDF surface", async () => {
    render(<PdfReaderSurface url="http://127.0.0.1:8000/paper.pdf" title="Paper" initialPage={1} onSelection={vi.fn()} />)
    await screen.findByLabelText("PDF page 1")
    await waitFor(() => expect(getPage).toHaveBeenCalledWith(1))

    const surface = screen.getByLabelText("Interactive PDF · Paper")
    fireEvent.wheel(surface, { ctrlKey: true, deltaY: -100 })
    await waitFor(() => expect(screen.getByText("110%")).toBeInTheDocument())

    fireEvent.wheel(surface, { ctrlKey: true, deltaY: 100 })
    await waitFor(() => expect(screen.getByText("100%")).toBeInTheDocument())
  })
})
