from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.chat.models import ChatContext
from app.ai.errors import AIResponseError
from app.research.memory import (
    ResearchMemoryClaimDraft,
    ResearchMemoryEntityDraft,
    ResearchMemoryExtractionDraft,
    ResearchMemoryRelationDraft,
    ResearchMemoryStore,
)
from app.research.notes import ResearchNoteStore
from app.research.workspaces import ResearchWorkspaceStore
from backend.main import create_app
from backend.services.research_memory_extraction_service import (
    ResearchMemoryExtractionService,
)
from backend.services.research_memory_service import ResearchMemoryService
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService


class _FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.response


class _FakeProvider:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client


class _FakeTextService:
    provider_name = "fake"
    model = "fake-structured-model"

    def __init__(self, response: str) -> None:
        self.client = _FakeClient(response)
        self.provider = _FakeProvider(self.client)

    def close(self) -> None:
        return None


class _StubExtractor:
    def __init__(self, extraction: ResearchMemoryExtractionDraft) -> None:
        self.extraction = extraction
        self.notes: list[str] = []

    def extract(self, note):
        self.notes.append(note.note_id)
        return self.extraction

    def close(self) -> None:
        return None


def _workspace_service(tmp_path: Path) -> ResearchWorkspaceService:
    return ResearchWorkspaceService(
        ResearchWorkspaceStore(storage_path=tmp_path / "workspaces.sqlite3")
    )


def _note_service(
    tmp_path: Path,
    workspaces: ResearchWorkspaceService,
) -> ResearchNoteService:
    return ResearchNoteService(
        ResearchNoteStore(storage_path=tmp_path / "notes.sqlite3"),
        workspace_service=workspaces,
    )


def _draft() -> ResearchMemoryExtractionDraft:
    return ResearchMemoryExtractionDraft(
        claims=(
            ResearchMemoryClaimDraft(
                text="Gaussian-process localization narrows the search region.",
                claim_type="method",
                confidence=0.94,
                evidence_excerpt="Gaussian-process localization narrows the search region",
            ),
        ),
        entities=(
            ResearchMemoryEntityDraft(
                canonical_name="Gaussian process",
                entity_type="model",
                aliases=("GP",),
                description="Statistical localization model.",
            ),
            ResearchMemoryEntityDraft(
                canonical_name="Search region",
                entity_type="concept",
            ),
        ),
        relations=(
            ResearchMemoryRelationDraft(
                subject="GP",
                predicate="narrows",
                object="Search region",
                claim_index=0,
                confidence=0.91,
            ),
        ),
        extractor_version="1.0.0",
        prompt_id="research.memory.extract@1.0.0",
    )


def test_memory_store_persists_grounded_claim_evidence_entity_relation(tmp_path: Path) -> None:
    store = ResearchMemoryStore(storage_path=tmp_path / "memory.sqlite3")
    source_text = (
        "The controller uses bounded refinement. "
        "Gaussian-process localization narrows the search region before refinement."
    )

    record = store.replace_note_memory(
        workspace_id="workspace-a",
        note_id="note-a",
        source_text=source_text,
        extraction=_draft(),
    )
    snapshot = store.snapshot(workspace_id="workspace-a")

    assert record.workspace_id == "workspace-a"
    assert record.note_id == "note-a"
    assert record.extractor_version == "1.0.0"
    assert len(snapshot.extractions) == 1
    assert len(snapshot.claims) == 1
    assert len(snapshot.evidence) == 1
    assert len(snapshot.entities) == 2
    assert len(snapshot.relations) == 1
    evidence = snapshot.evidence[0]
    assert evidence.start_offset >= 0
    assert source_text[evidence.start_offset : evidence.end_offset] == evidence.excerpt
    relation = snapshot.relations[0]
    assert relation.claim_id == snapshot.claims[0].claim_id


def test_reextracting_note_atomically_replaces_claims_without_duplicate_extraction(
    tmp_path: Path,
) -> None:
    store = ResearchMemoryStore(storage_path=tmp_path / "memory.sqlite3")
    source = "Gaussian-process localization narrows the search region. LLM refinement is bounded."
    first = store.replace_note_memory(
        workspace_id="workspace-a",
        note_id="note-a",
        source_text=source,
        extraction=_draft(),
    )
    second = store.replace_note_memory(
        workspace_id="workspace-a",
        note_id="note-a",
        source_text=source,
        extraction=ResearchMemoryExtractionDraft(
            claims=(
                ResearchMemoryClaimDraft(
                    text="LLM refinement is bounded.",
                    claim_type="method",
                    confidence=0.9,
                    evidence_excerpt="LLM refinement is bounded",
                ),
            ),
            entities=(
                ResearchMemoryEntityDraft(
                    canonical_name="Gaussian process",
                    entity_type="model",
                    aliases=("GP", "Gaussian-process"),
                ),
            ),
            extractor_version="1.1.0",
            prompt_id="research.memory.extract@1.1.0",
        ),
    )
    snapshot = store.snapshot(workspace_id="workspace-a")

    assert second.extraction_id == first.extraction_id
    assert len(snapshot.extractions) == 1
    assert [claim.text for claim in snapshot.claims] == ["LLM refinement is bounded."]
    assert len(snapshot.evidence) == 1
    assert len(snapshot.entities) == 2
    gp = next(item for item in snapshot.entities if item.canonical_name == "Gaussian process")
    assert "Gaussian-process" in gp.aliases


