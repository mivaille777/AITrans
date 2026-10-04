from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.bad_cases.models import RagBadCase
from backend.rag.benchmarks.common import atomic_write_json
from backend.rag.benchmarks.runtime import build_benchmark_rag_runtime
from backend.rag.config import RagConfig
from backend.rag.graph.repository import GraphRepository
from backend.rag.graph_retriever import GraphRetriever
from backend.rag.retrieval_service import RetrievalService
from backend.rag.stores.base import VectorSearchFilter


def replay(case: RagBadCase, runtime):
    if case.source_redacted:
        raise ValueError("source was redacted; supply the explicitly retained case before replay")
    active = runtime.manifest.list_active_generations()
    if any(key not in active or active[key] != generation for key, generation in case.generations.items()):
        raise ValueError("frozen generation is unavailable; replay cannot use a newer index")
    if not case.generations:
        raise ValueError("replay requires a frozen generation snapshot")
    if case.case.expected_scope_document_ids and set(case.case.expected_scope_document_ids) != set(case.generations):
        raise ValueError("frozen generation scope does not match the case scope")
    if "embedding" not in case.fingerprints or "config" not in case.fingerprints:
        raise ValueError("replay requires frozen embedding and config fingerprints")
    from hashlib import sha256
    if case.fingerprints["config"] != sha256(runtime.config.model_dump_json().encode()).hexdigest():
        raise ValueError("frozen config fingerprint mismatch")
    if case.fingerprints["embedding"] != runtime.embedding_provider.fingerprint.digest:
        raise ValueError("frozen model fingerprint mismatch")
    result = runtime.retrieval_service.retrieve(case.case.query, filters=VectorSearchFilter(document_ids=list(case.generations)))
    before = case.stages.get("CONTEXT", [])
    after = [item.chunk.chunk_id for item in result.candidates]
    return {"case_id": case.case.case_id, "source_trace_id": case.trace_id, "generations": case.generations,
            "before": before, "after": after, "added": sorted(set(after)-set(before)),
            "removed": sorted(set(before)-set(after)), "metadata": result.metadata}


def main():
    parser = argparse.ArgumentParser(description="Replay one retained bad case against its frozen index.")
    parser.add_argument("--case-json", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    case = RagBadCase.model_validate_json(Path(args.case_json).read_text(encoding="utf-8"))
    config = RagConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8"))
    runtime = build_benchmark_rag_runtime(args.runtime_root, config=config)
    try:
        if config.graph.enabled:
            graph_path = runtime.root / "graph.sqlite3"
            if not graph_path.is_file():
                raise ValueError("frozen graph index is unavailable")
            runtime.retrieval_service = RetrievalService(
                embedding_provider=runtime.embedding_provider, vector_store=runtime.vector_store,
                sparse_retriever=runtime.sparse_retriever, config=config.retrieval,
                reranker=runtime.reranker, manifest=runtime.manifest,
                graph_retriever=GraphRetriever(repository=GraphRepository(graph_path),
                                               store=runtime.vector_store, config=config.graph),
            )
        atomic_write_json(args.output, replay(case, runtime))
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
