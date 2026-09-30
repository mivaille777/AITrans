"""Run full-corpus HF retrieval benchmarks through AITrans's sparse store.

Data and per-query results stay in the ignored data/ directory. HF downloads
need huggingface_hub; MedicalRetrieval additionally needs pyarrow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
import time
import types
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.evaluation import ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from backend.rag.models import DocumentChunk
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.sparse.tokenizer import SparseTokenizer

S00_COMMIT = "3f39f81b377aa6e4618ee88ab0a25be8569a03c5"
DATASETS = {
    "scifact": {
        "repo": "mteb/scifact",
        "revision": "cf10ab6856b15b0e670ef8ae5dae4e266c12d035",
        "language": "en",
        "splits": ("train", "test"),
        "files": (
            "README.md",
            "corpus.jsonl",
            "queries.jsonl",
            "qrels/train.jsonl",
            "qrels/test.jsonl",
        ),
    },
    "medical": {
        "repo": "mteb/MedicalRetrieval",
        "revision": "bc05e883de33f26fb745fe57092796ceb65a48bb",
        "language": "zh",
        "splits": ("dev",),
        "files": (
            "README.md",
            "corpus/dev-00000-of-00001.parquet",
            "queries/dev-00000-of-00001.parquet",
            "data/dev-00000-of-00001.parquet",
        ),
    },
}


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _rows(path: Path) -> list[dict]:
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        return pq.read_table(path).to_pylist()
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _historical_store() -> tuple[type, type, dict[str, str]]:
    """Load trusted S00 Git sources without switching the user's checkout."""
    loaded = {}
    hashes = {}
    for part in ("tokenizer", "bm25", "store"):
        relative_path = f"backend/rag/sparse/{part}.py"
        source = subprocess.check_output(
            ["git", "show", f"{S00_COMMIT}:{relative_path}"], cwd=REPO_ROOT
        )
        hashes[relative_path] = hashlib.sha256(source).hexdigest()
        code = source.decode("utf-8")
        if part == "store":
            code = code.replace(
                "from backend.rag.sparse.bm25 import BM25Index",
                "from _aitrans_s00_bm25 import BM25Index",
            ).replace(
                "from backend.rag.sparse.tokenizer import SparseTokenizer",
                "from _aitrans_s00_tokenizer import SparseTokenizer",
            )
        module = types.ModuleType(f"_aitrans_s00_{part}")
        module.__file__ = f"{S00_COMMIT}:{relative_path}"
        sys.modules[module.__name__] = module
        # Only source from the fixed, trusted S00 Git commit is executed.
        exec(compile(code, module.__file__, "exec"), module.__dict__)  # noqa: S102
        loaded[part] = module
    return (
        loaded["store"].BM25SparseRetriever,
        loaded["tokenizer"].SparseTokenizer,
        hashes,
    )


def _query_kind(text: str) -> str:
    # Heuristic diagnostic slices; alphanumeric terms also include protein IDs.
    if re.search(r"10\.\d{4,9}/|\b[A-Z]{2,}\b|\b[A-Za-z]+\d+", text):
        return "identifier"
    return "term"


def _aggregate(cases: list[dict]) -> dict:
    return {
        "query_count": len(cases),
        **{
            name: mean(case[name] for case in cases) if cases else None
            for name in (
                "Recall@1",
                "Recall@5",
                "Recall@10",
                "Recall@20",
                "MRR@100",
                "nDCG@10",
            )
        },
        "retrieval_p50_ms": percentile([case["latency_ms"] for case in cases], 50),
        "retrieval_p95_ms": percentile([case["latency_ms"] for case in cases], 95),
    }


