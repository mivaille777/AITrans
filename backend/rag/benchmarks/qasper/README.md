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
