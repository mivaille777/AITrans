from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.research.memory import (
    ResearchMemoryClaimDraft,
    ResearchMemoryEntityDraft,
    ResearchMemoryExtractionDraft,
    ResearchMemoryRelationDraft,
)
from backend.rag.benchmarks.common import atomic_write_json, atomic_write_jsonl
from backend.rag.benchmarks.runtime import build_benchmark_rag_runtime
from backend.rag.citation_service import build_evidence_citations
from backend.rag.config import RagConfig
from backend.rag.context_builder import GroundedContextBuilder
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.exceptions import RagRetrievalError
from backend.rag.graph.extractor import GraphExtractor
from backend.rag.graph.indexer import GraphIndexer
from backend.rag.graph.repository import GraphRepository
from backend.rag.graph_retriever import GraphRetriever
from backend.rag.index_manifest import IndexStatus
from backend.rag.index_service import IndexService
from backend.rag.parsers import parse_document
from backend.rag.retrieval_service import RetrievalService
from backend.rag.stores.base import VectorSearchFilter

PROFILES = {
    "V": (True, False, False, False), "B": (False, True, False, False),
    "VB": (True, True, False, False), "VR": (True, False, False, True),
    "G": (False, False, True, False), "GV": (True, False, True, False),
    "GVB": (True, True, True, False), "GVBR": (True, True, True, True),
}


