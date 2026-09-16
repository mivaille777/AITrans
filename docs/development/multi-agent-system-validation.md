# Multi-Agent System Validation Baseline

> Stage: MA00 — production baseline, research scenarios, and evaluation set  
> Baseline branch: `WebReBuild`  
> Baseline commit: `ad27691d18b49a4e180c641d1a6a12773cbf1ddd`  
> MA00 implementation commit: `1464581a7f6a33427557746e67f8529e2135b612`  
> Recorded: 2026-09-16  
> Status: **verified** for MA00 scope; full repository CI remains red because of one pre-existing Knowledge V2 contract failure documented below.

## 1. Purpose and release boundary

This document freezes the production behavior that the staged multi-agent redesign must preserve or deliberately replace. MA00 does **not** implement the target Supervisor/task DAG, scoped Evidence Service, expert subgraphs, persistent multi-agent memory, bounded concurrency, Writer, or Curator. Passing characterization tests means only that the current behavior is reproducible.

The product goal remains a local-first research workspace. Multi-agent work is justified only when it improves a user task such as document understanding, cross-paper comparison, evidence-backed writing, or knowledge curation. Simple translation/polish remains a direct language capability.

## 2. Repository and entry-point audit

No repository `AGENTS.md` is present at the MA00 baseline. The implementation therefore follows existing repository conventions and the staged design/taskbook supplied for this work.

### 2.1 Canonical runtime path

The current production path is:

```text
Agent API / WebSocket
  -> backend/api/agent_dependencies.py:get_agent_runtime()
  -> AgentRuntime
  -> backend/agent_graph/reading_agent_graph.py:ReadingAgentGraph
     -> resolve_context
     -> run_collaboration
        -> backend/services/multi_agent_runtime_bridge.py
        -> MultiAgentWorkspaceService
        -> keyword AgentPlanner
        -> KnowledgeInjector
        -> serial AgentExecutor
     -> prepare_conversation
     -> route_request
     -> direct/ReAct execution
     -> final evidence/grounding/conversation handling
```

The mature `ReadingAgentGraph` remains the authority for final tool execution, evidence checks, answer generation, confirmation, and conversation completion. The Stage-5 multi-agent layer is an advisory pre-workflow.

### 2.2 Front-end contract

`apps/desktop/src/api/agent.ts` exposes the canonical `/api/agent/run/trace` request/response and the current fixed multi-agent trace event family (`multi_agent_started`, `multi_agent_plan_ready`, specialist start/complete/fail/skip, and `multi_agent_completed`). The current request already carries `workspace_id`, `knowledge_document_ids`, `research_source_ids`, and knowledge context, but the Stage-5 `KnowledgeInjector` does not consume that scope when calling its runtime.

## 3. Current production findings frozen by characterization tests

| ID | Current behavior at baseline | Characterization |
| --- | --- | --- |
| F01 | `AgentPlanner` selects roles by keywords and sends the exact same raw task to every selected role. | `test_characterization_f01_keyword_planner_sends_same_task_to_every_selected_role` |
| F03 | `KnowledgeInjector.inject()` calls `build_context(query, top_k=...)` only. Workspace/document scope stored in shared runtime metadata is not passed to the knowledge runtime. | `test_characterization_f03_scope_metadata_does_not_reach_knowledge_runtime` |
| F04 | `SharedAgentContext.intermediate_results` is keyed by `agent_name`; a second instance of the same role overwrites the first. | `test_characterization_f04_same_role_result_overwrites_previous_instance` |
| F07 | `MultiAgentRuntimeBridge.run_with_events()` waits for synchronous `service.run()` to return and only then forwards the collected events. | `test_characterization_f07_bridge_forwards_events_only_after_service_returns` |
| F09 | A default `AgentMemoryAdapter` owns a new `InMemoryAgentMemoryStore`; reconstructing the adapter loses prior values. The bridge also currently passes `session_id` as collaboration `user_id`. | `test_characterization_f09_default_memory_is_lost_when_adapter_is_reconstructed` |

These are intentionally current-behavior assertions. When MA01/MA02/MA06/M08 repairs a behavior, the relevant characterization must be replaced by the target contract in the same change. A passing characterization is never evidence that the target architecture is complete.

## 4. Knowledge, notes, graph, and evidence ownership

MA00 chooses the following ownership model for later Curator work. This prevents a fourth facts database from appearing.

