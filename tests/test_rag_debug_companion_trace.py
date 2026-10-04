from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import perf_counter, sleep
from types import SimpleNamespace

import pytest

from backend.models.knowledge_access import KnowledgeAccessPolicy
from backend.models.rag_debug import RagDebugCase, RagDebugRunRequest
from backend.rag.config import RagConfig
from backend.rag.index_manifest import IndexManifestRecord, IndexStatus
from backend.rag.models import RetrievalResult
from backend.services.rag_debug_service import RagDebugService
from backend.services.rag_debug_store_service import RagDebugStoreService


def test_debug_stage_durations_and_event_clock_measure_actual_work(monkeypatch, tmp_path):
    from backend.services.rag_debug_service import _RunState

    service = RagDebugService(store=RagDebugStoreService(storage_path=tmp_path / "debug.sqlite3"))

    def retrieve(_query, **_kwargs):
        sleep(0.02)
        return RetrievalResult(query=_query, candidates=[], metadata={
            "embedding_ms": 2.0, "dense_search_ms": 3.0, "sparse_search_ms": 7.0,
        })

    monkeypatch.setattr(service, "_retriever_for_profile", lambda *_args: SimpleNamespace(retrieve=retrieve))
    try:
        trace = service.run_trace_sync(
            RagDebugRunRequest(query="Find evidence", knowledge_access_policy=KnowledgeAccessPolicy.ALWAYS),
            runtime=SimpleNamespace(config=RagConfig()),
        )
        stages = {item.key: item for item in trace.stages}
        assert stages["dense"].elapsed_ms == 5.0
        assert stages["bm25"].elapsed_ms == 7.0
        assert stages["answer"].elapsed_ms == 0.0
        state = _RunState(response=trace, events=[], cancel=Event(), started_clock=perf_counter() - 0.1)
        service._runs[trace.run_id] = state
        service._update_run(trace.run_id, "dense", "complete", {"elapsed_ms": 5.0})
        service._update_run(trace.run_id, "bm25", "complete", {"elapsed_ms": 7.0})
        assert state.events[0].elapsed_ms >= 100.0
        assert state.events[1].elapsed_ms >= state.events[0].elapsed_ms
        assert datetime.fromisoformat(state.events[0].payload["timestamp"]).tzinfo is not None
        assert {item.key: item for item in state.response.stages}["bm25"].elapsed_ms == 7.0
    finally:
        service.close()


def _record_companion_trace(service: RagDebugService, request_id: int = 7) -> str:
    return service.record_companion_route(
        request_id=request_id,
        conversation_id="conversation-1",
        query="private-user-question",
        knowledge_enabled=True,
        document_ids=("doc-1",),
        route="knowledge_search",
        route_reason="knowledge_capability_enabled",
        grounding_policy="evidence",
        retrieval_skipped=False,
        verification_skipped=False,
        retrieval={"original_query": "private-retrieval-query", "total_rag_ms": 12.5},
        evidence=[{"evidence_id": "ev-1", "excerpt": "private-document-excerpt"}],
        citations=[{"citation_id": "cite-1", "label": "[1]"}],
    )


def test_companion_history_survives_restart_with_redacted_source(tmp_path: Path) -> None:
    path = tmp_path / "rag-debug.sqlite3"
    service = RagDebugService(store=RagDebugStoreService(storage_path=path))
    try:
        trace_id = _record_companion_trace(service)
        assert service.list_companion_traces()[0].query == "private-user-question"
        service.update_companion_verification(
            trace_id,
            verification={"passed": False, "reason_codes": ["weak_claim_evidence_overlap"]},
            fallback_applied=True,
        )
    finally:
        service.close()

    restarted = RagDebugService(store=RagDebugStoreService(storage_path=path))
    try:
        trace = restarted.list_companion_traces()[0]
        assert trace.trace_id == trace_id
        assert trace.document_scope == "selected"
        assert trace.route == "knowledge_search"
        assert trace.query == "[redacted]"
        assert trace.retrieval["original_query"] == "[redacted]"
        assert trace.retrieval["total_rag_ms"] == 12.5
        assert trace.evidence == [{"evidence_id": "ev-1", "excerpt": "[redacted]"}]
        assert trace.citations[0]["label"] == "[1]"
        assert trace.verification["reason_codes"] == ["weak_claim_evidence_overlap"]
        assert trace.fallback_applied is True
        snapshot = restarted.store.get_snapshot(f"companion:{trace_id}")
        assert snapshot is not None
        assert "private-" not in str(snapshot)
        trace.verification["passed"] = True
        assert restarted.list_companion_traces()[0].verification["passed"] is False
    finally:
        restarted.close()


