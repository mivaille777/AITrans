from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from backend.models.agent_artifacts import ArtifactRef, EvidenceRef
from backend.models.agent_tasks import TaskResult


class TaskResultConflictError(ValueError):
    pass


class ArtifactRefConflictError(ValueError):
    pass


class EvidenceRefConflictError(ValueError):
    pass


class EventIdentityConflictError(ValueError):
    pass


def _key(result: TaskResult) -> tuple[str, str, int]:
    return (result.task_id, result.attempt_id, result.result_version)


def _sort_key(result: TaskResult) -> tuple[str, int, int, str]:
    return (
        result.task_id,
        result.attempt_ordinal,
        result.result_version,
        result.attempt_id,
    )


def reduce_task_results(
    existing: Iterable[TaskResult],
    incoming: Iterable[TaskResult],
) -> tuple[TaskResult, ...]:
    merged: dict[tuple[str, str, int], TaskResult] = {}
    for result in [*existing, *incoming]:
        key = _key(result)
        previous = merged.get(key)
        if previous is None:
            merged[key] = result.model_copy(deep=True)
            continue
        if previous.content_hash != result.content_hash:
            raise TaskResultConflictError(
                "conflicting task result for "
                f"task={result.task_id}, attempt={result.attempt_id}, "
                f"version={result.result_version}"
            )
    return tuple(sorted(merged.values(), key=_sort_key))


def reduce_artifact_refs(
    existing: Iterable[ArtifactRef | Mapping[str, Any]],
    incoming: Iterable[ArtifactRef | Mapping[str, Any]],
) -> tuple[ArtifactRef, ...]:
    """Merge immutable artifact versions, rejecting identity/hash conflicts."""

    merged: dict[tuple[str, int], ArtifactRef] = {}
    for raw in [*existing, *incoming]:
        artifact = ArtifactRef.model_validate(raw)
        key = (artifact.artifact_id, artifact.version)
        previous = merged.get(key)
        if previous is not None and previous != artifact:
            raise ArtifactRefConflictError(
                "conflicting artifact ref for "
                f"artifact={artifact.artifact_id}, version={artifact.version}"
            )
        merged[key] = artifact
    return tuple(
        item
        for _key_value, item in sorted(
            merged.items(), key=lambda pair: (pair[0][0], pair[0][1])
        )
    )


def reduce_evidence_refs(
    existing: Iterable[EvidenceRef | Mapping[str, Any]],
    incoming: Iterable[EvidenceRef | Mapping[str, Any]],
) -> tuple[EvidenceRef, ...]:
    """Merge evidence identities deterministically and reject divergent refs."""

    merged: dict[str, EvidenceRef] = {}
    for raw in [*existing, *incoming]:
        evidence = EvidenceRef.model_validate(raw)
        previous = merged.get(evidence.evidence_id)
        if previous is not None and previous != evidence:
            raise EvidenceRefConflictError(
                "conflicting evidence ref for "
                f"evidence={evidence.evidence_id}"
            )
        merged[evidence.evidence_id] = evidence
    return tuple(merged[key] for key in sorted(merged))


def reduce_event_ids(existing: Iterable[str], incoming: Iterable[str]) -> tuple[str, ...]:
    """Return a stable, idempotent event-ID set."""

    return tuple(
        sorted(
            {
                str(item).strip()
                for item in [*existing, *incoming]
                if str(item).strip()
            }
        )
    )


def reduce_event_fingerprints(
    existing: Mapping[str, str], incoming: Mapping[str, str]
) -> dict[str, str]:
    """Merge event ID to semantic fingerprint, rejecting ID reuse conflicts."""

    merged = {str(key).strip(): str(value).strip() for key, value in existing.items()}
    for raw_key, raw_fingerprint in incoming.items():
        event_id = str(raw_key).strip()
        fingerprint = str(raw_fingerprint).strip()
        if not event_id or not fingerprint:
            continue
        previous = merged.get(event_id)
        if previous is not None and previous != fingerprint:
            raise EventIdentityConflictError(
                f"conflicting event identity for event_id={event_id}"
            )
        merged[event_id] = fingerprint
    return {key: merged[key] for key in sorted(merged)}


def event_fingerprint(event: Mapping[str, Any]) -> tuple[str, str]:
    """Create a stable hash for an AgentEvent-like record without storing payloads."""

    event_id = str(event.get("event_id", "")).strip()
    if not event_id:
        raise ValueError("event_id is required")
    semantic_fields = (
        "event_type",
        "run_id",
        "trace_id",
        "task_id",
        "step_id",
        "tool_call_id",
        "sequence",
        "payload",
    )
    semantic = {key: event.get(key) for key in semantic_fields if key in event}
    encoded = json.dumps(
        semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return event_id, hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ArtifactRefConflictError",
    "EventIdentityConflictError",
    "EvidenceRefConflictError",
    "TaskResultConflictError",
    "event_fingerprint",
    "reduce_artifact_refs",
    "reduce_event_fingerprints",
    "reduce_event_ids",
    "reduce_evidence_refs",
    "reduce_task_results",
]
