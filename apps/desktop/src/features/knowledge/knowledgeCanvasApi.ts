export type KnowledgeCanvasGraph = {
  nodes: Array<{
    id: string
    title: string
    type: "paper" | "concept" | "note"
    summary?: string
  }>
  edges: Array<{
    source: string
    target: string
    relation: string
    confidence: number
  }>
}

export type KnowledgeRetrievalResult = {
  id: string
  title: string
  type: string
  score: number
  reason: string
}

const API_BASE = "http://127.0.0.1:8766"

export async function fetchKnowledgeCanvas(): Promise<KnowledgeCanvasGraph> {
  const response = await fetch(`${API_BASE}/knowledge/canvas`)
  if (!response.ok) {
    throw new Error("Failed to load knowledge canvas")
  }
  return response.json()
}

export async function retrieveKnowledge(
  query: string,
  topK = 5,
): Promise<KnowledgeRetrievalResult[]> {
  const response = await fetch(`${API_BASE}/knowledge/canvas/retrieve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ query, top_k: topK }),
  })

  if (!response.ok) {
    throw new Error("Failed to retrieve knowledge")
  }

  const data = await response.json()
  return data.results ?? []
}
