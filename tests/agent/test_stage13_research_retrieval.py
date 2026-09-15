from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from app.research.notes import ResearchNote
from backend.agent_tools.base import AgentToolExecutionResult, AgentToolSpec
from backend.agent_tools.research import (
    ResearchAgentTools,
    SearchResearchNotesArgs,
    build_research_tool_definitions,
)
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.services.product_agent_service import ProductAgentService
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_source_profile import research_source_id


class StubStore:
    def __init__(self, notes: list[ResearchNote]) -> None:
        self.notes = notes

    def list_recent(self, *, limit: int):
        return self.notes[:limit]


def note(
    note_id: str,
    *,
    title: str,
    section: str,
    text: str,
    user_note: str = "",
    updated_at: str = "2026-08-28T00:00:00+00:00",
) -> ResearchNote:
    return ResearchNote(
        note_id=note_id,
        fingerprint=f"fp-{note_id}",
        created_at="2026-08-27T00:00:00+00:00",
        updated_at=updated_at,
        resource_url=f"file:///{title}.pdf",
        resource_title=title,
        section_heading=section,
        source_kind="pdf_uia",
        source_text=text,
        user_note=user_note,
    )


def test_research_memory_search_ranks_weighted_fields_and_respects_source_scope() -> None:
    title_match = note(
        "note-title",
        title="Gaussian Process Safety",
        section="Background",
        text="A general controller discussion.",
    )
    body_match = note(
        "note-body",
        title="Controller Study",
        section="Methods",
        text="Gaussian process uncertainty guides the safe local search.",
    )
    unrelated = note(
        "note-other",
        title="Actuator Dynamics",
        section="Results",
        text="The actuator lag increased settling time.",
    )
    service = ResearchNoteService(store=StubStore([body_match, unrelated, title_match]))

    matches = service.search("Gaussian Process", limit=10)

    assert [item.note.note_id for item in matches] == ["note-title", "note-body"]
    assert matches[0].score > matches[1].score > 0

    scoped_source = research_source_id(body_match)
    scoped = service.search("Gaussian Process", source_ids=[scoped_source])
    assert [item.note.note_id for item in scoped] == ["note-body"]
    assert all(item.source_id == scoped_source for item in scoped)


def test_search_research_notes_tool_returns_valid_grounding_contract() -> None:
    research_note = note(
        "note-1",
        title="Safety Paper",
        section="3.2 Safe search",
        text="Constraint-aware Gaussian process search limits unsafe candidates.",
        user_note="Important evidence for the safety argument.",
    )
    service = ResearchNoteService(store=StubStore([research_note]))
    tool = ResearchAgentTools(research_note_service=service)

    result = tool.search_research_notes(
        SimpleNamespace(request_id=7),
        SearchResearchNotesArgs(query="Gaussian process safety"),
    )

    assert result.tool_name == "search_research_notes"
    assert result.effect == "read"
    assert result.data is not None
    assert result.data["count"] == 1
    evidence = [AgentEvidenceItem.model_validate(item) for item in result.data["evidence"]]
    citations = [AgentCitationRef.model_validate(item) for item in result.data["citations"]]
    assert evidence[0].evidence_id == "research-note:note-1"
    assert evidence[0].source_type == "research_note"
    assert evidence[0].metadata["has_user_annotation"] is True
    assert citations[0].evidence_ids == ["research-note:note-1"]

    definition = next(
        item
        for item in build_research_tool_definitions(tool)
        if item.spec.name == "search_research_notes"
    )
    assert set(definition.spec.input_schema) == {"query"}
    assert definition.spec.effect == "read"
    assert definition.spec.requires_confirmation is False
    assert definition.allows_safe_retry is True