def _qasper_backfill(args: argparse.Namespace) -> int:
    from backend.rag.benchmarks.qasper.evaluator import _gold_chunk_sets
    from backend.rag.stores.base import VectorSearchFilter

    source = args.qasper_source_root.resolve()
    source_indexes = list((source / "indexes").glob("*/bm25_index.json"))
    source_qrels = list((source / "qrels").glob("*.jsonl"))
    if len(source_indexes) != 1 or len(source_qrels) != 1:
        raise ValueError("expected one frozen QASPER index and qrels file")
    ids_path = REPO_ROOT / "data/benchmarks/qasper/frozen_s00/dev-question-ids.txt"
    question_ids = set(ids_path.read_text(encoding="utf-8-sig").splitlines())
    qrels = _rows(source_qrels[0])
    if {row["question_id"] for row in qrels} != question_ids:
        raise ValueError("QASPER qrels do not match frozen S00 dev IDs")
    catalogue = json.loads(source_indexes[0].read_text(encoding="utf-8"))
    chunks = [DocumentChunk.model_validate(row) for row in catalogue["chunks"].values()]
    mapping = defaultdict(list)
    paper_documents = defaultdict(set)
    for chunk in chunks:
        benchmark = chunk.metadata.get("benchmark", {})
        paper_documents[benchmark.get("paper_id")].add(chunk.document_id)
        for paragraph_id in benchmark.get("source_paragraph_ids", []):
            mapping[paragraph_id].append(chunk.chunk_id)
    if args.implementation == "s00":
        store_class, tokenizer_class, code_hashes = _historical_store()
    else:
        store_class, tokenizer_class = BM25SparseRetriever, SparseTokenizer
        code_hashes = {
            f"backend/rag/sparse/{part}.py": _sha256(
                REPO_ROOT / f"backend/rag/sparse/{part}.py"
            )
            for part in ("tokenizer", "bm25", "store")
        }
    output = args.root.resolve() / "results"
    output.mkdir(parents=True, exist_ok=True)
    name = f"qasper-validation-{args.implementation}"
    index_path = output / f"{name}-bm25.json"
    tokenizer = tokenizer_class()
    store = store_class(index_path, tokenizer=tokenizer)
    started = time.perf_counter()
    store.rebuild(chunks)
    build_seconds = time.perf_counter() - started
    cases = []
    all_latencies = []
    for qrel in qrels:
        query = qrel["question"]
        allowed_documents = sorted(paper_documents.get(qrel["paper_id"], ()))
        if not allowed_documents:
            raise ValueError("QASPER paper ID has no indexed document")
        started = time.perf_counter()
        ranked = [
            candidate.chunk.chunk_id
            for candidate in store.search(
                query, 100, VectorSearchFilter(document_ids=allowed_documents)
            )
        ]
        elapsed_ms = (time.perf_counter() - started) * 1000
        all_latencies.append(elapsed_ms)
        gold_sets = [items for items in _gold_chunk_sets(qrel, mapping) if items]
        if not gold_sets:
            continue
        cases.append(
            {
                "query_id": qrel["question_id"],
                "query": query,
                "kind": _query_kind(query),
                "query_tokens": tokenizer.tokenize(query),
                "gold_chunk_sets": [sorted(items) for items in gold_sets],
                "ranked_ids": ranked,
                "latency_ms": elapsed_ms,
                **{
                    f"Recall@{k}": max(
                        recall_at_k(ranked, gold, k) for gold in gold_sets
                    )
                    for k in (1, 5, 10, 20)
                },
                "MRR@100": max(reciprocal_rank(ranked, gold) for gold in gold_sets),
                "nDCG@10": max(
                    ndcg_at_k(ranked, dict.fromkeys(gold, 1), 10) for gold in gold_sets
                ),
            }
        )
    if not cases or not any(case["ranked_ids"] for case in cases):
        raise ValueError("QASPER backfill has no evaluable retrieval candidates")
    result = {
        "dataset": "QASPER validation frozen S00 dev100, known-paper filtered",
        "implementation": args.implementation,
        "baseline_commit": S00_COMMIT if args.implementation == "s00" else None,
        "retrieval_top_k": 100,
        "query_count_total": len(qrels),
        "corpus_count": len(chunks),
        "tokenizer_version": getattr(tokenizer_class, "VERSION", "unversioned"),
        "index_build_seconds": build_seconds,
        "index_json_bytes": index_path.stat().st_size,
        "metrics": _aggregate(cases),
        "retrieval_p95_all_queries_ms": percentile(all_latencies, 95),
        "data_files": [
            {"path": str(path), "sha256": _sha256(path)}
            for path in (source_indexes[0], source_qrels[0], ids_path)
        ],
        "code_sha256": code_hashes,
        "slices": {
            kind: _aggregate([case for case in cases if case["kind"] == kind])
            for kind in ("identifier", "term")
        },
        "cases": cases,
    }
    (output / f"{name}-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"cases", "data_files", "code_sha256"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=(*DATASETS, "qasper"), required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument(
        "--implementation", choices=("current", "s00"), default="current"
    )
    parser.add_argument("--root", type=Path, default=Path("data/benchmarks/s04"))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--qasper-source-root",
        type=Path,
        default=Path("data/benchmarks/qasper/s03-3-vector-only"),
    )
    parser.add_argument(
        "--limit", type=int, help="Diagnostic query subset; corpus remains complete"
    )
    args = parser.parse_args()
    if args.dataset == "qasper":
        if args.split != "validation" or args.limit or args.download:
            parser.error(
                "QASPER backfill requires --split validation; limit/download are unavailable"
            )
        return _qasper_backfill(args)
    config = DATASETS[args.dataset]
    if args.split not in config["splits"]:
        parser.error(f"split must be one of {config['splits']}")
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    root = args.root.resolve()
    data = root / "hf_raw" / config["repo"].replace("/", "__")
    if args.download:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=config["repo"],
            repo_type="dataset",
            revision=config["revision"],
            local_dir=str(data),
            allow_patterns=list(config["files"]),
        )
    file_fingerprints = [
        {
            "path": name,
            "bytes": (data / name).stat().st_size,
            "sha256": _sha256(data / name),
        }
        for name in config["files"]
    ]
    if args.dataset == "scifact":
        corpus = _rows(data / "corpus.jsonl")
        queries = _rows(data / "queries.jsonl")
        judgments = _rows(data / f"qrels/{args.split}.jsonl")
    else:
        corpus = _rows(data / "corpus/dev-00000-of-00001.parquet")
        queries = _rows(data / "queries/dev-00000-of-00001.parquet")
        judgments = _rows(data / "data/dev-00000-of-00001.parquet")

    corpus_ids = {str(item["_id"]) for item in corpus}
    query_texts = {str(item["_id"]): str(item["text"]) for item in queries}
    if len(corpus_ids) != len(corpus) or len(query_texts) != len(queries):
        raise ValueError("duplicate corpus or query IDs")
    qrels = defaultdict(dict)
    for item in judgments:
        if int(item["score"]) > 0:
            qid, docid = str(item["query-id"]), str(item["corpus-id"])
            if qid not in query_texts or docid not in corpus_ids:
                raise ValueError("qrel points to missing query/corpus ID")
            qrels[qid][docid] = int(item["score"])
    selected = list(qrels.items())
    if args.limit:
        selected = random.Random(args.seed).sample(
            selected, min(args.limit, len(selected))
        )
    if not selected:
        raise ValueError("no positive judgments")

    if args.implementation == "s00":
        store_class, tokenizer_class, code_hashes = _historical_store()
    else:
        store_class, tokenizer_class = BM25SparseRetriever, SparseTokenizer
        code_hashes = {
            f"backend/rag/sparse/{part}.py": _sha256(
                REPO_ROOT / f"backend/rag/sparse/{part}.py"
            )
            for part in ("tokenizer", "bm25", "store")
        }
    name = f"{args.dataset}-{args.split}-{args.implementation}"
    if args.limit:
        name += f"-limit{args.limit}"
    output = root / "results"
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / f"{name}-bm25.json"
    tokenizer = tokenizer_class()
    store = store_class(index_path, tokenizer=tokenizer)
    chunks = [
        DocumentChunk(
            chunk_id=str(item["_id"]),
            document_id=str(item["_id"]),
            title=str(item.get("title", "") or ""),
            text=str(item["text"]),
            language=config["language"],
            chunk_index=0,
        )
        for item in corpus
    ]
    started = time.perf_counter()
    store.rebuild(chunks)
    build_seconds = time.perf_counter() - started
    print(f"{name}: indexed full corpus {len(corpus)}", flush=True)
    cases = []
    for position, (query_id, gold) in enumerate(selected, 1):
        query = query_texts[query_id]
        started = time.perf_counter()
        ranked = [item.chunk.chunk_id for item in store.search(query, 100)]
        elapsed_ms = (time.perf_counter() - started) * 1000
        cases.append(
            {
                "query_id": query_id,
                "query": query,
                "kind": _query_kind(query),
                "query_tokens": tokenizer.tokenize(query),
                "gold_ids": list(gold),
                "ranked_ids": ranked,
                "latency_ms": elapsed_ms,
                **{f"Recall@{k}": recall_at_k(ranked, gold, k) for k in (1, 5, 10, 20)},
                "MRR@100": reciprocal_rank(ranked, gold),
                "nDCG@10": ndcg_at_k(ranked, gold, 10),
            }
        )
        if position % 50 == 0:
            print(f"{name}: {position}/{len(selected)} queries", flush=True)
    result = {
        "dataset": config["repo"],
        "revision": config["revision"],
        "split": args.split,
        "implementation": args.implementation,
        "baseline_commit": S00_COMMIT if args.implementation == "s00" else None,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "corpus_count": len(corpus),
        "judgment_rows": len(judgments),
        "query_limit": args.limit,
        "query_subset_seed": args.seed if args.limit else None,
        "tokenizer_version": getattr(tokenizer_class, "VERSION", "unversioned"),
        "bm25_k1": 1.5,
        "bm25_b": 0.75,
        "retrieval_top_k": 100,
        "index_build_seconds": build_seconds,
        "index_json_bytes": index_path.stat().st_size,
        "data_files": file_fingerprints,
        "code_sha256": code_hashes,
        "metrics": _aggregate(cases),
        "slices": {
            kind: _aggregate([case for case in cases if case["kind"] == kind])
            for kind in ("identifier", "term")
        },
        "cases": cases,
    }
    result_path = output / f"{name}-results.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / f"{name}-misses.json").write_text(
        json.dumps(
            [case for case in cases if case["Recall@5"] == 0],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"cases", "data_files", "code_sha256"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result_file: {result_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
