import { useEffect, useRef, useState } from "react"
import { MoreHorizontal, PanelRightClose, PanelRightOpen } from "lucide-react"
import { Link } from "react-router-dom"

export function ChatConversationHeader({
  title,
  contextLabel,
  statusLabel,
  contextPanelOpen,
  newChatDisabled,
  onToggleContext,
  onNewChat,
  onViewContext,
  onViewRun,
  onExportMarkdown,
}: {
  title: string
  contextLabel: string
  statusLabel: string
  contextPanelOpen: boolean
  newChatDisabled: boolean
  onToggleContext: () => void
  onNewChat: () => void
  onViewContext: () => void
  onViewRun?: () => void
  onExportMarkdown?: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      setMenuOpen(false)
      menuButtonRef.current?.focus()
    }
    document.addEventListener("pointerdown", onPointerDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("pointerdown", onPointerDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [menuOpen])

  function runAction(action: () => void) {
    setMenuOpen(false)
    action()
    menuButtonRef.current?.focus()
  }

  return (
    <header className="ait-chat-conversation-header">
      <div className="ait-chat-conversation-heading">
        <h1 className="ait-chat-conversation-name">{title}</h1>
        <p className="ait-chat-conversation-meta-line">
          {contextLabel}<span aria-hidden="true">·</span>{statusLabel}
        </p>
      </div>
      <div className="ait-chat-header-actions">
        <button
          type="button"
          className="ait-chat-conversation-menu"
          aria-label={contextPanelOpen ? "Hide context panel" : "Show context panel"}
          title={contextPanelOpen ? "Hide context panel" : "Show context panel"}
          aria-expanded={contextPanelOpen}
          aria-controls="chat-context-panel"
          onClick={onToggleContext}
        >
          {contextPanelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
        </button>
        <div className="ait-chat-actions-menu" ref={menuRef}>
          <button
            ref={menuButtonRef}
            type="button"
            className="ait-chat-conversation-menu"
            aria-label="Conversation actions"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          ><MoreHorizontal size={19} /></button>
          {menuOpen && (
            <div className="ait-chat-actions-menu-content" role="menu" aria-label="Conversation actions">
              <button type="button" role="menuitem" disabled={newChatDisabled} onClick={() => runAction(onNewChat)}>New chat</button>
              <button type="button" role="menuitem" onClick={() => runAction(onViewContext)}>View context</button>
              {onViewRun && <button type="button" role="menuitem" onClick={() => runAction(onViewRun)}>View run details</button>}
              {onExportMarkdown && <button type="button" role="menuitem" onClick={() => runAction(onExportMarkdown)}>导出会话 Markdown</button>}
              <Link to="/knowledge" role="menuitem" onClick={() => setMenuOpen(false)}>Open Knowledge</Link>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
