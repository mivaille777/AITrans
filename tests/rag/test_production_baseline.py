from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import RagChunkingConfig, RagConfig
from backend.rag.evaluation_dataset import load_evaluation_dataset
from backend.rag.index_manifest import IndexManifest
from backend.rag.index_service import IndexService
from backend.rag.models import DocumentChunk
from backend.rag.parsers import parse_document
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse import BM25SparseRetriever
from backend.services.knowledge_library_service import KnowledgeLibraryService
from scripts.rag_production_baseline import (
    FIXTURE_ROOT,
    run_import_smoke_case,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _FixedEmbedding:
    model_name = "fixture-hash-embedding-v1"
    dimension = 4

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


class _MemoryVectorStore:
    def __init__(self) -> None:
        self.chunks: dict[tuple[str | None, str], DocumentChunk] = {}

    def ensure_collection(self) -> None:
        return None

    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        *,
        generation_id: str | None = None,
    ) -> None:
        assert len(chunks) == len(vectors)
        self.chunks.update({(generation_id, chunk.chunk_id): chunk for chunk in chunks})

    def list_chunks(self, *, generation_id: str | None = None):
        return [
            chunk
            for (stored_generation, _chunk_id), chunk in self.chunks.items()
            if stored_generation == generation_id
        ]

    def search(self, *_args, **_kwargs):
        return []

    def delete_document(self, document_id: str, *, generation_id=None) -> None:
        self.chunks = {
            key: chunk
            for key, chunk in self.chunks.items()
            if chunk.document_id != document_id
            or (generation_id is not None and key[0] != generation_id)
        }

    def delete_chunks(self, chunk_ids: list[str], *, generation_id=None) -> None:
        for chunk_id in chunk_ids:
            self.chunks.pop((generation_id, chunk_id), None)

    def get_chunk(self, chunk_id: str, *, generation_id=None) -> DocumentChunk | None:
        return self.chunks.get((generation_id, chunk_id))


def _make_import_pipeline(tmp_path: Path):
    embedding = _FixedEmbedding()
    vector_store = _MemoryVectorStore()
    manifest = IndexManifest(tmp_path / "index_manifest.json")
    sparse = BM25SparseRetriever(tmp_path / "bm25_index.json")
    index = IndexService(
        chunker=StructureAwareChunker(
            RagChunkingConfig(target_tokens=20, overlap_tokens=4, minimum_tokens=3)
        ),
        embedding_provider=embedding,
        vector_store=vector_store,
        manifest=manifest,
        parser=parse_document,
        sparse_retriever=sparse,
    )
    config = RagConfig()
    library = KnowledgeLibraryService(
        index_service=index,
        manifest=manifest,
        config=config,
        embedding_provider=embedding,
        allowed_roots=(tmp_path,),
    )
    retrieval = RetrievalService(
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        config=config.retrieval,
        manifest=manifest,
    )
    return library, retrieval


def test_production_eval_fixture_is_valid_and_deidentified() -> None:
    cases = load_evaluation_dataset(FIXTURE_ROOT / "cases.jsonl")
    chunks = [
        json.loads(line)
        for line in (FIXTURE_ROOT / "chunks.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    chunk_ids = {item["chunk_id"] for item in chunks}
    answerable_ids = {chunk_id for case in cases for chunk_id in case.graded_relevance}

    assert len(cases) == 6
    assert {category for case in cases for category in case.categories} == {
        "term",
        "exact_identifier",
        "cross_section",
        "multilingual",
        "multi_document",
        "no_answer",
    }
    assert answerable_ids == chunk_ids
    assert sum(case.no_answer for case in cases) == 1
    import_case = json.loads(
        (FIXTURE_ROOT / "import-smoke.json").read_text(encoding="utf-8")
    )
    assert import_case["source"] == "synthetic"
    assert all(case.metadata["source"] == "synthetic" for case in cases)


def test_import_smoke_runs_real_parser_index_retrieval_and_citations(
    tmp_path: Path,
) -> None:
    fixture = FIXTURE_ROOT / "import-smoke.txt"
    source = tmp_path / fixture.name
    source.write_bytes(fixture.read_bytes())
    fixture_case = json.loads(
        (FIXTURE_ROOT / "import-smoke.json").read_text(encoding="utf-8")
    )
    library, retrieval = _make_import_pipeline(tmp_path)

    result = run_import_smoke_case(
        source,
        fixture_case["query"],
        library_service=library,
        retrieval_service=retrieval,
        required_term=fixture_case["expected_term"],
    )

    assert result["status"] == "complete"
    assert result["manifest_status"] == "ready"
    assert result["chunk_count"] > 0
    assert result["retrieved_chunk_ids"]
    assert result["retrieved_document_ids"] == [result["document_id"]]
    assert result["expected_term_match_count"] > 0
    assert result["scope_violation_count"] == 0
    assert result["evidence_count"] == len(result["retrieved_chunk_ids"])
    assert result["citations"]
    assert all(citation["evidence_ids"] for citation in result["citations"])
    assert "query" not in result
    assert "excerpt" not in result


def test_production_baseline_fails_nonzero_when_qasper_data_is_missing(
    tmp_path: Path,
) -> None:
    missing_dataset = tmp_path / "missing-qasper.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/rag_production_baseline.py",
            "--mode",
            "qasper",
            "--run-id",
            "missing-data",
            "--output-dir",
            str(tmp_path / "output"),
            "--qasper-raw-json",
            str(missing_dataset),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    artifact = tmp_path / "output" / "missing-data" / "summary.json"
    report = json.loads(artifact.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["results"]["qasper"]["status"] == "failed"
    assert report["errors"][0]["stage"] == "qasper"
