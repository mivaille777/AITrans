from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.rag.exceptions import RagInvariantError
from backend.rag.index_manifest import (
    ACTIVE_INDEX_STATUSES,
    IndexGenerationStatus,
    IndexManifest,
    IndexStatus,
    ready_manifest_record,
)


def make_record(document_id: str = "doc_one"):
    return ready_manifest_record(
        document_id=document_id,
        content_hash="hash",
        source_uri=f"file:///{document_id}.txt",
        title="Paper",
        parser_version="text-v1",
        chunker_version="structure-aware-v1",
        embedding_model="fake-model",
        embedding_dimension=4,
        chunk_ids=["chunk_one"],
    )


def test_manifest_round_trip_and_source_lookup(tmp_path: Path) -> None:
    path = tmp_path / "index_manifest.json"
    first = IndexManifest(path)
    record = make_record()

    first.upsert(record)
    second = IndexManifest(path)

    assert second.get("doc_one") == record
    assert second.find_by_source_uri(record.source_uri) == record
    assert second.list_records() == [record]


def test_manifest_status_updates_preserve_index_metadata(tmp_path: Path) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(make_record())

    failed = manifest.mark_status(
        "doc_one",
        IndexStatus.FAILED,
        error="embedding failed",
    )

    assert failed.status is IndexStatus.FAILED
    assert failed.error == "embedding failed"
    assert failed.chunk_ids == ["chunk_one"]
    assert failed.content_hash == "hash"


def test_manifest_recovers_interrupted_active_states(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = IndexManifest(path)

    for index, status in enumerate(
        sorted(ACTIVE_INDEX_STATUSES, key=lambda item: item.value)
    ):
        document_id = f"doc_{index}"
        manifest.upsert(make_record(document_id))
        manifest.mark_status(document_id, status)
    manifest.upsert(make_record("doc_ready"))

    reloaded = IndexManifest(path)
    recovered = reloaded.recover_interrupted_operations()

    assert set(recovered) == {
        f"doc_{index}" for index in range(len(ACTIVE_INDEX_STATUSES))
    }
    for document_id in recovered:
        record = reloaded.get(document_id)
        assert record is not None
        assert record.status is IndexStatus.FAILED
        assert "Previous indexing run was interrupted during" in record.error
        assert "Reindex the document" in record.error
        assert record.chunk_ids == ["chunk_one"]
    ready = reloaded.get("doc_ready")
    assert ready is not None
    assert ready.status is IndexStatus.READY


def test_manifest_delete_persists(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = IndexManifest(path)
    manifest.upsert(make_record())

    assert manifest.delete("doc_one") is True
    assert manifest.delete("doc_one") is False
    assert IndexManifest(path).get("doc_one") is None


def test_manifest_atomic_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = IndexManifest(path)

    manifest.upsert(make_record())

    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert '"version": 1' in path.read_text(encoding="utf-8")


def test_manifest_loads_legacy_json_without_generation_fields(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    legacy_record = make_record().model_dump(mode="json")
    legacy_record.pop("generation_id")
    path.write_text(
        json.dumps({"version": 1, "documents": {"doc_one": legacy_record}}),
        encoding="utf-8",
    )

    manifest = IndexManifest(path)

    assert manifest.get("doc_one").generation_id == ""
    assert manifest.list_generations("doc_one") == []


def test_generation_publish_switches_active_and_retains_previous_version(
    tmp_path: Path,
) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(make_record())

    first = manifest.begin_generation("doc_one", "generation-1", ["chunk_v1"])
    assert first.status is IndexGenerationStatus.BUILDING
    validated_first = manifest.validate_generation(
        "doc_one", "generation-1", ["chunk_v1"]
    )
    assert validated_first.status is IndexGenerationStatus.VALIDATING
    manifest.publish_generation("doc_one", "generation-1")

    active_first = manifest.get_active_generation("doc_one")
    assert active_first is not None
    assert active_first.generation_id == "generation-1"
    assert active_first.status is IndexGenerationStatus.READY
    assert manifest.get("doc_one").generation_id == "generation-1"

    manifest.begin_generation("doc_one", "generation-2", ["chunk_v2"])
    manifest.validate_generation("doc_one", "generation-2", ["chunk_v2"])
    manifest.publish_generation("doc_one", "generation-2")

    active_second = manifest.get_active_generation("doc_one")
    previous = manifest.get_generation("doc_one", "generation-1")
    assert active_second is not None
    assert active_second.generation_id == "generation-2"
    assert active_second.chunk_ids == ["chunk_v2"]
    assert previous is not None
    assert previous.status is IndexGenerationStatus.RETIRED
    assert previous.chunk_ids == ["chunk_v1"]
    assert [item.generation_id for item in manifest.list_generations("doc_one")] == [
        "generation-1",
        "generation-2",
    ]


def test_generation_state_machine_rejects_invalid_and_duplicate_publish(
    tmp_path: Path,
) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(make_record())
    manifest.begin_generation("doc_one", "generation-1", ["chunk_one"])

    with pytest.raises(RagInvariantError, match="requires 'validating'"):
        manifest.publish_generation("doc_one", "generation-1")
    with pytest.raises(RagInvariantError, match="failed validation"):
        manifest.validate_generation("doc_one", "generation-1", ["chunk_wrong"])
    assert manifest.get_generation("doc_one", "generation-1").status is (
        IndexGenerationStatus.BUILDING
    )

    manifest.validate_generation("doc_one", "generation-1", ["chunk_one"])
    manifest.publish_generation("doc_one", "generation-1")
    with pytest.raises(RagInvariantError, match="requires 'validating'"):
        manifest.publish_generation("doc_one", "generation-1")
    with pytest.raises(RagInvariantError, match="generation already exists"):
        manifest.begin_generation("doc_one", "generation-1", ["chunk_one"])


def test_interrupted_generations_recover_and_preserve_previous_active_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"
    manifest = IndexManifest(path)
    manifest.upsert(make_record())
    manifest.begin_generation("doc_one", "generation-1", ["chunk_v1"])
    manifest.validate_generation("doc_one", "generation-1", ["chunk_v1"])
    manifest.publish_generation("doc_one", "generation-1")
    manifest.begin_generation("doc_one", "generation-2", ["chunk_v2"])
    manifest.validate_generation("doc_one", "generation-2", ["chunk_v2"])
    manifest.begin_generation("doc_one", "generation-3", ["chunk_v3"])
    manifest.mark_status("doc_one", IndexStatus.INDEXING)

    restarted = IndexManifest(path)
    recovered_documents = restarted.recover_interrupted_operations()

    assert recovered_documents == ["doc_one"]
    assert restarted.get_active_generation("doc_one").generation_id == "generation-1"
    assert restarted.get("doc_one").status is IndexStatus.READY
    assert restarted.get_generation("doc_one", "generation-1").status is (
        IndexGenerationStatus.READY
    )
    for generation_id in ("generation-2", "generation-3"):
        recovered = restarted.get_generation("doc_one", generation_id)
        assert recovered is not None
        assert recovered.status is IndexGenerationStatus.FAILED
        assert "interrupted" in recovered.error
    assert restarted.recover_interrupted_generations() == []
