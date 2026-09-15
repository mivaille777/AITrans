export function resolveReadingPaperId(searchParams: URLSearchParams): string {
  return (searchParams.get("paper") ?? "").trim()
}

export function buildOpenReadingPaperParams(
  searchParams: URLSearchParams,
  itemId: string,
): URLSearchParams {
  const next = new URLSearchParams(searchParams)
  const normalized = itemId.trim()
  if (normalized) next.set("paper", normalized)
  else next.delete("paper")
  return next
}

export function buildCloseReadingPaperParams(searchParams: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(searchParams)
  next.delete("paper")
  return next
}

export function buildReadingPaperPath(itemId: string): string {
  const normalized = itemId.trim()
  if (!normalized) return "/reading"
  const params = new URLSearchParams()
  params.set("paper", normalized)
  return `/reading?${params.toString()}`
}
