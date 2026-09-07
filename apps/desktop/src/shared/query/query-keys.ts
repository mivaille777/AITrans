export const queryKeys = {
  health: ["health"] as const,
  translation: {
    status: ["translation", "status"] as const,
  },
  browser: {
    status: ["browser", "status"] as const,
    selection: ["browser", "selection"] as const,
    page: ["browser", "page"] as const,
  },
  reading: {
    selection: ["reading", "selection"] as const,
  },
  overlay: {
    state: ["overlay", "state"] as const,
  },
  quickActions: {
    status: ["quick-actions", "status"] as const,
  },
  companion: {
    handoff: ["companion", "handoff"] as const,
    chatStatus: ["companion", "chat-status"] as const,
    ownership: (conversationId: string) => ["companion", "ownership", conversationId] as const,
  },
  conversations: {
    list: (limit: number) => ["conversations", "list", limit] as const,
    detail: (conversationId: string) => ["conversations", "detail", conversationId] as const,
  },
  research: {
    notes: (limit: number) => ["research", "notes", limit] as const,
    workspace: (limit: number) => ["research", "workspace", limit] as const,
    source: (sourceId: string) => ["research", "source", sourceId] as const,
    detail: (noteId: string) => ["research", "detail", noteId] as const,
  },
  knowledge: {
    documents: ["knowledge", "documents"] as const,
    document: (documentId: string) => ["knowledge", "documents", documentId] as const,
    items: ["knowledge", "items"] as const,
    item: (itemId: string) => ["knowledge", "items", itemId] as const,
    boards: ["knowledge", "boards"] as const,
    board: (boardId: string) => ["knowledge", "boards", boardId] as const,
    relations: ["knowledge", "relations"] as const,
    runtime: ["knowledge", "runtime"] as const,
  },
  ragModels: {
    list: ["rag-models", "list"] as const,
  },
} as const

export const queryPolling = {
  health: 5_000,
  translationStatus: 15_000,
  browserStatus: 2_000,
  browserSelection: 500,
  browserPage: 2_000,
  readingSelection: 500,
  overlayState: 1_000,
  companionHandoff: 650,
  companionChatStatus: 30_000,
  companionOwnership: 500,
  conversationList: 5_000,
  researchNotes: 5_000,
  researchWorkspace: 5_000,
  knowledgeDocuments: 5_000,
  knowledgeActiveDocuments: 1_000,
} as const
