from backend.agent_core.orchestration.artifact_store import SQLiteArtifactStore
from backend.agent_core.orchestration.coordinator_memory import CoordinatorMemoryPort
from backend.memory.coordinator import MemoryCoordinator
from backend.memory.repository import SQLiteMemoryRepository
from backend.models.agent_artifacts import (
    ClaimRecord,
    DocumentAnalysisArtifact,
    EvidenceRef,
    VerificationStatus,
)
from backend.models.agent_tasks import ScopeContext
from backend.models.memory import MemoryKind


def scope(workspace_id: str) -> ScopeContext:
    return ScopeContext.issue(
        profile_id="profile-a",
        workspace_id=workspace_id,
        scope_revision=f"scope-{workspace_id}",
    )


def test_real_memory_port_reopens_and_projects_one_snapshot_by_role(tmp_path):
    path = tmp_path / "memory.sqlite3"
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(path))
    coordinator.remember(
        operation_id="global-terms",
        profile_id="profile-a",
        kind=MemoryKind.TERMINOLOGY,
        content="Use RAG as the preferred abbreviation.",
        source_ref="user:message-1",
    )
    coordinator.remember(
        operation_id="workspace-decision",
        profile_id="profile-a",
        workspace_id="workspace-a",
        kind=MemoryKind.RESEARCH_DECISION,
        content="Compare retrieval quality before generation quality.",
        source_ref="user:message-2",
    )

    reopened = CoordinatorMemoryPort(MemoryCoordinator(SQLiteMemoryRepository(path)))
    packet = reopened.load_snapshot(
        profile_id="profile-a",
        scope=scope("workspace-a"),
        run_id="run-a",
    )
    other = reopened.load_snapshot(
        profile_id="profile-a",
        scope=scope("workspace-b"),
        run_id="run-b",
    )

    assert packet["status"] == "ready"
    assert packet["snapshot_id"]
    assert {item["kind"] for item in packet["role_projections"]["writer"]} == {
        "research_decision",
        "terminology",
    }
    assert packet["role_projections"]["language"][0]["kind"] == "terminology"
    assert {item["kind"] for item in other["role_projections"]["writer"]} == {
        "terminology"
    }
    assert "research_decision" not in str(other)


def test_temporary_memory_packet_reads_nothing_and_creates_no_snapshot(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    coordinator = MemoryCoordinator(repository)
    coordinator.remember(
        operation_id="private",
        profile_id="profile-a",
        kind=MemoryKind.WRITING_STYLE,
        content="A UNIQUE PRIVATE STYLE",
        source_ref="user:private",
    )

    packet = coordinator.load_snapshot(
        profile_id="profile-a",
        scope=scope("workspace-a"),
        run_id="temporary-run",
        temporary=True,
    )

    assert packet["status"] == "temporary"
    assert "UNIQUE PRIVATE STYLE" not in str(packet)
    with repository._connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM memory_snapshots WHERE run_id='temporary-run'"
        ).fetchone()[0]
    assert count == 0


def test_verified_artifact_outbox_replays_once_after_delivery_crash(tmp_path):
    artifacts = SQLiteArtifactStore(tmp_path / "artifacts.sqlite3")
    artifact = DocumentAnalysisArtifact(
        artifact_id="analysis-1",
        producer_task_id="document-1",
        scope_ref="scope:workspace-a",
        document_id="paper-1",
        claims=[
            ClaimRecord(
                claim_id="claim-1",
                statement="The verified retrieval decision.",
                evidence_ids=["evidence-1"],
            )
        ],
        evidence_refs=[
            EvidenceRef(
                evidence_id="evidence-1",
                source_id="paper-1",
                source_type="document",
            )
        ],
        verification_status=VerificationStatus.PASSED,
    )
    stored = artifacts.put(artifact)
    other = artifacts.put(
        DocumentAnalysisArtifact(
            artifact_id="analysis-other-workspace",
            producer_task_id="document-other",
            scope_ref="scope:workspace-b",
            document_id="paper-other",
            claims=[
                ClaimRecord(
                    claim_id="claim-other",
                    statement="Other workspace decision.",
                    evidence_ids=["evidence-other"],
                )
            ],
            evidence_refs=[
                EvidenceRef(
                    evidence_id="evidence-other",
                    source_id="paper-other",
                    source_type="document",
                )
            ],
            verification_status=VerificationStatus.PASSED,
        )
    )
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    coordinator = MemoryCoordinator(repository)

    # Simulate memory commit succeeding before the artifact-store delivery
    # acknowledgement. The next delivery must replay the stable operation key.
    first = coordinator.submit_artifact_candidates(
        profile_id="profile-a",
        workspace_id="workspace-a",
        artifacts=[stored],
    )
    assert len(first) == 1
    assert len(artifacts.pending_memory_refs()) == 2

    port = CoordinatorMemoryPort(coordinator, artifact_store=artifacts)
    replay = port.submit_candidates(
        profile_id="profile-a",
        workspace_id="workspace-a",
        artifact_refs=[],
        scope_ref=stored.scope_ref,
    )

    assert len(replay) == 1
    assert replay[0].item_id == first[0].item_id
    assert replay[0].version == 1
    assert [ref.artifact_id for ref in artifacts.pending_memory_refs()] == [
        other.artifact_id
    ]
    with repository._connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 1
        )
