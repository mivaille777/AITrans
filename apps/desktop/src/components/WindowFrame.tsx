import { useEffect, useState, type ReactNode } from "react"
import { Copy, Minus, Square, X } from "lucide-react"

import { desktop } from "../desktop"

import "./WindowFrame.css"

type WindowAction = "minimize" | "maximize" | "close"

export default function WindowFrame({ children }: { children: ReactNode }) {
  const [isMaximized, setIsMaximized] = useState(false)
  const [activeAction, setActiveAction] = useState<WindowAction | null>(null)

  useEffect(() => {
    let mounted = true

    void desktop.window
      .isMaximized()
      .then((maximized) => {
        if (mounted) setIsMaximized(maximized)
      })
      .catch(() => {
        // The browser adapter and a reloading Tauri shell may not expose native state.
      })

    return () => {
      mounted = false
    }
  }, [])

  async function runWindowAction(
    action: WindowAction,
    operation: () => Promise<void>,
  ): Promise<void> {
    if (activeAction) return

    setActiveAction(action)
    try {
      await operation()
    } catch (error) {
      console.error(`AITranslator window action failed: ${action}`, error)
    } finally {
      setActiveAction(null)
    }
  }

  function handleMinimize() {
    void runWindowAction("minimize", () => desktop.window.minimize())
  }

  function handleToggleMaximize() {
    void runWindowAction("maximize", async () => {
      const maximized = await desktop.window.toggleMaximize()
      setIsMaximized(maximized)
    })
  }

  function handleClose() {
    void runWindowAction("close", () => desktop.window.close())
  }

  const maximizeLabel = isMaximized ? "Restore" : "Maximize"
  const MaximizeIcon = isMaximized ? Copy : Square

  return (
    <div className={`window-frame ${isMaximized ? "is-maximized" : ""}`}>
      <header className="window-titlebar" data-tauri-drag-region>
        <div className="window-brand" data-tauri-drag-region>
          <span className="window-logo">A</span>
          <div>
            <span>AITranslator</span>
            <small>Desktop Agent</small>
          </div>
        </div>

        <div className="window-drag-space" data-tauri-drag-region />

        <div className="window-controls">
          <button
            type="button"
            title="Minimize"
            aria-label="Minimize"
            disabled={activeAction !== null}
            aria-busy={activeAction === "minimize"}
            onClick={handleMinimize}
          >
            <Minus size={12} strokeWidth={2.2} />
          </button>
          <button
            type="button"
            title={maximizeLabel}
            aria-label={maximizeLabel}
            aria-pressed={isMaximized}
            disabled={activeAction !== null}
            aria-busy={activeAction === "maximize"}
            onClick={handleToggleMaximize}
          >
            <MaximizeIcon size={11} strokeWidth={2.2} />
          </button>
          <button
            type="button"
            title="Close"
            className="close"
            aria-label="Close"
            disabled={activeAction !== null}
            aria-busy={activeAction === "close"}
            onClick={handleClose}
          >
            <X size={13} strokeWidth={2.2} />
          </button>
        </div>
      </header>
      <div className="window-content">{children}</div>
    </div>
  )
}
