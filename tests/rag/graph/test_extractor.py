from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

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
@pytest.mark.parametrize("invalid", ["endpoint", "evidence", "json"])
def test_invalid_model_output_has_one_feedback_retry(graph_chunk, persistent, invalid):
    document, chunk = graph_chunk()
    valid = {
        "claims": [{"text": chunk.text, "evidence_excerpt": chunk.text}],
        "entities": [{"canonical_name": name} for name in ("Alpha", "Beta")],
        "relations": [
            {"subject": "Alpha", "predicate": "uses", "object": "Beta", "claim_index": 0}
        ],
    }
    broken = json.loads(json.dumps(valid))
    if invalid == "endpoint":
        broken["relations"][0]["object"] = "Invented"
    elif invalid == "evidence":
        broken["claims"][0]["evidence_excerpt"] = "Alpha improves Beta."
    broken_raw = "{invalid json" if invalid == "json" else json.dumps(broken)
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return broken_raw if len(calls) == 1 or persistent else json.dumps(valid)

    source = GraphExtractionService(
        SimpleNamespace(provider=SimpleNamespace(client=SimpleNamespace(complete=complete)))
    )
    extractor = GraphExtractor(source)
    if persistent:
        with pytest.raises(AIResponseError, match="verbatim|invalid structured"):
            extractor.extract(chunk, document)
    else:
        result = extractor.extract(chunk, document)
        assert len(result.relations) == 1
        assert resolve_source_span(result.relations[0].source_span, document.text) == chunk.text
    assert len(calls) == 2
    first, repair = (json.loads(call["user_prompt"]) for call in calls)
    assert "validation_feedback" not in first
    assert repair["source_text"] == first["source_text"] == chunk.text
    assert repair["validation_feedback"]["error"]
    assert repair["validation_feedback"]["previous_output"] == broken_raw
    if invalid == "endpoint":
        assert "reference extracted entities" in repair["validation_feedback"]["details"]
        assert "Invented" in repair["validation_feedback"]["details"]


def test_graph_validation_repair_does_not_retry_provider_errors(graph_chunk):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("provider unavailable")

    source = GraphExtractionService(
        SimpleNamespace(provider=SimpleNamespace(client=SimpleNamespace(complete=complete)))
    )
    document, chunk = graph_chunk()
    with pytest.raises(AIResponseError, match="provider failed"):
        GraphExtractor(source).extract(chunk, document)
    assert len(calls) == 1


@pytest.mark.parametrize("unsupported", [False, True])
def test_missing_source_endpoint_preserves_only_grounded_relations(graph_chunk, unsupported):
    text = "Alpha uses Beta. Gamma remains deterministic."
    document, chunk = graph_chunk(text)
    payload = {
        "claims": [{"text": text, "evidence_excerpt": text}],
        "entities": [{"canonical_name": "Alpha"}, {"canonical_name": "Gamma"}],
        "relations": [
            {"subject": "Alpha", "predicate": "uses", "object": "Beta", "claim_index": 0}
        ],
    }
    if unsupported:
        payload["relations"].append(
            {"subject": "Gamma", "predicate": "constrained_to_be",
             "object": "deterministic", "claim_index": 0}
        )
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(payload)

    source = GraphExtractionService(
        SimpleNamespace(provider=SimpleNamespace(client=SimpleNamespace(complete=complete)))
    )
    result = GraphExtractor(source).extract(chunk, document)

    assert len(result.relations) == 1
    relation = result.relations[0]
    assert result.entities[relation.source_index].canonical_name == "Alpha"
    assert result.entities[relation.target_index].canonical_name == "Beta"
    assert resolve_source_span(relation.source_span, document.text) == text
    assert len(calls) == 1
    if unsupported:
        assert "unsupported_predicate" in result.rejected


@pytest.mark.parametrize("invalid", ["invented", "substring", "evidence", "capacity"])
def test_endpoint_completion_cannot_bypass_source_or_schema_checks(graph_chunk, invalid):
    text = "Alpha uses BetaX." if invalid == "substring" else "Alpha uses Beta."
    document, chunk = graph_chunk(text)
    payload = {
        "claims": [{"text": text, "evidence_excerpt":
                    "Invented evidence." if invalid == "evidence" else text}],
        "entities": [{"canonical_name": "Alpha"}],
        "relations": [{"subject": "Alpha", "predicate": "uses",
                       "object": "Invented" if invalid == "invented" else "Beta",
                       "claim_index": 0}],
    }
    if invalid == "capacity":
        payload["entities"].extend({"canonical_name": f"Other{index}"} for index in range(39))
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(payload)

    source = GraphExtractionService(
        SimpleNamespace(provider=SimpleNamespace(client=SimpleNamespace(complete=complete)))
    )
    with pytest.raises(AIResponseError, match="verbatim|invalid structured"):
        GraphExtractor(source).extract(chunk, document)
    assert len(calls) == 2


@pytest.mark.parametrize("quote_id", ["source_quote_0", "source_quote_999"])
def test_graph_repair_resolves_only_supplied_verbatim_excerpt_ids(graph_chunk, quote_id):
    document, chunk = graph_chunk()
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps({
            "claims": [{"text": "Alpha uses Beta.", "evidence_excerpt":
                        "Invented evidence." if len(calls) == 1 else quote_id}],
            "entities": [{"canonical_name": "Alpha", "entity_type": "model"},
                         {"canonical_name": "Beta", "entity_type": "model"}],
            "relations": [{"subject": "Alpha", "object": "Beta",
                           "predicate": "uses", "claim_index": 0}],
        })

    source = GraphExtractionService(
        SimpleNamespace(provider=SimpleNamespace(client=SimpleNamespace(complete=complete)))
    )
    if quote_id == "source_quote_0":
        result = GraphExtractor(source).extract(chunk, document)
        assert len(result.relations) == 1
        assert resolve_source_span(result.relations[0].source_span, document.text) == chunk.text
    else:
        with pytest.raises(AIResponseError, match="verbatim"):
            GraphExtractor(source).extract(chunk, document)
    assert len(calls) == 2
    feedback = json.loads(calls[1]["user_prompt"])["validation_feedback"]
    assert feedback["source_excerpts"]["source_quote_0"] == chunk.text


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
