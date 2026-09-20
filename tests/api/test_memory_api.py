from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.memory import router as memory_router
from backend.api.memory_dependencies import get_memory_coordinator
from backend.memory.coordinator import MemoryCoordinator
from backend.memory.repository import SQLiteMemoryRepository
from backend.models.memory import MemoryCandidate, MemoryKind


def test_explicit_memory_api_is_versioned_scoped_and_forgettable(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    app = FastAPI()
    app.include_router(memory_router)
    app.dependency_overrides[get_memory_coordinator] = lambda: coordinator
    client = TestClient(app)

    created = client.post(
        "/api/memory/items",
        json={
            "operation_id": "api-create-1",
            "kind": "terminology",
            "content": "retrieval-augmented generation => 检索增强生成",
            "workspace_id": "workspace-a",
        },
    )
    assert created.status_code == 201
    item = created.json()
    assert item["profile_id"] == "local-default"
    assert item["version"] == 1

    assert (
        client.get("/api/memory/items", params={"workspace_id": "workspace-b"}).json()[
            "items"
        ]
        == []
    )
    listed = client.get(
        "/api/memory/items", params={"workspace_id": "workspace-a"}
    ).json()["items"]
    assert [entry["item_id"] for entry in listed] == [item["item_id"]]

    updated = client.patch(
        f"/api/memory/items/{item['item_id']}",
        json={
            "operation_id": "api-update-1",
            "expected_version": 1,
            "content": "RAG => 检索增强生成",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    conflict = client.patch(
        f"/api/memory/items/{item['item_id']}",
        json={
            "operation_id": "api-stale-update",
            "expected_version": 1,
            "content": "stale",
        },
    )
    assert conflict.status_code == 409

    forgotten = client.request(
        "DELETE",
        f"/api/memory/items/{item['item_id']}",
        json={"expected_version": 2},
    )
    assert forgotten.status_code == 200
    assert forgotten.json()["status"] == "revoked"
    assert (
        client.get(
            "/api/memory/items",
            params={"workspace_id": "workspace-a", "status": "active"},
        ).json()["items"]
        == []
    )


def test_verified_candidate_requires_explicit_activation(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    candidate = coordinator.submit_candidate(
        MemoryCandidate(
            operation_id="artifact:candidate-1",
            profile_id="local-default",
            workspace_id="workspace-a",
            kind=MemoryKind.RESEARCH_DECISION,
            content="Use the verified benchmark protocol.",
            source_ref="artifact:analysis-1:1",
        )
    )
    app = FastAPI()
    app.include_router(memory_router)
    app.dependency_overrides[get_memory_coordinator] = lambda: coordinator
    client = TestClient(app)

    assert (
        client.get("/api/memory/items", params={"status": "active"}).json()["items"]
        == []
    )
    activated = client.patch(
        f"/api/memory/items/{candidate.item_id}",
        json={
            "operation_id": "activate-candidate-1",
            "expected_version": 1,
            "activate": True,
        },
    )

    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert activated.json()["version"] == 2