def test_companion_verification_can_update_restored_history(tmp_path: Path) -> None:
    path = tmp_path / "rag-debug.sqlite3"
    service = RagDebugService(store=RagDebugStoreService(storage_path=path))
    try:
        trace_id = _record_companion_trace(service)
    finally:
        service.close()
    restarted = RagDebugService(store=RagDebugStoreService(storage_path=path))
    try:
        restarted.update_companion_verification(
            trace_id, verification={"passed": True}, fallback_applied=False,
        )
        snapshot = restarted.store.get_snapshot(f"companion:{trace_id}")
        assert snapshot is not None
        assert snapshot["verification"] == {"passed": True}
    finally:
        restarted.close()


@pytest.mark.parametrize("terminal", ["complete", "error", "cancelled"])
def test_companion_lifecycle_has_real_times_and_survives_restart(tmp_path, terminal):
    path = tmp_path / "debug.sqlite3"
    service = RagDebugService(store=RagDebugStoreService(storage_path=path))
    trace_id = _record_companion_trace(service)
    try:
        service.record_companion_event(trace_id, stage="preparing", status="active")
        service.record_companion_event(trace_id, stage="generating", status="active")
        service.record_companion_event(trace_id, stage="answer", status=terminal,
            metadata={"output_characters": 20})
        service.record_companion_event(trace_id, stage="generating", status="active")
        service.record_companion_route(request_id=7, conversation_id="conversation-7", query="private",
            knowledge_enabled=True, document_ids=("doc-1",), route="knowledge_search", route_reason="ready",
            grounding_policy="evidence", retrieval_skipped=False, verification_skipped=False, trace_id=trace_id)
        assert len(service.list_companion_traces()) == 1
    finally:
        service.close()
    restarted = RagDebugService(store=RagDebugStoreService(storage_path=path))
    try:
        trace = restarted.list_companion_traces()[0]
        spans = trace.retrieval["lifecycle"]
        assert len(spans) == 3
        assert trace.retrieval["answer_status"] == terminal
        assert spans[-1]["status"] == terminal
        for span in spans:
            assert span["parent_id"] == trace_id
            start = datetime.fromisoformat(span["started_at"])
            end = datetime.fromisoformat(span["ended_at"])
            assert start.tzinfo and end >= start
            assert span["elapsed_ms"] == pytest.approx((end - start).total_seconds() * 1000)
            assert span["token_usage"] is None and span["cost"] is None
    finally:
        restarted.close()


def test_companion_history_retention_preserves_other_snapshot_kinds(tmp_path: Path) -> None:
    path = tmp_path / "rag-debug.sqlite3"
    store = RagDebugStoreService(storage_path=path)
    store.save_snapshot("trace:keep", "trace", {"run_id": "keep"})
    store.save_snapshot("badcase:keep", "bad_case", {"case_id": "keep"})
    service = RagDebugService(store=store)
    try:
        trace_ids = [_record_companion_trace(service, index) for index in range(102)]
        oldest_kept = trace_ids[2]
        service.update_companion_verification(
            oldest_kept, verification={"passed": True}, fallback_applied=False,
        )
        assert store.get_snapshot(f"companion:{trace_ids[0]}") is None
        assert store.get_snapshot(f"companion:{trace_ids[1]}") is None
        assert store.get_snapshot("trace:keep") == {"run_id": "keep"}
        assert store.get_snapshot("badcase:keep") == {"case_id": "keep"}
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint"):
            store.save_snapshot("trace:keep", "trace", {"run_id": "replacement"})
    finally:
        service.close()
    restarted = RagDebugService(store=RagDebugStoreService(storage_path=path))
    try:
        history = restarted.list_companion_traces(limit=100)
        assert len(history) == 100
        assert [trace.trace_id for trace in history] == list(reversed(trace_ids[2:]))
        assert history[-1].verification == {"passed": True}
    finally:
        restarted.close()


def test_debug_document_listing_serializes_index_timestamp(tmp_path: Path) -> None:
    service = RagDebugService(
        store=RagDebugStoreService(storage_path=tmp_path / "rag-debug.sqlite3")
    )
    indexed_at = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
    runtime = SimpleNamespace(
        manifest=SimpleNamespace(
            list_records=lambda: [
                IndexManifestRecord(
                    document_id="doc-1",
                    title="Paper",
                    source_uri="file:///paper.pdf",
                    chunk_ids=["chunk-1"],
                    status=IndexStatus.READY,
                    indexed_at=indexed_at,
                )
            ]
        )
    )

    try:
        documents = service.list_documents(runtime)

        assert len(documents) == 1
        assert documents[0].updated_at == indexed_at.isoformat()
    finally:
        service.close()


