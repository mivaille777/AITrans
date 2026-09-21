from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.models.companion_routing import CompanionQueryRoute, GroundingPolicy
from backend.services.agent_claim_evidence_verifier import AgentClaimEvidenceVerifier
from backend.services.companion_chat_service import (
    CompanionChatService,
    CompanionKnowledgeGrounding,
)
from backend.services.grounded_synthesis_service import evidence_only_grounding_fallback


class ChatStub:
    prompt_id = "chat.matrix@1"

    def execute(self, request):
        return SimpleNamespace(
            session_id=request.session_id,
            user_message=request.user_message,
            output_text="provider answer",
            provider="stub",
            model="stub-model",
            request_id=request.request_id,
        )


class LibraryStub:
    def list_documents(self):
        return [
            SimpleNamespace(
                document_id="doc-1",
                title="Control Paper",
                status=SimpleNamespace(value="ready"),
                chunk_ids=["c1"],
                section_count=3,
            )
        ]


class MatrixService(CompanionChatService):
    def __init__(self) -> None:
        super().__init__(
            chat_service=ChatStub(),
            knowledge_library_service=LibraryStub(),
        )
        self.retrieval_calls: list[tuple[str, tuple[str, ...]]] = []

    def prepare_knowledge(
        self,
        query: str,
        document_ids: tuple[str, ...] = (),
        *,
        history: tuple[tuple[str, str], ...] = (),
    ) -> CompanionKnowledgeGrounding:
        _ = history
        self.retrieval_calls.append((query, document_ids))
        evidence = AgentEvidenceItem(
            evidence_id="ev-1",
            source_type="knowledge",
            source_id="doc-1",
            title="Control Paper",
            location="Section 3",
            excerpt="Bayesian optimization improves sample efficiency.",
        )
        citation = AgentCitationRef(
            citation_id="cite-1",
            evidence_ids=["ev-1"],
            label="[1]",
        )
        return CompanionKnowledgeGrounding(
            evidence=(evidence,),
            citations=(citation,),
            tool_context="[1] Control Paper evidence.",
            debug_metadata={"total_rag_ms": 12.5},
        )


@pytest.mark.parametrize(
    (
        "query",
        "knowledge_enabled",
        "source_text",
        "document_ids",
        "expected_route",
        "expected_policy",
        "expected_use_knowledge",
    ),
    [
        ("我是谁", False, "", (), CompanionQueryRoute.SYSTEM_IDENTITY, GroundingPolicy.NONE, False),
        ("我是谁", True, "", (), CompanionQueryRoute.SYSTEM_IDENTITY, GroundingPolicy.NONE, False),
        ("你好", False, "", (), CompanionQueryRoute.GENERAL, GroundingPolicy.NONE, False),
        ("资料库里有什么？", True, "", (), CompanionQueryRoute.KNOWLEDGE_CATALOG, GroundingPolicy.MANIFEST, False),
        ("资料库里的 PID tuning 怎么做", True, "", (), CompanionQueryRoute.KNOWLEDGE_SEARCH, GroundingPolicy.EVIDENCE, True),
        ("解释 PID tuning", True, "", ("doc-1",), CompanionQueryRoute.DOCUMENT_SCOPED_SEARCH, GroundingPolicy.EVIDENCE, True),
        ("总结这段文字", True, "bounded reading context", (), CompanionQueryRoute.READING_CONTEXT, GroundingPolicy.NONE, False),
    ],
)
def test_companion_capability_routing_matrix(
    query: str,
    knowledge_enabled: bool,
    source_text: str,
    document_ids: tuple[str, ...],
    expected_route: CompanionQueryRoute,
    expected_policy: GroundingPolicy,
    expected_use_knowledge: bool,
) -> None:
    service = MatrixService()

    prepared = service.prepare_execution(
        query=query,
        knowledge_enabled=knowledge_enabled,
        document_ids=document_ids,
        context_mode="reading" if source_text else "general",
        source_text=source_text,
    )

    assert prepared.plan.route is expected_route
    assert prepared.plan.grounding_policy is expected_policy
    assert prepared.plan.use_knowledge is expected_use_knowledge
    if expected_use_knowledge:
        assert service.retrieval_calls == [(query, document_ids)]
    else:
        assert service.retrieval_calls == []


def test_all_documents_scope_survives_identity_then_enables_next_knowledge_query() -> None:
    service = MatrixService()

    identity = service.prepare_execution(
        query="我是谁",
        knowledge_enabled=True,
        document_ids=(),
        context_mode="general",
    )
    knowledge = service.prepare_execution(
        query="资料库里的 PID tuning 怎么做",
        knowledge_enabled=True,
        document_ids=(),
        context_mode="general",
    )

    assert identity.plan.route is CompanionQueryRoute.SYSTEM_IDENTITY
    assert identity.plan.use_knowledge is False
    assert knowledge.plan.route is CompanionQueryRoute.KNOWLEDGE_SEARCH
    assert knowledge.plan.document_ids == ()
    assert service.retrieval_calls == [
        ("资料库里的 PID tuning 怎么做", ())
    ]


def test_verifier_failure_replaces_generated_claim_with_bounded_evidence() -> None:
    evidence = [
        AgentEvidenceItem(
            evidence_id="ev-1",
            source_type="knowledge",
            source_id="doc-1",
            title="Control Paper",
            location="Section 3",
            excerpt="The GP constrains the broad search region.",
        )
    ]
    citations = [
        AgentCitationRef(
            citation_id="cite-1",
            evidence_ids=["ev-1"],
            label="[1]",
        )
    ]
    generated = "The GP guarantees global optimality and removes all safety constraints [1]."

    verification = AgentClaimEvidenceVerifier().verify(
        output_text=generated,
        evidence=evidence,
        citations=citations,
    )
    fallback = evidence_only_grounding_fallback(
        evidence=evidence,
        citations=citations,
    )

    assert verification.passed is False
    assert verification.reason_codes
    assert "guarantees global optimality" not in fallback
    assert "Control Paper" in fallback
    assert "Section 3" in fallback
    assert "[1]" in fallback
