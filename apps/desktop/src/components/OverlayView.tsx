import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react"
import { useMutation, useQuery } from "@tanstack/react-query"

import { dismissOverlay, getOverlayState } from "../api/overlay"
import { desktop } from "../desktop"
import { dispatchOverlayCommand } from "../desktop/overlay-commands"
import {
  readOverlayPreferences,
  subscribeOverlayPreferences,
  updateOverlayPreferences,
  type OverlayPreferences,
} from "../desktop/overlay-preferences"
import { computeOverlayWindowSize } from "../desktop/overlay-sizing"
import { queryKeys, queryPolling } from "../shared/query/query-keys"
import OverlayQuickActions from "./OverlayQuickActions"
import OverlayHeader from "./OverlayHeader"
import OverlayWindowShell from "./OverlayWindowShell"

type MenuPosition = { x: number; y: number }

export default function OverlayView() {
  const [preferences, setPreferences] = useState(readOverlayPreferences)
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null)
  const autoDismissTimerRef = useRef<number | null>(null)
  const lastPlacedContextRef = useRef("")
  const lastSizeKeyRef = useRef("")

  const overlayQuery = useQuery({
    queryKey: queryKeys.overlay.state,
    queryFn: getOverlayState,
    refetchInterval: queryPolling.overlayState,
    staleTime: 0,
  })

  const { mutate: dismiss } = useMutation({
    mutationFn: dismissOverlay,
    onSuccess: () => {
      void desktop.overlay.hide()
    },
  })

  const state = overlayQuery.data
  const overlayVisible = state?.visible ?? false
  const overlayContextId = state?.context_id ?? ""
  const overlayRevision = state?.revision ?? 0
  const overlayMode = state?.mode ?? "assistant"
  const overlayTranslatedText = state?.translated_text ?? ""
  const menuOpen = menuPosition !== null
  const overlaySize = useMemo(
    () => state
      ? computeOverlayWindowSize({
          phase: state.phase,
          mode: overlayMode,
          message: state.message,
          menuOpen,
        })
      : null,
    [menuOpen, overlayMode, state],
  )
  const overlaySizeKey = overlaySize ? `${overlaySize.width}x${overlaySize.height}` : ""

  const cancelAutoDismiss = useCallback(() => {
    if (autoDismissTimerRef.current !== null) {
      window.clearTimeout(autoDismissTimerRef.current)
      autoDismissTimerRef.current = null
    }
  }, [])

  const handleCopy = useCallback(async () => {
    if (!overlayTranslatedText) return
    try {
      await navigator.clipboard.writeText(overlayTranslatedText)
    } catch {
      // Clipboard access can be unavailable during a dev reload.
    }
  }, [overlayTranslatedText])

  useEffect(() => subscribeOverlayPreferences(setPreferences), [])
  useEffect(() => () => cancelAutoDismiss(), [cancelAutoDismiss])

  useEffect(() => {
    let disposed = false
    let unlisten: () => void = () => {}

    void desktop.overlay
      .onMoved((position) => {
        const next = updateOverlayPreferences({
          positionMode: "custom_fixed_position",
          customPosition: position,
        })
        setPreferences(next)
      })
      .then((dispose) => {
        if (disposed) dispose()
        else unlisten = dispose
      })

    return () => {
      disposed = true
      unlisten()
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    async function syncNativeWindow() {
      if (!overlayVisible) {
        cancelAutoDismiss()
        lastPlacedContextRef.current = ""
        lastSizeKeyRef.current = ""
        await desktop.overlay.hide()
        return
      }

      const currentPreferences = readOverlayPreferences()
      await desktop.overlay.setAlwaysOnTop(currentPreferences.alwaysOnTop)
      await desktop.overlay.setClickThrough(currentPreferences.clickThrough)

      if (overlaySize && lastSizeKeyRef.current !== overlaySizeKey) {
        await desktop.overlay.resize(overlaySize)
        lastSizeKeyRef.current = overlaySizeKey
      }

      if (lastPlacedContextRef.current !== overlayContextId) {
        cancelAutoDismiss()
        await desktop.overlay.place(
          currentPreferences.positionMode,
          currentPreferences.customPosition,
        )
        lastPlacedContextRef.current = overlayContextId
      }

      if (!cancelled) await desktop.overlay.show()
    }

    void syncNativeWindow()
    return () => {
      cancelled = true
    }
  }, [
    cancelAutoDismiss,
    overlayContextId,
    overlayRevision,
    overlaySize,
    overlaySizeKey,
    overlayVisible,
  ])

  useEffect(() => {
    if (!overlayVisible) return

    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return

      cancelAutoDismiss()

      if (event.key === "Escape") {
        event.preventDefault()
        if (menuOpen) {
          setMenuPosition(null)
        } else if (overlayMode === "translation") {
          dispatchOverlayCommand("escape")
        } else {
          dismiss()
        }
        return
      }

      if (
        state?.phase === "ready" &&
        overlayMode === "translation" &&
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === "c"
      ) {
        const selectedText = window.getSelection()?.toString().trim() ?? ""
        if (selectedText) return
        event.preventDefault()
        void handleCopy()
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [
    cancelAutoDismiss,
    dismiss,
    handleCopy,
    menuOpen,
    overlayMode,
    overlayVisible,
    state?.phase,
  ])

  function handleContextMenu(event: ReactMouseEvent<HTMLElement>) {
    event.preventDefault()
    if (preferences.clickThrough) return

    cancelAutoDismiss()
    const width = 220
    const estimatedVisibleHeight = Math.min(300, window.innerHeight - 16)
    setMenuPosition({
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
      y: Math.max(
        8,
        Math.min(event.clientY, window.innerHeight - estimatedVisibleHeight - 8),
      ),
    })
  }

  async function applyPreferences(patch: Partial<OverlayPreferences>) {
    cancelAutoDismiss()
    const next = updateOverlayPreferences(patch)
    setPreferences(next)
    setMenuPosition(null)

    if ("alwaysOnTop" in patch) {
      await desktop.overlay.setAlwaysOnTop(next.alwaysOnTop)
    }
    if ("clickThrough" in patch) {
      await desktop.overlay.setClickThrough(next.clickThrough)
    }
    if ("positionMode" in patch || "customPosition" in patch) {
      await desktop.overlay.place(next.positionMode, next.customPosition)
    }
  }

  async function fixAtCurrentPosition() {
    const position = await desktop.overlay.getPosition()
    if (!position) return
    await applyPreferences({
      positionMode: "custom_fixed_position",
      customPosition: position,
    })
  }

  async function togglePositionLock() {
    if (preferences.locked) {
      await applyPreferences({ locked: false })
      return
    }

    const position = await desktop.overlay.getPosition()
    if (!position) {
      await applyPreferences({ locked: true })
      return
    }

    await applyPreferences({
      locked: true,
      positionMode: "custom_fixed_position",
      customPosition: position,
    })
  }

  if (!state?.visible) return null

  return (
    <OverlayWindowShell
      contextId={overlayContextId}
      nearCursor={preferences.positionMode === "mouse_follow"}
      onContextMenu={handleContextMenu}
      onBackgroundPointerDown={() => {
        cancelAutoDismiss()
        setMenuPosition(null)
      }}
      menu={
        menuPosition && (
          <div
            data-overlay-menu
            data-tauri-drag-region="false"
            className="ait-overlay-context-menu ait-system-popover fixed z-50 max-h-[calc(100vh-16px)] w-[220px] overflow-y-auto rounded-[16px] border border-white/10 bg-slate-800 p-1.5 text-xs shadow-2xl"
            style={{ left: menuPosition.x, top: menuPosition.y }}
            onPointerDown={(event) => event.stopPropagation()}
          >
            <MenuHeading>Position</MenuHeading>
            <MenuItem label="Near cursor" active={preferences.positionMode === "mouse_follow"} disabled={preferences.locked} onClick={() => void applyPreferences({ positionMode: "mouse_follow" })} />
            <MenuItem label="Fix here" active={preferences.positionMode === "custom_fixed_position"} disabled={preferences.locked} onClick={() => void fixAtCurrentPosition()} />
            <MenuItem label="Screen top" active={preferences.positionMode === "desktop_lyrics_top"} disabled={preferences.locked} onClick={() => void applyPreferences({ positionMode: "desktop_lyrics_top" })} />
            <MenuItem label="Screen center" active={preferences.positionMode === "desktop_lyrics_center"} disabled={preferences.locked} onClick={() => void applyPreferences({ positionMode: "desktop_lyrics_center" })} />
            <MenuItem label="Screen bottom" active={preferences.positionMode === "desktop_lyrics_bottom"} disabled={preferences.locked} onClick={() => void applyPreferences({ positionMode: "desktop_lyrics_bottom" })} />

            <div className="my-1 border-t border-white/10" />
            <MenuItem label="Always on top" active={preferences.alwaysOnTop} onClick={() => void applyPreferences({ alwaysOnTop: !preferences.alwaysOnTop })} />
            <MenuItem label="Lock position" active={preferences.locked} onClick={() => void togglePositionLock()} />
            <MenuItem label="Click-through" active={preferences.clickThrough} onClick={() => void applyPreferences({ clickThrough: !preferences.clickThrough })} />
            <MenuItem label="Smart auto-dismiss" active={preferences.smartAutoDismiss} onClick={() => void applyPreferences({ smartAutoDismiss: !preferences.smartAutoDismiss })} />

            <div className="my-1 border-t border-white/10" />
            <MenuHeading>Shortcuts</MenuHeading>
            <MenuShortcut label={overlayMode === "translation" ? "Back to assistant" : "Close overlay"} keys="Esc" />
            {overlayMode === "translation" && <MenuShortcut label="Copy translation" keys="Ctrl+C" />}

            <div className="my-1 border-t border-white/10" />
            <MenuItem label="Hide overlay" danger onClick={() => dismiss()} />
          </div>
        )
      }
    >
      <OverlayHeader
        sourceLanguage={state.source_language}
        targetLanguage={state.target_language}
        provider={overlayMode === "assistant" ? "AI Assistant" : state.provider}
        locked={preferences.locked}
        dragEnabled={!preferences.locked && !preferences.clickThrough}
        onClose={() => dismiss()}
      />

      {state.phase === "ready" && <OverlayQuickActions state={state} />}
    </OverlayWindowShell>
  )
}

function MenuHeading({ children }: { children: string }) {
  return <p className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{children}</p>
}

function MenuShortcut({ label, keys }: { label: string; keys: string }) {
  return (
    <div className="flex items-center justify-between gap-3 px-2.5 py-1.5 text-[10px] text-slate-500">
      <span>{label}</span>
      <kbd className="rounded-md border border-white/10 bg-white/[0.035] px-1.5 py-0.5 font-mono text-[9px] text-slate-400">{keys}</kbd>
    </div>
  )
}

function MenuItem({
  label,
  active = false,
  danger = false,
  disabled = false,
  onClick,
}: {
  label: string
  active?: boolean
  danger?: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      data-tauri-drag-region="false"
      disabled={disabled}
      className={`ait-control-motion flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left disabled:cursor-not-allowed disabled:opacity-35 ${danger ? "text-rose-300 hover:bg-rose-400/10" : "text-slate-300 hover:bg-white/10 hover:text-white"}`}
      onClick={onClick}
    >
      <span>{label}</span>
      {active && <span className="text-emerald-400">✓</span>}
    </button>
  )
}
