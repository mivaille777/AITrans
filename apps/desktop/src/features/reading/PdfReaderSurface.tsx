import { ChevronLeft, ChevronRight, LoaderCircle, Minus, Plus, RotateCcw } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "../../shared/ui/Button"

const PDFJS_VERSION = "6.3.289"
const PDFJS_MODULE_URL = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${PDFJS_VERSION}/pdf.min.mjs`
const PDFJS_WORKER_URL = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${PDFJS_VERSION}/pdf.worker.min.mjs`

const MIN_ZOOM = 0.7
const MAX_ZOOM = 2.2
const ZOOM_STEP = 0.15

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
  getDocument: (source: { url: string }) => PdfLoadingTask
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

let pdfJsPromise: Promise<PdfJsModule> | null = null

async function loadPdfJs(): Promise<PdfJsModule> {
  if (!pdfJsPromise) {
    pdfJsPromise = import(/* @vite-ignore */ PDFJS_MODULE_URL).then((module) => {
      const pdfjs = module as unknown as PdfJsModule
      pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL
      return pdfjs
    })
  }
  return pdfJsPromise
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
      .then((module) => {
        if (disposed) return null
        setPdfJs(module)
        loadingTask = module.getDocument({ url })
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
    onSelection(null)

    void pdfDocument.getPage(pageNumber)
      .then(async (page) => {
        if (disposed) return
        const baseViewport = page.getViewport({ scale: 1 })
        const fitScale = Math.max(0.45, (hostWidth - 48) / Math.max(1, baseViewport.width))
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
  }, [hostWidth, onSelection, pageNumber, pdfDocument, pdfjs, zoom])

  function clearNativeSelection() {
    window.getSelection()?.removeAllRanges()
    onSelection(null)
  }

  function changePage(nextPage: number) {
    if (!pdfDocument) return
    clearNativeSelection()
    setPageNumber(clampPdfPage(nextPage, pdfDocument.numPages))
  }

  function captureSelection() {
    window.setTimeout(() => {
      const current = window.getSelection()
      const textLayer = textLayerRef.current
      if (!current || current.isCollapsed || current.rangeCount === 0 || !textLayer) {
        onSelection(null)
        return
      }
      const range = current.getRangeAt(0)
      if (!textLayer.contains(range.commonAncestorContainer)) {
        onSelection(null)
        return
      }
      const text = current.toString().replace(/\s+/g, " ").trim()
      if (!text) {
        onSelection(null)
        return
      }
      const rect = range.getBoundingClientRect()
      onSelection({
        source: "pdf",
        text,
        pageNumber,
        left: Math.min(window.innerWidth - 220, Math.max(220, rect.left + rect.width / 2)),
        top: Math.max(68, rect.top - 12),
      })
    }, 0)
  }

  const pageCount = pdfDocument?.numPages ?? 0

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-100/75">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2.5 text-[10px] text-slate-500">
        <div className="flex items-center gap-1.5">
          <Button size="xs" variant="ghost" disabled={!pdfDocument || pageNumber <= 1} onClick={() => changePage(pageNumber - 1)}><ChevronLeft size={12} /></Button>
          <span className="min-w-20 text-center font-medium text-slate-600">Page {pageNumber}{pageCount ? ` / ${pageCount}` : ""}</span>
          <Button size="xs" variant="ghost" disabled={!pdfDocument || pageNumber >= pageCount} onClick={() => changePage(pageNumber + 1)}><ChevronRight size={12} /></Button>
        </div>
        <span className="hidden text-slate-400 lg:inline">Select PDF text to create knowledge or ask AI.</span>
        <div className="flex items-center gap-1.5">
          <Button size="xs" variant="ghost" disabled={zoom <= MIN_ZOOM} onClick={() => { clearNativeSelection(); setZoom((value) => Math.max(MIN_ZOOM, value - ZOOM_STEP)) }}><Minus size={12} /></Button>
          <span className="w-10 text-center">{Math.round(zoom * 100)}%</span>
          <Button size="xs" variant="ghost" disabled={zoom >= MAX_ZOOM} onClick={() => { clearNativeSelection(); setZoom((value) => Math.min(MAX_ZOOM, value + ZOOM_STEP)) }}><Plus size={12} /></Button>
          <Button size="xs" variant="ghost" disabled={zoom === 1} onClick={() => { clearNativeSelection(); setZoom(1) }}><RotateCcw size={12} /></Button>
        </div>
      </div>

      <div ref={hostRef} className="ait-scroll-panel relative min-h-0 flex-1 overflow-auto overscroll-contain p-6" aria-label={`Interactive PDF · ${title}`}>
        {(loading || rendering) && (
          <div className="pointer-events-none sticky top-2 z-20 mx-auto flex w-fit items-center gap-2 rounded-full border border-slate-200 bg-white/95 px-3 py-1.5 text-[10px] text-slate-500 shadow-sm">
            <LoaderCircle size={12} className="animate-spin" />{loading ? "Loading PDF…" : "Rendering page…"}
          </div>
        )}
        {error ? (
          <div className="mx-auto mt-12 max-w-lg rounded-[16px] border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-800">
            <p className="font-semibold">Interactive PDF mode is unavailable.</p>
            <p className="mt-1">{error}</p>
            <p className="mt-2 text-[10px] text-amber-700">Text mode remains available. PDF.js is loaded from a pinned CDN build in this batch.</p>
          </div>
        ) : (
          <div className="relative mx-auto w-fit bg-white shadow-[0_12px_40px_rgba(15,23,42,0.12)]" onMouseUp={captureSelection} onKeyUp={captureSelection}>
            <canvas ref={canvasRef} className="block" aria-label={`PDF page ${pageNumber}`} />
            <div ref={textLayerRef} className="ait-pdf-text-layer textLayer" />
          </div>
        )}
      </div>
    </div>
  )
}
