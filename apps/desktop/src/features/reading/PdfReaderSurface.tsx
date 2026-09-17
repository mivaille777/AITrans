import { ChevronLeft, ChevronRight, LoaderCircle, Minus, Plus, RotateCcw } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "../../shared/ui/Button"
import { createLocalPdfDocumentSource, loadPdfJs } from "./pdfjs-runtime"
import type { LocalPdfDocumentSource } from "./pdfjs-runtime"

const MIN_ZOOM = 0.75
const MAX_ZOOM = 1.6
const ZOOM_STEP = 0.1

export interface PdfReaderSelection {
  source: "pdf"
  text: string
  pageNumber: number
  left: number
  top: number
}

interface PdfViewport {
  width: number
  height: number
  scale: number
}

interface PdfRenderTask {
  promise: Promise<void>
  cancel: () => void
}

interface PdfTextLayer {
  render: () => Promise<void>
  cancel: () => void
}

interface PdfPageProxy {
  getViewport: (options: { scale: number }) => PdfViewport
  getTextContent: (options?: { includeMarkedContent?: boolean }) => Promise<unknown>
  render: (options: {
    canvasContext: CanvasRenderingContext2D
    viewport: PdfViewport
    transform?: number[]
  }) => PdfRenderTask
}

interface PdfDocumentProxy {
  numPages: number
  getPage: (pageNumber: number) => Promise<PdfPageProxy>
  destroy: () => Promise<void>
}

interface PdfLoadingTask {
  promise: Promise<PdfDocumentProxy>
  destroy?: () => Promise<void>
}

interface PdfJsModule {
  GlobalWorkerOptions: { workerSrc: string }
  getDocument: (source: LocalPdfDocumentSource) => PdfLoadingTask
  TextLayer: new (options: {
    textContentSource: unknown
    container: HTMLElement
    viewport: PdfViewport
  }) => PdfTextLayer
}

interface PdfReaderSurfaceProps {
  url: string
  title: string
  initialPage: number
  onSelection: (selection: PdfReaderSelection | null) => void
}

export function clampPdfPage(pageNumber: number, pageCount: number): number {
  if (!Number.isFinite(pageNumber) || pageCount <= 0) return 1
  return Math.min(pageCount, Math.max(1, Math.round(pageNumber)))
}

