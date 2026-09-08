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

const API_BASE = "http://127.0.0.1:8766"

export async function fetchKnowledgeCanvas(): Promise<KnowledgeCanvasGraph> {
  const response = await fetch(`${API_BASE}/knowledge/canvas`)
  if (!response.ok) {
    throw new Error("Failed to load knowledge canvas")
  }
  return response.json()
}