def test_companion_trace_records_route_retrieval_evidence_and_verification(tmp_path: Path) -> None:
    service = RagDebugService(
        store=RagDebugStoreService(storage_path=tmp_path / "rag-debug.sqlite3")
    )
    try:
        trace_id = service.record_companion_route(
            request_id=7,
            conversation_id="conversation-1",
            query="资料库里的 PID tuning 怎么做",
            knowledge_enabled=True,
            document_ids=(),
            route="knowledge_search",
            route_reason="knowledge_capability_enabled",
            grounding_policy="evidence",
            retrieval_skipped=False,
            verification_skipped=False,
            retrieval={
                "total_rag_ms": 12.5,
                "selected_chunks": [{"chunk_id": "chunk-1"}],
            },
            evidence=[{"evidence_id": "ev-1"}],
            citations=[{"citation_id": "cite-1", "label": "[1]"}],
        )
        service.update_companion_verification(
            trace_id,
            verification={
                "passed": False,
                "reason_codes": ["weak_claim_evidence_overlap"],
            },
            fallback_applied=True,
        )

        trace = service.list_companion_traces(limit=1)[0]
        assert trace.route == "knowledge_search"
        assert trace.document_scope == "all"
        assert trace.retrieval["total_rag_ms"] == 12.5
        assert trace.retrieval["selected_chunks"][0]["chunk_id"] == "chunk-1"
        assert trace.evidence[0]["evidence_id"] == "ev-1"
        assert trace.citations[0]["label"] == "[1]"
        assert trace.verification["reason_codes"] == ["weak_claim_evidence_overlap"]
        assert trace.fallback_applied is True
    finally:
        service.close()


def test_rag_debug_trace_exposes_knowledge_decision_and_scope_when_retrieval_is_skipped(
    tmp_path: Path,
) -> None:
    service = RagDebugService(
        store=RagDebugStoreService(storage_path=tmp_path / "rag-debug.sqlite3")
    )
    try:
        trace = service.run_trace_sync(
            RagDebugRunRequest(
                query="你好",
                knowledge_access_policy=KnowledgeAccessPolicy.AUTO,
            ),
            runtime=SimpleNamespace(config=RagConfig()),
        )

        assert trace.knowledge_decision["should_retrieve"] is False
        assert trace.knowledge_decision["reason_code"] == "current_context_sufficient"
        assert trace.knowledge_scope["strategy"] == "none"
        assert trace.metadata["retrieval_skipped"] is True
        assert trace.metadata["retrieval_round_count"] == 0
        assert {stage.key for stage in trace.stages if stage.status == "skipped"} == {
            "dense",
            "bm25",
            "graph",
            "fusion",
            "rerank",
            "context",
            "answer",
        }
    finally:
        service.close()


def test_rag_debug_evaluation_forces_retrieval_instead_of_auto_gate(
    monkeypatch, tmp_path: Path
) -> None:
    service = RagDebugService(
        store=RagDebugStoreService(storage_path=tmp_path / "rag-debug.sqlite3")
    )
    try:
        dataset = service.store.create_dataset("evaluation")
        service.store.save_case(
            dataset.dataset_id,
            RagDebugCase(
                case_id="answerable",
                query="Which chunk contains the answer?",
                categories=["term"],
                relevant_chunk_ids=["chunk-1"],
            ),
        )
        service.store.save_case(
            dataset.dataset_id,
            RagDebugCase(
                case_id="no-answer",
                query="Which certification number is in the indexed corpus?",
                categories=["no_answer"],
                no_answer=True,
                answerable=False,
            ),
        )
        requests: list[RagDebugRunRequest] = []

        def fake_run_trace(request: RagDebugRunRequest, *, runtime: object):
            del runtime
            requests.append(request)
            candidate = (
                SimpleNamespace(id="chunk-1")
                if request.query.startswith("Which chunk")
                else None
            )
            return SimpleNamespace(
                candidates=[candidate] if candidate is not None else [],
                metadata={},
            )

        monkeypatch.setattr(service, "run_trace_sync", fake_run_trace)
        report = service.evaluate_dataset(
            dataset_id=dataset.dataset_id,
            config_id="default",
            top_k=10,
            case_ids=[],
            runtime=SimpleNamespace(config=RagConfig()),
        )

        assert requests
        policy_by_query = {
            request.query: request.knowledge_access_policy for request in requests
        }
        assert (
            policy_by_query["Which chunk contains the answer?"]
            is KnowledgeAccessPolicy.ALWAYS
        )
        assert (
            policy_by_query["Which certification number is in the indexed corpus?"]
            is KnowledgeAccessPolicy.AUTO
        )
        assert report["retrieval"]["recall_at_10"] == 1.0
        assert report["retrieval"]["no_answer_accuracy"] == 1.0
        assert report["retrieval"]["routing_cases"] == 2
    finally:
        service.close()