export default function PdfReaderSurface({
  url,
  title,
  initialPage,
  onSelection,
}: PdfReaderSurfaceProps) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const textLayerRef = useRef<HTMLDivElement | null>(null)
  const onSelectionRef = useRef(onSelection)
  onSelectionRef.current = onSelection

  const [pdfDocument, setPdfDocument] = useState<PdfDocumentProxy | null>(null)
  const [pdfjs, setPdfJs] = useState<PdfJsModule | null>(null)
  const [pageNumber, setPageNumber] = useState(Math.max(1, initialPage))
  const [zoom, setZoom] = useState(1)
  const [hostWidth, setHostWidth] = useState(0)
  const [loading, setLoading] = useState(true)
  const [rendering, setRendering] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const update = () => setHostWidth(host.clientWidth)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let disposed = false
    let loadingTask: PdfLoadingTask | null = null
    setLoading(true)
    setError("")
    setPdfDocument(null)

    void loadPdfJs()
      .then((runtimeModule) => {
        if (disposed) return null
        const module = runtimeModule as unknown as PdfJsModule
        setPdfJs(module)
        loadingTask = module.getDocument(createLocalPdfDocumentSource(url))
        return loadingTask.promise
      })
      .then((document) => {
        if (!document || disposed) return
        setPdfDocument(document)
        setPageNumber(clampPdfPage(initialPage, document.numPages))
        setLoading(false)
      })
      .catch((reason: unknown) => {
        if (disposed) return
        setLoading(false)
        setRendering(false)
        setError(reason instanceof Error ? reason.message : "Unable to load the interactive PDF reader.")
      })

    return () => {
      disposed = true
      void loadingTask?.destroy?.().catch(() => undefined)
    }
  }, [initialPage, url])

  useEffect(() => {
    if (!pdfDocument) return
    setPageNumber(clampPdfPage(initialPage, pdfDocument.numPages))
  }, [initialPage, pdfDocument])

  useEffect(() => {
    if (!pdfDocument || !pdfjs || !hostWidth) return
    const canvas = canvasRef.current
    const textLayer = textLayerRef.current
    if (!canvas || !textLayer) return

    let disposed = false
    let renderTask: PdfRenderTask | null = null
    let textLayerTask: PdfTextLayer | null = null
    setRendering(true)
    setError("")
    onSelectionRef.current(null)

    void pdfDocument.getPage(pageNumber)
      .then(async (page) => {
        if (disposed) return
        const baseViewport = page.getViewport({ scale: 1 })
        const fitScale = Math.max(0.45, (hostWidth - 64) / Math.max(1, baseViewport.width))
        const viewport = page.getViewport({ scale: fitScale * zoom })
        const pixelRatio = Math.max(1, window.devicePixelRatio || 1)
        const context = canvas.getContext("2d", { alpha: false })
        if (!context) throw new Error("PDF canvas is unavailable.")

        canvas.width = Math.max(1, Math.floor(viewport.width * pixelRatio))
        canvas.height = Math.max(1, Math.floor(viewport.height * pixelRatio))
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`
        textLayer.replaceChildren()
        textLayer.style.width = `${viewport.width}px`
        textLayer.style.height = `${viewport.height}px`
        textLayer.style.setProperty("--total-scale-factor", String(viewport.scale))

        renderTask = page.render({
          canvasContext: context,
          viewport,
          transform: pixelRatio === 1 ? undefined : [pixelRatio, 0, 0, pixelRatio, 0, 0],
        })
        const textContent = await page.getTextContent({ includeMarkedContent: true })
        if (disposed) return
        textLayerTask = new pdfjs.TextLayer({
          textContentSource: textContent,
          container: textLayer,
          viewport,
        })
        await Promise.all([renderTask.promise, textLayerTask.render()])
        if (!disposed) setRendering(false)
      })
      .catch((reason: unknown) => {
        if (disposed || reason instanceof DOMException && reason.name === "AbortError") return
        setRendering(false)
        setError(reason instanceof Error ? reason.message : "Unable to render this PDF page.")
      })

    return () => {
      disposed = true
      renderTask?.cancel()
      textLayerTask?.cancel()
    }
  }, [hostWidth, pageNumber, pdfDocument, pdfjs, zoom])

  function clearNativeSelection() {
    window.getSelection()?.removeAllRanges()
    onSelectionRef.current(null)
  }

  function changePage(nextPage: number) {
    if (!pdfDocument) return
    clearNativeSelection()
    setPageNumber(clampPdfPage(nextPage, pdfDocument.numPages))
    hostRef.current?.scrollTo({ top: 0, left: 0 })
  }

  function changeZoom(nextZoom: number) {
    clearNativeSelection()
    setZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(nextZoom.toFixed(2)))))
  }

  function captureSelection() {
    window.setTimeout(() => {
      const current = window.getSelection()
      const textLayer = textLayerRef.current
      if (!current || current.isCollapsed || current.rangeCount === 0 || !textLayer) {
        onSelectionRef.current(null)
        return
      }
      const range = current.getRangeAt(0)
      if (!textLayer.contains(range.commonAncestorContainer)) {
        onSelectionRef.current(null)
        return
      }
      const text = current.toString().replace(/\s+/g, " ").trim()
      if (!text) {
        onSelectionRef.current(null)
        return
      }
      const rect = range.getBoundingClientRect()
      onSelectionRef.current({
        source: "pdf",
        text,
        pageNumber,
        left: Math.min(window.innerWidth - 220, Math.max(220, rect.left + rect.width / 2)),
        top: Math.max(68, rect.top - 12),
      })
    }, 0)
  }

  const pageCount = pdfDocument?.numPages ?? 0
  const nativePreviewUrl = `${url}#page=${Math.max(1, pageNumber)}`

  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-[#f5f5f5]">
      <div className="grid min-h-[48px] shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-2 border-b border-[#e5e5e5] bg-white px-4 py-2 text-[10px] text-[#777]">
        <div className="flex items-center gap-1.5 justify-self-start">
          <Button aria-label="Previous PDF page" size="xs" variant="ghost" disabled={!pdfDocument || pageNumber <= 1} onClick={() => changePage(pageNumber - 1)}><ChevronLeft size={12} /></Button>
          <span className="min-w-20 text-center font-medium text-[#555]">Page {pageNumber}{pageCount ? ` / ${pageCount}` : ""}</span>
          <Button aria-label="Next PDF page" size="xs" variant="ghost" disabled={!pdfDocument || pageNumber >= pageCount} onClick={() => changePage(pageNumber + 1)}><ChevronRight size={12} /></Button>
        </div>
        <span className="hidden text-[#999] lg:inline">Select text to create knowledge or ask AI.</span>
        <span className="justify-self-end text-[#aaa]">PDF</span>
      </div>

      <div
        ref={hostRef}
        className="ait-scroll-panel ait-pdf-scroll-surface relative min-h-0 flex-1 overflow-scroll overscroll-contain p-6 pb-20"
        style={{ scrollbarGutter: "stable both-edges" }}
        aria-label={`Interactive PDF · ${title}`}
      >
        {(loading || rendering) && (
          <div className="pointer-events-none sticky top-2 z-20 mx-auto flex w-fit items-center gap-2 rounded-full border border-[#dddddd] bg-white/95 px-3 py-1.5 text-[10px] text-[#666] shadow-sm">
            <LoaderCircle size={12} className="animate-spin" />{loading ? "Loading PDF…" : "Rendering page…"}
          </div>
        )}
        {error ? (
          <div className="mx-auto flex min-h-full max-w-5xl flex-col gap-3">
            <div className="shrink-0 rounded-[12px] border border-[#dddddd] bg-white px-4 py-3 text-xs leading-5 text-[#555]">
              <p className="font-semibold text-[#333]">Interactive selection is unavailable; showing the native PDF preview instead.</p>
              <p className="mt-1">{error}</p>
              <p className="mt-1 text-[10px] text-[#777]">Text mode and the native preview remain available. Selection actions require the interactive PDF layer.</p>
            </div>
            <iframe
              key={nativePreviewUrl}
              title={`Native PDF fallback · ${title}`}
              src={nativePreviewUrl}
              className="min-h-[560px] flex-1 rounded-[12px] border border-[#dddddd] bg-white"
            />
          </div>
        ) : (
          <div className="relative mx-auto mb-4 w-fit bg-white shadow-[0_12px_40px_rgba(0,0,0,0.10)]" onMouseUp={captureSelection} onKeyUp={captureSelection}>
            <canvas ref={canvasRef} className="block" aria-label={`PDF page ${pageNumber}`} />
            <div ref={textLayerRef} className="ait-pdf-text-layer textLayer" />
          </div>
        )}
      </div>

      <div
        className="absolute bottom-4 right-4 z-40 flex items-center gap-1 rounded-[9px] border border-[#d9d9d9] bg-white/95 p-1 shadow-[0_8px_24px_rgba(0,0,0,.10)] backdrop-blur-sm"
        aria-label="Document zoom controls"
      >
        <button
          type="button"
          aria-label="Zoom PDF out"
          title="Zoom out"
          disabled={zoom <= MIN_ZOOM || Boolean(error)}
          onClick={() => changeZoom(zoom - ZOOM_STEP)}
          className="flex h-8 w-8 items-center justify-center rounded-[7px] text-[#444] transition hover:bg-[#f1f1f1] disabled:opacity-30"
        >
          <Minus size={14} />
        </button>
        <button
          type="button"
          aria-label="Reset PDF zoom"
          title="Reset zoom"
          disabled={Boolean(error)}
          onClick={() => changeZoom(1)}
          className="flex h-8 min-w-[54px] items-center justify-center gap-1 rounded-[7px] px-2 text-[10.5px] font-medium text-[#555] transition hover:bg-[#f1f1f1] disabled:opacity-30"
        >
          <RotateCcw size={11} />
          {Math.round(zoom * 100)}%
        </button>
        <button
          type="button"
          aria-label="Zoom PDF in"
          title="Zoom in"
          disabled={zoom >= MAX_ZOOM || Boolean(error)}
          onClick={() => changeZoom(zoom + ZOOM_STEP)}
          className="flex h-8 w-8 items-center justify-center rounded-[7px] text-[#444] transition hover:bg-[#f1f1f1] disabled:opacity-30"
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  )
}
