"""Full public corpus retrieval through AITrans's existing Dense/BM25/RRF/reranker.

Public rows are pre-parsed documents, not a PDF parsing or answer-quality test.
Gold IDs are used only by the scorer. Isolated indexes bind source and model hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.benchmarks.common import atomic_write_json, atomic_write_jsonl
from backend.rag.benchmarks.runtime import build_benchmark_rag_runtime
from backend.rag.config import RagConfig
from backend.rag.evaluation import ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from backend.rag.model_manager import RERANKER_MODEL_ID, ModelManager
from backend.rag.models import DocumentChunk
from backend.rag.retrieval_service import RetrievalService
from backend.rag.source_span import SourceSpan
from scripts.run_hf_sparse_benchmark import DATASETS, _rows, _sha256

PROFILES = {
    "dense": (True, False, False, 8),
    "sparse": (False, True, False, 8),
    "hybrid": (True, True, False, 8),
    "rerank8": (True, True, True, 8),
    "rerank12": (True, True, True, 12),
    "rerank20": (True, True, True, 20),
}


def load_cases(data: Path, dataset: str, split: str, limit: int | None, seed: int):
    specification = DATASETS[dataset]
    if split not in specification["splits"]:
        raise ValueError("split is not available for this dataset")
    files = (
        ("corpus.jsonl", "queries.jsonl", f"qrels/{split}.jsonl")
        if dataset == "scifact" else (
            "corpus/dev-00000-of-00001.parquet",
            "queries/dev-00000-of-00001.parquet",
            "data/dev-00000-of-00001.parquet",
        )
    )
    corpus, queries, judgments = [_rows(data / file) for file in files]
    corpus_ids = {str(row["_id"]) for row in corpus}
    query_texts = {str(row["_id"]): str(row["text"]) for row in queries}
    if len(corpus_ids) != len(corpus) or len(query_texts) != len(queries):
        raise ValueError("duplicate corpus or query IDs")
    qrels = defaultdict(dict)
    for row in judgments:
        qid, docid = str(row["query-id"]), str(row["corpus-id"])
        if qid not in query_texts or docid not in corpus_ids:
            raise ValueError("qrel points to missing query/corpus ID")
        if int(row["score"]) > 0:
            qrels[qid][docid] = int(row["score"])
    selected = sorted(qrels)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        selected = random.Random(seed).sample(selected, min(limit, len(selected)))
    if not selected:
        raise ValueError("no positive judgments")
    hashes = {file: _sha256(data / file) for file in files}
    return corpus, query_texts, qrels, selected, hashes


def make_chunks(corpus: list[dict], language: str, source_uri: str) -> list[DocumentChunk]:
    chunks = []
    for row in corpus:
        text = str(row["text"])
        raw_hash = hashlib.sha256(json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        uri = f"{source_uri}#{row['_id']}"
        span = SourceSpan.from_text(text, start_char=0, end_char=len(text),
                                    document_hash=raw_hash, source_uri=uri)
        chunks.append(DocumentChunk(
            chunk_id=str(row["_id"]), document_id=str(row["_id"]), text=text,
            title=str(row.get("title", "") or ""), chunk_index=0, language=language,
            source_uri=uri, document_hash=raw_hash, end_char=len(text), source_span=span,
            parser_version="hf-preparsed-row-v1", chunker_version="hf-full-document-v1",
        ))
    return chunks


def aggregate(cases: list[dict]) -> dict:
    return {
        "query_count": len(cases),
        **{metric: mean(case[metric] for case in cases) for metric in (
            "Recall@5", "Recall@10", "Recall@20", "MRR@20", "nDCG@10",
            "pre_rerank_recall@5", "rerank_input_recall", "post_rerank_recall@5",
        )},
        "warm_retrieval_p95_ms": percentile([case["elapsed_ms"] for case in cases], 95),
        "degraded_queries": sum(bool(case["errors"]) for case in cases),
    }


def gate(metrics: dict) -> dict:
    checks = {
        "recall_at_5": metrics["Recall@5"] >= 0.80,
        "mrr": metrics["MRR@20"] >= 0.70,
        "warm_p95": metrics["warm_retrieval_p95_ms"] <= 800,
        "minimum_sample": metrics["query_count"] >= 30,
        "no_degradation": metrics["degraded_queries"] == 0,
    }
    return {"checks": checks, "retrieval_status": "PASS" if all(checks.values()) else "FAIL",
            "citation_accuracy": None, "overall_status": "BLOCKED",
            "reason": "Retrieval-only run; independent claim/citation labels are absent."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=tuple(DATASETS), required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--root", type=Path, default=Path("data/benchmarks/s04/hf_raw"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config-json", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profiles", nargs="+", choices=tuple(PROFILES), default=list(PROFILES))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("output must be new; preserve previous evaluation results")
    specification = DATASETS[args.dataset]
    data = args.root / specification["repo"].replace("/", "__")
    corpus, queries, qrels, selected, source_hashes = load_cases(
        data, args.dataset, args.split, args.limit, args.seed
    )
    config = (RagConfig.model_validate_json(args.config_json.read_text(encoding="utf-8"))
              if args.config_json else RagConfig())
    config.retrieval.fusion_top_k = max(config.retrieval.fusion_top_k, 20)
    config.retrieval.final_top_k = 8
    config.retrieval.embedding_cache_size = 0
    if not config.reranker.model_path:
        config.reranker.model_path = str(ModelManager().get_model_path(RERANKER_MODEL_ID))
    config.reranker.local_files_only = True
    runtime_root = args.root.parent / "dense-runtime" / args.dataset
    runtime = build_benchmark_rag_runtime(runtime_root, config=config)
    try:
        identity = {"corpus_sha256": next(iter(source_hashes.values())),
                    "embedding": runtime.embedding_provider.fingerprint.as_dict(),
                    "representation": "hf-full-document-v1"}
        index_manifest = runtime_root / "public-index.json"
        cached = json.loads(index_manifest.read_text(encoding="utf-8")) if index_manifest.exists() else None
        if cached is not None and cached["identity"] != identity:
            raise ValueError("index identity differs; use a different root for the new corpus/model")
        chunks = make_chunks(corpus, specification["language"], str(data.resolve()))
        if cached is None:
            for start in range(0, len(chunks), 128):
                batch = chunks[start:start + 128]
                vectors = runtime.embedding_provider.embed_documents([chunk.text for chunk in batch])
                runtime.vector_store.upsert_chunks(batch, vectors)
                if start % 1024 == 0 or start + 128 >= len(chunks):
                    print(f"indexed {min(start + 128, len(chunks))}/{len(chunks)}", flush=True)
            runtime.sparse_retriever.rebuild(chunks)
            atomic_write_json(index_manifest, {"identity": identity, "corpus_count": len(chunks)})
        if runtime.vector_store.count_chunks() != len(chunks) or len(runtime.sparse_retriever.list_chunks()) != len(chunks):
            raise ValueError("incomplete public corpus index")
        args.output.mkdir(parents=True)
        manifest = {
            "status": "running", "dataset": specification["repo"], "revision": specification["revision"],
            "split": args.split, "corpus_count": len(corpus), "query_count": len(selected),
            "selected_query_ids": selected, "seed": args.seed, "source_hashes": source_hashes,
            "index_identity": identity, "config": config.model_dump(mode="json"),
            "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(),
            "scope": "all corpus documents; no gold document filtering",
            "timing": "one unscored warmup per profile; caches disabled; elapsed_ms covers retrieval only",
            "mrr_cutoff": 20,
            "started_at": datetime.now(UTC).isoformat(),
            "code_hashes": {file: _sha256(REPO_ROOT / file) for file in (
                "scripts/run_hf_rag_benchmark.py", "backend/rag/retrieval_service.py",
                "backend/rag/rerankers/qwen3.py", "backend/rag/embeddings/qwen3.py",
                "backend/rag/stores/faiss.py", "backend/rag/sparse/store.py",
                "backend/rag/sparse/bm25.py", "backend/rag/sparse/tokenizer.py",
            )},
            "reranker_hashes": {str(path.relative_to(config.reranker.model_path)): _sha256(path)
                                for path in sorted(Path(config.reranker.model_path).rglob("*"))
                                if path.is_file() and path.suffix in {".json", ".safetensors"}},
        }
        atomic_write_json(args.output / "manifest.json", manifest)
        summary = {}
        for name in args.profiles:
            dense, sparse, rerank, pool = PROFILES[name]
            retrieval_config = config.retrieval.model_copy(update={"rerank_candidate_k": pool})
            # Pre-parsed public corpus has no production manifest. Its complete identity is checked above.
            service = RetrievalService(embedding_provider=runtime.embedding_provider,
                vector_store=runtime.vector_store, sparse_retriever=runtime.sparse_retriever,
                config=retrieval_config, reranker=runtime.reranker)
            options = {"dense_enabled": dense, "sparse_enabled": sparse, "reranker_enabled": rerank,
                       "structural_enabled": False, "small_to_big_enabled": False, "graph_enabled": False}
            service.retrieve(queries[selected[0]], **options)
            cases = []
            for position, qid in enumerate(selected, 1):
                result = service.retrieve(queries[qid], **options)
                meta = result.metadata
                ranked = (meta["post_rerank_chunk_ids"] if meta["reranker_applied"]
                          else meta["pre_rerank_chunk_ids"])
                gold = qrels[qid]
                errors = {key: meta.get(key) for key in (
                    "dense_error", "sparse_error", "fallback_reason", "reranker_fallback_reason"
                ) if meta.get(key)}
                cases.append({"query_id": qid, "ranked_ids": ranked,
                    "final_ids": [item.chunk.chunk_id for item in result.candidates],
                    "gold_ids": sorted(gold), "elapsed_ms": result.elapsed_ms, "errors": errors,
                    **{f"Recall@{k}": recall_at_k(ranked, set(gold), k) for k in (5, 10, 20)},
                    "MRR@20": reciprocal_rank(ranked[:20], set(gold)),
                    "nDCG@10": ndcg_at_k(ranked, gold, 10),
                    "pre_rerank_recall@5": recall_at_k(meta["pre_rerank_chunk_ids"], set(gold), 5),
                    "rerank_input_recall": recall_at_k(meta["rerank_input_chunk_ids"], set(gold), pool),
                    "post_rerank_recall@5": recall_at_k(ranked, set(gold), 5), "trace": meta})
                if position % 25 == 0:
                    print(f"{name}: {position}/{len(selected)}", flush=True)
            atomic_write_jsonl(args.output / f"{name}-predictions.jsonl", cases)
            metrics = aggregate(cases)
            summary[name] = {"metrics": metrics, "gate": gate(metrics)}
            atomic_write_json(args.output / "metrics.json", summary)
            print(json.dumps({name: summary[name]}), flush=True)
        manifest["status"] = "complete"
        manifest["completed_at"] = datetime.now(UTC).isoformat()
        atomic_write_json(args.output / "manifest.json", manifest)
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