def test_extractor_requires_verbatim_source_evidence(tmp_path: Path) -> None:
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "The method reduces error.",
                    "claim_type": "finding",
                    "confidence": 0.8,
                    "evidence_excerpt": "paraphrased evidence not in source",
                }
            ],
            "entities": [],
            "relations": [],
        }
    )
    service = ResearchMemoryExtractionService(_FakeTextService(response))
    note_store = ResearchNoteStore(storage_path=tmp_path / "notes.sqlite3")
    note = note_store.save_context(
        ChatContext(source_text="The proposed method reduces the terminal error.")
    ).note

    with pytest.raises(AIResponseError, match="verbatim source excerpt"):
        service.extract(note)


def test_extractor_accepts_grounded_entities_and_relations(tmp_path: Path) -> None:
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "GP selects an anchor.",
                    "claim_type": "method",
                    "confidence": 0.95,
                    "evidence_excerpt": "GP selects an anchor",
                }
            ],
            "entities": [
                {
                    "canonical_name": "Gaussian process",
                    "entity_type": "model",
                    "aliases": ["GP"],
                    "description": "Statistical model",
                },
                {
                    "canonical_name": "Anchor",
                    "entity_type": "concept",
                    "aliases": [],
                    "description": "Candidate search point",
                },
            ],
            "relations": [
                {
                    "subject": "GP",
                    "predicate": "selects",
                    "object": "Anchor",
                    "claim_index": 0,
                    "confidence": 0.92,
                }
            ],
        }
    )
    text_service = _FakeTextService(response)
    extractor = ResearchMemoryExtractionService(text_service)
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    workspace_id = workspaces.create(name="Structured memory").workspace.workspace_id
    note = notes.save(
        source_text="GP selects an anchor before the local refinement step.",
        resource_title="Paper",
        source_kind="pdf_uia",
        workspace_id=workspace_id,
    ).note

    extraction = extractor.extract(note)

    assert extraction.claims[0].evidence_excerpt == "GP selects an anchor"
    assert extraction.entities[0].canonical_name == "Gaussian process"
    assert extraction.relations[0].subject == "GP"
    assert len(text_service.client.calls) == 1
    assert "untrusted_data" in str(text_service.client.calls[0]["user_prompt"])


def test_memory_service_enforces_workspace_note_membership(tmp_path: Path) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    workspace_a = workspaces.create(name="A").workspace.workspace_id
    workspace_b = workspaces.create(name="B").workspace.workspace_id
    note = notes.save(
        source_text="Workspace A evidence.",
        workspace_id=workspace_a,
    ).note
    service = ResearchMemoryService(
        ResearchMemoryStore(storage_path=tmp_path / "memory.sqlite3"),
        research_note_service=notes,
        workspace_service=workspaces,
        extraction_service=_StubExtractor(_draft()),
    )

    with pytest.raises(ValueError, match="not attached"):
        service.extract_note(workspace_id=workspace_b, note_id=note.note_id)


def test_memory_service_searches_claim_entity_and_relation_within_workspace(
    tmp_path: Path,
) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    workspace_id = workspaces.create(name="Searchable project").workspace.workspace_id
    note = notes.save(
        source_text=(
            "Gaussian-process localization narrows the search region before local refinement."
        ),
        workspace_id=workspace_id,
    ).note
    service = ResearchMemoryService(
        ResearchMemoryStore(storage_path=tmp_path / "memory.sqlite3"),
        research_note_service=notes,
        workspace_service=workspaces,
        extraction_service=_StubExtractor(_draft()),
    )
    service.extract_note(workspace_id=workspace_id, note_id=note.note_id)

    results = service.search(
        workspace_id=workspace_id,
        query="Gaussian process search region",
    )

    assert results
    assert {item.kind for item in results} & {"claim", "entity", "relation"}
    assert all(item.score > 0 for item in results)


def test_deleting_derived_memory_preserves_original_note(tmp_path: Path) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    workspace_id = workspaces.create(name="Preserve sources").workspace.workspace_id
    note = notes.save(
        source_text="Gaussian-process localization narrows the search region.",
        workspace_id=workspace_id,
    ).note
    service = ResearchMemoryService(
        ResearchMemoryStore(storage_path=tmp_path / "memory.sqlite3"),
        research_note_service=notes,
        workspace_service=workspaces,
        extraction_service=_StubExtractor(_draft()),
    )
    service.extract_note(workspace_id=workspace_id, note_id=note.note_id)

    assert service.delete_note_memory(workspace_id=workspace_id, note_id=note.note_id) is True
    assert service.snapshot(workspace_id=workspace_id).claims == ()
    assert notes.get(note.note_id) is not None


def test_fastapi_mounts_stage17_structured_memory_routes() -> None:
    paths = set(create_app().openapi().get("paths", {}))

    assert "/api/research/workspaces/{workspace_id}/memory" in paths
    assert "/api/research/workspaces/{workspace_id}/memory/search" in paths
    assert "/api/research/workspaces/{workspace_id}/memory/notes/{note_id}/extract" in paths
