from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from backend.agent_core.orchestration.reducer import (
    ArtifactRefConflictError,
    EventIdentityConflictError,
    EvidenceRefConflictError,
    TaskResultConflictError,
    event_fingerprint,
    reduce_artifact_refs,
    reduce_event_fingerprints,
    reduce_event_ids,
    reduce_evidence_refs,
    reduce_task_results,
)
from backend.models.agent_artifacts import ArtifactKind, ArtifactRef, EvidenceRef
from backend.models.agent_tasks import TaskResult

_FRONTIER_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "native-frontier-cases.json").read_text(
        encoding="utf-8"
    )
)


def _result(
    task_id: str,
    attempt_id: str,
    *,
    ordinal: int = 1,
    version: int = 1,
    warning: str = "",
) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        attempt_id=attempt_id,
        attempt_ordinal=ordinal,
        result_version=version,
        status="succeeded",
        warnings=[warning] if warning else [],
        source_versions={f"source:{task_id}": "v1"},
    )


def test_two_instances_of_same_role_are_preserved_by_task_id() -> None:
    a = _result("document-a", "attempt-1")
    b = _result("document-b", "attempt-1")

    reduced = reduce_task_results((), (a, b))

    assert [item.task_id for item in reduced] == ["document-a", "document-b"]
    assert len(reduced) == 2


def test_reducer_is_independent_of_completion_order() -> None:
    results = [
        _result("document-b", "attempt-1"),
        _result("research", "attempt-1"),
        _result("document-a", "attempt-1"),
        _result("document-a", "attempt-2", ordinal=2),
    ]
    expected = [
        (item.task_id, item.attempt_ordinal, item.result_version, item.content_hash)
        for item in reduce_task_results((), results)
    ]

    rng = random.Random(17)
    for _ in range(20):
        shuffled = list(results)
        rng.shuffle(shuffled)
        actual = [
            (item.task_id, item.attempt_ordinal, item.result_version, item.content_hash)
            for item in reduce_task_results((), shuffled)
        ]
        assert actual == expected


def test_duplicate_same_hash_is_idempotent() -> None:
    result = _result("document-a", "attempt-1")
    duplicate = TaskResult.model_validate(result.model_dump(mode="json"))

    reduced = reduce_task_results((result,), (duplicate,))

    assert len(reduced) == 1
    assert reduced[0].content_hash == result.content_hash


def test_same_task_attempt_version_with_different_hash_is_conflict() -> None:
    first = _result("document-a", "attempt-1")
    different = _result(
        "document-a",
        "attempt-1",
        warning="different normalized result",
    )

    with pytest.raises(TaskResultConflictError, match="conflicting task result"):
        reduce_task_results((first,), (different,))


def test_artifact_and_evidence_refs_are_idempotent_stable_and_conflict_checked() -> None:
    artifact_a = ArtifactRef(
        artifact_id="artifact-a",
        version=1,
        kind=ArtifactKind.DOCUMENT_ANALYSIS,
        content_hash="hash-a",
    )
    artifact_b = ArtifactRef(
        artifact_id="artifact-b",
        version=1,
        kind=ArtifactKind.OUTLINE,
        content_hash="hash-b",
    )
    evidence_a = EvidenceRef(
        evidence_id="evidence-a",
        source_id="paper-a",
        source_type="document",
        source_version="v1",
        source_hash="source-hash-a",
    )
    evidence_b = EvidenceRef(
        evidence_id="evidence-b",
        source_id="paper-b",
        source_type="document",
        source_version="v1",
        source_hash="source-hash-b",
    )

    assert reduce_artifact_refs((artifact_b,), (artifact_a, artifact_b)) == (
        artifact_a,
        artifact_b,
    )
    assert reduce_evidence_refs((evidence_b,), (evidence_a, evidence_b)) == (
        evidence_a,
        evidence_b,
    )
    with pytest.raises(ArtifactRefConflictError, match="conflicting artifact ref"):
        reduce_artifact_refs(
            (artifact_a,), (artifact_a.model_copy(update={"content_hash": "other"}),)
        )
    with pytest.raises(EvidenceRefConflictError, match="conflicting evidence ref"):
        reduce_evidence_refs(
            (evidence_a,),
            (evidence_a.model_copy(update={"source_hash": "other"}),),
        )


def test_event_ids_dedupe_and_same_id_fingerprint_conflicts_are_explicit() -> None:
    first = {
        "event_id": "event-a",
        "event_type": "task_completed",
        "run_id": "run-1",
        "task_id": "task-a",
        "sequence": 1,
        "timestamp": "2026-09-01T00:00:00Z",
        "payload": {"status": "succeeded"},
    }
    replay = {**first, "timestamp": "2026-09-02T00:00:00Z"}
    changed = {**first, "payload": {"status": "failed"}}
    event_id, fingerprint = event_fingerprint(first)
    replay_id, replay_fingerprint = event_fingerprint(replay)

    assert event_id == replay_id == "event-a"
    assert fingerprint == replay_fingerprint
    assert reduce_event_ids(("event-b", "event-a"), ("event-a", "event-c")) == (
        "event-a",
        "event-b",
        "event-c",
    )
    assert reduce_event_fingerprints({}, {event_id: fingerprint}) == {
        "event-a": fingerprint
    }
    with pytest.raises(EventIdentityConflictError, match="conflicting event identity"):
        changed_id, changed_fingerprint = event_fingerprint(changed)
        reduce_event_fingerprints(
            {event_id: fingerprint}, {changed_id: changed_fingerprint}
        )


@pytest.mark.parametrize(
    "case",
    [
        item
        for item in _FRONTIER_FIXTURE["cases"]
        if item["id"] in {"same-result-replay", "conflicting-result-replay"}
    ],
    ids=lambda item: item["id"],
)
def test_frontier_fixture_replay_matches_executor_result_merge(case) -> None:
    original = TaskResult(
        task_id=case["task_id"],
        attempt_id=case["attempt_id"],
        status=case["status"],
    )
    replay = TaskResult(
        task_id=case["task_id"],
        attempt_id=case["attempt_id"],
        status=case["status"],
        warnings=case.get("warnings", []),
    )

    if case.get("expect_conflict"):
        with pytest.raises(TaskResultConflictError, match="conflicting task result"):
            reduce_task_results((original,), (replay,))
        return

    reduced = reduce_task_results(
        (original,), (original,) * (case["replay_count"] - 1)
    )
    assert len(reduced) == case["expected_unique_results"]
    assert reduced[0].content_hash == original.content_hash
