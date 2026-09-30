from __future__ import annotations

from app.research.memory import ResearchMemoryEntityDraft
from backend.rag.graph.resolver import EntityResolver


def test_explicit_abbreviation_and_full_name_share_grounded_identity():
    resolver = EntityResolver()
    first = ResearchMemoryEntityDraft(
        "GP", "model", ("Gaussian process",), "stochastic model"
    )
    second = ResearchMemoryEntityDraft(
        "Gaussian process", "model", ("ＧＰ",), "stochastic model"
    )
    a = resolver.resolve(first, scope_id="workspace", document_id="paper-a")
    b = resolver.resolve(second, scope_id="workspace", document_id="paper-b")
    assert a.entity_id == b.entity_id
    assert a.canonical_name == "Gaussian process"


def test_same_name_different_type_context_or_scope_remains_separate():
    resolver = EntityResolver()
    entities = [
        (
            "workspace",
            ResearchMemoryEntityDraft("Mercury", "planet", description="solar planet"),
        ),
        (
            "workspace",
            ResearchMemoryEntityDraft("Mercury", "chemical", description="metal"),
        ),
        (
            "workspace",
            ResearchMemoryEntityDraft("Mercury", "planet", description="software name"),
        ),
        (
            "other",
            ResearchMemoryEntityDraft("Mercury", "planet", description="solar planet"),
        ),
    ]
    assert (
        len(
            {
                resolver.resolve(e, scope_id=scope, document_id="paper").entity_id
                for scope, e in entities
            }
        )
        == 4
    )


def test_undetermined_same_name_does_not_merge_across_documents():
    resolver = EntityResolver()
    entity = ResearchMemoryEntityDraft("GP", "model")
    a = resolver.resolve(entity, scope_id="workspace", document_id="a")
    b = resolver.resolve(entity, scope_id="workspace", document_id="b")
    assert a.entity_id != b.entity_id
    assert resolver.resolve(entity, scope_id="workspace", document_id="a") == a
