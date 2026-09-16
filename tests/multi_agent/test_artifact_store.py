from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent_core.orchestration.artifact_store import (
    ARTIFACT_STORE_SCHEMA_VERSION,
    ArtifactConflictError,
    InMemoryArtifactStore,
    SQLiteArtifactStore,
    build_artifact_store,
)
from backend.models.agent_artifacts import DocumentAnalysisArtifact


def _artifact(scope_ref: str, *, version: int = 1, contribution: str = "A") -> DocumentAnalysisArtifact:
    return DocumentAnalysisArtifact(
        artifact_id="analysis-paper-a",
        version=version,
        producer_task_id="document-a",
        scope_ref=scope_ref,
        document_id="paper-a",
        document_version="sha256:paper-a-v1",
        contributions=[contribution],
        content={"summary": contribution},
    )


def test_sqlite_store_persists_versions_across_reopen(isolated_data_root: Path) -> None:
    scope_ref = "scope:test"
    first = SQLiteArtifactStore()
    assert first.database_path == (isolated_data_root / "agent_artifacts.sqlite3").resolve()
    assert first.migrate() == ARTIFACT_STORE_SCHEMA_VERSION

    v1 = first.put(_artifact(scope_ref, version=1, contribution="A"))
    v2 = first.put(_artifact(scope_ref, version=2, contribution="B"))

    reopened = SQLiteArtifactStore()
    loaded = reopened.get(v1.artifact_id, 1)
    versions = reopened.list_versions(v1.artifact_id)

    assert loaded is not None
    assert loaded.content_hash == v1.content_hash
    assert [item.version for item in versions] == [1, 2]
    assert versions[1].content_hash == v2.content_hash


def test_put_is_idempotent_but_hash_conflict_is_rejected(isolated_data_root: Path) -> None:
    store = SQLiteArtifactStore()
    original = _artifact("scope:test")
    stored = store.put(original)
    duplicate = DocumentAnalysisArtifact.model_validate(original.model_dump(mode="json"))

    assert store.put(duplicate).content_hash == stored.content_hash

    conflicting = _artifact("scope:test", contribution="changed")
    with pytest.raises(ArtifactConflictError):
        store.put(conflicting)


def test_revocation_hides_content_without_deleting_version(isolated_data_root: Path) -> None:
    store = SQLiteArtifactStore()
    artifact = store.put(_artifact("scope:test"))

    assert store.revoke(artifact.artifact_id, artifact.version, reason="source revoked") is True
    assert store.get(artifact.artifact_id, artifact.version) is None
    retained = store.get(
        artifact.artifact_id,
        artifact.version,
        include_revoked=True,
    )
    assert retained is not None
    assert retained.content_hash == artifact.content_hash
    assert store.revoke(artifact.artifact_id, artifact.version, reason="again") is False


def test_temporary_store_is_in_memory_and_does_not_create_sqlite(
    isolated_data_root: Path,
) -> None:
    expected_db = isolated_data_root / "agent_artifacts.sqlite3"
    store = build_artifact_store(temporary=True)

    assert isinstance(store, InMemoryArtifactStore)
    artifact = store.put(_artifact("scope:temporary"))
    assert store.get(artifact.artifact_id, artifact.version) is not None
    assert not expected_db.exists()


def test_artifact_store_payload_round_trip_has_no_live_python_objects(
    isolated_data_root: Path,
) -> None:
    store = SQLiteArtifactStore()
    artifact = store.put(_artifact("scope:test"))
    loaded = store.get(artifact.artifact_id, artifact.version)

    assert loaded is not None
    payload = loaded.model_dump(mode="json")
    assert isinstance(payload, dict)
    assert payload["content"] == {"summary": "A"}
    assert "sqlite3.Connection" not in repr(payload)
