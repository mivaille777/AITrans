# AITrans Knowledge System

## Goal

The Knowledge System transforms documents and interactions into reusable personal knowledge.

## Core Objects

```text
Document
   |
Knowledge Card
   |
Knowledge Relation
   |
Knowledge Graph
   |
Agent Context
```

## Knowledge Workspace

Main capabilities:

- Document ingestion
- Knowledge extraction
- Card management
- Relation visualization
- Agent-assisted refinement
- Retrieval and reuse

## Agent Integration

Knowledge is not only stored data. It is the context foundation for Agents.

```text
Knowledge Retrieval
        |
Context Builder
        |
Agent Reasoning
        |
Knowledge Update
```

## Future Direction

The system will evolve toward a Personal Research Knowledge Base powered by multimodal RAG and multi-agent collaboration.

## Companion Capability Routing and Grounding Contract

Companion chat treats Knowledge as an available capability, not as a command to run RAG on every turn. The deterministic router resolves the request before expensive retrieval or generation work begins.

| Route | Typical intent | Retrieval | Grounding policy | Verifier |
| --- | --- | --- | --- | --- |
| `system_identity` | "who are you / what can you do" | skipped | `none` | skipped |
| `general` | general conversation | skipped | `none` | skipped |
| `knowledge_catalog` | list imported/indexed documents | manifest only | `manifest` | skipped |
| `reading_context` | explain/summarize attached reading context | skipped by default | `none` | skipped |
| `document_scoped_search` | ask about selected/local document(s) | enabled | `evidence` | required |
| `knowledge_search` | semantic question across the local library | enabled | `evidence` | required |

Knowledge scope semantics are explicit:

- `knowledge_enabled = false` means Knowledge is unavailable.
- `knowledge_enabled = true` with `knowledge_document_ids = []` means **All documents**.
- `knowledge_enabled = true` with non-empty IDs means retrieval is restricted to those selected documents.

The HTTP and WebSocket paths share `CompanionChatService.prepare_execution()`. Streaming exposes `routing`, `retrieving`, `generating`, and `verifying` phases when applicable. Evidence verification only runs for `GroundingPolicy.EVIDENCE`; identity, general chat, and catalog answers must not be rewritten by the evidence verifier.

RAG Debug Studio records recent production Companion traces including route, route reason, Knowledge/document scope, grounding policy, retrieval latency/counts/selected chunks, evidence/citations, verifier result/reason codes, and whether a fallback replaced the generated answer.
