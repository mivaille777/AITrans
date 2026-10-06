import sqlite3
import subprocess
import sys

import numpy as np
import pytest

from backend.rag.exceptions import RagConfigurationError, RagVectorStoreError
from backend.rag.stores.local_repository import LocalVectorRepository
from tests.rag.test_faiss_store import make_chunk


def entry(name="a", document="doc_one", generation=None):
    chunk = make_chunk(name, document_id=document)
    if generation:
        chunk.metadata["index_generation"] = generation
    return chunk, np.array([1.0, 0.0], dtype=np.float32), "", None


def test_idempotent_ids_generation_backup_and_readonly(tmp_path):
    root = tmp_path / "live"
    with LocalVectorRepository(root) as repo:
        repo.ensure_collection("text", "text", 2, "cosine", "fp")
        repo.write("text", [entry()])
        first = repo.rows("text")[0].vector_id
        repo.write("text", [entry()])
        assert repo.rows("text")[0].vector_id == first
        repo.write("text", [entry(generation="g1")])
        assert len(repo.rows("text")) == 2
        repo.backup(tmp_path / "copy.sqlite3")
        with LocalVectorRepository(root, read_only=True) as reader:
            assert [r.vector_id for r in reader.rows("text")] == [
                r.vector_id for r in repo.rows("text")
            ]
            with pytest.raises(RagVectorStoreError):
                reader.write("text", [entry()])
    with LocalVectorRepository(root) as repo:
        assert repo.rows("text", with_vectors=True)[0].vector.tolist() == [1.0, 0.0]
        with sqlite3.connect(tmp_path / "copy.sqlite3") as backup:
            assert backup.execute("select count(*) from items").fetchone()[0] == 2


def test_batch_transaction_and_conflicting_identity_roll_back(tmp_path):
    with LocalVectorRepository(tmp_path) as repo:
        repo.ensure_collection("text", "text", 2, "dot")
        repo.write("text", [entry()])
        revision = repo.collection("text")["revision"]
        with pytest.raises(RagVectorStoreError):
            repo.write("text", [entry("b"), entry("a", document="other")])
        assert [r.chunk.chunk_id for r in repo.rows("text")] == ["a"]
        assert repo.collection("text")["revision"] == revision
        repo.connection.execute(
            "CREATE TRIGGER injected BEFORE INSERT ON items WHEN NEW.chunk_id='c' BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
        with pytest.raises(RagVectorStoreError):
            repo.write("text", [entry("b"), entry("c")])
        assert [r.chunk.chunk_id for r in repo.rows("text")] == ["a"]


@pytest.mark.parametrize(
    "blob", [b"bad", np.array([float("nan"), 0.0], dtype="<f4").tobytes()]
)
def test_corrupt_blob_rejected(tmp_path, blob):
    with LocalVectorRepository(tmp_path) as repo:
        repo.ensure_collection("text", "text", 2, "dot")
        repo.write("text", [entry()])
        repo.connection.execute("UPDATE items SET vector=?", (blob,))
        with pytest.raises(RagVectorStoreError):
            repo.rows("text", with_vectors=True)


def test_schema_fingerprint_and_owner_lock(tmp_path):
    with LocalVectorRepository(tmp_path) as repo:
        repo.ensure_collection("text", "text", 2, "dot", "fp")
        with pytest.raises(RagConfigurationError):
            LocalVectorRepository(tmp_path)
        code = "from backend.rag.stores.local_repository import LocalVectorRepository; import sys; LocalVectorRepository(sys.argv[1])"
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, check=False
        )
        assert result.returncode != 0 and "another writer" in result.stderr
        with pytest.raises(RagConfigurationError):
            repo.ensure_collection("text", "text", 3, "dot", "fp")
        with pytest.raises(RagConfigurationError):
            repo.ensure_collection("text", "text", 2, "dot", "new")
        repo.connection.execute("UPDATE store_meta SET schema_version=999")
    with pytest.raises(RagConfigurationError):
        LocalVectorRepository(tmp_path)
