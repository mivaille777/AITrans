import type { PointerEvent as ReactPointerEvent } from "react"

import { startOverlayWindowDrag } from "../desktop/overlay-native-theme"

type OverlayHeaderProps = {
  sourceLanguage: string
  targetLanguage: string
  provider?: string
  locked: boolean
  dragEnabled: boolean
  onClose: () => void
}

export default function OverlayHeader({
  locked,
  dragEnabled,
  onClose,
}: OverlayHeaderProps) {
  function handlePointerDown(event: ReactPointerEvent<HTMLElement>) {
    if (!dragEnabled || event.button !== 0) return

    const target = event.target
    if (
      target instanceof HTMLElement &&
      target.closest("button, input, textarea, select, a, [data-ait-overlay-no-drag='true']")
    ) {
      return
    }

    event.preventDefault()
    void startOverlayWindowDrag().catch(() => undefined)
  }

  return (
    <header
      className={`flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3 ${
        dragEnabled ? "cursor-move" : "cursor-default"
      }`}
      data-tauri-drag-region="false"
      onPointerDown={handlePointerDown}
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="ait-overlay-drag-handle select-none text-xs tracking-[-0.15em] text-slate-600">••••</span>
        <p className="truncate text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          AITranslator
        </p>
      </div>

      <div className="flex items-center gap-2" data-ait-overlay-no-drag="true">
        {locked && (
          <span className="rounded-md bg-white/5 px-2 py-1 text-[10px] font-medium text-slate-500">
            Locked
          </span>
        )}
        <button
          type="button"
          aria-label="Close overlay"
          title="关闭 · Esc"
          className="ait-overlay-quiet-button flex h-7 w-7 items-center justify-center rounded-full text-sm text-slate-400"
          onClick={onClose}
        >
          ×
        </button>
      </div>
    </header>
  )
}
