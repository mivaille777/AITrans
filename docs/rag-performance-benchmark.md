# RAG Performance Benchmark

Stage 10.29 keeps the production defaults at embedding dimension 1024, batch size
8, chunk size 512, overlap 80, and final top-k 8. A candidate is eligible only
when it changes one factor, remains within the configured Recall@10 and nDCG@10
quality budgets, and improves measured embedding throughput or total RAG p95.

List the controlled sweep matrix:

```powershell
python scripts/benchmark_rag.py --list-variants
```

The matrix covers batch sizes 8/16/32; default, FP16, and BF16 model loading;
embedding dimensions 1024/768/512/256; chunk sizes 384/512/768; overlaps
48/80/128; and final top-k 4/8/12. Variants that change more than one of these
fields are rejected.

Use the Stage 10.25 evaluator to produce quality/latency reports, record embedding
throughput with `benchmark_embedding_batches`, and serialize each run as a
`RagPerformanceCandidate`. Compare a candidate with the baseline:

```powershell
python scripts/benchmark_rag.py `
  --baseline outputs/rag-baseline.json `
  --candidate outputs/rag-batch-16.json
```

Exit code 0 means the candidate passed both quality and speed gates. Exit code 2
means it should not become a production default. INT4, GGUF, ONNX, and
FlashAttention remain outside this Stage; they require a separate benchmark and
quality review.
