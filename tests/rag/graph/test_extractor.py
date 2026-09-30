from __future__ import annotations

from dataclasses import replace

import pytest

from app.ai.errors import AIResponseError
from app.research.memory import (
    ResearchMemoryClaimDraft,
    ResearchMemoryEntityDraft,
    ResearchMemoryExtractionDraft,
    ResearchMemoryRelationDraft,
)
from backend.models.research_memory import ResearchMemoryExtraction
from backend.rag.graph.extractor import GraphExtractionService, GraphExtractor
from backend.rag.source_span import resolve_source_span


class DraftExtractor:
    version = "fixture-v1"
    prompt_id = "fixture.prompt:v1"
    provider_name = "fixture"
    model = "recorded-output"

    def __init__(self, draft):
        self.draft, self.calls = draft, 0

    def extract(self, note):
        self.calls += 1
        return self.draft


def draft(quote="Alpha uses Beta.", *, claim_index=0, source="Alpha", target="Beta"):
    return ResearchMemoryExtractionDraft(
        entities=(
            ResearchMemoryEntityDraft("Alpha", "model"),
            ResearchMemoryEntityDraft("Beta", "model"),
        ),
        claims=(ResearchMemoryClaimDraft(quote, evidence_excerpt=quote),),
        relations=(
            ResearchMemoryRelationDraft(source, "uses", target, claim_index, 0.9),
        ),
    )


def test_relation_resolves_original_text_and_preserves_provider_identity(graph_chunk):
    document, chunk = graph_chunk("Context. Alpha uses Beta. Another sentence.")
    extractor = GraphExtractor(DraftExtractor(draft()))
    result = extractor.extract(chunk, document)

    assert len(result.relations) == 1
    relation = result.relations[0]
    assert (
        resolve_source_span(relation.source_span, document.text) == "Alpha uses Beta."
    )
    assert relation.source_span.start_char == 9
    assert "fixture.prompt:v1" in extractor.version
    assert relation.confidence == 0.9


@pytest.mark.parametrize(
    "text,proposal,reason",
    [
        (
            "Alpha does not use Beta.",
            draft("Alpha does not use Beta."),
            "negated_or_uncertain",
        ),
        ("Alpha may use Beta.", draft("Alpha may use Beta."), "negated_or_uncertain"),
        ("Alpha uses Beta.", draft("Alpha causes Beta."), "missing_evidence"),
        ("Alpha uses Beta.", draft(claim_index=None), "missing_claim"),
        (
            "Alpha uses Beta.",
            draft(target="Alpha", source="Beta"),
            "unsupported_predicate",
        ),
        ("Alpha uses Beta.", draft(target="Invented"), "missing_entity"),
        ("Alpha does not use Beta. Alpha uses Beta.", draft(), None),
    ],
)
def test_unsupported_relations_are_rejected_without_inventing_edges(
    graph_chunk, text, proposal, reason
):
    document, chunk = graph_chunk(text)
    result = GraphExtractor(DraftExtractor(proposal)).extract(chunk, document)
    if reason is None:
        assert len(result.relations) == 1
    else:
        assert result.relations == ()
        assert reason in result.rejected


def test_tables_and_chunks_without_source_span_never_call_model(graph_chunk):
    document, chunk = graph_chunk()
    source = DraftExtractor(draft())
    extractor = GraphExtractor(source)
    for skipped in (
        chunk.model_copy(update={"chunk_type": "table_group"}),
        chunk.model_copy(update={"source_span": None}),
    ):
        assert extractor.extract(skipped, document).relations == ()
    assert source.calls == 0


def test_clipped_quote_does_not_hide_negation(graph_chunk):
    document, chunk = graph_chunk("It is not true that Alpha uses Beta.")
    result = GraphExtractor(DraftExtractor(draft())).extract(chunk, document)
    assert result.relations == ()
    assert "negated_or_uncertain" in result.rejected


