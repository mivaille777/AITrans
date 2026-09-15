import { describe, expect, it } from "vitest"

import type { AgentKnowledgeContext, AgentTraceEvent } from "../../../api/agent"
import {
  previewKnowledgeContextObservability,
  runtimeKnowledgeContextObservability,
} from "./agent-context-observability"

const context: AgentKnowledgeContext = {
  canvas: {
    board_id: "board-1",
    board_name: "test1",
    scope_label: "Canvas",
  },
  cards: [
    {
      item_id: "card-1",
      item_type: "insight",
      title: "Insight",
      summary: "Summary",
      document_id: "doc-1",
    },
    {
      item_id: "card-2",
      item_type: "evidence",
      title: "Evidence",
      summary: "Evidence",
      document_id: "doc-1",
    },
  ],
  relations: [
    {
      relation_id: "relation-1",
      source_item_id: "card-1",
      source_title: "Insight",
      target_item_id: "card-2",
      target_title: "Evidence",
      relation_type: "supports",
      label: "manual edge",
      origin: "manual",
      confidence: null,
    },
  ],
}

describe("knowledge context observability", () => {
  it("shows an attached preview before runtime confirms the contract", () => {
    const preview = previewKnowledgeContextObservability(context)

    expect(preview).toMatchObject({
      status: "attached",
      binding: "knowledge_canvas",
      canvasName: "test1",
      cards: 2,
      relations: 1,
      documents: 1,
      visibility: {
        planner: false,
        react: false,
        synthesis: false,
      },
    })
  })

  it("uses the backend knowledge_context_ready event as the runtime source of truth", () => {
    const event: AgentTraceEvent = {
      sequence: 2,
      event_type: "knowledge_context_ready",
      timestamp: "2026-09-15T00:00:00Z",
      run_id: "run-1",
      trace_id: "trace-1",
      elapsed_ms: 4,
      payload: {
        binding: "knowledge_canvas",
        canvas: {
          board_id: "board-1",
          board_name: "test1",
          scope_label: "Canvas",
        },
        attached: { cards: 2, relations: 1, documents: 1 },
        visibility: { planner: true, react: true, synthesis: true },
        stages: {
          synthesis: {
            max_chars: 9000,
            used_chars: 2410,
            cards_included: 2,
            relations_included: 1,
            card_summaries_compacted: 0,
            cards_dropped: 0,
            relations_dropped: 0,
            truncated: false,
          },
        },
        relation_trust: "organizational_context_not_factual_evidence",
      },
    }

    expect(runtimeKnowledgeContextObservability([event])).toEqual({
      status: "runtime_confirmed",
      binding: "knowledge_canvas",
      canvasName: "test1",
      cards: 2,
      relations: 1,
      documents: 1,
      visibility: {
        planner: true,
        react: true,
        synthesis: true,
      },
      synthesis: {
        maxChars: 9000,
        usedChars: 2410,
        cardsIncluded: 2,
        relationsIncluded: 1,
        cardSummariesCompacted: 0,
        cardsDropped: 0,
        relationsDropped: 0,
        truncated: false,
      },
      relationTrust: "organizational_context_not_factual_evidence",
    })
  })
})
