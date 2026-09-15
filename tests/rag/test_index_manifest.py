from __future__ import annotations

from pathlib import Path

from backend.rag.index_manifest import (
    ACTIVE_INDEX_STATUSES,
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

    for index, status in enumerate(sorted(ACTIVE_INDEX_STATUSES, key=lambda item: item.value)):
        document_id = f"doc_{index}"
        manifest.upsert(make_record(document_id))
        manifest.mark_status(document_id, status)
    manifest.upsert(make_record("doc_ready"))

    reloaded = IndexManifest(path)
    recovered = reloaded.recover_interrupted_operations()

    assert set(recovered) == {f"doc_{index}" for index in range(len(ACTIVE_INDEX_STATUSES))}
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
