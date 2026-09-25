# Stage 1 Report

## 1. Git

- branch: `WebReBuild`
- baseline implementation commit: `1d09c6b177cacbcb4a941605ff64e2f3df48b11e`
- stage commit: recorded by Git history for this report

## 2. Baseline

- baseline profile: `rag-improvement-baseline-v1`
- baseline rerank behavior: `rerank_candidate_k=None` -> effective `final_top_k=8`
- known repository CI baseline: four pre-existing failures in `tests/agent/test_grounded_synthesis_partial_verification.py`; the same four failures were present on parent SHA `75d41ace90e41af5aa000dd321f55341ef5d9553`.

## 3. Candidate

- B profile: `rag-stage1-rerank12-v1.json`
- C profile: `rag-stage1-rerank20-v1.json`
- target behavior: RRF Top20 -> rerank Top12/20 -> final Top8
- product default remains unchanged until the experimental Gate passes.

## 4. Only Variable Changed

Stage 1 adds an explicit reranker candidate-pool boundary. Dense, sparse, fusion, final TopK, embedding model, reranker model, answer path, parser, chunker, and small-to-big behavior are otherwise unchanged.

## 5. Unit Tests

Coverage added for:

- an RRF rank-12 gold candidate rescued to rank 1 when `rerank_candidate_k=20`
- explicit rerank pool size 12 with final Top8
- final TopK stability
- reranker failure restoring the full RRF order
- invalid `final_top_k > rerank_candidate_k`
- invalid `rerank_candidate_k > fusion_top_k`
- structural section-hint path reranking the full fused pool without duplicates
- trace input/output candidate counts and chunk IDs without full text

## 6. Retrieval Metrics

Pending real retrieval-only A/B/C ablation on the frozen Smoke28 and Dev100 samples.

## 7. Evidence Metrics

Pending real Smoke28 / Dev100 runs.

## 8. Answer Metrics

Pending real answer runs.

## 9. Runtime Metrics

The implementation records `fusion_candidate_count`, `rerank_candidate_count`, `final_candidate_count`, `rerank_input_chunk_ids`, `post_rerank_chunk_ids`, and rerank latency. Real p50/p95 comparison is pending.

## 10. Paired Bootstrap

Pending real Dev100 candidate runs; required settings remain 5000 resamples, seed 42.

## 11. Challenge Cases

Pending real runs. The required manual review should include at least three cases where a candidate below rank 8 is rescued by reranking.

## 12. Regressions

The Stage 0 push CI reproduced the exact pre-existing four grounded-synthesis test failures from the previous commit and introduced no new failing test class. Stage 1 push CI must be compared against that known baseline.

## 13. Gate

**PENDING / NO-GO for default promotion and Stage 2.**

The code path is feature-configurable and preserves the existing effective rerank Top8 when `rerank_candidate_k` is omitted. The taskbook quality Gate still requires real Recall/MRR/Evidence/Answer and p95 measurements.

## 14. Decision

Keep `rerank_candidate_k` unset in the product/default config. Use the explicit 12/20 profiles only for controlled QASPER ablation. Do not start Stage 2 until the Stage 1 experimental Gate is closed.
