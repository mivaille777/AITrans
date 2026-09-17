import { Minus, Plus, RotateCcw } from "lucide-react"
import { useEffect, useRef, useState, type CSSProperties } from "react"

import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import UnifiedReadingWorkspace from "./UnifiedReadingWorkspace"
import "./reading-document-viewport.css"

const DOCUMENT_ZOOM_KEY = "aitrans.reading.documentZoom"
const MIN_DOCUMENT_ZOOM = 0.75
const MAX_DOCUMENT_ZOOM = 1.6
const DOCUMENT_ZOOM_STEP = 0.1

function clampZoom(value: number): number {
  return Math.min(MAX_DOCUMENT_ZOOM, Math.max(MIN_DOCUMENT_ZOOM, value))
}

function readDocumentZoom(): number {
  if (typeof window === "undefined") return 1
  const stored = Number(window.localStorage.getItem(DOCUMENT_ZOOM_KEY))
  return Number.isFinite(stored) ? clampZoom(stored) : 1
}

export default function ReadingWorkspace({ workspace }: { workspace: TranslationWorkspaceController }) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [documentZoom, setDocumentZoom] = useState(readDocumentZoom)
  const [textReaderActive, setTextReaderActive] = useState(false)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const detectReader = () => {
      setTextReaderActive(Boolean(root.querySelector("main > .ait-scroll-panel")))
    }

    detectReader()
    const observer = new MutationObserver(detectReader)
    observer.observe(root, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [])

  function changeZoom(next: number) {
    const value = clampZoom(Number(next.toFixed(2)))
    setDocumentZoom(value)
    window.localStorage.setItem(DOCUMENT_ZOOM_KEY, String(value))
  }

  const readingStyle = {
    "--ait-reading-document-zoom": documentZoom,
  } as CSSProperties

  return (
    <div
      ref={rootRef}
      className="ait-reading-workspace relative h-full min-h-0 overflow-hidden"
      style={readingStyle}
    >
      <UnifiedReadingWorkspace workspace={workspace} />

      {textReaderActive && (
        <div
          className="ait-reading-document-zoom flex items-center gap-1 rounded-[9px] border border-[#d9d9d9] bg-white/95 p-1 shadow-[0_8px_24px_rgba(0,0,0,.10)] backdrop-blur-sm"
          aria-label="Document zoom controls"
        >
          <button
            type="button"
            aria-label="Zoom document out"
            title="Zoom out"
            disabled={documentZoom <= MIN_DOCUMENT_ZOOM}
            onClick={() => changeZoom(documentZoom - DOCUMENT_ZOOM_STEP)}
            className="flex h-8 w-8 items-center justify-center rounded-[7px] text-[#444] transition hover:bg-[#f1f1f1] disabled:opacity-30"
          >
            <Minus size={14} />
          </button>
          <button
            type="button"
            aria-label="Reset document zoom"
            title="Reset zoom"
            onClick={() => changeZoom(1)}
            className="flex h-8 min-w-[54px] items-center justify-center gap-1 rounded-[7px] px-2 text-[10.5px] font-medium text-[#555] transition hover:bg-[#f1f1f1]"
          >
            <RotateCcw size={11} />
            {Math.round(documentZoom * 100)}%
          </button>
          <button
            type="button"
            aria-label="Zoom document in"
            title="Zoom in"
            disabled={documentZoom >= MAX_DOCUMENT_ZOOM}
            onClick={() => changeZoom(documentZoom + DOCUMENT_ZOOM_STEP)}
            className="flex h-8 w-8 items-center justify-center rounded-[7px] text-[#444] transition hover:bg-[#f1f1f1] disabled:opacity-30"
          >
            <Plus size={14} />
          </button>
        </div>
      )}
    </div>
  )
}
