# Research Workspaces (Stage 16)

Stage 16 changes AITrans from a conversation-centric research assistant into a research-project-centric product without replacing the existing Knowledge Library, Research Notes, Conversation store, or Agent Runtime.

## 1. Core model

A Research Workspace owns project metadata and stable links to resources that remain in their original stores:

```text
ResearchWorkspace
├── workspace_id
├── name
├── description
├── research_goal
├── document_ids[]
├── note_ids[]
└── conversation_ids[]
```

The Workspace does **not** copy document bytes, Research Note text, or Conversation messages. Deleting a Workspace removes only project metadata and membership relationships; the underlying resources remain available.

## 2. Storage boundary

`app/research/workspaces.py` owns a separate SQLite database with:

```text
research_workspaces
workspace_documents
workspace_notes
workspace_conversations
```

This avoids a destructive schema migration of the existing Research Note and Knowledge stores and keeps Stage 16 backward compatible with existing local data.

`ResearchWorkspaceService` is the application boundary for CRUD, membership changes, and trusted scope resolution.

## 3. Product flow

```text
Create / select Research Project
        ↓
Attach indexed documents and saved notes
        ↓
Run Agent with workspace_id
        ↓
Backend resolves persisted Workspace membership
        ↓
Knowledge retrieval is constrained to Workspace documents
Research-memory retrieval is constrained to sources represented by Workspace notes
        ↓
Agent runs through the existing Runtime / ReAct / Tool / RAG path
        ↓
Successful Conversation and newly saved Research Note are associated back to Workspace
```

The current Workspace is shared by the desktop Research and Agent surfaces through the existing translation/reading workspace controller.

## 4. Trusted Agent context

`workspace_id` is an optional field on `AgentRunRequest`.

When it is empty, the existing Stage 13 temporary/global retrieval behavior is preserved.

When it is present, the backend treats persisted Workspace membership as authoritative:

```text
client temporary document scope ─┐
                                 ├─ ignored when Workspace is active
client temporary research scope ─┘

Workspace.document_ids
        → knowledge_document_ids

Workspace.note_ids
        → load persisted notes
        → derive represented research source ids
        → research_source_ids
```

A missing Workspace is rejected instead of silently falling back to global retrieval. This prevents a stale or forged Workspace id from widening the Agent's evidence scope.

The LLM planner cannot create or modify Workspace membership and cannot supply the runtime-only workspace context through Tool arguments.

## 5. Research-memory precision

Stage 16 stores exact Research Note membership. `ResearchNoteService.search()` already supports a trusted `note_ids` filter for deterministic internal use.

The production Agent integration intentionally reuses the existing Stage 13 `research_source_ids` execution boundary, so an active Workspace currently constrains Agent research-memory retrieval to the **sources represented by its member notes**, rather than claiming exact note-level Agent retrieval.

Stage 17 (Research Memory 2.0) is the planned place to promote this into semantic entity / claim / evidence-level Workspace memory and exact memory retrieval.

## 6. Automatic association

After a successful Workspace-bound Agent run, the backend associates:

- the resulting Conversation id;
- a `save_research_note` Tool result's note id, when present.

The desktop also performs an idempotent post-run association as a UI-side compensation path. Membership tables use unique `(workspace_id, resource_id)` keys, so repeated attachment is safe.

## 7. Resource preservation

Workspace deletion never calls the Knowledge document store, Research Note delete path, or Conversation delete path.

API deletion returns:

```json
{
  "deleted": true,
  "workspace_id": "...",
  "resources_preserved": true
}
```

This property is covered by Stage 16 tests using independent Workspace and Research Note SQLite databases.

## 8. Desktop behavior

The Research route contains:

```text
Research Project selector / creator
        ↓
Trusted Research Scope editor
        ↓
Existing Research Workspace / memory view
```

With no active project, the old temporary scope remains available. With an active project, document and note checkboxes modify persistent Workspace membership.

## 9. Stage 16 verification

Focused backend tests cover:

- Workspace CRUD and idempotent membership;
- document / note / conversation attach-detach;
- note and conversation auto-association;
- Workspace deletion preserving Research Note data;
- exact internal note-id search filtering;
- Workspace scope overriding client temporary scope;
- missing Workspace rejection;
- successful Agent result association.

Frontend tests cover carrying `workspace_id` independently of temporary retrieval ids in the Agent request contract.

The complete CI must still pass the existing Stage 14 deterministic Agent benchmark, Stage 15 qualitative-protocol replay, React tests/build, legacy smoke test, and Tauri shell build.
