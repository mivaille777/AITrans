import { invoke } from "@tauri-apps/api/core"
import { emitTo, listen } from "@tauri-apps/api/event"
import {
  LogicalSize,
  PhysicalPosition,
  Window as TauriWindow,
  cursorPosition,
  getCurrentWindow,
  monitorFromPoint,
  primaryMonitor,
} from "@tauri-apps/api/window"

import type {
  CompanionConversationChangeSignal,
  CompanionNavigationSignal,
  DesktopAdapter,
  DesktopPoint,
  DesktopSize,
  OverlayPositionMode,
} from "../adapter"
import { computeOverlayPosition } from "../overlay-positioning"

const OVERLAY_STATE_CHANGED_EVENT = "aitrans-overlay-state-changed"
const COMPANION_NAVIGATION_EVENT = "aitrans-companion-navigation"
const COMPANION_CONVERSATION_CHANGED_EVENT = "aitrans-companion-conversation-changed"
const OVERLAY_INTERACTIVE_DATASET_KEY = "aitOverlayInteractive"

let overlayResizeGeneration = 0
let ignoreProgrammaticOverlayMovesUntil = 0

async function getMainWindow(): Promise<TauriWindow | null> {
  const current = getCurrentWindow()
  if (current.label === "main") return current
  return TauriWindow.getByLabel("main")
}

async function getOverlayWindow(): Promise<TauriWindow | null> {
  const current = getCurrentWindow()
  if (current.label === "overlay") return current
  return TauriWindow.getByLabel("overlay")
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(value, Math.max(minimum, maximum)))
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function overlayRequiresPointerInteraction(): boolean {
  return document.documentElement.dataset[OVERLAY_INTERACTIVE_DATASET_KEY] === "true"
}

function suppressProgrammaticOverlayMoves(duration = 160): void {
  ignoreProgrammaticOverlayMovesUntil = Math.max(
    ignoreProgrammaticOverlayMovesUntil,
    Date.now() + duration,
  )
}

async function cancelOverlayMotion(): Promise<void> {
  try {
    await invoke("cancel_overlay_motion")
  } catch {
    // Keep cancellation best-effort so resize/hide still works while the dev shell reloads.
  }
}

async function updateOverlayWindowShape(): Promise<void> {
  try {
    await invoke("update_overlay_window_shape")
  } catch {
    // The browser adapter and a reloading Tauri shell can briefly lack the native window.
  }
}

async function keepOverlayInsideWorkArea(overlay: TauriWindow): Promise<void> {
  const position = await overlay.outerPosition()
  const size = await overlay.outerSize()
  const monitor =
    (await monitorFromPoint(position.x, position.y)) ??
    (await primaryMonitor())
  if (!monitor) return

  const workArea = monitor.workArea
  const minX = workArea.position.x
  const minY = workArea.position.y
  const maxX = minX + workArea.size.width - size.width
  const maxY = minY + workArea.size.height - size.height
  const nextX = clamp(position.x, minX, maxX)
  const nextY = clamp(position.y, minY, maxY)

  if (nextX !== position.x || nextY !== position.y) {
    suppressProgrammaticOverlayMoves()
    await overlay.setPosition(new PhysicalPosition(nextX, nextY))
  }
}

async function placeOverlay(
  mode: OverlayPositionMode,
  customPosition?: DesktopPoint | null,
): Promise<DesktopPoint | null> {
  const overlay = await getOverlayWindow()
  if (!overlay) return null

  const cursor = await cursorPosition()
  const reference =
    mode === "custom_fixed_position" && customPosition
      ? customPosition
      : { x: cursor.x, y: cursor.y }

  const monitor =
    (await monitorFromPoint(reference.x, reference.y)) ??
    (await monitorFromPoint(cursor.x, cursor.y)) ??
    (await primaryMonitor())
  if (!monitor) return null

  const size = await overlay.outerSize()
  const workArea = monitor.workArea
  const position = computeOverlayPosition({
    mode,
    cursor: { x: cursor.x, y: cursor.y },
    windowSize: { width: size.width, height: size.height },
    workArea: {
      x: workArea.position.x,
      y: workArea.position.y,
      width: workArea.size.width,
      height: workArea.size.height,
    },
    customPosition,
  })

  const animate = mode === "mouse_follow" && (await overlay.isVisible())
  suppressProgrammaticOverlayMoves(animate ? 180 : 120)

  if (animate) {
    await invoke("animate_overlay_position", {
      x: position.x,
      y: position.y,
      durationMs: 76,
    })
  } else {
    await cancelOverlayMotion()
    await overlay.setPosition(new PhysicalPosition(position.x, position.y))
  }
  return position
}