@dataclass
class CapturingRegistry:
    tool_name: str

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.spec = AgentToolSpec(
            name=self.tool_name,
            title="Search",
            description="Search trusted evidence.",
            category="research",
            effect="read",
            requires_reading_context=False,
            requires_confirmation=False,
            input_schema={"query": {"type": "string", "minLength": 1, "maxLength": 4000}},
        )

    def list_tools(self):
        return (self.spec,)

    def get_tool(self, name: str):
        return self.spec if name == self.tool_name else None

    def validate_planner_arguments(self, name: str, arguments: dict[str, object]):
        assert name == self.tool_name
        return {"query": str(arguments.get("query", "")).strip()}

    def allows_safe_retry(self, name: str):
        assert name == self.tool_name
        return True

    def execute(self, name: str, **payload):
        assert name == self.tool_name
        self.calls.append(dict(payload))
        evidence = AgentEvidenceItem(
            evidence_id="evidence-1",
            source_type="research_note" if name == "search_research_notes" else "knowledge_chunk",
            source_id="source-1",
            title="Grounded source",
            excerpt="Grounded evidence excerpt.",
            score=1.0,
        )
        citation = AgentCitationRef(
            citation_id="citation-1",
            evidence_ids=["evidence-1"],
            label="[1]",
        )
        return AgentToolExecutionResult(
            tool_name=name,
            output_text="retrieved evidence",
            effect="read",
            request_id=int(payload.get("request_id", 0) or 0),
            data={
                "query": payload.get("query", ""),
                "results": [],
                "count": 1,
                "evidence": [evidence.model_dump(mode="json")],
                "citations": [citation.model_dump(mode="json")],
            },
        )


class StubGroundedSynthesis:
    prompt_id = "test.stage13"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_verified(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            answer=SimpleNamespace(
                output_text="Grounded research answer [1]",
                provider="stub",
                model="stub-model",
                request_id=kwargs["request_id"],
            ),
            verification=None,
            fallback_applied=False,
        )


class ExplodingChat:
    prompt_id = "test.chat"

    def send(self, **_kwargs):
        raise AssertionError("grounded retrieval must not use ordinary synthesis")

    def close(self):
        return None


def _payload(**overrides):
    payload = {
        "session_id": "stage13",
        "user_message": "What does my research evidence say about safety?",
        "source_text": "Current reading context.",
        "translated_text": "",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_url": "file:///current.pdf",
        "resource_title": "Current paper",
        "section_heading": "Discussion",
        "context_before": "",
        "context_after": "",
        "source_kind": "knowledge_document",
        "style": "academic",
        "request_id": 11,
        "confirmed_write_tools": [],
    }
    payload.update(overrides)
    return payload


def test_research_search_uses_grounded_synthesis_and_trusted_source_scope() -> None:
    registry = CapturingRegistry("search_research_notes")
    grounded = StubGroundedSynthesis()
    service = ProductAgentService(
        registry=registry,
        chat_service=ExplodingChat(),
        grounded_synthesis_service=grounded,
    )

    result = service.run(
        **_payload(research_source_ids=["source-a", "source-b"]),
        _resolved_route={
            "kind": "tool",
            "source": "planner",
            "intent": "search_research_notes",
            "tool_name": "search_research_notes",
            "user_visible_reason": "Search research memory.",
            "arguments": {"query": "safety evidence"},
        },
    )

    assert result.output_text == "Grounded research answer [1]"
    assert result.evidence and result.citations
    assert registry.calls[0]["source_ids"] == ["source-a", "source-b"]
    assert grounded.calls[0]["evidence"][0].evidence_id == "evidence-1"


def test_trusted_document_scope_replaces_planner_document_scope() -> None:
    registry = CapturingRegistry("search_knowledge_base")
    service = ProductAgentService(
        registry=registry,
        chat_service=ExplodingChat(),
        grounded_synthesis_service=StubGroundedSynthesis(),
    )

    service.run(
        **_payload(knowledge_document_ids=["doc-trusted"]),
        _resolved_route={
            "kind": "tool",
            "source": "planner",
            "intent": "search_knowledge_base",
            "tool_name": "search_knowledge_base",
            "user_visible_reason": "Search documents.",
            "arguments": {"query": "controller", "document_scope": "doc-untrusted"},
        },
    )

    call = registry.calls[0]
    assert call["document_ids"] == ["doc-trusted"]
    assert call["document_scope"] == ""
