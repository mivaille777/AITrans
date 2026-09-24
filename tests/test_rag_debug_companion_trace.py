from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from backend.models.knowledge_access import KnowledgeAccessPolicy
from backend.models.rag_debug import RagDebugCase, RagDebugRunRequest
from backend.rag.config import RagConfig
from backend.rag.index_manifest import IndexManifestRecord, IndexStatus
from backend.services.rag_debug_service import RagDebugService
from backend.services.rag_debug_store_service import RagDebugStoreService


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
