from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.research.evidence_ledger import EvidenceLedgerStore
from app.research.memory import (
    ResearchMemoryClaimDraft,
    ResearchMemoryEntityDraft,
    ResearchMemoryExtractionDraft,
    ResearchMemoryRelationDraft,
    ResearchMemoryStore,
)
from app.research.memory_reliability import ResearchMemoryReliabilityStore
from app.research.notes import ResearchNoteStore
from app.research.workspaces import ResearchWorkspaceStore
from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.evidence_ledger import (
    EvidenceLedgerAgentTools,
    SaveEvidenceLedgerArgs,
    SearchEvidenceLedgerArgs,
    build_evidence_ledger_tool_definitions,
)
from backend.models.agent_runtime import AgentRouteDecision
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.cross_document_research_service import CrossDocumentResearchService
from backend.services.evidence_ledger_service import EvidenceLedgerService
from backend.services.product_agent_service import ProductAgentService
from backend.services.research_memory_service import ResearchMemoryService
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService


class _NoopExtractor:
    def close(self) -> None:
        return None


class _CaptureGroundedSynthesis:
    prompt_id = "stage19-grounded@1"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_verified(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            answer=SimpleNamespace(
                output_text="Grounded Evidence Ledger answer.",
                provider="test",
                model="test-grounded",
                request_id=int(kwargs.get("request_id", 0) or 0),
            ),
            verification=None,
            fallback_applied=False,
        )


class _UnusedChatService:
    prompt_id = "unused"

    def send(self, **_kwargs):
        raise AssertionError("Ungrounded chat synthesis must not be used.")

    def close(self) -> None:
        return None


def _services(tmp_path: Path):
    workspaces = ResearchWorkspaceService(
        ResearchWorkspaceStore(storage_path=tmp_path / "workspaces.sqlite3")
    )
    notes = ResearchNoteService(
        ResearchNoteStore(storage_path=tmp_path / "notes.sqlite3"),
        workspace_service=workspaces,
    )
    revisions = ResearchMemoryReliabilityStore(
        storage_path=tmp_path / "memory-reliability.sqlite3"
    )
    memory = ResearchMemoryService(
        ResearchMemoryStore(storage_path=tmp_path / "memory.sqlite3"),
        research_note_service=notes,
        workspace_service=workspaces,
        extraction_service=_NoopExtractor(),
        reliability_store=revisions,
    )
    cross = CrossDocumentResearchService(
        research_memory_service=memory,
        research_note_service=notes,
    )
    ledger_store = EvidenceLedgerStore(storage_path=tmp_path / "ledger.sqlite3")
    ledger = EvidenceLedgerService(
        store=ledger_store,
        research_memory_service=memory,
        cross_document_service=cross,
    )
    return workspaces, notes, memory, revisions, cross, ledger_store, ledger


def _save_claim(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    resource_url: str,
    resource_title: str,
    claim_text: str,
):
    note = notes.save(
        source_text=f"Evidence sentence: {claim_text}",
        resource_url=resource_url,
        resource_title=resource_title,
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=ResearchMemoryExtractionDraft(
            claims=(
                ResearchMemoryClaimDraft(
                    text=claim_text,
                    claim_type="result",
                    confidence=0.93,
                    evidence_excerpt=claim_text,
                ),
            ),
            extractor_version="stage19-test",
            prompt_id="stage19-test",
        ),
    )
    return note


def _save_relation(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    resource_url: str,
    resource_title: str,
    target: str,
):
    excerpt = f"Controller defined_as {target}"
    note = notes.save(
        source_text=f"{excerpt}.",
        resource_url=resource_url,
        resource_title=resource_title,
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=ResearchMemoryExtractionDraft(
            claims=(
                ResearchMemoryClaimDraft(
                    text=f"Controller defined_as {target}.",
                    claim_type="definition",
                    confidence=0.95,
                    evidence_excerpt=excerpt,
                ),
            ),
            entities=(
                ResearchMemoryEntityDraft(
                    canonical_name="Controller",
                    entity_type="concept",
                ),
                ResearchMemoryEntityDraft(
                    canonical_name=target,
                    entity_type="concept",
                ),
            ),
            relations=(
                ResearchMemoryRelationDraft(
                    subject="Controller",
                    predicate="defined_as",
                    object=target,
                    claim_index=0,
                    confidence=0.95,
                ),
            ),
            extractor_version="stage19-test",
            prompt_id="stage19-test",
        ),
    )
    return note


def _seed_agreement(tmp_path: Path):
    services = _services(tmp_path)
    workspaces, notes, memory, _revisions, cross, _store, ledger = services
    workspace_id = workspaces.create(name="Stage 19 agreement").workspace.workspace_id
    claim = "The proposed controller reduced tracking error."
    note_a = _save_claim(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        claim_text=claim,
    )
    note_b = _save_claim(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-b.pdf",
        resource_title="Paper B",
        claim_text=claim,
    )
    analysis = cross.analyze(workspace_id=workspace_id, query="tracking error")
    assert analysis.agreement_count == 1
    return services, workspace_id, note_a, note_b, analysis


