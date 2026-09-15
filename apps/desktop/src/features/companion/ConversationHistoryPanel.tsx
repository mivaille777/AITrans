import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Search } from "lucide-react"

import {
  deleteConversation,
  getConversations,
  renameConversation,
} from "../../api/conversations"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import { companionLayoutClassNames } from "./companion-layout"
import {
  filterConversationHistory,
  groupConversationHistory,
} from "./conversation-history"

const HISTORY_LIMIT = 50

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
      <div className="shrink-0 px-1 py-1">
        <Button className="w-full justify-center" size="xs" onClick={onNewGeneralConversation}>
          <Plus size={13} />
          New chat
        </Button>

        {hasCurrentReading && (
          <button
            type="button"
            className="ait-control-motion mt-2.5 w-full rounded-[11px] border border-blue-200/70 bg-blue-50/70 px-3 py-2.5 text-left text-xs font-medium text-blue-700 hover:bg-blue-50"
            onClick={onUseCurrentReading}
          >
            Use current reading context
          </button>
        )}

        <label className="mt-2.5 flex items-center gap-2 rounded-[11px] border border-slate-200/80 bg-white px-3 py-2.5 transition-colors focus-within:border-blue-300 focus-within:ring-2 focus-within:ring-blue-100">
          <Search size={13} className="shrink-0 text-slate-400" />
          <input
            className="min-w-0 flex-1 bg-transparent text-xs text-slate-700 outline-none placeholder:text-slate-400"
            value={search}
            placeholder="Search conversations"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>

      <div className={companionLayoutClassNames.historyScroller}>
        {conversationsQuery.isLoading && (
          <p className="px-2 py-3 text-xs text-slate-400">Loading conversations…</p>
        )}
        {!conversationsQuery.isLoading && conversations.length === 0 && (
          <p className="px-2 py-3 text-xs leading-5 text-slate-400">
            No saved conversations yet. Start a General Chat or open the current reading context.
          </p>
        )}
        {!conversationsQuery.isLoading && conversations.length > 0 && filtered.length === 0 && (
          <p className="px-2 py-3 text-xs leading-5 text-slate-400">
            No conversations match “{search.trim()}”.
          </p>
        )}

        <div className="space-y-4 pt-2">
          {groups.map((group) => (
            <section key={group.label}>
              <p className="mb-1 px-2 text-[9px] font-semibold uppercase tracking-[0.15em] text-slate-400">
                {group.label}
              </p>
              <div className="space-y-1">
                {group.conversations.map((conversation) => {
                  const active = conversation.conversation_id === activeConversationId
                  const editing = conversation.conversation_id === editingId
                  return (
                    <div
                      key={conversation.conversation_id}
                      className={`ait-conversation-item group rounded-[11px] border p-2.5 ${
                        active
                          ? "border-blue-200/70 bg-blue-50/75 shadow-sm"
                          : "border-transparent hover:border-slate-200/80 hover:bg-white"
                      }`}
                    >
                      {editing ? (
                        <div>
                          <input
                            autoFocus
                            className="w-full rounded-[9px] border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-800 outline-none focus:border-blue-300"
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
                          <div className="mt-2 flex gap-1">
                            <button
                              type="button"
                              className="rounded-[8px] bg-slate-900 px-2 py-1 text-[10px] text-white"
                              disabled={renameMutation.isPending}
                              onClick={() => commitRename(conversation.conversation_id)}
                            >
                              Save
                            </button>
                            <button
                              type="button"
                              className="rounded-[8px] px-2 py-1 text-[10px] text-slate-400 hover:bg-slate-100 hover:text-slate-700"
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
                            className="block w-full text-left"
                            onClick={() => onOpen(conversation.conversation_id)}
                          >
                            <p className="line-clamp-2 text-xs font-medium leading-5 text-slate-700">
                              {conversation.title}
                            </p>
                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                              <Badge tone={conversation.context_mode === "reading" ? "info" : "neutral"}>
                                {conversation.context_mode === "reading" ? "Reading" : "General"}
                              </Badge>
                              {conversation.model && <Badge tone="neutral">{conversation.model}</Badge>}
                              {conversation.section_heading && (
                                <span className="line-clamp-1 text-[10px] text-slate-400">
                                  {conversation.section_heading}
                                </span>
                              )}
                            </div>
                          </button>
                          <div className={`mt-2 flex gap-1 transition-opacity ${active ? "opacity-70" : "opacity-0 group-hover:opacity-70"}`}>
                            <button
                              type="button"
                              className="rounded-[7px] px-1.5 py-1 text-[10px] text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                              onClick={() => beginRename(conversation.conversation_id, conversation.title)}
                            >
                              Rename
                            </button>
                            <button
                              type="button"
                              className="rounded-[7px] px-1.5 py-1 text-[10px] text-slate-400 hover:bg-rose-50 hover:text-rose-600"
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
