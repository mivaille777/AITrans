import hashlib
import json

import pytest

from backend.rag.stores.local_repository import LocalVectorRepository
from scripts.migration.import_faiss import migrate
from tests.rag.test_faiss_store import make_chunk


@pytest.mark.parametrize(
    "name,kind,wanted",
    [
        (
            "aitrans_knowledge_visual_2stage_mv128_dot",
            "visual",
            "aitrans_knowledge_visual",
        ),
        ("aitrans_knowledge_visual_mv128_dot", "visual", "aitrans_knowledge_visual"),
        ("text_mv128_dot", "text", "text_mv128_dot"),
    ],
)
def test_legacy_visual_name_maps_to_runtime_collection_without_old_client(
    name, kind, wanted
):
    from scripts.migration.export_qdrant import target_collection_name

    assert target_collection_name(name, kind, 128, "dot") == wanted


def bundle(tmp_path):
    root = tmp_path / "export"
    root.mkdir()
    chunk = make_chunk("a").model_dump(mode="json")
    chunk["index_generation"] = "g1"
    chunk["metadata"]["index_generation"] = "g1"
    record = {
        "collection": "text",
        "payload": chunk,
        "vector": [2.0, 0.0],
        "index_version": "",
    }
    (root / "vectors.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    meta = {
        "format_version": 1,
        "collections": [
            {
                "name": "text",
                "kind": "text",
                "dimension": 2,
                "distance": "cosine",
                "fingerprint": "fp",
                "count": 1,
            }
        ],
        "files": {
            "vectors.jsonl": hashlib.sha256(
                (root / "vectors.jsonl").read_bytes()
            ).hexdigest()
        },
    }
    (root / "bundle.json").write_text(json.dumps(meta), encoding="utf-8")
    return root


def test_import_resume_verify_keep_ids(tmp_path):
    source = bundle(tmp_path)
    dest = tmp_path / "staging"
    assert migrate(source, dest) == {"text": 1}
    with LocalVectorRepository(dest, read_only=True) as repo:
        row = repo.rows("text", with_vectors=True)[0]
        first = row.vector_id
        assert row.generation == "g1" and row.vector.tolist() == [1.0, 0.0]
    assert migrate(source, dest, resume=True) == {"text": 1}
    assert migrate(source, dest, verify_only=True) == {"text": 1}
    with LocalVectorRepository(dest, read_only=True) as repo:
        assert repo.rows("text")[0].vector_id == first
    with pytest.raises(ValueError, match="resume"):
        migrate(source, dest)


def test_checksums_fail_before_target_mutation(tmp_path):
    source = bundle(tmp_path)
    dest = tmp_path / "staging"
    (source / "vectors.jsonl").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        migrate(source, dest)
    assert not dest.exists()


def test_corrupt_persisted_vector_fails_verify(tmp_path):
    source = bundle(tmp_path)
    dest = tmp_path / "staging"
    migrate(source, dest)
    with LocalVectorRepository(dest) as repo:
        repo.connection.execute("UPDATE items SET vector=x'0000'")
    from backend.rag.exceptions import RagVectorStoreError

    with pytest.raises(RagVectorStoreError):
        migrate(source, dest, verify_only=True)


def test_visual_tokens_and_version_roundtrip_and_readonly_preflight(tmp_path):
    from scripts.migration.import_faiss import validate_bundle

    source = bundle(tmp_path)
    chunk = make_chunk("page").model_dump(mode="json")
    chunk["metadata"]["visual_index_version"] = "visual-v1"
    record = {
        "collection": "visual",
        "payload": chunk,
        "vector": [[2.0, 0.0], [0.0, 1.0]],
        "index_version": "visual-v1",
    }
    (source / "vectors.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    meta = json.loads((source / "bundle.json").read_text())
    meta["collections"][0].update(
        name="visual", kind="visual", distance="dot", fingerprint="visual-v1"
    )
    meta["files"]["vectors.jsonl"] = hashlib.sha256(
        (source / "vectors.jsonl").read_bytes()
    ).hexdigest()
    (source / "bundle.json").write_text(json.dumps(meta), encoding="utf-8")
    dest = tmp_path / "visual-staging"
    assert validate_bundle(source) == {"visual": 1}
    assert not dest.exists()
    migrate(source, dest)
    assert migrate(source, dest, verify_only=True) == {"visual": 1}
    with LocalVectorRepository(dest, read_only=True) as repo:
        row = repo.rows("visual", with_vectors=True, with_coarse=True)[0]
        assert row.token_count == 2 and row.index_version == "visual-v1"
        assert row.vector.tolist() == record["vector"]
        assert row.coarse.tolist() == pytest.approx([2 / (5**0.5), 1 / (5**0.5)])


def test_resume_after_committed_batch_and_before_completion(tmp_path, monkeypatch):
    source = bundle(tmp_path)
    dest = tmp_path / "staging"
    original = LocalVectorRepository.write

    def interrupted(repository, *args, **kwargs):
        original(repository, *args, **kwargs)
        raise RuntimeError("interrupted after durable commit")

    with monkeypatch.context() as patcher:
        patcher.setattr(LocalVectorRepository, "write", interrupted)
        with pytest.raises(RuntimeError, match="durable commit"):
            migrate(source, dest)
    with LocalVectorRepository(dest, read_only=True) as repo:
        first = repo.rows("text")[0].vector_id
    assert migrate(source, dest, resume=True) == {"text": 1}
    with LocalVectorRepository(dest, read_only=True) as repo:
        assert repo.rows("text")[0].vector_id == first
