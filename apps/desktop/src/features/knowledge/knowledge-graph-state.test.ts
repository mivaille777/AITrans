import { describe, expect, it } from "vitest"

import type { KnowledgeItem, KnowledgeRelation } from "./knowledge-types"
import {
  ALL_KNOWLEDGE_ITEM_TYPES,
  ALL_KNOWLEDGE_RELATION_ORIGINS,
  buildLocalKnowledgeGraph,
} from "./knowledge-graph-state"

const now = "2026-09-08T00:00:00Z"

function item(itemId: string, itemType: KnowledgeItem["item_type"], title = itemId): KnowledgeItem {
  return {
    item_id: itemId,
    item_type: itemType,
    title,
    summary: "",
    resource_document_id: null,
    source_uri: "",
    metadata: {},
    created_at: now,
    updated_at: now,
  }
}

function relation(
  relationId: string,
  sourceItemId: string,
  targetItemId: string,
  relationType: string,
  origin: KnowledgeRelation["origin"] = "manual",
): KnowledgeRelation {
  return {
    relation_id: relationId,
    source_item_id: sourceItemId,
    target_item_id: targetItemId,
    relation_type: relationType,
    label: "",
    origin,
    confidence: null,
    metadata: {},
    created_at: now,
    updated_at: now,
  }
}

const filters = {
  itemTypes: ALL_KNOWLEDGE_ITEM_TYPES,
  relationTypes: [],
  origins: ALL_KNOWLEDGE_RELATION_ORIGINS,
}

describe("buildLocalKnowledgeGraph", () => {
  it("keeps the focus at depth zero and expands undirected neighborhoods by depth", () => {
    const items = [item("paper", "paper"), item("note", "note"), item("concept", "concept")]
    const relations = [
      relation("r1", "note", "paper", "reading_note"),
      relation("r2", "concept", "note", "explains"),
    ]

    const depthOne = buildLocalKnowledgeGraph(items, relations, "paper", 1, filters)
    expect(depthOne.nodes.map((node) => [node.item.item_id, node.depth])).toEqual([
      ["paper", 0],
      ["note", 1],
    ])
    expect(depthOne.edges.map((edge) => edge.relation.relation_id)).toEqual(["r1"])

    const depthTwo = buildLocalKnowledgeGraph(items, relations, "paper", 2, filters)
    expect(depthTwo.nodes.map((node) => node.item.item_id)).toEqual(["paper", "note", "concept"])
    expect(depthTwo.edges).toHaveLength(2)
  })

  it("filters relation origins and types before traversal", () => {
    const items = [item("paper", "paper"), item("manual", "note"), item("ai", "concept")]
    const relations = [
      relation("r1", "manual", "paper", "derived_from", "manual"),
      relation("r2", "ai", "paper", "supports", "ai"),
    ]

    const snapshot = buildLocalKnowledgeGraph(items, relations, "paper", 1, {
      itemTypes: ALL_KNOWLEDGE_ITEM_TYPES,
      relationTypes: ["derived_from"],
      origins: ["manual"],
    })

    expect(snapshot.nodes.map((node) => node.item.item_id)).toEqual(["paper", "manual"])
    expect(snapshot.edges.map((edge) => edge.relation.relation_id)).toEqual(["r1"])
  })

  it("keeps only the focus when every relation origin is disabled", () => {
    const items = [item("paper", "paper"), item("note", "note")]
    const relations = [relation("r1", "note", "paper", "derived_from")]

    const snapshot = buildLocalKnowledgeGraph(items, relations, "paper", 2, {
      itemTypes: ALL_KNOWLEDGE_ITEM_TYPES,
      relationTypes: [],
      origins: [],
    })

    expect(snapshot.nodes.map((node) => node.item.item_id)).toEqual(["paper"])
    expect(snapshot.edges).toHaveLength(0)
  })

  it("always keeps the focus visible while respecting neighboring item type filters", () => {
    const items = [item("paper", "paper"), item("note", "note"), item("concept", "concept")]
    const relations = [
      relation("r1", "note", "paper", "derived_from"),
      relation("r2", "concept", "paper", "related_to"),
    ]

    const snapshot = buildLocalKnowledgeGraph(items, relations, "paper", 1, {
      itemTypes: ["concept"],
      relationTypes: [],
      origins: ALL_KNOWLEDGE_RELATION_ORIGINS,
    })

    expect(snapshot.nodes.map((node) => node.item.item_id)).toEqual(["paper", "concept"])
    expect(snapshot.edges.map((edge) => edge.relation.relation_id)).toEqual(["r2"])
  })
})
