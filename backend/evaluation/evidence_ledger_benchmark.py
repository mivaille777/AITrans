from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

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
from backend.evaluation.evidence_ledger import (
    EvidenceLedgerEvaluationBatchResult,
    EvidenceLedgerEvaluationExpectation,
    aggregate_evidence_ledger_results,
    evaluate_evidence_ledger_case,
    load_evidence_ledger_evaluation_dataset,
)
from backend.services.cross_document_research_service import CrossDocumentResearchService
from backend.services.evidence_ledger_service import EvidenceLedgerService
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
    ledger_store = EvidenceLedgerStore(storage_path=root / "ledger.sqlite3")
    ledger = EvidenceLedgerService(
        store=ledger_store,
        research_memory_service=memory,
        cross_document_service=cross,
    )
    return workspaces, notes, memory, revisions, cross, ledger_store, ledger


def _persist_claim(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    label: str,
):
    claim = "The proposed controller reduced tracking error."
    note = notes.save(
        source_text=f"Synthetic Stage 19 evidence: {claim}",
        resource_url=f"file:///paper-{label}.pdf",
        resource_title=f"Paper {label.upper()}",
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
                    confidence=0.93,
                    evidence_excerpt=claim,
                ),
            ),
            extractor_version="stage19-benchmark",
            prompt_id="stage19-benchmark",
        ),
    )
    return note


def _persist_relation(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    label: str,
    target: str,
):
    excerpt = f"Controller defined_as {target}"
    note = notes.save(
        source_text=f"Synthetic Stage 19 evidence: {excerpt}.",
        resource_url=f"file:///paper-{label}.pdf",
        resource_title=f"Paper {label.upper()}",
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
                ResearchMemoryEntityDraft(canonical_name="Controller", entity_type="concept"),
                ResearchMemoryEntityDraft(canonical_name=target, entity_type="concept"),
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
            extractor_version="stage19-benchmark",
            prompt_id="stage19-benchmark",
        ),
    )
    return note


def _replace_claim(
    *,
    memory: ResearchMemoryService,
    workspace_id: str,
    note_id: str,
    suffix: str,
) -> None:
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note_id,
        extraction=ResearchMemoryExtractionDraft(
            claims=(
                ResearchMemoryClaimDraft(
                    text=f"Replacement Stage 19 claim {suffix}.",
                    claim_type="result",
                    confidence=0.8,
                    evidence_excerpt="Replacement Stage 19 claim",
                ),
            ),
            extractor_version="stage19-replacement",
            prompt_id="stage19-replacement",
        ),
    )


def _prepare_fixture(
    case: EvidenceLedgerEvaluationExpectation,
    *,
    root: Path,
) -> tuple[EvidenceLedgerService, ResearchMemoryService, str]:
    workspaces, notes, memory, revisions, cross, _store, ledger = _services(root)
    workspace_id = workspaces.create(name=case.case_id).workspace.workspace_id

    if case.fixture in {
        "agreement_supported",
        "idempotent_capture",
        "one_stale_source",
        "all_stale_sources",
        "one_provenance_replaced",
        "all_provenance_replaced",
        "workspace_isolation",
        "query_filter",
    }:
        note_a = _persist_claim(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            label="a",
        )
        note_b = _persist_claim(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            label="b",
        )
        analysis = cross.analyze(
            workspace_id=workspace_id,
            query=case.capture_query,
        )
        ledger.capture_analysis(analysis)

        if case.fixture == "idempotent_capture":
            ledger.capture_analysis(analysis)
        elif case.fixture == "one_stale_source":
            revisions.record_source_revision(
                workspace_id=workspace_id,
                note_id=note_b.note_id,
                source_fingerprint="stage19-stale-b",
            )
        elif case.fixture == "all_stale_sources":
            for note, suffix in ((note_a, "a"), (note_b, "b")):
                revisions.record_source_revision(
                    workspace_id=workspace_id,
                    note_id=note.note_id,
                    source_fingerprint=f"stage19-stale-{suffix}",
                )
        elif case.fixture == "one_provenance_replaced":
            _replace_claim(
                memory=memory,
                workspace_id=workspace_id,
                note_id=note_b.note_id,
                suffix="b",
            )
        elif case.fixture == "all_provenance_replaced":
            _replace_claim(
                memory=memory,
                workspace_id=workspace_id,
                note_id=note_a.note_id,
                suffix="a",
            )
            _replace_claim(
                memory=memory,
                workspace_id=workspace_id,
                note_id=note_b.note_id,
                suffix="b",
            )
        elif case.fixture == "workspace_isolation":
            other_workspace = workspaces.create(
                name=f"{case.case_id}-other"
            ).workspace.workspace_id
            _persist_claim(
                notes=notes,
                memory=memory,
                workspace_id=other_workspace,
                label="c",
            )
            _persist_claim(
                notes=notes,
                memory=memory,
                workspace_id=other_workspace,
                label="d",
            )
            ledger.capture_query(
                workspace_id=other_workspace,
                query=case.capture_query,
            )
        return ledger, memory, workspace_id

    if case.fixture in {"disagreement_contested", "disagreement_peer_stale"}:
        note_a = _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            label="a",
            target="Method A",
        )
        note_b = _persist_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            label="b",
            target="Method B",
        )
        ledger.capture_query(
            workspace_id=workspace_id,
            query=case.capture_query,
        )
        _ = note_a
        if case.fixture == "disagreement_peer_stale":
            revisions.record_source_revision(
                workspace_id=workspace_id,
                note_id=note_b.note_id,
                source_fingerprint="stage19-disagreement-stale-b",
            )
        return ledger, memory, workspace_id

    raise ValueError(f"Unknown Stage 19 Evidence Ledger fixture: {case.fixture}")


def run_stage19_evidence_ledger_benchmark(
    dataset_path: str | Path,
) -> EvidenceLedgerEvaluationBatchResult:
    cases = load_evidence_ledger_evaluation_dataset(dataset_path)
    results = []
    with TemporaryDirectory(prefix="aitrans-stage19-") as temporary:
        root = Path(temporary)
        for index, case in enumerate(cases):
            case_root = root / f"case-{index:02d}"
            case_root.mkdir(parents=True, exist_ok=True)
            ledger, memory, workspace_id = _prepare_fixture(case, root=case_root)
            results.append(
                evaluate_evidence_ledger_case(
                    case,
                    service=ledger,
                    workspace_id=workspace_id,
                )
            )
            memory.close()
    return aggregate_evidence_ledger_results(tuple(results))


__all__ = ["run_stage19_evidence_ledger_benchmark"]