def test_ambiguous_alias_never_selects_first_entity(graph_chunk):
    document, chunk = graph_chunk(
        "Alpha (GP) and Gamma (GP) are different. GP uses Beta."
    )
    proposal = replace(
        draft("GP uses Beta.", source="GP"),
        entities=(
            ResearchMemoryEntityDraft("Alpha", "model", ("GP",)),
            ResearchMemoryEntityDraft("Gamma", "model", ("GP",)),
            ResearchMemoryEntityDraft("Beta", "model"),
        ),
    )
    result = GraphExtractor(DraftExtractor(proposal)).extract(chunk, document)
    assert result.relations == ()
    assert "ambiguous_entity" in result.rejected


def test_provider_failure_is_not_successful_empty_graph(graph_chunk):
    class FailedExtractor(DraftExtractor):
        def extract(self, note):
            raise RuntimeError("model unavailable")

    document, chunk = graph_chunk()
    with pytest.raises(RuntimeError, match="model unavailable"):
        GraphExtractor(FailedExtractor(draft())).extract(chunk, document)


@pytest.mark.parametrize(
    "source,target,expected", [("Alpha", "Beta", 1), ("Beta", "Alpha", 0)]
)
def test_passive_uses_preserves_relation_direction(
    graph_chunk, source, target, expected
):
    document, chunk = graph_chunk("Beta is used by Alpha.")
    proposal = draft(chunk.text, source=source, target=target)
    result = GraphExtractor(DraftExtractor(proposal)).extract(chunk, document)
    assert len(result.relations) == expected


def test_predicate_in_another_clause_cannot_ground_a_relation(graph_chunk):
    document, chunk = graph_chunk("Alpha uses Beta, while Gamma measures Delta.")
    proposal = replace(
        draft(chunk.text, target="Delta"),
        entities=(*draft().entities, ResearchMemoryEntityDraft("Delta", "model")),
        relations=(ResearchMemoryRelationDraft("Alpha", "measures", "Delta", 0, 0.9),),
    )
    result = GraphExtractor(DraftExtractor(proposal)).extract(chunk, document)
    assert result.relations == ()


@pytest.mark.parametrize("persistent", [False, True])
def test_invalid_model_evidence_has_one_bounded_retry(graph_chunk, persistent):
    class InvalidEvidenceExtractor(DraftExtractor):
        def extract(self, note):
            self.calls += 1
            if self.calls == 1 or persistent:
                raise AIResponseError(
                    "Research-memory claim 0 evidence is not a verbatim source excerpt."
                )
            return self.draft

    document, chunk = graph_chunk()
    source = InvalidEvidenceExtractor(draft())
    extractor = GraphExtractor(source)
    if persistent:
        with pytest.raises(AIResponseError, match="verbatim"):
            extractor.extract(chunk, document)
    else:
        result = extractor.extract(chunk, document)
        assert len(result.relations) == 1
        assert "extraction_validation_retry" in result.rejected
    assert source.calls == 2


@pytest.mark.parametrize(
    "text,quote,expected",
    [
        ("Alpha uses\nBeta.", "Alpha uses Beta.", "Alpha uses\nBeta."),
        ("Alpha uses\nBeta. Alpha uses\tBeta.", "Alpha uses Beta.", None),
        ("Alpha uses\nBeta.", "Alpha improves Beta.", None),
    ],
)
def test_graph_evidence_whitespace_mapping_is_unique_and_verbatim(
    text, quote, expected
):
    extraction = ResearchMemoryExtraction.model_validate(
        {
            "claims": [{"text": "claim", "evidence_excerpt": quote}],
            "entities": [],
            "relations": [],
        }
    )
    if expected is None:
        with pytest.raises(AIResponseError, match="verbatim"):
            GraphExtractionService._verify_claim_evidence(extraction, source_text=text)
    else:
        GraphExtractionService._verify_claim_evidence(extraction, source_text=text)
        assert extraction.claims[0].evidence_excerpt == expected
