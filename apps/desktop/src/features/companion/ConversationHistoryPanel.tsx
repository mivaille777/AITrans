import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Search } from "lucide-react"

import {
  deleteConversation,
  getConversations,
  renameConversation,
} from "../../api/conversations"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import { Button } from "../../shared/ui/Button"
import { companionLayoutClassNames } from "./companion-layout"
import {
  filterConversationHistory,
  groupConversationHistory,
} from "./conversation-history"

const HISTORY_LIMIT = 50

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
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
      if (result.deleted && result.conversation_id === activeConversationId) {
        onDeletedActive()
      }
    },
  })

  const conversations = conversationsQuery.data?.conversations ?? []
  const filtered = filterConversationHistory(conversations, search)
  const groups = groupConversationHistory(filtered)

  function beginRename(conversationId: string, title: string) {
    setEditingId(conversationId)
    setEditingTitle(title)
  }

  function commitRename(conversationId: string) {
    const normalized = editingTitle.trim()
    if (!normalized) return
    renameMutation.mutate({ conversationId, title: normalized })
  }

  function remove(conversationId: string, title: string) {
    if (!window.confirm(`Delete “${title}”?`)) return
    deleteMutation.mutate(conversationId)
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
                      className={`ait-conversation-item ait-chat-conversation-item group ${active ? "is-active" : ""}`}
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
                            onClick={() => onOpen(conversation.conversation_id)}
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
                            <div className="ait-chat-conversation-meta">
                              <span className="ait-chat-history-pill">
                                {conversation.context_mode === "reading" ? "Reading" : "General"}
                              </span>
                              {conversation.model && (
                                <span className="ait-chat-history-pill">{conversation.model}</span>
                              )}
                              {conversation.section_heading && (
                                <span className="ait-chat-conversation-source">{conversation.source_kind || "Context"}</span>
                              )}
                            </div>
                          </button>
                          <div className={`ait-chat-conversation-actions ${active ? "is-visible" : ""}`}>
                            <button
                              type="button"
                              className="ait-chat-small-action"
                              onClick={() => beginRename(conversation.conversation_id, conversation.title)}
                            >
                              Rename
                            </button>
                            <button
                              type="button"
                              className="ait-chat-small-action is-danger"
                              onClick={() => remove(conversation.conversation_id, conversation.title)}
                            >
                              Delete
                            </button>
                          </div>
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
    </aside>
  )
}
