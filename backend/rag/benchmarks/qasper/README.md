# QASPER Adapter

Prepare the public QASPER v0.3 dev split (exposed as `validation`) from the
repository root:

```powershell
python scripts/prepare_qasper.py prepare --split validation
```

The downloader reuses an existing archive or extracted JSON and records the
archive and raw JSON SHA256 values under `data/benchmarks/qasper/manifests/`.
Use `--limit 20 --seed 42` for a reproducible sample, or `--raw-json <path>` to
prepare a local QASPER JSON file. Dataset, normalized corpus, qrels, alignment
errors, and manifests are written below the ignored
`data/benchmarks/qasper/` directory.

Run the AITrans known-paper baseline from the repository root:

```powershell
python scripts/run_qasper_benchmark.py --mode smoke
python scripts/run_qasper_benchmark.py --mode dev --seed 42
python scripts/run_qasper_benchmark.py --mode full
```

Smoke selects up to 20 questions, dev selects up to 100 questions, and full
uses every question in the selected split. Each question is retrieved with a
`document_id` filter for its own paper. The default run generates a grounded
answer through the configured AITrans chat provider; add `--retrieval-only`
to capture retrieval traces without calling a chat model. Results, run-local
qrels, and cache manifests remain under the ignored benchmark directory.

Each completed run also writes a full `metrics.json` with AITrans chunk-level
retrieval and reranking metrics, paragraph-level evidence coverage, latency
percentiles, and the official QASPER Answer/Evidence F1. Re-evaluate a run with:

```powershell
python scripts/evaluate_qasper.py --run-directory data/benchmarks/qasper/results/<run-id>
```

The evaluator uses the run manifest's sample qrels and indexed chunk catalogue.
It reports both all-evidence and text-evidence-only official scores; the latter
excludes QASPER figure/table evidence marked `FLOAT SELECTED`.

Run the Phase 5 query-time ablation suite with a shared QASPER index:

```powershell
python scripts/run_qasper_ablation.py --mode smoke
python scripts/run_qasper_ablation.py --mode dev --seed 42
```

The default suite runs B0 through B7 and `FULL`. Select a subset with
`--variants B0 B3 B5 FULL`. The runner records each variant's feature switches,
cache-hit status, retrieval traces, official answer/evidence scores, paragraph
coverage, adaptive retrieval coverage, latency, and estimated context tokens.
All variants use the same corpus/chunking/embedding fingerprint, so they reuse
the same index. B6, B7, and `FULL` use the configured query-planner provider;
`--retrieval-only` disables answer generation while preserving query planning.

`FULL` represents the current direct AITrans knowledge-search path: dense and
BM25 retrieval, RRF, reranking, Small-to-Big context, and query planning. The
incremental B4-B7 variants additionally enable structural retrieval before
progressively adding Small-to-Big, query planning, and the evidence gate.

Phase 6 evaluates each B7 Gate decision against QASPER gold: cumulative context
is gold-sufficient only when it contains every paragraph in at least one
annotator's complete evidence set. The metrics report sufficiency precision,
recall, and F1, premature stops among labeled stop decisions, and unnecessary
retrievals among extra rounds. Questions with no mapped gold evidence are
excluded from the sufficiency classification and counted separately.

Run the Phase 7 RAPTOR variants with a cached recursive summary tree:

```powershell
python scripts/run_qasper_raptor_ablation.py --mode smoke --retrieval-only
python scripts/run_qasper_raptor_ablation.py --mode dev --summary-provider llm
```

R0 is the flat + structural baseline. R1 mixes dense leaf retrieval with
summary-node retrieval, R2 searches summary nodes and expands them to leaf
evidence, and R3 joins RAPTOR candidates with dense + BM25 + RRF before
reranking. The CLI defaults to an offline extractive summary provider; select
`--summary-provider llm` to use the configured AI synthesis model. Each tree
cache key includes the leaf content, embedding model, summary model, prompt
version, clustering version, and branching factor, but excludes query-time
settings. Tree nodes retain child links and descendant chunk/paragraph IDs.
Results include Local, Cross-section, Global, and Overall groups; scope is
derived from the number of QASPER sections in a complete annotator evidence
set, with questions lacking mapped evidence counted separately as unanswerable
or unclassified depending on the source annotation.

Run the Phase 8 evidence-selection comparison:

```powershell
python scripts/run_qasper_evidence_selection_ablation.py --mode smoke --retrieval-only
python scripts/run_qasper_evidence_selection_ablation.py --mode dev --extractor llm
```

The suite compares hybrid Raw Top-K, hybrid Rerank Top-K, and Evidence
Selection on one shared index. Evidence Selection reranks a pool of up to 20
chunks, extracts query-conditioned verbatim spans, scores them with lexical
coverage and the configured embedding model, then sends up to five selected
spans through the existing grounded synthesis path. The default extractor is
deterministic and offline; `--extractor llm` asks the configured synthesis
model for exact source spans and rejects text that cannot be found verbatim in
the source chunk. Run results retain source chunk IDs, offsets, paragraph IDs,
extraction/scoring latency, context token counts, official QASPER Answer and
Evidence F1, and unsupported claim rate when answer generation is enabled.

Run the Phase 9 adaptive-retrieval comparison:

```powershell
python scripts/run_qasper_adaptive_retrieval_ablation.py --mode smoke --retrieval-only
python scripts/run_qasper_adaptive_retrieval_ablation.py --mode dev --seed 42
```

The suite compares one-shot hybrid retrieval, Query Planner multi-query,
evidence-gated re-retrieval, and requirement-aware re-retrieval on one index.
The requirement-aware variant infers lightweight `EvidenceRequirement` records
from question cues, marks each as covered or missing from retrieved text and
section labels, then spends at most three retrieval rounds targeting uncovered
requirements. Its runtime coverage heuristic is reported separately from
gold-labeled QASPER evidence recall. The multi-query and evidence-gated variants
use the configured AITrans Query Planner.

Paragraph IDs have the form
`qasper:{split}:{paper_id}:p{global_paragraph_index}`. The adapter constructs
`NormalizedDocument` values directly from QASPER sections and paragraphs; it
does not invoke PDF parsing. Qrels retain every annotator answer, evidence
string, highlighted span, and the stable paragraph IDs that were resolved.
Evidence that cannot be mapped is written to
`alignment_errors/{split}.jsonl`.

The official validation run contains 281 papers and 1005 questions. Text
evidence alignment is 99.92%; the remaining text miss cases are evidence that
points to an empty `Experimental Setup` section. Figure/table evidence marked
`FLOAT SELECTED` is kept in the qrels and reported separately because the raw
text split does not contain the corresponding figure or table body. It is not
silently treated as a text paragraph.
