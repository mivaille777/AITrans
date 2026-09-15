import { describe, expect, it } from "vitest"

import { buildAgentRunRequest } from "./agent-run-request"

const context = {
  resource_url: "https://example.com/paper",
  resource_title: "Control Paper",
  section_heading: "Methods",
  context_before: "before",
  context_after: "after",
  source_kind: "browser_dom",
}

describe("Agent run request", () => {
  it("builds the main-surface request from runtime-owned state", () => {
    const request = buildAgentRunRequest({
      context,
      sessionId: "agent-session-1",
      traceId: "trace-1",
      requestId: 4,
      userMessage: "Explain this paragraph",
      sourceText: "source",
      translatedText: "translated",
      sourceLanguage: "en",
      targetLanguage: "zh-CN",
      conversationId: "conversation-1",
    })

    expect(request).toMatchObject({
      ...context,
      session_id: "agent-session-1",
      client_id: "agent-session-1",
      client_surface: "main",
      context_mode: "general",
      trace_id: "trace-1",
      request_id: 4,
      style: "academic",
      conversation_id: "conversation-1",
      workspace_id: "",
      confirmed_write_tools: [],
      knowledge_context: null,
    })
  })

  it("carries an explicit knowledge context mode without a reading source", () => {
    const request = buildAgentRunRequest({
      context: {
        resource_url: "",
        resource_title: "",
        section_heading: "",
        context_before: "",
        context_after: "",
        source_kind: "desktop",
      },
      contextMode: "knowledge",
      sessionId: "agent-session-knowledge",
      traceId: "trace-knowledge",
      requestId: 5,
      userMessage: "Analyze the knowledge base",
      sourceText: "",
      translatedText: "",
      sourceLanguage: "auto",
      targetLanguage: "zh-CN",
      conversationId: "",
    })

    expect(request.context_mode).toBe("knowledge")
    expect(request.source_text).toBe("")
    expect(request.resource_title).toBe("")
  })

  it("carries Canvas cards and relations independently of context mode or source text", () => {
    const request = buildAgentRunRequest({
      context: {
        resource_url: "",
        resource_title: "",
        section_heading: "",
        context_before: "",
        context_after: "",
        source_kind: "knowledge_document",
      },
      contextMode: "general",
      sessionId: "agent-session-canvas",
      traceId: "trace-canvas",
      requestId: 6,
      userMessage: "List every explicit Canvas relation in context",
      sourceText: "",
      translatedText: "",
      sourceLanguage: "auto",
      targetLanguage: "zh-CN",
      conversationId: "",
      knowledgeContext: {
        canvas: { board_id: "board-1", board_name: "test1", scope_label: "Canvas" },
        cards: [
          { item_id: "a", item_type: "insight", title: "A", summary: "A summary", document_id: "doc-1" },
          { item_id: "b", item_type: "evidence", title: "B", summary: "B summary", document_id: "doc-1" },
        ],
        relations: [
          {
            relation_id: "r1",
            source_item_id: "a",
            source_title: "A",
            target_item_id: "b",
            target_title: "B",
            relation_type: "supports",
            label: "manual edge",
            origin: "manual",
            confidence: null,
          },
        ],
      },
    })

    expect(request.context_mode).toBe("general")
    expect(request.source_text).toBe("")
    expect(request.knowledge_context?.canvas?.board_name).toBe("test1")
    expect(request.knowledge_context?.cards).toHaveLength(2)
    expect(request.knowledge_context?.relations[0]).toMatchObject({
      relation_id: "r1",
      relation_type: "supports",
      origin: "manual",
      label: "manual edge",
    })
  })

  it("carries only the explicitly confirmed write tool into a retry", () => {
    const request = buildAgentRunRequest({
      context,
      sessionId: "agent-session-1",
      traceId: "trace-2",
      requestId: 7,
      userMessage: "Save this note",
      sourceText: "source",
      translatedText: "",
      sourceLanguage: "en",
      targetLanguage: "zh-CN",
      conversationId: "conversation-1",
      confirmedWriteTools: ["save_research_note"],
    })

    expect(request.confirmed_write_tools).toEqual(["save_research_note"])
  })

  it("carries the active Research Workspace separately from temporary scopes", () => {
    const request = buildAgentRunRequest({
      context,
      sessionId: "agent-session-1",
      traceId: "trace-stage16",
      requestId: 8,
      userMessage: "Compare my project evidence",
      sourceText: "source",
      translatedText: "",
      sourceLanguage: "en",
      targetLanguage: "zh-CN",
      conversationId: "conversation-1",
      workspaceId: "workspace-16",
      knowledgeDocumentIds: ["temporary-doc"],
      researchSourceIds: ["temporary-source"],
    })

    expect(request.workspace_id).toBe("workspace-16")
    expect(request.knowledge_document_ids).toEqual(["temporary-doc"])
    expect(request.research_source_ids).toEqual(["temporary-source"])
  })
})