def build_functional_runtime(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    specification = manifest["functional"]
    hashes = {}
    for entry in specification["inputs"]:
        path = (REPO_ROOT / entry["path"]).resolve()
        if REPO_ROOT not in path.parents or hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != entry["sha256"]:
            raise ValueError(f"functional input fingerprint mismatch: {entry['path']}")
        hashes[entry["path"]] = entry["sha256"]
    config = RagConfig.model_validate(specification["config"])
    runtime = build_benchmark_rag_runtime(REPO_ROOT / specification["runtime_root"], config=config)
    try:
        raw = json.loads((REPO_ROOT / specification["extraction"]).read_text(encoding="utf-8"))
        source_path = REPO_ROOT / specification["source"]
        normalized = parse_document(source_path)
        class FrozenExtraction:
            version, prompt_id = raw["extractor_version"], raw["prompt_id"]
            provider_name, model = "frozen_live_provider_record", "deepseek-v4-flash"
            def extract(self, note):
                if note.source_text != normalized.text:
                    raise ValueError("frozen extraction does not match the normalized source")
                return ResearchMemoryExtractionDraft(
                    claims=tuple(ResearchMemoryClaimDraft(**item) for item in raw["claims"]),
                    entities=tuple(ResearchMemoryEntityDraft(**{**item, "aliases": tuple(item["aliases"])}) for item in raw["entities"]),
                    relations=tuple(ResearchMemoryRelationDraft(**item) for item in raw["relations"]),
                    extractor_version=self.version, prompt_id=self.prompt_id,
                )
        repository = GraphRepository(runtime.root / "graph.sqlite3")
        indexer = GraphIndexer(repository=repository, extractor=GraphExtractor(FrozenExtraction()), scope_id=config.graph.scope_id)
        runtime.index_service = IndexService(chunker=runtime.chunker, embedding_provider=runtime.embedding_provider,
                                            vector_store=runtime.vector_store, sparse_retriever=runtime.sparse_retriever,
                                            manifest=runtime.manifest, parser=parse_document, graph_indexer=indexer)
        indexed = runtime.index_service.index_document(source_path)
        if indexed.status is not IndexStatus.READY:
            raise RuntimeError(indexed.error)
        graph = GraphRetriever(repository=repository, store=runtime.vector_store, config=config.graph)
        runtime.retrieval_service = RetrievalService(embedding_provider=runtime.embedding_provider,
                                                     vector_store=runtime.vector_store, sparse_retriever=runtime.sparse_retriever,
                                                     config=config.retrieval, reranker=runtime.reranker,
                                                     manifest=runtime.manifest, graph_retriever=graph)
        cases = [{**case, "document_ids": [indexed.document_id] if not case.get("denied") else ["forbidden-document"]}
                 for case in specification["cases"]]
        hashes.update({"config": hashlib.sha256(config.model_dump_json().encode()).hexdigest(),
                       "embedding": runtime.embedding_provider.fingerprint.as_dict(),
                       "generations": runtime.manifest.list_active_generations()})
        return runtime, graph, cases, hashes
    except Exception:
        runtime.close()
        raise


def verify_result(runtime, result, filters):
    runtime.retrieval_service.validate_evidence_candidates(result, filters=filters)
    evidence = build_agent_evidence(result)
    citations = build_evidence_citations(evidence)
    context = GroundedContextBuilder().build(evidence, citations)
    included = set(context.included_evidence_ids)
    if any(not set(citation.evidence_ids).issubset(included) for citation in citations):
        raise ValueError("citation references evidence omitted from context")
    return {"hits": len(result.candidates), "citations": len(citations), "context_tokens": context.estimated_tokens}


def functional_operation(runtime, graph, cases, *, scenario="warm"):
    def fault(*args, **kwargs):
        raise TimeoutError("injected channel fault")
    def operation(index):
        case = cases[index % len(cases)]
        filters = VectorSearchFilter(document_ids=case["document_ids"])
        service = runtime.retrieval_service
        kwargs = {"filters": filters, "reranker_enabled": False, "structural_enabled": False,
                  "small_to_big_enabled": False, "trace_id": f"load-{index}"}
        injected = scenario == "mixed" and index >= len(cases) and index % 20 == 0
        all_failed = injected and index % 100 == 0
        if injected:
            service = RetrievalService(embedding_provider=SimpleNamespace(embed_query=fault),
                                       vector_store=runtime.vector_store,
                                       sparse_retriever=SimpleNamespace(search=fault) if all_failed else runtime.sparse_retriever,
                                       manifest=runtime.manifest, config=runtime.config.retrieval,
                                       graph_retriever=None if all_failed else graph)
        if scenario == "mixed" and index == len(cases)*5 + 1:
            record = next(item for item in runtime.manifest.list_records() if item.document_id in case["document_ids"])
            rebuilt = runtime.index_service.reindex_document(record.document_id)
            if rebuilt.status is not IndexStatus.READY:
                raise RuntimeError(rebuilt.error)
        try:
            result = service.retrieve(case["query"], **kwargs)
            verified = verify_result(runtime, result, filters)
        except RagRetrievalError as exc:
            if all_failed and "injected channel fault" in str(exc):
                return {"expected_failure": "all_channels_failed", "citations": 0}
            if scenario == "mixed" and "active generation" in str(exc):
                return {"expected_failure": "stale_evidence_refused", "citations": 0}
            raise
        if case.get("denied") and result.candidates:
            raise ValueError("scope violation")
        if not case.get("denied") and not result.candidates:
            raise ValueError("functional positive case returned no evidence")
        if injected and not result.metadata.get("fallback_reason"):
            raise ValueError("fault degradation was not reported")
        return {**verified, "case_id": case["case_id"], "fallback": result.metadata.get("fallback_reason", ""),
                "cache_hit": result.metadata.get("embedding_cache_hit", False)}
    return operation


def main():
    parser = argparse.ArgumentParser(description="Run real-model functional profile checks; quality acceptance is deferred.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="data/benchmarks/rag-final/final")
    args = parser.parse_args()
    runtime, _graph, cases, hashes = build_functional_runtime(args.manifest)
    rows = []
    try:
        for name, (dense, sparse, use_graph, rerank) in PROFILES.items():
            for case in cases:
                filters = VectorSearchFilter(document_ids=case["document_ids"])
                result = runtime.retrieval_service.retrieve(case["query"], filters=filters, dense_enabled=dense,
                                                            sparse_enabled=sparse, graph_enabled=use_graph, reranker_enabled=rerank,
                                                            structural_enabled=False, small_to_big_enabled=False, trace_id=f"final-{name}-{case['case_id']}")
                verified = verify_result(runtime, result, filters)
                if bool(result.candidates) == bool(case.get("denied")):
                    raise ValueError(f"functional result mismatch: {name}/{case['case_id']}")
                if use_graph and not case.get("denied") and not result.metadata["graph_hits"]:
                    raise ValueError("positive graph fixture did not return a grounded graph hit")
                rows.append({"profile": name, "case_id": case["case_id"], **verified,
                             "elapsed_ms": result.elapsed_ms,
                             "metadata": result.metadata, "candidates": [item.model_dump(mode="json") for item in result.candidates]})
        destination = Path(args.output)
        if (destination / "manifest.json").exists():
            raise FileExistsError("final output is immutable; choose a new output directory")
        atomic_write_jsonl(destination / "per_case.jsonl", rows)
        report = {"status": "PASS_FUNCTIONAL", "quality_acceptance": "deferred", "holdout_used": False,
                  "input_kind": "synthetic_functional_fixture_real_models_and_storage", "requests": len(rows),
                  "profiles": list(PROFILES), "fingerprints": hashes,
                  "source_extraction": "frozen S07 live-provider output, revalidated by current GraphExtractor",
                  "production_defaults_changed": False}
        atomic_write_json(destination / "manifest.json", report)
        print(json.dumps(report))
        return 0
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
