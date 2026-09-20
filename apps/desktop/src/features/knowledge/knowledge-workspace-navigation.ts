export type KnowledgeView = "canvas" | "graph" | "library"
export type KnowledgePrimaryView = KnowledgeView

export function resolveLegacyKnowledgeReaderPaperId(searchParams: URLSearchParams): string {
  if (searchParams.get("view") !== "reader") return ""
  return (searchParams.get("paper") ?? "").trim()
}

export function resolveKnowledgeView(searchParams: URLSearchParams): KnowledgeView {
  const requestedView = searchParams.get("view")

  if (requestedView === "graph") return "graph"
  if (
    searchParams.has("document") ||
    searchParams.has("item") ||
    requestedView === "library" ||
    requestedView === "reader"
  ) {
    return "library"
  }
  return "canvas"
}

export function buildKnowledgeViewParams(
  searchParams: URLSearchParams,
  nextView: KnowledgePrimaryView,
) {
  const next = new URLSearchParams(searchParams)
  next.delete("paper")
  next.delete("document")
  next.delete("item")
  if (nextView !== "graph") next.delete("focus")
  if (nextView === "canvas") next.delete("view")
  else next.set("view", nextView)
  return next
}

export function buildOpenGraphParams(searchParams: URLSearchParams, itemId: string) {
  const next = new URLSearchParams(searchParams)
  next.set("view", "graph")
  next.set("focus", itemId)
  next.delete("paper")
  next.delete("document")
  next.delete("item")
  return next
}

export function buildOpenLibraryItemParams(searchParams: URLSearchParams, itemId: string) {
  const next = new URLSearchParams(searchParams)
  next.set("view", "library")
  next.set("item", itemId)
  next.delete("paper")
  next.delete("document")
  next.delete("focus")
  return next
}
