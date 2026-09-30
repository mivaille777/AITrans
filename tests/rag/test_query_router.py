import pytest

from backend.rag.query_router import RagQueryRouter


@pytest.mark.parametrize(
    ("query", "kind", "rounds", "dense", "graph"),
    [
        ("Find 10.1234/example", "keyword", 1, False, False),
        ("What is GP?", "keyword", 1, False, False),
        ("What is ＧＰ?", "keyword", 1, False, False),
        ("GP是什么模型", "keyword", 1, False, False),
        ("Explain the mechanism", "semantic", 3, True, False),
        ("比较 M10 与 C8", "multi-hop", 3, True, None),
        ("Compare papers across documents", "multi-hop", 3, True, None),
    ],
)
def test_enabled_routes_have_bounded_channels_and_keep_exact_scope(
    query, kind, rounds, dense, graph
):
    scope = ("doc-B", "doc-A")
    route = RagQueryRouter(enabled=True).route(query, allowed_document_ids=scope)
    assert route.query_type == kind
    assert route.max_queries == rounds
    assert route.retrieval_kwargs == {
        "dense_enabled": dense, "sparse_enabled": True, "graph_enabled": graph,
    }
    assert route.document_ids == scope
    assert route.reason


@pytest.mark.parametrize("enabled", [False, True])
def test_empty_scope_fails_closed_even_with_router_disabled(enabled):
    route = RagQueryRouter(enabled=enabled).route("GP", allowed_document_ids=())
    assert route.query_type == "no-answer"
    assert route.should_retrieve is False
    assert route.max_queries == 0
    assert route.document_ids == ()


def test_disabled_route_preserves_existing_channels_and_round_limit():
    route = RagQueryRouter().route("GP", allowed_document_ids=("doc-A",))
    assert route.max_queries == 3
    assert route.retrieval_kwargs == {}
    assert route.reason == "router_disabled"


def test_empty_query_is_not_a_claim_about_corpus_answerability():
    assert not RagQueryRouter(enabled=True).route(" ").should_retrieve
    assert RagQueryRouter(enabled=True).route("An unknown mechanism?").should_retrieve
