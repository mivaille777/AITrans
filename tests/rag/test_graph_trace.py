from types import SimpleNamespace

import pytest

from backend.models.rag_debug import RagDebugRunRequest
from backend.rag.config import RagConfig
from backend.rag.models import RetrievalResult
from backend.rag.observability import build_rag_trace_events
from backend.rag.query_planner import RagQueryPlan
from backend.services.rag_debug_service import RagDebugService
from backend.services.rag_debug_store_service import RagDebugStoreService


def test_graph_stage_carries_trace_scope_generation_and_paths():
    result = RetrievalResult(query="q", metadata={"graph_enabled": True, "graph_count": 0,
                             "graph_trace": {"seed_ids": ["alpha"], "reason": "no_paths"},
                             "allowed_document_ids": ["d"], "active_generations": {"d": "g"}})
    events = build_rag_trace_events(plan=RagQueryPlan(original_query="q", rewritten_query="q"),
                                    retrievals=[result], merged=result, evidence=[], query_id="root")
    graph = next(event for event in events if event.event_type == "rag_graph_completed")
    assert graph.payload["trace_id"] == "root"
    assert graph.payload["parent_id"] == "root:0"
    assert graph.payload["generations"] == [{"d": "g"}]
    assert graph.payload["graph_trace"][0]["reason"] == "no_paths"
    assert graph.payload["cost"] is None


def test_trace_is_redacted_immutable_and_available_after_restart(tmp_path):
    store = RagDebugStoreService(storage_path=tmp_path / "debug.sqlite3")
    first = RagDebugService(store=store)
    try:
        trace = first.run_trace_sync(RagDebugRunRequest(query="你好"), runtime=SimpleNamespace(config=RagConfig()))
    finally:
        first.close()
    second = RagDebugService(store=store)
    try:
        loaded = second.get_run(trace.run_id)
        assert loaded.trace_id == trace.trace_id
        assert loaded.query == "[redacted]"
        assert loaded.metadata["source_redacted"]
        assert loaded.metadata["snapshot_schema_version"] == 1
    finally:
        second.close()


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_terminal_failure_trace_survives_restart(tmp_path, monkeypatch, status):
    import asyncio

    from backend.services.rag_debug_service import _RunCancelled, wait_for_run_terminal

    store = RagDebugStoreService(storage_path=tmp_path / "debug.sqlite3")
    first = RagDebugService(store=store)
    def fail(**kwargs):
        raise _RunCancelled() if status == "cancelled" else RuntimeError("channel unavailable")
    monkeypatch.setattr(first, "_execute_core", fail)
    try:
        accepted = first.start_trace(RagDebugRunRequest(query="private question"), runtime=SimpleNamespace(config=RagConfig()))
        finished = asyncio.run(wait_for_run_terminal(first, accepted.run_id))
        assert finished.status == status
    finally:
        first.close()
    second = RagDebugService(store=store)
    try:
        restored = second.get_run(accepted.run_id)
        assert restored.status == status
        assert restored.query == "[redacted]"
    finally:
        second.close()
