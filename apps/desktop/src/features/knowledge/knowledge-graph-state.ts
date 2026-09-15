import type { KnowledgeItem, KnowledgeItemType, KnowledgeRelation, KnowledgeRelationOrigin } from "./knowledge-types"

export interface KnowledgeGraphFilters {
  itemTypes: KnowledgeItemType[]
  relationTypes: string[]
  origins: KnowledgeRelationOrigin[]
}

export interface KnowledgeGraphNode {
  item: KnowledgeItem
  depth: number
  inboundCount: number
  outboundCount: number
}

export interface KnowledgeGraphEdge {
  relation: KnowledgeRelation
  source: KnowledgeItem
  target: KnowledgeItem
}

export interface KnowledgeGraphSnapshot {
  focus: KnowledgeItem | null
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
}

export const ALL_KNOWLEDGE_ITEM_TYPES: KnowledgeItemType[] = [
  "paper",
  "note",
  "concept",
  "highlight",
  "evidence",
  "insight",
  "question",
  "document",
  "web",
]

export const ALL_KNOWLEDGE_RELATION_ORIGINS: KnowledgeRelationOrigin[] = [
  "manual",
  "imported",
  "ai",
  "citation",
  "rag",
]

export function buildLocalKnowledgeGraph(
  items: KnowledgeItem[],
  relations: KnowledgeRelation[],
  focusItemId: string,
  maxDepth: number,
  filters: KnowledgeGraphFilters,
): KnowledgeGraphSnapshot {
  const itemById = new Map(items.map((item) => [item.item_id, item] as const))
  const focus = itemById.get(focusItemId) ?? null
  if (!focus) return { focus: null, nodes: [], edges: [] }

  const allowedItemTypes = new Set(filters.itemTypes)
  const allowedRelationTypes = new Set(filters.relationTypes)
  const allowedOrigins = new Set(filters.origins)
  const boundedDepth = Math.max(0, Math.min(3, Math.trunc(maxDepth)))
  const visibleRelations = relations.filter((relation) => (
    (allowedRelationTypes.size === 0 || allowedRelationTypes.has(relation.relation_type))
    && allowedOrigins.has(relation.origin)
  ))

  const adjacency = new Map<string, KnowledgeRelation[]>()
  visibleRelations.forEach((relation) => {
    const source = itemById.get(relation.source_item_id)
    const target = itemById.get(relation.target_item_id)
    if (!source || !target) return
    if (source.item_id !== focus.item_id && !allowedItemTypes.has(source.item_type)) return
    if (target.item_id !== focus.item_id && !allowedItemTypes.has(target.item_type)) return
    adjacency.set(source.item_id, [...(adjacency.get(source.item_id) ?? []), relation])
    adjacency.set(target.item_id, [...(adjacency.get(target.item_id) ?? []), relation])
  })

  const depthById = new Map<string, number>([[focus.item_id, 0]])
  const queue = [focus.item_id]
  while (queue.length > 0) {
    const currentId = queue.shift() as string
    const currentDepth = depthById.get(currentId) ?? 0
    if (currentDepth >= boundedDepth) continue
    for (const relation of adjacency.get(currentId) ?? []) {
      const otherId = relation.source_item_id === currentId
        ? relation.target_item_id
        : relation.source_item_id
      if (depthById.has(otherId)) continue
      depthById.set(otherId, currentDepth + 1)
      queue.push(otherId)
    }
  }

  const visibleIds = new Set(depthById.keys())
  const edges = visibleRelations
    .filter((relation) => visibleIds.has(relation.source_item_id) && visibleIds.has(relation.target_item_id))
    .map((relation) => ({
      relation,
      source: itemById.get(relation.source_item_id) as KnowledgeItem,
      target: itemById.get(relation.target_item_id) as KnowledgeItem,
    }))

  const nodes = [...depthById.entries()]
    .map(([itemId, depth]) => {
      const item = itemById.get(itemId) as KnowledgeItem
      return {
        item,
        depth,
        inboundCount: edges.filter((edge) => edge.relation.target_item_id === itemId).length,
        outboundCount: edges.filter((edge) => edge.relation.source_item_id === itemId).length,
      }
    })
    .sort((left, right) => left.depth - right.depth || left.item.title.localeCompare(right.item.title))

  return { focus, nodes, edges }
}

export function localGraphRelationTypes(relations: KnowledgeRelation[]): string[] {
  return [...new Set(relations.map((relation) => relation.relation_type))].sort((left, right) => left.localeCompare(right))
}
