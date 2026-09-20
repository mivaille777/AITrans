export const companionLayoutClassNames = {
  shell:
    "ait-chat-shell grid h-full min-h-0 grid-cols-1 overflow-y-auto min-[960px]:grid-cols-[288px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_348px] xl:grid-rows-[minmax(0,1fr)] xl:overflow-hidden",
  historyPanel:
    "ait-chat-history-panel order-1 flex min-h-0 max-h-[380px] flex-col overflow-hidden border-b border-slate-200 bg-white text-slate-900 min-[960px]:max-h-[520px] min-[960px]:border-b-0 min-[960px]:border-r xl:order-1 xl:h-full xl:max-h-none",
  historyScroller:
    "ait-chat-history-scroller ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-contain",
  contextPanel:
    "ait-chat-context-panel ait-scroll-panel order-3 min-h-0 min-w-0 max-h-[420px] overflow-y-auto overscroll-contain border-t border-slate-200 bg-white min-[960px]:col-span-2 xl:order-3 xl:col-span-1 xl:h-full xl:max-h-none xl:border-l xl:border-t-0",
  chatColumn:
    "ait-chat-column order-2 grid min-h-[500px] min-w-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-white min-[960px]:min-h-[540px] xl:order-2 xl:h-full xl:min-h-0",
  conversationHeader:
    "ait-chat-conversation-header",
  messageScroller:
    "ait-chat-message-scroll min-h-0 overflow-y-scroll overscroll-contain px-5 py-5 min-[960px]:px-7 xl:px-9",
  composer:
    "ait-chat-composer sticky bottom-0 z-20 shrink-0 border-t border-slate-200 bg-white px-5 py-4 backdrop-blur min-[960px]:px-7 xl:static",
} as const
