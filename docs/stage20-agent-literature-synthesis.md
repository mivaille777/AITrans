# Stage 20.1 — Agent-backed Literature Synthesis

Stage 20.1 turns the deterministic Stage 20 Evidence Review plan into a natural-language literature synthesis without weakening the evidence boundary.

## Runtime boundary

```text
Evidence Ledger
  -> live provenance revalidation
  -> human Review Gate
  -> deterministic synthesis plan
  -> validate allowed provenance IDs against live Research Memory
  -> build model context from review-gated Ledger statements only
  -> bounded grounded context
  -> LLM synthesis
  -> Claim–Evidence Verification
  -> release OR deterministic Stage 20 fallback
```

The model does **not** run RAG or decide which ledger entries are admissible. It receives only entries that already passed both the human review decision and the current machine provenance status.

A strict Stage 20.1 boundary also applies between the Evidence Ledger and Research Memory: Research Memory is consulted only to confirm that a ledger provenance link still exists, still points to the expected note, and still has a usable source status. The original Research Memory/RAG excerpt is **not** copied into the model-visible `AgentEvidenceItem.excerpt`. This prevents the model from introducing a fact that happened to be present in the same raw snippet but was never admitted through the Review Gate.

## Admission rules

- `accepted + supported` -> consensus context
- `accepted + contested` -> disagreement context
- `accepted + stale|insufficient` -> excluded
- `rejected|unreviewed|needs_review` -> excluded

Immediately before generation, every provenance link is resolved against live Stage 17 Research Memory and its source status is rechecked. This prevents a previously accepted claim from remaining usable after its source becomes stale.

## Grounding and fallback

Each allowed provenance link becomes an `AgentEvidenceItem`, but its citable text is the corresponding review-gated Evidence Ledger statement rather than the original RAG snippet. Stable note/document metadata remains attached for provenance and program-owned citation labels.

The existing `GroundedSynthesisService` then builds a bounded context and the existing `AgentClaimEvidenceVerifier` enforces citation coverage and lexical evidence support against those admitted ledger statements.

If the provider is unavailable, the context cannot be built, or verification fails, the generated text is not released. The API returns the deterministic Stage 20 synthesis instead and marks the result as `fallback`.

## API

`POST /api/research/workspaces/{workspace_id}/literature-synthesis/agent`

Request:

```json
{"query": "optional literature-review focus"}
```

The response includes generation status, provider/model, evidence/citation counts, verification metrics, fallback reason, and the deterministic synthesis plan used as the policy baseline.

## CI

`python scripts/run_agent_literature_synthesis_regression.py --report test-results/agent-literature-synthesis-regression.json`

The regression is deterministic and performs no live provider calls.
