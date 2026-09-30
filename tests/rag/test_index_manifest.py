from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.rag.embeddings.base import EmbeddingFingerprint
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


@pytest.mark.parametrize(
    "chunks,scope,version",
    [
        (["wrong"], "workspace", "graph-v1"),
        (["chunk_one"], "", "graph-v1"),
        (["chunk_one"], "workspace", ""),
    ],
)
def test_graph_validation_rejects_incomplete_or_mismatched_identity(
    tmp_path, chunks, scope, version
):
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(make_record())
    manifest.begin_generation("doc_one", "new", ["chunk_one"])
    with pytest.raises(RagInvariantError, match="graph generation"):
        manifest.validate_generation(
            "doc_one",
            "new",
            ["chunk_one"],
            graph_chunk_ids=chunks,
            graph_scope_id=scope,
            graph_index_version=version,
        )
    assert (
        manifest.get_generation("doc_one", "new").status
        is IndexGenerationStatus.BUILDING
    )


def test_graph_publication_requires_validated_identity_and_keeps_previous_pointer(
    tmp_path,
):
    path = tmp_path / "manifest.json"
    manifest = IndexManifest(path)
    manifest.upsert(make_record())
    manifest.begin_generation("doc_one", "old", ["chunk_one"])
    manifest.validate_generation("doc_one", "old", ["chunk_one"])
    manifest.publish_generation("doc_one", "old")
    manifest.begin_generation("doc_one", "new", ["chunk_one"])
    manifest.validate_generation(
        "doc_one",
        "new",
        ["chunk_one"],
        graph_chunk_ids=["chunk_one"],
        graph_scope_id="workspace",
        graph_index_version="graph-v1",
    )
    with pytest.raises(RagInvariantError, match="published graph identity"):
        manifest.publish_generation("doc_one", "new", manifest_record=make_record())
    assert manifest.list_active_generations() == {"doc_one": "old"}
    assert (
        manifest.get_generation("doc_one", "old").status is IndexGenerationStatus.READY
    )
    record = make_record().model_copy(
        update={"graph_scope_id": "workspace", "graph_index_version": "graph-v1"}
    )
    manifest.publish_generation("doc_one", "new", manifest_record=record)
    restarted = IndexManifest(path)
    assert restarted.list_active_generations() == {"doc_one": "new"}
    assert restarted.get("doc_one").graph_index_version == "graph-v1"
    assert restarted.get_generation("doc_one", "new").graph_scope_id == "workspace"
    assert make_record().graph_index_version == ""


def test_manifest_round_trip_and_source_lookup(tmp_path: Path) -> None:
    path = tmp_path / "index_manifest.json"
    first = IndexManifest(path)
    record = make_record()

    first.upsert(record)
    second = IndexManifest(path)

    assert second.get("doc_one") == record
    assert second.find_by_source_uri(record.source_uri) == record
    assert second.list_records() == [record]
    assert record.embedding_fingerprint["model_id"] == "fake-model"
    assert record.embedding_fingerprint["dimension"] == 4
    assert record.embedding_fingerprint["normalized"] is True
    assert record.embedding_fingerprint["query_prefix"] == "query"
    assert record.embedding_fingerprint["document_prefix"] == ""
    assert record.embedding_fingerprint["digest"]


def test_manifest_rejects_fingerprint_model_or_dimension_mismatch() -> None:
    mismatched = EmbeddingFingerprint(
        model_id="other-model",
        dimension=4,
        normalized=True,
        query_prefix="query",
        document_prefix="",
    )

    with pytest.raises(RagInvariantError, match="does not match manifest"):
        ready_manifest_record(
            document_id="doc_one",
            content_hash="hash",
            source_uri="file:///doc_one.txt",
            title="Paper",
            parser_version="text-v1",
            chunker_version="structure-aware-v1",
            embedding_model="fake-model",
            embedding_dimension=4,
            embedding_fingerprint=mismatched,
            chunk_ids=["chunk_one"],
        )


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


def test_manifest_delete_removes_generation_catalogue(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = IndexManifest(path)
    manifest.upsert(make_record())
    manifest.begin_generation("doc_one", "generation-1", ["chunk_one"])
    manifest.validate_generation("doc_one", "generation-1", ["chunk_one"])
    manifest.publish_generation("doc_one", "generation-1")

    assert manifest.delete("doc_one") is True
    restarted = IndexManifest(path)
    assert restarted.get("doc_one") is None
    assert restarted.list_generations("doc_one") == []


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
    legacy_record.pop("embedding_fingerprint")
    path.write_text(
        json.dumps({"version": 1, "documents": {"doc_one": legacy_record}}),
        encoding="utf-8",
    )

    manifest = IndexManifest(path)

    assert manifest.get("doc_one").generation_id == ""
    assert manifest.get("doc_one").embedding_fingerprint == {}
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
    assert manifest.list_active_generations() == {"doc_one": "generation-2"}


def test_active_generation_catalog_keeps_legacy_documents_and_hides_failed_builds(
    tmp_path: Path,
) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(make_record("legacy_doc"))
    manifest.upsert(make_record("versioned_doc"))
    manifest.begin_generation("versioned_doc", "generation-1", ["chunk_v1"])
    manifest.validate_generation("versioned_doc", "generation-1", ["chunk_v1"])
    manifest.publish_generation("versioned_doc", "generation-1")
    manifest.begin_generation("versioned_doc", "generation-2", ["chunk_v2"])
    manifest.fail_generation("versioned_doc", "generation-2", error="injected")

    assert manifest.list_active_generations() == {
        "legacy_doc": None,
        "versioned_doc": "generation-1",
    }


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


def test_failed_atomic_publish_keeps_previous_active_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(make_record())
    manifest.begin_generation("doc_one", "generation-1", ["chunk_v1"])
    manifest.validate_generation("doc_one", "generation-1", ["chunk_v1"])
    manifest.publish_generation("doc_one", "generation-1")
    manifest.begin_generation("doc_one", "generation-2", ["chunk_v2"])
    manifest.validate_generation("doc_one", "generation-2", ["chunk_v2"])

    def fail_save() -> None:
        raise OSError("injected manifest disk failure")

    monkeypatch.setattr(manifest, "_save", fail_save)
    with pytest.raises(OSError, match="injected manifest disk failure"):
        manifest.publish_generation("doc_one", "generation-2")

    monkeypatch.undo()
    assert manifest.get_active_generation("doc_one").generation_id == "generation-1"
    assert manifest.get_generation("doc_one", "generation-1").status is (
        IndexGenerationStatus.READY
    )
    assert manifest.get_generation("doc_one", "generation-2").status is (
        IndexGenerationStatus.VALIDATING
    )


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
