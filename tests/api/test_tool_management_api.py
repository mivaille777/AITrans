from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.tools import get_tool_management_service, router
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.tool_management_service import ToolManagementService


def client():
    app = FastAPI()
    service = ToolManagementService(AgentToolRegistry())
    app.include_router(router)
    app.dependency_overrides[get_tool_management_service] = lambda: service
    return TestClient(app)


def test_catalog_counts_paging_filter_and_unknown():
    c = client()
    full = c.get("/api/tools").json()
    assert full["total"] == len(full["items"])
    assert sum(full["categories"].values()) == full["matched_total"]
    first = c.get("/api/tools?limit=2").json()
    second = c.get(
        "/api/tools", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert {x["tool_id"] for x in first["items"]}.isdisjoint(
        {x["tool_id"] for x in second["items"]}
    )
    assert (
        c.get(
            "/api/tools", params={"q": "other", "cursor": first["next_cursor"]}
        ).status_code
        == 409
    )
    assert c.get("/api/tools?q=search&category=knowledge").json()["matched_total"] == 1
    assert c.get("/api/tools?status=disabled").json()["matched_total"] == 0
    assert c.get("/api/tools?cursor=invalid").status_code == 422
    assert c.get("/api/tools/builtin:missing").status_code == 404


def test_schema_and_context_keep_native_profile_separate():
    c = client()
    detail = c.get("/api/tools/builtin:search_knowledge_base").json()
    assert detail["input_schema"]["required"] == ["query"]
    assert detail["output_schema"]["$defs"]
    assert detail["input_profiles"]["native_chat"]["required"] == [
        "query",
        "document_ids",
        "top_k",
    ]
    assert "knowledge_scope" in detail["context_requirements"]
    assert detail["available"] is False  # Lightweight registry has no retriever.
    read = c.get("/api/tools/builtin:inspect_reading_context").json()
    assert "reading_context" in read["context_requirements"]
    assert read["permissions"]["network_access"] == "not declared"
    assert read["examples"][0]["arguments"] == {}


def test_empty_registry_is_supported():
    class Empty:
        def list_tools(self):
            return ()

    result = ToolManagementService(Empty()).list()
    assert result.total == result.matched_total == 0


def test_all_published_examples_match_the_executor_model():
    registry = AgentToolRegistry(jit_search_read_enabled=True)
    service = ToolManagementService(registry)
    for spec in registry.list_tools():
        definition = registry.get_definition(spec.name)
        for example in service.detail("builtin:" + spec.name).examples:
            definition.args_model.model_validate(example["arguments"], strict=True)
