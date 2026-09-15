from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

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
from backend.evaluation.cross_document_research import (
    CrossDocumentEvaluationBatchResult,
    CrossDocumentEvaluationExpectation,
    aggregate_cross_document_results,
    evaluate_cross_document_case,
    load_cross_document_evaluation_dataset,
)
from backend.services.cross_document_research_service import CrossDocumentResearchService
from backend.services.research_memory_service import ResearchMemoryService
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService


class _NoopExtractor:
    def close(self) -> None:
        return None


def _services(root: Path):
    workspaces = ResearchWorkspaceService(
        ResearchWorkspaceStore(storage_path=root / "workspaces.sqlite3")
    )
    notes = ResearchNoteService(
        ResearchNoteStore(storage_path=root / "notes.sqlite3"),
        workspace_service=workspaces,
    )
    revisions = ResearchMemoryReliabilityStore(
        storage_path=root / "memory-reliability.sqlite3"
    )
    memory = ResearchMemoryService(
        ResearchMemoryStore(storage_path=root / "memory.sqlite3"),
        research_note_service=notes,
        workspace_service=workspaces,
        extraction_service=_NoopExtractor(),
        reliability_store=revisions,
    )
    cross = CrossDocumentResearchService(
        research_memory_service=memory,
        research_note_service=notes,
    )
    return workspaces, notes, memory, revisions, cross


def _persist_relation(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    resource_url: str,
    resource_title: str,
    predicate: str,
    target: str,
    suffix: str = "",
):
    excerpt = f"Controller {predicate} {target}"
    note = notes.save(
        source_text=f"Synthetic Stage 18 source: {excerpt}. {suffix}".strip(),
        resource_url=resource_url,
        resource_title=resource_title,
        section_heading=f"Benchmark {suffix}".strip(),
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=ResearchMemoryExtractionDraft(
            claims=(
                ResearchMemoryClaimDraft(
                    text=f"Controller {predicate} {target}.",
                    claim_type="method",
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
                    predicate=predicate,
                    object=target,
                    claim_index=0,
                    confidence=0.95,
                ),
            ),
            extractor_version="stage18-benchmark",
            prompt_id="stage18-benchmark",
        ),
    )
    return note


def _persist_claim(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    resource_url: str,
    resource_title: str,
):
    claim = "The proposed controller reduced tracking error."
    note = notes.save(
        source_text=f"Synthetic Stage 18 source: {claim}",
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
                    text=claim,
                    claim_type="result",
                    confidence=0.9,
                    evidence_excerpt=claim,
                ),
            ),
            extractor_version="stage18-benchmark",
            prompt_id="stage18-benchmark",
        ),
    )
    return note


def _prepare_fixture(
    case: CrossDocumentEvaluationExpectation,
    *,
    root: Path,
) -> tuple[CrossDocumentResearchService, ResearchMemoryService, str]:
    workspaces, notes, memory, revisions, cross = _services(root)
    workspace_id = workspaces.create(name=case.case_id).workspace.workspace_id

    if case.fixture == "exact_claim_agreement":
        for label in ("a", "b"):
            _persist_claim(
                notes=notes,
                memory=memory,
                workspace_id=workspace_id,
                resource_url=f"file:///paper-{label}.pdf",
                resource_title=f"Paper {label.upper()}",
            )
        return cross, memory, workspace_id

    if case.fixture == "same_document_sections":
        for suffix in ("one", "two"):
            _persist_relation(
                notes=notes,
                memory=memory,
                workspace_id=workspace_id,
                resource_url="file:///paper-a.pdf",
                resource_title="Paper A",
                predicate="uses",
                target="Method A",
                suffix=suffix,
            )
        return cross, memory, workspace_id

    if case.fixture in {
        "relation_agreement",
        "stale_peer",
        "detached_peer",
        "no_match",
    }:
        first = _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            resource_url="file:///paper-a.pdf",
            resource_title="Paper A",
            predicate="uses",
            target="Method A",
        )
        second = _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            resource_url="file:///paper-b.pdf",
            resource_title="Paper B",
            predicate="uses",
            target="Method A",
        )
        _ = first
        if case.fixture == "stale_peer":
            revisions.record_source_revision(
                workspace_id=workspace_id,
                note_id=second.note_id,
                source_fingerprint="stage18-stale-peer",
            )
        elif case.fixture == "detached_peer":
            workspaces.detach_note(workspace_id, second.note_id)
        return cross, memory, workspace_id

    if case.fixture in {"cross_document_disagreement", "same_document_conflict"}:
        second_url = (
            "file:///paper-b.pdf"
            if case.fixture == "cross_document_disagreement"
            else "file:///paper-a.pdf"
        )
        second_title = "Paper B" if case.fixture == "cross_document_disagreement" else "Paper A"
        _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            resource_url="file:///paper-a.pdf",
            resource_title="Paper A",
            predicate="defined_as",
            target="Method A",
            suffix="one",
        )
        _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            resource_url=second_url,
            resource_title=second_title,
            predicate="defined_as",
            target="Method B",
            suffix="two",
        )
        return cross, memory, workspace_id

    if case.fixture == "workspace_isolation":
        other_workspace_id = workspaces.create(
            name=f"{case.case_id}-other"
        ).workspace.workspace_id
        _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            resource_url="file:///paper-a.pdf",
            resource_title="Paper A",
            predicate="uses",
            target="Method A",
        )
        _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=other_workspace_id,
            resource_url="file:///paper-b.pdf",
            resource_title="Paper B",
            predicate="uses",
            target="Method A",
        )
        return cross, memory, workspace_id

    if case.fixture == "three_document_agreement":
        for label in ("a", "b", "c"):
            _persist_relation(
                notes=notes,
                memory=memory,
                workspace_id=workspace_id,
                resource_url=f"file:///paper-{label}.pdf",
                resource_title=f"Paper {label.upper()}",
                predicate="uses",
                target="Method A",
                suffix=label,
            )
        return cross, memory, workspace_id

    raise ValueError(f"Unknown Stage 18 cross-document fixture: {case.fixture}")


def run_stage18_cross_document_benchmark(
    dataset_path: str | Path,
) -> CrossDocumentEvaluationBatchResult:
    cases = load_cross_document_evaluation_dataset(dataset_path)
    results = []
    with TemporaryDirectory(prefix="aitrans-stage18-") as temporary:
        root = Path(temporary)
        for index, case in enumerate(cases):
            case_root = root / f"case-{index:02d}"
            case_root.mkdir(parents=True, exist_ok=True)
            cross, memory, workspace_id = _prepare_fixture(case, root=case_root)
            results.append(
                evaluate_cross_document_case(
                    case,
                    service=cross,
                    workspace_id=workspace_id,
                )
            )
            memory.close()
    return aggregate_cross_document_results(tuple(results))


__all__ = ["run_stage18_cross_document_benchmark"]
