export type KnowledgeView = "canvas" | "graph" | "library" | "reader"
export type KnowledgePrimaryView = Exclude<KnowledgeView, "reader">

export function resolveKnowledgeView(searchParams: URLSearchParams): KnowledgeView {
  const requestedView = searchParams.get("view")
  const paperItemId = searchParams.get("paper") ?? ""

  if (paperItemId && requestedView === "reader") return "reader"
  if (requestedView === "graph") return "graph"
  if (searchParams.has("document") || searchParams.has("item") || requestedView === "library") {
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

export function buildOpenPaperParams(searchParams: URLSearchParams, itemId: string) {
  const next = new URLSearchParams(searchParams)
  next.set("view", "reader")
  next.set("paper", itemId)
  next.delete("document")
  next.delete("item")
  next.delete("focus")
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

export function buildCloseReaderParams(searchParams: URLSearchParams) {
  const next = new URLSearchParams(searchParams)
  next.set("view", "library")
  next.delete("paper")
  return next
}
