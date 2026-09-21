import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Archive, ChevronRight, Copy, Eye, FolderOpen, GitBranch, ListFilter, Pencil, Pin, Plus, Search, Share2, Trash2 } from "lucide-react"
import { createPortal } from "react-dom"

import {
  deleteConversation,
  getConversations,
  renameConversation,
} from "../../api/conversations"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import { Button } from "../../shared/ui/Button"
import type { ConversationSummary } from "../../api/types"
import { companionLayoutClassNames } from "./companion-layout"
import {
  filterConversationHistory,
  groupConversationHistory,
} from "./conversation-history"

const HISTORY_LIMIT = 50

type ConversationContextMenuState = {
  conversationId: string
  title: string
  x: number
  y: number
}

type ConversationDeleteDialogState = {
  conversationId: string
  title: string
}

function formatConversationTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

export default function ConversationHistoryPanel({
  activeConversationId,
  hasCurrentReading,
  onOpen,
  onUseCurrentReading,
  onNewGeneralConversation,
  onDeletedActive,
}: {
  activeConversationId: string
  hasCurrentReading: boolean
  onOpen: (conversationId: string) => void
  onUseCurrentReading: () => void
  onNewGeneralConversation: () => void
  onDeletedActive: () => void
}) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState("")
  const [editingId, setEditingId] = useState("")
  const [editingTitle, setEditingTitle] = useState("")
  const [pinnedConversationIds, setPinnedConversationIds] = useState<Set<string>>(() => new Set())
  const [unreadConversationIds, setUnreadConversationIds] = useState<Set<string>>(() => new Set())
  const [contextMenu, setContextMenu] = useState<ConversationContextMenuState | null>(null)
  const [deleteDialog, setDeleteDialog] = useState<ConversationDeleteDialogState | null>(null)
  const contextMenuRef = useRef<HTMLDivElement | null>(null)
  const deleteCancelButtonRef = useRef<HTMLButtonElement | null>(null)
  const conversationsQuery = useQuery({
    queryKey: queryKeys.conversations.list(HISTORY_LIMIT),
    queryFn: () => getConversations(HISTORY_LIMIT),
    refetchInterval: queryPolling.conversationList,
  })

  const renameMutation = useMutation({
    mutationFn: ({ conversationId, title }: { conversationId: string; title: string }) =>
      renameConversation(conversationId, title),
    onSuccess: () => {
      setEditingId("")
      setEditingTitle("")
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteConversation,
    onSuccess: (result) => {
      setDeleteDialog(null)
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
      if (result.deleted && result.conversation_id === activeConversationId) {
        onDeletedActive()
      }
    },
  })

  const conversations = conversationsQuery.data?.conversations ?? []
  const filtered = filterConversationHistory(conversations, search)
  const groups = groupConversationHistory(filtered).map((group) => ({
    ...group,
    conversations: [...group.conversations].sort((left, right) => {
      const leftPinned = pinnedConversationIds.has(left.conversation_id) ? 1 : 0
      const rightPinned = pinnedConversationIds.has(right.conversation_id) ? 1 : 0
      return rightPinned - leftPinned
    }),
  }))

  useEffect(() => {
    if (!contextMenu) return
    function handleOutsidePointerDown(event: PointerEvent) {
      const target = event.target
      if (target instanceof Node && contextMenuRef.current?.contains(target)) return
      setContextMenu(null)
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setContextMenu(null)
    }
    function handleViewportChange() {
      setContextMenu(null)
    }
    window.addEventListener("pointerdown", handleOutsidePointerDown)
    window.addEventListener("keydown", handleEscape)
    window.addEventListener("resize", handleViewportChange)
    window.addEventListener("scroll", handleViewportChange, true)
    return () => {
      window.removeEventListener("pointerdown", handleOutsidePointerDown)
      window.removeEventListener("keydown", handleEscape)
      window.removeEventListener("resize", handleViewportChange)
      window.removeEventListener("scroll", handleViewportChange, true)
    }
  }, [contextMenu])

  useEffect(() => {
    if (!deleteDialog) return
    if (!deleteMutation.isPending) deleteCancelButtonRef.current?.focus()

    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape" || deleteMutation.isPending) return
      event.preventDefault()
      setDeleteDialog(null)
    }

    window.addEventListener("keydown", handleEscape)
    return () => window.removeEventListener("keydown", handleEscape)
  }, [deleteDialog, deleteMutation.isPending])

  function beginRename(conversationId: string, title: string) {
    setEditingId(conversationId)
    setEditingTitle(title)
  }

  function commitRename(conversationId: string) {
    const normalized = editingTitle.trim()
    if (!normalized) return
    renameMutation.mutate({ conversationId, title: normalized })
  }

  function requestDelete(conversationId: string, title: string) {
    deleteMutation.reset()
    setContextMenu(null)
    setDeleteDialog({ conversationId, title })
  }

  function cancelDelete() {
    if (deleteMutation.isPending) return
    setDeleteDialog(null)
  }

  function confirmDelete() {
    if (!deleteDialog || deleteMutation.isPending) return
    deleteMutation.mutate(deleteDialog.conversationId)
  }

  function openContextMenu(event: ReactMouseEvent, conversation: ConversationSummary) {
    event.preventDefault()
    const menuWidth = 286
    const menuHeight = 430
    setContextMenu({
      conversationId: conversation.conversation_id,
      title: conversation.title,
      x: Math.min(event.clientX, Math.max(8, window.innerWidth - menuWidth - 8)),
      y: Math.min(event.clientY, Math.max(8, window.innerHeight - menuHeight - 8)),
    })
  }

  function togglePinned(conversationId: string) {
    setPinnedConversationIds((current) => {
      const next = new Set(current)
      if (next.has(conversationId)) next.delete(conversationId)
      else next.add(conversationId)
      return next
    })
  }

  function toggleUnread(conversationId: string) {
    setUnreadConversationIds((current) => {
      const next = new Set(current)
      if (next.has(conversationId)) next.delete(conversationId)
      else next.add(conversationId)
      return next
    })
  }

  async function copyConversationLink(conversationId: string) {
    try {
      const currentHash = window.location.hash || "#/chat"
      const [hashPath, rawQuery = ""] = currentHash.split("?")
      const query = new URLSearchParams(rawQuery)
      query.set("conversation", conversationId)
      await navigator.clipboard.writeText(
        `${window.location.origin}${window.location.pathname}${hashPath}?${query.toString()}`,
      )
    } catch {
      // Clipboard access can be unavailable during a dev reload.
    }
    setContextMenu(null)
  }

  async function copyConversationTitle(title: string) {
    try {
      await navigator.clipboard.writeText(title)
    } catch {
      // Clipboard access can be unavailable during a dev reload.
    }
    setContextMenu(null)
  }

  return (
    <aside className={companionLayoutClassNames.historyPanel}>
      <div className="ait-chat-history-header shrink-0">
        <h2 className="ait-chat-history-title">Chat</h2>
        <Button
          className="ait-chat-new-button"
          size="xs"
          aria-label="New chat"
          title="New chat"
          onClick={onNewGeneralConversation}
        >
          <Plus size={18} strokeWidth={2.2} />
        </Button>
      </div>

      {hasCurrentReading && (
        <button
          type="button"
          className="ait-chat-reading-shortcut ait-control-motion"
          onClick={onUseCurrentReading}
        >
          Use current reading context
        </button>
      )}

      <label className="ait-chat-search">
        <Search size={17} className="shrink-0" />
        <input
          className="min-w-0 flex-1 bg-transparent outline-none"
          value={search}
          placeholder="Search conversations…"
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>

      <div className={companionLayoutClassNames.historyScroller}>
        {conversationsQuery.isLoading && (
          <p className="ait-chat-history-empty">Loading conversations…</p>
        )}
        {!conversationsQuery.isLoading && conversations.length === 0 && (
          <p className="ait-chat-history-empty">
            No saved conversations yet. Start a General Chat or open the current reading context.
          </p>
        )}
        {!conversationsQuery.isLoading && conversations.length > 0 && filtered.length === 0 && (
          <p className="ait-chat-history-empty">
            No conversations match “{search.trim()}”.
          </p>
        )}

        <div className="ait-chat-history-groups">
          {groups.map((group) => (
            <section key={group.label}>
              <p className="ait-chat-history-group-label">
                {group.label === "Previous 7 days" ? "This week" : group.label}
              </p>
              <div className="ait-chat-history-items">
                {group.conversations.map((conversation) => {
                  const active = conversation.conversation_id === activeConversationId
                  const editing = conversation.conversation_id === editingId
                  return (
                    <div
                      key={conversation.conversation_id}
                      className={`ait-conversation-item ait-chat-conversation-item ${active ? "is-active" : ""} ${unreadConversationIds.has(conversation.conversation_id) ? "is-unread" : ""}`}
                      onContextMenu={(event) => openContextMenu(event, conversation)}
                    >
                      {editing ? (
                        <div>
                          <input
                            autoFocus
                            className="ait-chat-conversation-edit-input"
                            value={editingTitle}
                            onChange={(event) => setEditingTitle(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") commitRename(conversation.conversation_id)
                              if (event.key === "Escape") {
                                setEditingId("")
                                setEditingTitle("")
                              }
                            }}
                          />
                          <div className="ait-chat-conversation-edit-actions">
                            <button
                              type="button"
                              className="ait-chat-small-action is-primary"
                              disabled={renameMutation.isPending}
                              onClick={() => commitRename(conversation.conversation_id)}
                            >
                              Save
                            </button>
                            <button
                              type="button"
                              className="ait-chat-small-action"
                              onClick={() => {
                                setEditingId("")
                                setEditingTitle("")
                              }}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="ait-chat-conversation-main"
                            onClick={() => {
                              setContextMenu(null)
                              onOpen(conversation.conversation_id)
                            }}
                          >
                            <div className="ait-chat-conversation-title-row">
                              <p className="ait-chat-conversation-title">
                                {conversation.title}
                              </p>
                              <span className="ait-chat-conversation-time">
                                {formatConversationTime(conversation.updated_at)}
                              </span>
                            </div>
                            <p className="ait-chat-conversation-snippet">
                              {conversation.section_heading || conversation.resource_title || (
                                conversation.context_mode === "reading" ? "Continue from reading context…" : "Start a new conversation…"
                              )}
                            </p>
                          </button>
                        </>
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      </div>
      {contextMenu && createPortal(
        <div
          ref={contextMenuRef}
          className="ait-chat-conversation-menu-panel"
          role="menu"
          aria-label={`Actions for ${contextMenu.title}`}
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onContextMenu={(event) => event.preventDefault()}
        >
          <ConversationContextMenuItem
            icon={<Pencil size={17} />}
            label="Rename"
            shortcut="Alt+Ctrl+R"
            onClick={() => {
              beginRename(contextMenu.conversationId, contextMenu.title)
              setContextMenu(null)
            }}
          />
          <ConversationContextMenuItem
            icon={<Pin size={17} />}
            label={pinnedConversationIds.has(contextMenu.conversationId) ? "Unpin" : "Pin"}
            shortcut="Alt+Ctrl+P"
            onClick={() => {
              togglePinned(contextMenu.conversationId)
              setContextMenu(null)
            }}
          />
          <ConversationContextMenuItem
            icon={<Eye size={17} />}
            label={unreadConversationIds.has(contextMenu.conversationId) ? "Mark as read" : "Mark as unread"}
            shortcut="Ctrl+Shift+U"
            onClick={() => {
              toggleUnread(contextMenu.conversationId)
              setContextMenu(null)
            }}
          />
          <ConversationContextMenuItem
            icon={<Archive size={17} />}
            label="Archive"
            shortcut="Ctrl+Shift+A"
            disabled
          />
          <ConversationContextMenuItem
            icon={<Trash2 size={17} />}
            label="Delete conversation"
            danger
            onClick={() => requestDelete(contextMenu.conversationId, contextMenu.title)}
          />

          <div className="ait-chat-context-menu-divider" />
          <ConversationContextMenuItem icon={<FolderOpen size={17} />} label="Project" trailing={<ChevronRight size={16} />} disabled />
          <ConversationContextMenuItem icon={<ListFilter size={17} />} label="Section" trailing={<ChevronRight size={16} />} disabled />

          <div className="ait-chat-context-menu-divider" />
          <ConversationContextMenuItem
            icon={<Share2 size={17} />}
            label="Share"
            onClick={() => void copyConversationLink(contextMenu.conversationId)}
          />
          <ConversationContextMenuItem
            icon={<Copy size={17} />}
            label="Copy title"
            trailing={<ChevronRight size={16} />}
            onClick={() => void copyConversationTitle(contextMenu.title)}
          />

          <div className="ait-chat-context-menu-divider" />
          <ConversationContextMenuItem icon={<GitBranch size={17} />} label="Branch" trailing={<ChevronRight size={16} />} disabled />
        </div>,
        document.body,
      )}
      {deleteDialog && createPortal(
        <div
          className="ait-chat-delete-dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) cancelDelete()
          }}
        >
          <section
            className="ait-chat-delete-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="ait-chat-delete-dialog-title"
            aria-describedby="ait-chat-delete-dialog-description"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="ait-chat-delete-dialog-heading">
              <span className="ait-chat-delete-dialog-icon" aria-hidden="true">
                <Trash2 size={19} strokeWidth={1.9} />
              </span>
              <div className="ait-chat-delete-dialog-copy">
                <h3 id="ait-chat-delete-dialog-title">Delete this conversation?</h3>
                <p id="ait-chat-delete-dialog-description">
                  <strong>“{deleteDialog.title}”</strong> will be permanently removed from your chat history.
                  This action can’t be undone.
                </p>
              </div>
            </div>

            {deleteMutation.isError && (
              <p className="ait-chat-delete-dialog-error" role="alert">
                Couldn’t delete this conversation. Please try again.
              </p>
            )}

            <footer className="ait-chat-delete-dialog-actions">
              <button
                ref={deleteCancelButtonRef}
                type="button"
                className="ait-chat-delete-dialog-button"
                disabled={deleteMutation.isPending}
                onClick={cancelDelete}
              >
                Cancel
              </button>
              <button
                type="button"
                className="ait-chat-delete-dialog-button is-danger"
                disabled={deleteMutation.isPending}
                onClick={confirmDelete}
              >
                {deleteMutation.isPending ? "Deleting…" : "Delete"}
              </button>
            </footer>
          </section>
        </div>,
        document.body,
      )}
    </aside>
  )
}

function ConversationContextMenuItem({
  icon,
  label,
  shortcut,
  trailing,
  danger = false,
  disabled = false,
  onClick,
}: {
  icon: ReactNode
  label: string
  shortcut?: string
  trailing?: ReactNode
  danger?: boolean
  disabled?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      role="menuitem"
      className={`ait-chat-context-menu-item ${danger ? "is-danger" : ""}`}
      disabled={disabled}
      onClick={onClick}
    >
      <span className="ait-chat-context-menu-icon">{icon}</span>
      <span className="ait-chat-context-menu-label">{label}</span>
      {shortcut && <kbd>{shortcut}</kbd>}
      {trailing && <span className="ait-chat-context-menu-trailing">{trailing}</span>}
    </button>
  )
}