async function resizeOverlay(target: DesktopSize): Promise<void> {
  const overlay = await getOverlayWindow()
  if (!overlay) return

  await cancelOverlayMotion()
  const generation = ++overlayResizeGeneration
  const scaleFactor = await overlay.scaleFactor()
  const current = await overlay.outerSize()
  const startWidth = current.width / scaleFactor
  const startHeight = current.height / scaleFactor
  const deltaWidth = target.width - startWidth
  const deltaHeight = target.height - startHeight

  if (Math.abs(deltaWidth) < 1 && Math.abs(deltaHeight) < 1) {
    await keepOverlayInsideWorkArea(overlay)
    await updateOverlayWindowShape()
    return
  }

  const steps = 8
  const stepDelay = 18
  for (let step = 1; step <= steps; step += 1) {
    if (generation !== overlayResizeGeneration) return

    const t = step / steps
    const eased = 1 - Math.pow(1 - t, 4)
    await overlay.setSize(
      new LogicalSize(
        Math.round(startWidth + deltaWidth * eased),
        Math.round(startHeight + deltaHeight * eased),
      ),
    )

    if (step < steps) await wait(stepDelay)
  }

  if (generation === overlayResizeGeneration) {
    await keepOverlayInsideWorkArea(overlay)
    await updateOverlayWindowShape()
  }
}

async function emitCompanionConversationChange(
  signal: CompanionConversationChangeSignal,
): Promise<void> {
  const currentLabel = getCurrentWindow().label
  const targets = currentLabel === "main"
    ? ["overlay"]
    : currentLabel === "overlay"
      ? ["main"]
      : ["main", "overlay"]

  await Promise.all(
    targets.map(async (target) => {
      try {
        await emitTo(target, COMPANION_CONVERSATION_CHANGED_EVENT, signal)
      } catch {
        // Cross-window synchronization is best-effort; persisted conversation
        // state remains the source of truth when a target window is unavailable.
      }
    }),
  )
}

async function invokeWindowControl<T>(command: string): Promise<T> {
  return invoke<T>(command, {
    windowLabel: getCurrentWindow().label,
  })
}

export const tauriDesktopAdapter: DesktopAdapter = {
  runtime: "tauri",
  files: {
    async pickKnowledgeDocument() {
      return invoke<string | null>("pick_knowledge_document")
    },
    async openEvidenceSource(resourceUrl) {
      await invoke("open_evidence_source", { resourceUrl })
    },
  },
  window: {
    async show() {
      const main = await getMainWindow()
      await main?.show()
    },
    async hide() {
      const main = await getMainWindow()
      await main?.hide()
    },
    async focus() {
      const main = await getMainWindow()
      await main?.show()
      await main?.setFocus()
    },
    async minimize() {
      await invokeWindowControl<void>("window_minimize")
    },
    async toggleMaximize() {
      return invokeWindowControl<boolean>("window_toggle_maximize")
    },
    async isMaximized() {
      return invokeWindowControl<boolean>("window_is_maximized")
    },
    async close() {
      await invokeWindowControl<void>("window_close")
    },
  },
  overlay: {
    async show() {
      const overlay = await getOverlayWindow()
      await updateOverlayWindowShape()
      await overlay?.show()
    },
    async hide() {
      overlayResizeGeneration += 1
      await cancelOverlayMotion()
      const overlay = await getOverlayWindow()
      await overlay?.hide()
    },
    async focus() {
      const overlay = await getOverlayWindow()
      await overlay?.setFocus()
    },
    place: placeOverlay,
    resize: resizeOverlay,
    async getPosition() {
      const overlay = await getOverlayWindow()
      if (!overlay) return null
      const position = await overlay.outerPosition()
      return { x: position.x, y: position.y }
    },
    async setAlwaysOnTop(enabled: boolean) {
      const overlay = await getOverlayWindow()
      await overlay?.setAlwaysOnTop(enabled)
    },
    async setClickThrough(enabled: boolean) {
      const overlay = await getOverlayWindow()
      const effectiveClickThrough = enabled && !overlayRequiresPointerInteraction()
      await overlay?.setIgnoreCursorEvents(effectiveClickThrough)
    },
    async onMoved(callback) {
      const overlay = await getOverlayWindow()
      if (!overlay) return () => undefined
      return overlay.onMoved(({ payload }) => {
        if (Date.now() < ignoreProgrammaticOverlayMovesUntil) return
        callback({ x: payload.x, y: payload.y })
      })
    },
    async notifyStateChanged(contextId = "") {
      await emitTo("overlay", OVERLAY_STATE_CHANGED_EVENT, { contextId })
    },
    async onStateChanged(callback) {
      return listen<{ contextId?: string }>(OVERLAY_STATE_CHANGED_EVENT, (event) => {
        callback(event.payload?.contextId ?? "")
      })
    },
    async notifyCompanionNavigation(signal) {
      await emitTo("main", COMPANION_NAVIGATION_EVENT, signal)
    },
    async onCompanionNavigation(callback) {
      return listen<CompanionNavigationSignal>(COMPANION_NAVIGATION_EVENT, (event) => {
        const conversationId = String(event.payload?.conversationId ?? "").trim()
        const handoffId = String(event.payload?.handoffId ?? "").trim()
        if (!conversationId) return
        callback({ conversationId, handoffId })
      })
    },
    async notifyCompanionConversationChanged(signal) {
      await emitCompanionConversationChange(signal)
    },
    async onCompanionConversationChanged(callback) {
      return listen<CompanionConversationChangeSignal>(
        COMPANION_CONVERSATION_CHANGED_EVENT,
        (event) => {
          const conversationId = String(event.payload?.conversationId ?? "").trim()
          const kind = event.payload?.kind === "deleted" ? "deleted" : "updated"
          if (!conversationId) return
          callback({ conversationId, kind })
        },
      )
    },
  },
}
