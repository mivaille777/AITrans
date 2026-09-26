# Stage 2 Report: Search / Read Separation

## 1. Git

- Branch: `WebReBuild`
- Baseline implementation commit: `f508530e5f49b3266eb53ea3e899792111ffe77a`
- Stage 2 changes are local and uncommitted.
- Remote tracking branch was up to date before these local changes.

## 2. Scope

Implemented the Search/Read split behind `RagConfig.jit_search_read_enabled`, which defaults to `false`:

- Search returns bounded, whitespace-normalized snippets (up to 320 characters) and does not create evidence or citations when JIT mode is enabled.
- `read_knowledge_chunk` and `read_knowledge_section` return source text and are the only JIT knowledge tools that create evidence and citations.
- Read access repeats the document-scope check; section reads are constrained to the anchor's document and section path.
- Search and Read have separate counters and budgets; the default maximum is six reads.
- Repeated Read evidence is deduplicated. Trace events retain aggregate candidate and output-character counts without retaining tool output text.
- The ReAct policy explains that Search snippets are navigation hints and that selected evidence must be read.
- With JIT disabled, the legacy Search payload and evidence behavior remain active.

## 3. Deterministic Validation

- Focused Search/Read, Agent E2E, runtime adapter, and routing tests: **26 passed**.
- Agent fixture: **1 Search**, **4 relevant Reads**, **8 noise candidates skipped**, and **4 final evidence items**.
- Scope-bypass, bounded section-read, Search-without-evidence, duplicate-read, separate budget, and trace-content-boundary tests are included in the Agent suite.
- Full `tests/agent`: **531 passed, 4 failed**. The four failures are the pre-existing failures in `tests/agent/test_grounded_synthesis_partial_verification.py`, also documented against earlier baseline commits; no Stage 2 test failed.
- RAG and QASPER debug regressions: **379 passed, 2 skipped**. The skipped tests require `AITRANS_RUN_RAG_GPU_TESTS=1` to load the real embedding and reranker models.
- `git diff --check`: clean.

## 4. Search Output Budget

A local Qwen tokenizer comparison on a synthetic fixture of 12 candidates, each approximately 6,000 characters, measured:

| Search result | Characters | Qwen tokens |
|---|---:|---:|
| Full candidate text | 72,183 | 9,678 |
| Bounded snippets | 4,023 | 582 |

This is a **93.99% token reduction** for the synthetic Search payload. It meets the 60% target in the fixture. Provider-reported token usage and live Agent-runtime averages are not yet available, so this does not establish the production runtime reduction.

## 5. QASPER Compatibility

QASPER uses the direct RAG benchmark route and does not exercise Agent Search/Read. These runs are compatibility checks only.

| Run | Audit | Answer F1 | Evidence F1 | Paired result |
|---|---|---:|---:|---|
| Smoke28 baseline `stage1v2-smoke28-baseline-answer-20260925` | 28/28, 0 errors | 0.22049 | 0.10528 | — |
| Smoke28 candidate `stage2-smoke28-compat-20260926` | 28/28, 0 errors | 0.18426 | 0.10528 | Answer F1 delta −0.03623; 95% CI [−0.12212, +0.02273] |
| Dev100 baseline `p1q0-dev-current` | 100/100, 0 errors | 0.10013 | 0.06958 | — |
| Dev100 candidate `stage2-dev100-compat-20260925` | 100/100, 0 errors | 0.17293 | 0.10972 | Answer F1 delta +0.07280; 95% CI [+0.01750, +0.13682] |

Smoke28 paired Evidence F1, Gold Evidence Recall@10, and MRR were unchanged. Its Answer F1 interval crosses zero. Dev100 Evidence F1 delta was +0.04013 (95% CI [+0.02987, +0.05133]); Gold Evidence Recall@10 delta was −0.04618 (95% CI [−0.10241, +0.00602]); MRR delta was +0.01807 (95% CI [−0.00147, +0.04179]).

Both comparisons used the same QASPER source, question set, qrels, and index within each pair and passed `check_qasper_run.py`. They are compatibility evidence, not a causal measurement of the JIT Agent path.

## 6. Runtime Metrics Still Needed

The runtime trace now supports aggregate `candidate_count` and `output_chars` fields. A real Agent-runtime run is still needed to report average Search candidates, Read candidates, Search output characters, and Read output characters, and to verify that Reads remain much fewer than Search candidates.

## 7. Regression and Risks

- The feature flag remains off by default; no product-default promotion is made.
- The Agent suite's four known grounded-synthesis failures remain unchanged.
- The Stage 1 report still marks its experimental Gate **PENDING / NO-GO** because required real retrieval A/B/C, answer, and p95 measurements are outstanding. Stage 2 therefore also remains **PENDING / NO-GO for default enablement**.

## 8. Decision

Keep `jit_search_read_enabled=false` by default. The Search/Read implementation and deterministic fixture are in place, the synthetic payload reduction exceeds the target, and QASPER compatibility checks show no clear negative confidence interval. Do not promote the feature until the Stage 1 Gate is closed and real Agent-runtime metrics plus the required Agent E2E quality validation are recorded.