| Data/operation | Current owner | MA00 decision for target architecture |
| --- | --- | --- |
| Canonical knowledge items, relations, collections, tags | `backend/knowledge/service.py:KnowledgeWorkspaceService` and `backend/knowledge/domain.py` | **Authoritative Curator write target** for knowledge items and confirmed relations. Reuse current item/relation validation. |
| Relation proposals/review | `backend/services/knowledge_relation_suggestion_service.py` | Reuse proposal lifecycle, but MA02/MA07 must supply an explicit scoped candidate-ID set before Agent use. AI proposals remain pending until the existing review/accept flow changes state. |
| Research notes | `backend/services/research_note_service.py` | Remain authoritative for research-note body/source fields. Curator must not copy a second editable note body into canonical knowledge. |
| Canonical note/item association | currently not a single explicit durable mapping contract | MA07 must create/reuse one stable association key. Preferred rule: canonical NOTE item references `research_note_id` in metadata; if reverse lookup is required, add a dedicated mapping/index rather than duplicate note text. Verify repository constraints before migration. |
| Knowledge V2 card/graph service | `backend/knowledge/v2_service.py` | Compatibility/projection path, not a new Curator source of truth unless a later audit proves an existing canonical delegation. |
| Legacy graph snapshot | `backend/services/knowledge_graph_repository.py` | Compatibility/read projection only; do not use whole-snapshot injection as scoped evidence. |
| Stage20 evidence review + literature synthesis | review service + `backend/services/agent_literature_synthesis_service.py` | Remains authoritative gate for formal literature synthesis/Related Work. Accepted reviewed statements may be synthesized; raw Research Memory excerpts cannot silently bypass review. |
| Research Memory freshness/source state | existing Research Memory services | Reuse for source existence/fresh/stale/detached checks. It is not a replacement for the review ledger. |

### 4.1 Curator note/item rule to carry into MA07

A research note remains one editable note object. A canonical `KnowledgeItem(type=note)` may point to it for graph participation, but must not become an independently editable duplicate body. The stable association key must be unique within the owning workspace. Deletes/revocations must invalidate the association and derived artifact citations.

The exact persistence mechanism is deliberately deferred to MA07 because MA00 is baseline-only; MA07 must first inspect the active repository schema/migrations and then add the smallest durable mapping compatible with existing UIs.

## 5. Evidence and review boundary

`AgentLiteratureSynthesisService` enforces an important existing boundary: it builds synthesis evidence from review-gated ledger statements, resolves Research Memory only to confirm provenance/freshness, and deliberately does not expose raw memory excerpts to the model as substitute facts. The new Research Synthesizer and Academic Writer must preserve this boundary for formal literature-review output.

General document Q&A may use scoped original-document evidence. Formal review-gated synthesis may use only accepted/usable reviewed evidence. User-supplied experiments are a separate source category and must never be represented as published literature.

## 6. Isolated MA evaluation assets

`tests/multi_agent/conftest.py` provides a disposable per-test data root, explicit disposable SQLite/artifact and Qdrant paths, a fake clock, deterministic provider/tool doubles with call accounting, and default external-network blocking for `tests/multi_agent`.

`tests/multi_agent/fixtures/research_workspace.json` contains synthetic, non-user data for papers A/B on different datasets/splits, table/footnote/unit data, a degraded image fixture, a partial document, contradictory evidence, same-name concepts in different workspaces, same-source notes in different scopes, a manuscript with stable paragraph IDs, and user-supplied experiment data with a deliberately missing field.

No MA test may point at the user's normal data root. Real provider tests must be separately and explicitly enabled; deterministic tests must not silently fall through to a remote model.

## 7. Fixed development and held-out evaluation set

The canonical case schema is `tests/multi_agent/evaluation_schema.json`; the frozen case list is `tests/multi_agent/evaluation_cases.json` and covers T01-T36. Each case fixes its `dev`/`heldout` split, owning stage, fixture references, hard assertions, and scoring dimensions.

For reading/comparison quality, score completion, source support, scope/coverage declaration, and numeric/unit correctness separately. Record model/tool attempts, token usage when available (`unknown` otherwise), retrieval duplication, cold/warm latency, cancellation timing, and degraded/failure reason codes separately.

Scope, fabricated experiments/references, note preservation, revocation, idempotent writes, and temporary-mode persistence are binary release gates and cannot be averaged away by a quality score.

## 8. Baseline tests and reproducibility

Historical targeted baseline recorded before this MA00 change:

```powershell
conda run -n aitrans python -m pytest tests/agent/test_multi_agent_stage5_6.py tests/agent/test_multi_agent_stage5_7.py tests/agent/test_multi_agent_stage5_8.py tests/agent/test_multi_agent_stage5_9.py tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_trace_event_contract.py -q
# recorded result: 92 passed

conda run -n aitrans python -m pytest tests/agent/test_writing_tool_boundary.py tests/test_knowledge_relation_suggestions_stage15.py tests/api/test_knowledge_relation_suggestions_api_stage15.py tests/research/test_agent_literature_synthesis_review_gate_boundary.py -q
# recorded result: 10 passed
```

### 8.1 Full-CI comparison around MA00

Pre-MA00 CI run `34973222564` on baseline commit `ad27691d...`:

- Python: **1 failed, 1064 passed, 2 skipped**.
- Existing failure: `tests/api/test_knowledge_v2_api_contract.py::test_knowledge_v2_routes_are_registered_on_application` because an `_IncludedRouter` entry in `app.routes` has no `.path` attribute.
- React lint/test/build: passed.
- Tauri shell build: passed.

MA00 CI run `35060705843` on implementation commit `1464581a...`:

- Python: **1 failed, 1069 passed, 2 skipped**.
- The only failure is the exact same pre-existing Knowledge V2 API-contract failure above.
- The +5 passing tests are the five new MA00 characterization contracts; no new Python failure was introduced.
- React lint/test/build: passed.
- GPU Qwen3 embedding/reranker integration tests were skipped by the existing opt-in policy.
- Tauri job was still running when this MA00 verification record was finalized; MA00 changed no Rust/frontend/production runtime code, and the pre-MA00 Tauri baseline was green.

The repository-level CI conclusion is therefore red for a known pre-existing failure, but MA00 itself is verified as **no-new-regression** in its changed Python/test surface. The Knowledge V2 test defect is not relabeled as a multi-agent defect and must be handled separately rather than hidden or deleted.

## 9. MA00 implementation record — 2026-09-16

- Status: `verified` (MA00 scope; known unrelated full-CI failure retained).
- Starting HEAD: `ad27691d18b49a4e180c641d1a6a12773cbf1ddd`.
- Implementation commit: `1464581a7f6a33427557746e67f8529e2135b612`.
- Production code changes: none.
- Added: validation record, isolated MA test harness, five characterization contracts, synthetic research fixture, fixed evaluation schema/cases.
- Shared-memory dependency: none; current in-memory loss is characterized only.
- Data/checkpoint migration: none.
- Real paid/remote model quality run: not executed and not claimed.
- Known limitation: this stage intentionally does not repair F01/F03/F04/F07/F09.
- Next stage: MA01 typed tasks/artifacts/roles/state contracts; MA02 then closes the P0 scope/evidence gap before new expert behavior is enabled.

## 10. MA01 contract verification — 2026-09-16

MA01 is implemented by commits `17f959d` through `7fca71c`. It adds typed task,
scope, result, evidence-reference, and research-artifact contracts; a validated role/tool
registry; an acyclic task-plan validator; an attempt-aware task state machine; a
deterministic result reducer; injectable orchestration ports; and versioned SQLite/in-memory
artifact stores with conflict detection and revocation.

Local verification after synchronizing `origin/WebReBuild`:

```powershell
conda run -n aitrans python -m pytest tests/multi_agent -q
# 32 passed

conda run -n aitrans python -m pytest tests/agent/test_multi_agent_stage5_6.py tests/agent/test_multi_agent_stage5_7.py tests/agent/test_multi_agent_stage5_8.py tests/agent/test_multi_agent_stage5_9.py tests/agent/test_agent_checkpoint_persistence.py tests/agent/test_agent_trace_event_contract.py -q
# 92 passed

conda run -n aitrans python -m pytest tests/agent/test_writing_tool_boundary.py tests/test_knowledge_relation_suggestions_stage15.py tests/api/test_knowledge_relation_suggestions_api_stage15.py tests/research/test_agent_literature_synthesis_review_gate_boundary.py -q
# 10 passed
```

This verifies MA01's isolated contracts and compatibility baseline. It does not claim that
the new contracts are already wired into the production root graph; that begins in MA03,
after MA02 closes the scope/evidence boundary.

## 11. MA02 scoped evidence verification — 2026-09-16

Implementation commit: `196a2e127b29d620db73716ee63e5a490b2b6c8b`.

MA02 introduces a server-owned resolver for Research Workspace, Knowledge Board,
Knowledge Collection, explicit-selection, and product-global scopes. `ScopeContext`
now differentiates `unscoped_global` from `restricted`, so an empty restricted
workspace is a hard empty result rather than a fallback to all local data.

The new `ScopedEvidenceService` reuses the existing RAG, Research Note, Knowledge
Workspace, Research Memory reliability, Stage20 Review Gate, and citation services.
It emits typed packets containing source/version/status and page/chunk/element/table/image
locators. Cache keys bind scope revision, source versions, query/filters, and model
version. Knowledge graph relations can annotate an in-scope lexical hit but cannot
create evidence from graph degree alone. Relation-suggestion candidates can also be
bound to the authoritative item set.

F03 is no longer only characterized: scoped calls either use typed scoped evidence or
disable the scope-blind legacy graph path. The production root graph does not yet issue
the new authoritative scope on every request; MA03 owns that integration boundary.

Local verification:

```text
tests/multi_agent                                      47 passed
existing multi-agent/checkpoint/trace baseline         92 passed
writing/relation-suggestion/review-gate boundary        10 passed
Research Workspace/Memory/Evidence Review regression   60 passed
Knowledge Workspace/Board/RAG regression               53 passed
changed-file Ruff and Python compileall                 passed
```

No remote model, GPU model, or UI quality run was performed for MA02. No production
database migration was required.

## 12. MA03 serial root orchestration verification — 2026-09-16

Implementation commit: `decaa74f8eb2f6164fd6f65a2c1cf4febe10696b`.

The production ReadingAgentGraph now acquires durable conversation ownership before
specialist execution. Its collaboration bridge can run the new validated orchestration
service, which freezes one stable profile, authoritative ScopeContext, and MemoryPort
snapshot for a run. It stores typed task-plan/results on AgentState and keeps
`planned_action` only as a legacy projection. Specialist context is structured and no
longer appended to the unrelated reading `context_before` field.

Routing has three deterministic lanes: bounded translation/polish and ordinary canonical
requests remain `fast`; one paper-analysis request becomes `single`; genuine cross-paper,
writing, or curation work becomes `workflow`. `force` invokes the same router and does not
expand scope or turn a fast translation into fake collaboration. Missing comparison inputs
are reported explicitly. Provider-generated plans get one repair attempt and must pass the
MA01 validator against the server-issued scope and role/tool registry.

The first execution path is deliberately serial. Results are reduced by task ID, so two
Document instances remain distinct. A specialist/tool may mark a complete bounded output
for direct delivery, in which case the root graph skips a second ProductAgent generation.
Legacy Document/Research adapters are marked partial until MA04 replaces them; unavailable
Writer/Curator roles are blocked rather than fabricated.

Checkpoint compatibility now records graph version `reading-agent-ma03-v1` and state schema
v2. Pre-versioned state is migrated with a legacy marker. Unknown graph versions, future
schemas, and unknown pending node names are rejected explicitly while the existing SQLite
checkpoint database remains intact.

Verification:

```text
tests/multi_agent                                      63 passed
ReadingGraph/checkpoint/legacy collaboration           19 passed
Agent API/runtime/observability                         28 passed
full Python suite                       1126 passed, 2 skipped, 1 failed
changed-file Ruff and Python compileall                 passed
```

The sole full-suite failure remains the pre-existing Knowledge V2 route-contract test
(`_IncludedRouter` has no `.path`), identical to the MA00 baseline. An initially detected
Qdrant lock regression was fixed by lazy-loading RAG only on the first actual evidence
retrieval; the failing HTTP confirmation test then passed and the full suite returned to
the single known failure.

## 13. MA04 paper analysis and research synthesis verification — 2026-09-16

Implementation commit: `43d7a17`.

The production orchestration registry now executes real LangGraph Document Analyst and
Research Synthesizer subgraphs instead of the MA03 legacy previews. Each deterministic
document plan is bound to explicit server-authorized source IDs. Document retrieval is
limited to three scoped queries and records requested, visited, and unavailable documents,
sections, pages, chunks, tables, images, and source versions. A provider cannot promote a
prefix/top-k result to full-document coverage without a source-level coverage attestation.

Reading cards expose research question, contribution, method, dataset, experiment,
limitation, and open-question fields. Missing values remain unknown. Table/image evidence
preserves page/element locators, units, footnotes, and visual availability; unavailable OCR
or image capability produces an explicit partial result rather than an invented reading.

Research synthesis consumes immutable DocumentAnalysisArtifact references and performs no
additional retrieval. It rejects missing, wrong-type, hash-mismatched, or out-of-scope
inputs, builds a complete document-by-dimension matrix, keeps experiment conditions next
to values, and propagates partial input coverage. Formal Related Work/literature-review
requests still require accepted Stage20 review evidence. Authorized memory hypotheses are
bounded, separately typed, and never inserted into document-fact cells.

Both subgraphs persist typed artifacts with VerificationReport and may directly deliver a
leaf result. The serial executor refuses direct delivery from an intermediate task when a
downstream leaf remains, preventing a Research result from bypassing a requested Writer.
No artifact-store, checkpoint, AgentState, or event-schema migration was required.

Verification:

```text
MA04 focused expert/coverage/visual/verification tests   12 passed
tests/multi_agent                                        77 passed
Agent/ReadingGraph/checkpoint/trace regression          118 passed
Research/Knowledge/RAG regression                       452 passed, 2 skipped
full Python suite                                      1142 passed, 2 skipped
changed-file Ruff and Python compileall                  passed
```

The two skipped tests are the existing opt-in real Qwen3 embedding and reranker GPU
integrations. No paid/remote model or UI quality run was performed. Unlike the MA03 run,
the previously recorded Knowledge V2 route-contract test passed in this current full-suite
run; no production code was changed solely to conceal or delete that historical failure.
