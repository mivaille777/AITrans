from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.evidence_ledger import router
from backend.api.evidence_ledger_dependencies import get_evidence_ledger_service
from backend.models.evidence_ledger import EvidenceLedgerSnapshot


class _FakeLedgerService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def snapshot(self, *, workspace_id: str, query: str = "", limit: int = 100):
        self.calls.append((workspace_id, query, limit))
        return EvidenceLedgerSnapshot(
            workspace_id=workspace_id,
            query=query,
            entry_count=0,
            items=[],
        )

    def get(self, *, workspace_id: str, entry_id: str):
        _ = (workspace_id, entry_id)
        return None


def _client(service: _FakeLedgerService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_evidence_ledger_service] = lambda: service
    return TestClient(app)


def test_evidence_ledger_read_api_preserves_workspace_query_and_limit() -> None:
    service = _FakeLedgerService()
    client = _client(service)

    response = client.get(
        "/api/research/workspaces/workspace-19/evidence-ledger",
        params={"q": "tracking error", "limit": 25},
    )

    assert response.status_code == 200
    assert response.json()["workspace_id"] == "workspace-19"
    assert service.calls == [("workspace-19", "tracking error", 25)]


def test_evidence_ledger_detail_api_returns_404_for_unknown_entry() -> None:
    service = _FakeLedgerService()
    client = _client(service)

    response = client.get(
        "/api/research/workspaces/workspace-19/evidence-ledger/missing-entry"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Evidence Ledger entry not found."
