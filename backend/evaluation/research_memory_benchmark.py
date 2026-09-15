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
from backend.evaluation.research_memory import (
    ResearchMemoryEvaluationBatchResult,
    ResearchMemoryEvaluationExpectation,
    aggregate_research_memory_results,
    evaluate_research_memory_case,
    load_research_memory_evaluation_dataset,
)
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
    return workspaces, notes, memory, revisions


def _relation_draft(*, predicate: str, target: str, excerpt: str):
    return ResearchMemoryExtractionDraft(
        claims=(
            ResearchMemoryClaimDraft(
                text=f"Controller {predicate} {target}.",
                claim_type="definition",
                confidence=0.95,
                evidence_excerpt=excerpt,
            ),
        ),
        entities=(
            ResearchMemoryEntityDraft(canonical_name="Controller", entity_type="concept"),
            ResearchMemoryEntityDraft(canonical_name=target, entity_type="concept"),
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
        extractor_version="stage17.3-benchmark",
        prompt_id="stage17.3-benchmark",
    )


def _persist_relation(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    predicate: str,
    target: str,
):
    excerpt = f"Controller {predicate} {target}"
    note = notes.save(
        source_text=f"Synthetic benchmark source: {excerpt}.",
        resource_title=f"Synthetic {target}",
        section_heading="Benchmark",
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=_relation_draft(
            predicate=predicate,
            target=target,
            excerpt=excerpt,
        ),
    )
    return note


def _prepare_fixture(
    case: ResearchMemoryEvaluationExpectation,
    *,
    root: Path,
) -> tuple[ResearchMemoryService, str]:
    workspaces, notes, memory, revisions = _services(root)
    workspace_id = workspaces.create(name=case.case_id).workspace.workspace_id

    if case.fixture in {"fresh", "legacy", "stale", "orphaned", "detached", "no_match"}:
        note = _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            predicate="defined_as",
            target="Method A",
        )
        if case.fixture == "legacy":
            revisions.delete_source_revision(
                workspace_id=workspace_id,
                note_id=note.note_id,
            )
        elif case.fixture == "stale":
            revisions.record_source_revision(
                workspace_id=workspace_id,
                note_id=note.note_id,
                source_fingerprint="stale-benchmark-revision",
            )
        elif case.fixture == "orphaned":
            notes.delete(note.note_id)
        elif case.fixture == "detached":
            workspaces.detach_note(workspace_id, note.note_id)
        return memory, workspace_id

    if case.fixture == "single_value_conflict":
        for target in ("Method A", "Method B"):
            _persist_relation(
                notes=notes,
                memory=memory,
                workspace_id=workspace_id,
                predicate="defined_as",
                target=target,
            )
        return memory, workspace_id

    if case.fixture in {"multi_value", "taxonomic_multi_value"}:
        predicate = "uses" if case.fixture == "multi_value" else "is_a"
        for target in ("Method A", "Method B"):
            _persist_relation(
                notes=notes,
                memory=memory,
                workspace_id=workspace_id,
                predicate=predicate,
                target=target,
            )
        return memory, workspace_id

    if case.fixture == "entity_only":
        note = notes.save(
            source_text="Synthetic benchmark source with an unlinked entity.",
            resource_title="Synthetic entity source",
            workspace_id=workspace_id,
        ).note
        memory.persist_extraction(
            workspace_id=workspace_id,
            note_id=note.note_id,
            extraction=ResearchMemoryExtractionDraft(
                entities=(
                    ResearchMemoryEntityDraft(
                        canonical_name="Unlinked entity",
                        entity_type="concept",
                        description="Entity without Claim/Evidence provenance.",
                    ),
                ),
                extractor_version="stage17.3-benchmark",
                prompt_id="stage17.3-benchmark",
            ),
        )
        return memory, workspace_id

    if case.fixture == "workspace_isolation":
        other_workspace_id = workspaces.create(
            name=f"{case.case_id}-other"
        ).workspace.workspace_id
        _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            predicate="defined_as",
            target="Method A",
        )
        _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=other_workspace_id,
            predicate="defined_as",
            target="Method B",
        )
        return memory, workspace_id

    if case.fixture == "stale_conflict_peer":
        _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            predicate="defined_as",
            target="Method A",
        )
        stale_note = _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            predicate="defined_as",
            target="Method B",
        )
        revisions.record_source_revision(
            workspace_id=workspace_id,
            note_id=stale_note.note_id,
            source_fingerprint="stale-conflict-peer",
        )
        return memory, workspace_id

    raise ValueError(f"Unknown Stage 17.3 research-memory fixture: {case.fixture}")


def run_stage17_3_research_memory_benchmark(
    dataset_path: str | Path,
) -> ResearchMemoryEvaluationBatchResult:
    cases = load_research_memory_evaluation_dataset(dataset_path)
    results = []
    with TemporaryDirectory(prefix="aitrans-stage17-3-") as temporary:
        root = Path(temporary)
        for index, case in enumerate(cases):
            case_root = root / f"case-{index:02d}"
            case_root.mkdir(parents=True, exist_ok=True)
            service, workspace_id = _prepare_fixture(case, root=case_root)
            results.append(
                evaluate_research_memory_case(
                    case,
                    service=service,
                    workspace_id=workspace_id,
                )
            )
            service.close()
    return aggregate_research_memory_results(tuple(results))


__all__ = ["run_stage17_3_research_memory_benchmark"]
