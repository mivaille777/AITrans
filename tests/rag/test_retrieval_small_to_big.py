from __future__ import annotations

from backend.rag.config import RagRetrievalConfig
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.retrieval_service import RetrievalService


def chunk(chunk_id: str, index: int, text: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id="paper",
        text=text,
        section_heading="3.2 Method",
        section_path=["3 Methodology", "3.2 Method"],
        chunk_index=index,
        token_count=len(text.split()),
        start_char=index * 100,
        end_char=index * 100 + len(text),
    )


class Embedding:
    model_name = "fake"
    dimension = 2

    def embed_query(self, _query):
        return [1.0, 0.0]

    def embed_documents(self, _texts):
        return []


class VectorStore:
    def __init__(self, candidate):
        self.candidate = candidate

    def search(self, _vector, *, top_k, filters=None):
        _ = (top_k, filters)
        return [self.candidate]


class Sparse:
    def __init__(self, candidate, neighbors):
        self.candidate = candidate
        self.neighbors = neighbors
        self.neighbor_calls = []

    def search(self, _query, top_k, filters=None):
        _ = (top_k, filters)
        return [self.candidate]

    def search_sections(self, headings, top_k, filters=None):
        _ = (headings, top_k, filters)
        return []

    def section_neighbors(self, anchor, radius):
        self.neighbor_calls.append((anchor.chunk_id, radius))
        return self.neighbors


def test_retrieval_preserves_child_rank_and_attaches_synthesis_window() -> None:
    previous = chunk("previous", 0, "previous mechanism context")
    anchor = chunk("anchor", 1, "matched GP localization statement")
    following = chunk("following", 2, "following explanation context")
    hit = RetrievalCandidate(chunk=anchor, dense_score=0.9, sparse_score=2.0, rank=1)
    sparse = Sparse(hit, [previous, anchor, following])
    retrieval = RetrievalService(
        embedding_provider=Embedding(),
        vector_store=VectorStore(hit),
        sparse_retriever=sparse,
        config=RagRetrievalConfig(
            dense_top_k=30,
            sparse_top_k=30,
            fusion_top_k=20,
            final_top_k=8,
            small_to_big_top_k=4,
            small_to_big_neighbor_radius=1,
            small_to_big_max_tokens_per_anchor=100,
        ),
    )

    result = retrieval.retrieve("What is the role of GP?")

    assert [item.chunk.chunk_id for item in result.candidates] == ["anchor"]
    assert result.candidates[0].context_window is not None
    assert [item.chunk_id for item in result.candidates[0].context_window.chunks] == [
        "previous",
        "anchor",
        "following",
    ]
    assert sparse.neighbor_calls == [("anchor", 1)]
    assert result.metadata["small_to_big_expanded_count"] == 1
    assert result.metadata["small_to_big_neighbor_count"] == 2
    assert result.metadata["small_to_big_error"] == ""


def test_context_expansion_failure_does_not_fail_retrieval() -> None:
    anchor = chunk("anchor", 1, "matched statement")
    hit = RetrievalCandidate(chunk=anchor, dense_score=0.9, rank=1)

    class BrokenSparse(Sparse):
        def section_neighbors(self, anchor, radius):
            _ = (anchor, radius)
            raise RuntimeError("neighbor catalog unavailable")

    retrieval = RetrievalService(
        embedding_provider=Embedding(),
        vector_store=VectorStore(hit),
        sparse_retriever=BrokenSparse(hit, []),
        config=RagRetrievalConfig(),
    )

    result = retrieval.retrieve("query")

    assert result.candidates[0].chunk.chunk_id == "anchor"
    assert result.candidates[0].context_window is None
    assert result.metadata["small_to_big_error"] == "neighbor catalog unavailable"