def test_capture_agreement_creates_supported_claim_and_is_idempotent(tmp_path: Path) -> None:
    services, workspace_id, _note_a, _note_b, analysis = _seed_agreement(tmp_path)
    _workspaces, _notes, _memory, _revisions, _cross, store, ledger = services

    first_ids = ledger.capture_analysis(analysis)
    first = ledger.snapshot(workspace_id=workspace_id, query="tracking")
    first_validation = store.latest_validation(first_ids[0])
    second_ids = ledger.capture_analysis(analysis)
    second = ledger.snapshot(workspace_id=workspace_id, query="tracking")
    second_validation = store.latest_validation(second_ids[0])

    assert first_ids == second_ids
    assert first.entry_count == 1
    assert first.supported_count == 1
    assert first.items[0].validation.supporting_document_count == 2
    assert second.supported_count == 1
    assert first_validation is not None and second_validation is not None
    assert first_validation.validation_id == second_validation.validation_id


def test_stale_sources_downgrade_supported_claim_without_rewriting_ledger(tmp_path: Path) -> None:
    services, workspace_id, note_a, note_b, analysis = _seed_agreement(tmp_path)
    _workspaces, _notes, _memory, revisions, _cross, _store, ledger = services
    entry_id = ledger.capture_analysis(analysis)[0]
    assert ledger.get(workspace_id=workspace_id, entry_id=entry_id).validation.status == "supported"

    revisions.record_source_revision(
        workspace_id=workspace_id,
        note_id=note_b.note_id,
        source_fingerprint="stage19-stale-b",
    )
    one_stale = ledger.get(workspace_id=workspace_id, entry_id=entry_id)
    assert one_stale is not None
    assert one_stale.validation.status == "insufficient"
    assert one_stale.validation.supporting_document_count == 1
    assert one_stale.validation.stale_link_count == 1

    revisions.record_source_revision(
        workspace_id=workspace_id,
        note_id=note_a.note_id,
        source_fingerprint="stage19-stale-a",
    )
    all_stale = ledger.get(workspace_id=workspace_id, entry_id=entry_id)
    assert all_stale is not None
    assert all_stale.validation.status == "stale"
    assert all_stale.validation.stale_link_count == 2


def test_replaced_structured_memory_marks_old_provenance_missing(tmp_path: Path) -> None:
    services, workspace_id, note_a, note_b, analysis = _seed_agreement(tmp_path)
    _workspaces, _notes, memory, _revisions, _cross, _store, ledger = services
    entry_id = ledger.capture_analysis(analysis)[0]

    for note in (note_b,):
        memory.persist_extraction(
            workspace_id=workspace_id,
            note_id=note.note_id,
            extraction=ResearchMemoryExtractionDraft(
                claims=(
                    ResearchMemoryClaimDraft(
                        text="A replacement claim with new provenance.",
                        claim_type="result",
                        confidence=0.8,
                        evidence_excerpt="replacement claim",
                    ),
                ),
                extractor_version="stage19-replacement",
                prompt_id="stage19-replacement",
            ),
        )
    partial = ledger.get(workspace_id=workspace_id, entry_id=entry_id)
    assert partial is not None
    assert partial.validation.status == "insufficient"
    assert partial.validation.missing_link_count == 1

    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note_a.note_id,
        extraction=ResearchMemoryExtractionDraft(
            claims=(
                ResearchMemoryClaimDraft(
                    text="Another replacement claim.",
                    claim_type="result",
                    confidence=0.8,
                    evidence_excerpt="replacement claim",
                ),
            ),
            extractor_version="stage19-replacement",
            prompt_id="stage19-replacement",
        ),
    )
    missing = ledger.get(workspace_id=workspace_id, entry_id=entry_id)
    assert missing is not None
    assert missing.validation.status == "stale"
    assert missing.validation.missing_link_count == 2


def test_disagreement_becomes_claim_centered_contested_entries(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions, cross, _store, ledger = _services(tmp_path)
    workspace_id = workspaces.create(name="Stage 19 disagreement").workspace.workspace_id
    _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        target="Method A",
    )
    _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-b.pdf",
        resource_title="Paper B",
        target="Method B",
    )
    analysis = cross.analyze(workspace_id=workspace_id, query="Controller defined")
    assert analysis.disagreement_count == 1

    entry_ids = ledger.capture_analysis(analysis)
    snapshot = ledger.snapshot(workspace_id=workspace_id, query="Controller")

    assert len(entry_ids) == 2
    assert snapshot.entry_count == 2
    assert snapshot.contested_count == 2
    statements = {item.entry.statement for item in snapshot.items}
    assert statements == {
        "Controller defined_as Method A",
        "Controller defined_as Method B",
    }
    for item in snapshot.items:
        assert {link.role for link in item.entry.links} == {"supporting", "conflicting"}
        assert item.validation.supporting_document_count == 1
        assert item.validation.conflicting_document_count == 1


