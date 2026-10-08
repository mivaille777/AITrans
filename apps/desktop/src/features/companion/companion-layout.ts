export const companionLayoutClassNames = {
  shell:
    "ait-chat-shell grid h-full min-h-0 overflow-hidden",
  historyPanel:
    "ait-chat-history-panel flex min-h-0 flex-col overflow-hidden bg-white text-slate-900",
  historyScroller:
    "ait-chat-history-scroller ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-contain",
  contextPanel:
    "ait-chat-context-panel ait-scroll-panel min-h-0 min-w-0 overflow-y-auto overscroll-contain bg-white",
  chatColumn:
    "ait-chat-column grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-white",
  conversationHeader:
    "ait-chat-conversation-header",
  messageScroller:
    "ait-chat-message-scroll min-h-0 overflow-y-scroll overscroll-contain",
  composer:
    "ait-chat-composer z-20 shrink-0 bg-white",
} as const
