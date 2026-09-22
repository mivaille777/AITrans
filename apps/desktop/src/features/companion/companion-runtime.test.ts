import { describe, expect, it } from "vitest"

import type { CompanionHandoff, ConversationMessage } from "../../api/types"
import {
  buildCompanionChatRequest,
  companionHandoffRuntimeSeed,
  companionHistory,
  restoreCompanionMessages,
  type CompanionRuntimeMessage,
} from "./companion-runtime"

function message(
  id: string,
  role: "user" | "assistant",
  content: string,
  status: CompanionRuntimeMessage["status"] = "complete",
): CompanionRuntimeMessage {
  return { id, role, content, status }
}

describe("companion runtime", () => {
  it("keeps only complete recent messages in model history", () => {
    const messages = [
      ...Array.from({ length: 18 }, (_, index) =>
        message(`m-${index}`, index % 2 === 0 ? "user" : "assistant", `message ${index}`),
      ),
      message("streaming", "assistant", "partial", "streaming"),
    ]

    const history = companionHistory(messages)

    expect(history).toHaveLength(16)
    expect(history[0]?.content).toBe("message 2")
    expect(history.at(-1)?.content).toBe("message 17")
  })

  it("restores persisted knowledge evidence and citations with assistant messages", () => {
    const persisted = {
      message_id: "assistant-1",
      conversation_id: "conversation-1",
      request_id: 7,
      role: "assistant",
      content: "Grounded answer [1]",
      status: "complete",
      provider: "stub",
      model: "stub-model",
      error_code: "",
      created_at: "2026-08-24T00:00:00Z",
      updated_at: "2026-08-24T00:00:01Z",
      knowledge_enabled: true,
      knowledge_fallback_reason: "",
      evidence: [{
        evidence_id: "evidence-1",
        source_type: "knowledge",
        source_id: "doc-1",
        title: "Paper",
        resource_url: "file:///paper.pdf",
        location: "Page 8",
        excerpt: "Evidence",
        score: 0.9,
        metadata: {},
      }],
      citations: [{ citation_id: "citation-1", evidence_ids: ["evidence-1"], label: "[1]" }],
    } as ConversationMessage

    const restored = restoreCompanionMessages([persisted])[0]

    expect(restored?.knowledgeEnabled).toBe(true)
    expect(restored?.evidence?.[0]?.evidence_id).toBe("evidence-1")
    expect(restored?.citations?.[0]?.label).toBe("[1]")
  })

  it("preserves Knowledge On with an empty document list as All documents", () => {
    const handoff = {
      revision: 4,
      handoff_id: "handoff-all-documents",
      created_at: "2026-09-21T00:00:00Z",
      source_text: "selected source",
      translated_text: "",
      source_language: "en",
      target_language: "zh-CN",
      resource_url: "",
      resource_title: "",
      section_heading: "",
      context_before: "",
      context_after: "",
      source_kind: "knowledge",
      conversation_id: "",
      ai_content: "",
      ai_action: "",
      suggested_prompt: "",
      knowledge_enabled: true,
      knowledge_document_ids: [],
    } as CompanionHandoff & {
      knowledge_enabled: boolean
      knowledge_document_ids: string[]
    }

    const seed = companionHandoffRuntimeSeed(handoff)

    expect(seed.knowledgeEnabled).toBe(true)
    expect(seed.knowledgeDocumentIds).toEqual([])
  })

  it("builds the same reading-grounded request contract for every surface", () => {
    const request = buildCompanionChatRequest({
      conversationId: "conversation-1",
      sessionId: "session-1",
      userMessage: "  explain this  ",
      contextMode: "reading",
      context: {
        source_text: "source",
        translated_text: "translation",
        source_language: "en",
        target_language: "zh-CN",
        resource_url: "file:///paper.pdf",
        resource_title: "Paper",
        section_heading: "3.4",
        context_before: "before",
        context_after: "after",
        source_kind: "pdf",
      },
      messages: [message("u1", "user", "previous question")],
      requestId: 7,
      knowledgeEnabled: true,
      knowledgeDocumentIds: ["doc-1", "doc-2"],
    })

    expect(request).toMatchObject({
      conversation_id: "conversation-1",
      session_id: "session-1",
      user_message: "explain this",
      context_mode: "reading",
      source_text: "source",
      translated_text: "translation",
      resource_title: "Paper",
      section_heading: "3.4",
      request_id: 7,
      knowledge_enabled: true,
      knowledge_document_ids: ["doc-1", "doc-2"],
    })
    expect(request.history).toEqual([
      { role: "user", content: "previous question" },
    ])
  })

  it("serializes Auto as policy while preserving the selected scope boundary", () => {
    const request = buildCompanionChatRequest({
      sessionId: "session-auto",
      userMessage: "Compare these papers",
      contextMode: "general",
      messages: [],
      requestId: 8,
      knowledgeAccessPolicy: "auto",
      knowledgeDocumentIds: ["doc-a", "doc-b"],
    })

    expect(request.knowledge_access_policy).toBe("auto")
    expect(request.knowledge_enabled).toBe(false)
    expect(request.knowledge_document_ids).toEqual(["doc-a", "doc-b"])
  })

  it("creates a stable reading runtime seed and restores bounded knowledge scope", () => {
    const handoff = {
      revision: 3,
      handoff_id: "handoff-3",
      created_at: "2026-08-21T12:00:00Z",
      source_text: "selected source",
      translated_text: "selected translation",
      source_language: "en",
      target_language: "zh-CN",
      resource_url: "knowledge-item://evidence-1",
      resource_title: "Paper evidence",
      section_heading: "4.1",
      context_before: "before",
      context_after: "after",
      source_kind: "knowledge_evidence",
      conversation_id: "",
      ai_content: "existing explanation",
      ai_action: "knowledge_context",
      suggested_prompt: "continue from this context",
      knowledge_enabled: true,
      knowledge_document_ids: ["doc-1", "doc-1", " doc-2 "],
    } as CompanionHandoff & {
      knowledge_enabled: boolean
      knowledge_document_ids: string[]
    }

    const seed = companionHandoffRuntimeSeed(handoff)

    expect(seed).toMatchObject({
      contextMode: "reading",
      draft: "continue from this context",
      sessionId: "companion-handoff-3",
      scopeId: "handoff:handoff-3",
      knowledgeEnabled: true,
      knowledgeDocumentIds: ["doc-1", "doc-2"],
    })
    expect(seed.context).toMatchObject({
      source_text: "selected source",
      translated_text: "selected translation",
      ai_content: "existing explanation",
      ai_action: "knowledge_context",
    })
  })
})