def test_debug_evaluation_uses_actual_pre_rerank_order(
    monkeypatch, tmp_path: Path
) -> None:
    service = RagDebugService(
        store=RagDebugStoreService(storage_path=tmp_path / "debug.sqlite3")
    )
    try:
        dataset = service.store.create_dataset("rerank comparison")
        service.store.save_case(
            dataset.dataset_id,
            RagDebugCase(
                case_id="promoted", query="Find evidence", relevant_chunk_ids=["gold"]
            ),
        )
        monkeypatch.setattr(
            service,
            "run_trace_sync",
            lambda *_args, **_kwargs: SimpleNamespace(
                candidates=[SimpleNamespace(id="gold")],
                metadata={"pre_rerank_chunk_ids": ["noise", "gold"]},
            ),
        )
        report = service.evaluate_dataset(
            dataset_id=dataset.dataset_id,
            config_id="default",
            top_k=10,
            case_ids=[],
            runtime=SimpleNamespace(config=RagConfig()),
        )
        assert report["reranker"]["mrr_before"] == 0.5
        assert report["reranker"]["mrr_after"] == 1.0
        assert report["reranker"]["mrr_delta"] == 0.5
    finally:
        service.close()


def test_rag_debug_evaluation_computes_routing_scope_round_and_gate_metrics(
    monkeypatch, tmp_path: Path
) -> None:
    service = RagDebugService(
        store=RagDebugStoreService(storage_path=tmp_path / "rag-debug.sqlite3")
    )
    try:
        dataset = service.store.create_dataset("routing metrics")
        service.store.save_case(
            dataset.dataset_id,
            RagDebugCase(
                case_id="retrieval-needed",
                query="Find the answer",
                categories=["term"],
                relevant_chunk_ids=["chunk-1"],
                expected_retrieval=True,
                expected_scope_document_ids=["doc-a"],
            ),
        )
        service.store.save_case(
            dataset.dataset_id,
            RagDebugCase(
                case_id="context-only",
                query="Hello",
                categories=["no_answer"],
                no_answer=True,
                answerable=False,
                expected_retrieval=False,
            ),
        )

        candidate = SimpleNamespace(id="chunk-1", document_id="doc-a")

        def fake_run_trace(request: RagDebugRunRequest, *, runtime: object):
            del runtime
            if request.knowledge_access_policy is KnowledgeAccessPolicy.AUTO:
                if request.query == "Find the answer":
                    return SimpleNamespace(
                        candidates=[candidate],
                        metadata={
                            "retrieval_skipped": False,
                            "retrieval_round_count": 2,
                            "evidence_gate_rounds": [
                                {"sufficient": False},
                                {"sufficient": True},
                            ],
                            "evidence_sufficient": True,
                        },
                    )
                return SimpleNamespace(
                    candidates=[],
                    metadata={
                        "retrieval_skipped": True,
                        "retrieval_round_count": 0,
                        "evidence_gate_rounds": [],
                        "evidence_sufficient": False,
                    },
                )
            return SimpleNamespace(
                candidates=[candidate],
                metadata={
                    "retrieval_skipped": False,
                    "retrieval_round_count": 1,
                    "total_rag_ms": 1,
                },
            )

        monkeypatch.setattr(service, "run_trace_sync", fake_run_trace)
        report = service.evaluate_dataset(
            dataset_id=dataset.dataset_id,
            config_id="default",
            top_k=10,
            case_ids=[],
            runtime=SimpleNamespace(config=RagConfig()),
        )

        retrieval = report["retrieval"]
        assert retrieval["retrieval_trigger_precision"] == 1.0
        assert retrieval["retrieval_trigger_recall"] == 1.0
        assert retrieval["unnecessary_retrieval_rate"] == 0.0
        assert retrieval["missing_retrieval_rate"] == 0.0
        assert retrieval["scope_violation_rate"] == 0.0
        assert retrieval["second_round_retrieval_rate"] == 1.0
        assert retrieval["evidence_sufficiency_rate"] == 0.5
        assert report["routing"]["scope_checked_candidates"] == 1
    finally:
        service.close()
