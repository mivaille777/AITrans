from __future__ import annotations

from backend.rag.evidence_selection import (
    ContextualEvidenceExcerptProvider,
    EvidenceSelectionService,
)
from backend.rag.models import DocumentChunk, RetrievalCandidate


class _QueryMatchEmbedding:
    dimension = 2
    model_name = "query-match-test-embedding"

    def embed_query(self, _text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0] if "treatment" in text.casefold() else [0.0, 1.0]
            for text in texts
        ]


class _RankPriorityEmbedding(_QueryMatchEmbedding):
    model_name = "rank-priority-test-embedding"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0] if "strong semantic match" in text.casefold() else [0.0, 1.0]
            for text in texts
        ]


def test_evidence_selection_returns_verbatim_spans_and_original_chunk_provenance() -> None:
    source_text = (
        "The treatment improved the measured outcomes. "
        "The control group had no measurable change."
    )
    chunk = DocumentChunk(
        chunk_id="chunk-qasper-1",
        document_id="qasper:validation:paper-1",
        text=source_text,
        title="Evidence paper",
        section_heading="Results",
        chunk_index=0,
        start_char=100,
        end_char=100 + len(source_text),
        token_count=12,
        metadata={
            "benchmark": {
                "source_paragraph_ids": ["qasper:validation:paper-1:p0"]
            }
        },
    )
    candidate = RetrievalCandidate(chunk=chunk, rank=1)
    selector = EvidenceSelectionService(embedding_provider=_QueryMatchEmbedding())

    result = selector.select(
        "Did the treatment improve outcomes?",
        [candidate],
        top_n=1,
        top_k=1,
    )

    assert result.candidate_pool_count == 1
    assert result.extracted_span_count == 2
    assert result.selected_span_count == 1
    selected = result.selected[0]
    assert selected.text == "The treatment improved the measured outcomes."
    assert selected.candidate.chunk.text == source_text[
        selected.start_offset : selected.end_offset
    ]
    assert selected.candidate.chunk.start_char == 100 + selected.start_offset
    assert selected.candidate.chunk.end_char == 100 + selected.end_offset
    assert selected.candidate.chunk.chunk_id == chunk.chunk_id
    assert selected.candidate.metadata["evidence_selection"]["source_chunk_id"] == (
        chunk.chunk_id
    )
    assert selected.score > 0.25


def test_candidate_rank_selection_preserves_retrieval_order_and_source_diversity() -> None:
    candidates = [
        RetrievalCandidate(
            chunk=DocumentChunk(
                chunk_id=f"chunk-{rank}",
                document_id="qasper:validation:paper-1",
                text=text,
                title="Evidence paper",
                section_heading="Results",
                chunk_index=rank,
                start_char=0,
                end_char=len(text),
                token_count=8,
                metadata={"benchmark": {"source_paragraph_ids": [f"p{rank}"]}},
            ),
            rank=rank,
        )
        for rank, text in (
            (1, "Treatment improves a modest outcome."),
            (2, "The strong semantic match reports treatment benefit."),
        )
    ]
    selector = EvidenceSelectionService(
        embedding_provider=_RankPriorityEmbedding(),
    )

    result = selector.select(
        "Does treatment help?",
        candidates,
        top_n=2,
        top_k=2,
        selection_order="candidate_rank",
        max_spans_per_source_chunk=1,
    )

    assert [item.candidate.chunk.chunk_id for item in result.selected] == [
        "chunk-1",
        "chunk-2",
    ]
    assert len({item.candidate.chunk.chunk_id for item in result.selected}) == 2


def test_contextual_excerpts_preserve_qasper_failure_pattern_answer_sentences() -> None:
    translation_source = (
        "The training set is not very large. "
        "A possible method is to simply translate the datasets into other languages, leaving the labels intact. "
        "Since the present study focuses on Spanish tweets, all tweets from the English datasets were translated into Spanish. "
        "This new Spanish data was then added to our training set."
    )
    cases = (
        (
            "What clustering algorithms were used?",
            " ".join(
                [
                    "From 12742 sentences predicted to have label STRENGTH, we extract nouns and cluster them using cosine similarity.",
                    "We repeat this for sentences with predicted label WEAKNESS.",
                    "Tables show representative clusters.",
                    "We also explored clustering sentences directly using CLUTO and Carrot2 Lingo clustering algorithms.",
                    "Carrot2 Lingo discovered 167 clusters.",
                    "We then generated 167 clusters using CLUTO as well.",
                    "CLUTO does not generate cluster labels automatically.",
                    "Table TABREF19 shows the largest 5 clusters by both the algorithms.",
                    "It was observed that the clusters created by CLUTO were more meaningful.",
                    *(["A longer unrelated discussion follows about other work."] * 8),
                ]
            ),
            "CLUTO and Carrot2 Lingo",
        ),
        (
            "What other languages did they translate the data from?",
            translation_source,
            "English datasets were translated into Spanish",
        ),
    )
    provider = ContextualEvidenceExcerptProvider(maximum_excerpt_tokens=180)
    for query, source, answer_fact in cases:
        chunk = DocumentChunk(
            chunk_id="qasper-source",
            document_id="qasper:validation:paper",
            text=source,
            title="QASPER paper",
            section_heading="Results",
            chunk_index=0,
            start_char=100,
            end_char=100 + len(source),
            token_count=500,
        )
        excerpts = provider.extract(query, RetrievalCandidate(chunk=chunk, rank=1))
        assert excerpts
        assert any(answer_fact in excerpt.text for excerpt in excerpts)
        assert all(
            excerpt.text == source[excerpt.start_offset : excerpt.end_offset]
            for excerpt in excerpts
        )
        assert all(len(excerpt.text.split()) <= 180 for excerpt in excerpts)
