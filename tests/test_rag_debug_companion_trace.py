from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.models.knowledge_access import KnowledgeAccessPolicy
from backend.models.rag_debug import RagDebugRunRequest
from backend.rag.config import RagConfig
from backend.services.rag_debug_service import RagDebugService
from backend.services.rag_debug_store_service import RagDebugStoreService


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
