# RAG Improvement Baseline

## Scope

This document freezes the Stage 0 identity contract for the RAG improvement program.

- branch: `WebReBuild`
- baseline parent git SHA: `75d41ace90e41af5aa000dd321f55341ef5d9553`
- baseline profile: `backend/rag/benchmarks/qasper/profiles/rag-improvement-baseline-v1.json`
- prompt identity: recorded in each QASPER run manifest as `prompt_id`
- profile identity: recorded as `config_profile_id` and `config_profile_sha256`
- runtime config identity: recorded as `config_hash`
- index identity: recorded as `index_fingerprint`
- embedding model: `Qwen/Qwen3-Embedding-0.6B`
- reranker model: `Qwen/Qwen3-Reranker-0.6B`
- Smoke28 IDs: `backend/rag/benchmarks/qasper/sample_ids/validation-p1q2-smoke28-seed42.txt`
- Dev100 IDs: `backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt`

## Frozen retrieval configuration

```text
dense_top_k = 30
sparse_top_k = 30
fusion_top_k = 20
final_top_k = 8
small_to_big_enabled = true
```

The profile file is a valid `RagConfig` input and must be supplied through `--config-json`.
Its file SHA256 is calculated from the exact bytes of the profile and written to the run manifest.

## Required baseline commands

```powershell
python scripts/run_qasper_benchmark.py `
  --split validation `
  --mode full `
  --limit 28 `
  --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-p1q2-smoke28-seed42.txt `
  --config-json backend/rag/benchmarks/qasper/profiles/rag-improvement-baseline-v1.json `
  --config-profile-id rag-improvement-baseline-v1

python scripts/run_qasper_benchmark.py `
  --split validation `
  --mode full `
  --limit 100 `
  --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt `
  --config-json backend/rag/benchmarks/qasper/profiles/rag-improvement-baseline-v1.json `
  --config-profile-id rag-improvement-baseline-v1
```

After each run, audit it with `scripts/check_qasper_run.py` and retain the generated run IDs in the Stage 0 report.

## Gate status

The repository contract and deterministic tests are part of this Stage 0 commit. The real Smoke28 and Dev100 run IDs must be produced on an environment with the configured embedding/reranker/answer providers before Stage 0 can be marked PASS. Until then, Stage 1 must not become the default strategy.