def test_agent_tool_contract_separates_grounded_read_from_confirmed_write(tmp_path: Path) -> None:
    services, workspace_id, _note_a, _note_b, analysis = _seed_agreement(tmp_path)
    _workspaces, notes, memory, _revisions, _cross, _store, ledger = services
    tools = EvidenceLedgerAgentTools(
        evidence_ledger_service=ledger,
        research_memory_service=memory,
        research_note_service=notes,
    )
    search_definition, save_definition = build_evidence_ledger_tool_definitions(tools)

    assert set(search_definition.spec.input_schema) == {"query"}
    assert search_definition.spec.effect == "read"
    assert search_definition.spec.requires_confirmation is False
    assert set(save_definition.spec.input_schema) == {"query"}
    assert save_definition.spec.effect == "write"
    assert save_definition.spec.requires_confirmation is True
    assert save_definition.allows_safe_retry is False

    ledger.capture_analysis(analysis)
    result = tools.search_evidence_ledger(
        AgentToolInvocationContext(workspace_id=workspace_id, request_id=19),
        SearchEvidenceLedgerArgs(query="tracking error"),
    )
    assert result.data is not None
    assert result.data["supported_count"] == 1
    assert len(result.data["evidence"]) == 2
    assert result.data["citations"]
    assert all(
        item["metadata"]["source_verified"] is True
        for item in result.data["evidence"]
    )


def test_product_agent_requires_confirmation_to_persist_ledger(tmp_path: Path) -> None:
    services, workspace_id, _note_a, _note_b, _analysis = _seed_agreement(tmp_path)
    _workspaces, notes, memory, _revisions, cross, _store, ledger = services
    registry = AgentToolRegistry(
        research_note_service=notes,
        research_memory_service=memory,
        cross_document_research_service=cross,
        evidence_ledger_service=ledger,
    )
    service = ProductAgentService(
        registry=registry,
        chat_service=_UnusedChatService(),
    )
    route = AgentRouteDecision(
        kind="tool",
        source="planner",
        intent="save_evidence_ledger",
        tool_name="save_evidence_ledger",
        user_visible_reason="Persist cross-document findings.",
        arguments={"query": "tracking error"},
    )

    pending = service.run(
        _resolved_route=route,
        source_text="",
        user_message="Save these findings to the evidence ledger.",
        workspace_id=workspace_id,
        request_id=19,
    )
    assert pending.status == "confirmation_required"
    assert ledger.snapshot(workspace_id=workspace_id).entry_count == 0

    completed = service.run(
        _resolved_route=route,
        source_text="",
        user_message="Save these findings to the evidence ledger.",
        workspace_id=workspace_id,
        request_id=20,
        confirmed_write_tools=("save_evidence_ledger",),
    )
    assert completed.status == "completed"
    assert completed.tool_result is not None
    assert completed.tool_result.data["saved_entry_count"] == 1
    assert ledger.snapshot(workspace_id=workspace_id).supported_count == 1


def test_product_agent_reads_ledger_through_grounded_pipeline_and_redacts_trace(
    tmp_path: Path,
) -> None:
    services, workspace_id, note_a, note_b, analysis = _seed_agreement(tmp_path)
    _workspaces, notes, memory, _revisions, cross, _store, ledger = services
    ledger.capture_analysis(analysis)
    registry = AgentToolRegistry(
        research_note_service=notes,
        research_memory_service=memory,
        cross_document_research_service=cross,
        evidence_ledger_service=ledger,
    )
    grounded = _CaptureGroundedSynthesis()
    service = ProductAgentService(
        registry=registry,
        chat_service=_UnusedChatService(),
        grounded_synthesis_service=grounded,
    )
    events: list[tuple[str, dict[str, object]]] = []
    route = AgentRouteDecision(
        kind="tool",
        source="planner",
        intent="search_evidence_ledger",
        tool_name="search_evidence_ledger",
        user_visible_reason="Read revalidated research conclusions.",
        arguments={"query": "tracking error"},
    )

    result = service.run(
        event_sink=lambda event_type, payload: events.append((event_type, dict(payload))),
        _resolved_route=route,
        source_text="",
        user_message="What does my evidence ledger say about tracking error?",
        workspace_id=workspace_id,
        request_id=21,
    )

    assert result.output_text == "Grounded Evidence Ledger answer."
    assert {item.source_id for item in result.evidence} == {note_a.note_id, note_b.note_id}
    assert result.citations
    assert len(grounded.calls) == 1
    assert grounded.calls[0]["evidence"]
    tool_results = [payload for name, payload in events if name == "tool_result"]
    assert tool_results
    assert tool_results[-1]["tool_name"] == "search_evidence_ledger"
    assert tool_results[-1]["data"] == {}


def test_ledger_is_workspace_scoped(tmp_path: Path) -> None:
    services, workspace_id, _note_a, _note_b, analysis = _seed_agreement(tmp_path)
    workspaces, _notes, _memory, _revisions, _cross, _store, ledger = services
    ledger.capture_analysis(analysis)
    other_workspace = workspaces.create(name="Other workspace").workspace.workspace_id

    assert ledger.snapshot(workspace_id=workspace_id).entry_count == 1
    assert ledger.snapshot(workspace_id=other_workspace).entry_count == 0
