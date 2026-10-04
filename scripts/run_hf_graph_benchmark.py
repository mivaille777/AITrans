"""Public multi-document Graph/BM25 ablation on a fixed 2Wiki context union.

The corpus contains all supplied distractors for the sampled questions. This
is a bounded public proxy, not open retrieval over all Wikipedia or Dense QA.
GraphIndexer uses only raw documents; gold facts never enter extraction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from time import perf_counter

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ai.errors import AIError
from app.ai.gateway import LLMGateway
from backend.rag.benchmarks.common import atomic_write_json, atomic_write_jsonl
from backend.rag.config import RagGraphConfig
from backend.rag.evaluation import percentile, recall_at_k, reciprocal_rank
from backend.rag.fusion import rrf_fuse
from backend.rag.graph.extractor import GraphExtractionService, GraphExtractor
from backend.rag.graph.indexer import GraphIndexer
from backend.rag.graph.repository import GraphRepository
from backend.rag.graph_retriever import GraphRetriever
from backend.rag.models import KnowledgeDocument, NormalizedDocument
from backend.rag.retrievers.base import RetrievalRequest
from backend.rag.source_span import resolve_source_span
from backend.rag.sparse import BM25SparseRetriever
from scripts.run_hf_rag_benchmark import make_chunks
from scripts.run_hf_sparse_benchmark import _rows, _sha256


def prepare(rows: list[dict], limit: int, source: str):
    selected = random.Random(42).sample(rows, min(limit, len(rows)))
    corpus, cases = {}, []
    for row in selected:
        by_title = {}
        source_sentences = {}
        for title, sentences in zip(row["context"]["title"], row["context"]["sentences"], strict=True):
            text = "\n".join(sentences)
            docid = hashlib.sha256((title + "\n" + text).encode()).hexdigest()[:24]
            corpus[docid] = {"_id": docid, "title": title, "text": text}
            by_title[title] = docid
            source_sentences[title] = sentences
        gold_titles = row["supporting_facts"]["title"]
        if any(title not in by_title for title in gold_titles):
            raise ValueError("supporting fact refers to absent source")
        for title, sentence_id in zip(gold_titles, row["supporting_facts"]["sent_id"], strict=True):
            if not 0 <= sentence_id < len(source_sentences[title]):
                raise ValueError("supporting fact sentence is outside source")
        cases.append({"query_id": row["id"], "query": row["question"], "type": row["type"],
                      "gold_ids": sorted({by_title[title] for title in gold_titles}),
                      "gold_facts": row["supporting_facts"], "gold_relations": row["evidences"]})
    chunks = make_chunks(list(corpus.values()), "en", source)
    for chunk in chunks:
        chunk.metadata["index_generation"] = chunk.document_hash[:24]
    return chunks, cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    if args.limit <= 0 or args.output.exists():
        raise ValueError("positive limit and new output directory required")
    rows = _rows(args.source)
    chunks, cases = prepare(rows, args.limit, str(args.source.resolve()))
    args.output.mkdir(parents=True)
    atomic_write_jsonl(args.output / "chunks.jsonl", [chunk.model_dump(mode="json") for chunk in chunks])
    atomic_write_jsonl(args.output / "cases.jsonl", cases)
    sparse = BM25SparseRetriever(args.output / "bm25.json")
    sparse.rebuild(chunks)
    repository = GraphRepository(args.output / "graph.sqlite3")
    service = LLMGateway().create_text_service("agent_synthesis")
    extractor = GraphExtractor(GraphExtractionService(service))
    indexer = GraphIndexer(repository=repository, extractor=extractor, scope_id="public-2wiki")
    manifest = {"status": "building", "dataset": "framolfese/2WikiMultihopQA",
                "revision": "fe713bfbd1afbca1a65246741a75890405d56a3a",
                "source_sha256": _sha256(args.source), "seed": 42,
                "source_question_count": len(rows), "query_count": len(cases), "corpus_count": len(chunks),
                "scope": "union of all supplied context documents and distractors; no gold filters",
                "provider": service.provider_name, "model": service.model, "index_version": indexer.version,
                "limitations": "Pre-parsed closed public proxy; no Dense, answers, user ACL or Wikipedia-wide corpus."}
    atomic_write_json(args.output / "manifest.json", manifest)
    builds = []
    try:
        def build(chunk):
            document = NormalizedDocument(text=chunk.text, document=KnowledgeDocument(
                document_id=chunk.document_id, title=chunk.title, source_uri=chunk.source_uri,
                content_hash=chunk.document_hash, language="en", source_kind="hf-preparsed"))
            try:
                result = indexer.build_generation(document, [chunk], chunk.metadata["index_generation"])
                return {"document_id": chunk.document_id, **asdict(result)}
            except (AIError, ValueError) as exc:
                return {"document_id": chunk.document_id, "error": f"{type(exc).__name__}: {exc}",
                        "http_status": getattr(exc, "status_code", None)}

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(build, chunk): chunk for chunk in chunks}
            for future in as_completed(futures):
                if future.cancelled():
                    record = {"document_id": futures[future].document_id,
                              "error": "Cancelled: provider returned HTTP 402", "cancelled": True}
                else:
                    record = future.result()
                    if record.get("http_status") == 402:
                        # Payment failures need an account decision; stop queued API work.
                        for pending in futures:
                            pending.cancel()
                if "generation" in record:
                    record["generation"] = record["generation"].model_dump(mode="json")
                builds.append(record)
                atomic_write_jsonl(args.output / "builds.jsonl", builds)
                if len(builds) % 25 == 0:
                    print(f"graph built {len(builds)}/{len(chunks)}", flush=True)
        graph = GraphRetriever(repository=repository, store=sparse,
                               config=RagGraphConfig(enabled=True, scope_id="public-2wiki"))
        generations = {chunk.document_id: chunk.metadata["index_generation"] for chunk in chunks}
        source_text = {chunk.document_id: chunk.text for chunk in chunks}
        summary = {}
        for profile in ("sparse", "graph", "graph_sparse"):
            outputs = []
            for case in cases:
                started = perf_counter()
                graph_result = None
                hits = []
                if profile != "sparse":
                    graph_result = graph.retrieve_with_trace(RetrievalRequest(
                        query=case["query"], top_k=20, allowed_document_ids=sorted(generations),
                        active_generations=generations))
                    hits.append(graph_result.candidates)
                if profile != "graph":
                    hits.append(sparse.search(case["query"], 30, active_generations=generations))
                result = rrf_fuse(hits, limit=20)
                elapsed = (perf_counter() - started) * 1000
                for hit in result:
                    if hit.chunk.document_id not in generations:
                        raise ValueError("retrieval escaped public corpus scope")
                    for path in hit.graph_paths:
                        resolve_source_span(path.source_span, source_text[hit.chunk.document_id],
                                            expected_document_hash=hit.chunk.document_hash)
                ranked = [hit.chunk.document_id for hit in result]
                gold = set(case["gold_ids"])
                outputs.append({**case, "ranked_ids": ranked, "Recall@5": recall_at_k(ranked, gold, 5),
                    "MRR@20": reciprocal_rank(ranked, gold), "complete_evidence@5": gold.issubset(ranked[:5]),
                    "elapsed_ms": elapsed, "graph_trace": graph_result.metadata if graph_result else None,
                    "graph_paths": [path.model_dump(mode="json") for hit in result for path in hit.graph_paths]})
            atomic_write_jsonl(args.output / f"{profile}-predictions.jsonl", outputs)
            summary[profile] = {"N": len(outputs),
                "Recall@5": mean(row["Recall@5"] for row in outputs),
                "MRR@20": mean(row["MRR@20"] for row in outputs),
                "complete_evidence@5": mean(row["complete_evidence@5"] for row in outputs),
                "p95_ms": percentile([row["elapsed_ms"] for row in outputs], 95),
                "path_count": sum(len(row["graph_paths"]) for row in outputs)}
        summary["build"] = {"errors": sum("error" in row for row in builds),
            "entities": sum(row.get("entity_count", 0) for row in builds),
            "relations": sum(row.get("relation_count", 0) for row in builds)}
        atomic_write_json(args.output / "metrics.json", summary)
        manifest["error_count"] = summary["build"]["errors"]
        manifest["status"] = "partial" if manifest["error_count"] else "complete"
        manifest["graph_acceptance"] = "BLOCKED" if manifest["error_count"] else "evaluated"
        atomic_write_json(args.output / "manifest.json", manifest)
        print(json.dumps(summary), flush=True)
    finally:
        service.close()
    return 2 if manifest["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
