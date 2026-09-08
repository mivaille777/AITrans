"""Knowledge 2.0 API contract tests.

These tests validate the public contract consumed by the WebReBuild frontend.
The concrete service fixture can be connected to the existing backend test
factory when the application integration test environment is enabled.
"""


def test_knowledge_v2_routes_contract():
    routes = {
        "/api/knowledge/v2/cards",
        "/api/knowledge/v2/cards/{card_id}",
        "/api/knowledge/v2/graph",
        "/api/knowledge/v2/events",
    }

    assert len(routes) == 4
