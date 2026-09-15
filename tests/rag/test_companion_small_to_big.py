from __future__ import annotations

from types import SimpleNamespace

from backend.rag.models import (
    DocumentChunk,
    RetrievalCandidate,
    RetrievalContextWindow,
    RetrievalResult,
)
from backend.services.companion_chat_service import CompanionChatService


class Retrieval:
    def retrieve(self, query, **_kwargs):
        anchor = DocumentChunk(
            chunk_id="anchor",
            document_id="paper",
            title="Paper",
            source_uri="file:///paper.pdf",
            text="anchor child evidence",
            section_heading="3.2 Method",
            section_path=["3 Methodology", "3.2 Method"],
            page_number=5,
            chunk_index=1,
        )
        previous = DocumentChunk(
            chunk_id="previous",
            document_id="paper",
            title="Paper",
            source_uri="file:///paper.pdf",
            text="previous same-section context",
            section_heading="3.2 Method",
            section_path=["3 Methodology", "3.2 Method"],
            page_number=5,
            chunk_index=0,
        )
        following = DocumentChunk(
            chunk_id="following",
            document_id="paper",
            title="Paper",
            source_uri="file:///paper.pdf",
            text="following same-section context",
            section_heading="3.2 Method",
            section_path=["3 Methodology", "3.2 Method"],
            page_number=6,
            chunk_index=2,
        )
        window = RetrievalContextWindow(
            anchor_chunk_id="anchor",
            chunks=[previous, anchor, following],
            text=(
                "previous same-section context\n\n"
                "anchor child evidence\n\n"
                "following same-section context"
            ),
            token_count=9,
            page_start=5,
            page_end=6,
        )
        return RetrievalResult(
            query=query,
            retrieval_strategy="hybrid",
            candidates=[
                RetrievalCandidate(
                    chunk=anchor,
                    rank=1,
                    rerank_score=0.9,
                    context_window=window,
                )
            ],
        )


class Chat:
    prompt_id = "chat.test@1"

    def __init__(self):
        self.request = None

    def execute(self, request):
        self.request = request
        return SimpleNamespace(
            session_id=request.session_id,
            user_message=request.user_message,
            output_text="grounded [1]",
            provider="test",
            model="test",
            request_id=request.request_id,
        )


def test_small_to_big_context_is_internal_while_sources_remain_anchor_only() -> None:
    chat = Chat()
    service = CompanionChatService(
        chat_service=chat,
        retrieval_service=Retrieval(),
    )

    result = service.send(
        session_id="s1",
        user_message="Explain the method",
        context_mode="general",
        knowledge_enabled=True,
    )

    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_id == "evidence:anchor"
    assert result.evidence[0].excerpt == "anchor child evidence"
    assert len(result.citations) == 1
    assert result.citations[0].evidence_ids == ["evidence:anchor"]
    assert "Evidence: anchor child evidence" in chat.request.tool_context
    assert "Supplemental Same-Section Context" in chat.request.tool_context
    assert "not independently citable" in chat.request.tool_context
    assert "previous same-section context" in chat.request.tool_context
    assert "following same-section context" in chat.request.tool_context
    assert "evidence:previous" not in chat.request.tool_context
    assert "evidence:following" not in chat.request.tool_context
