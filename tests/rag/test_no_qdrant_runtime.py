import subprocess
import sys


def test_app_and_runtime_work_when_old_imports_are_forbidden(tmp_path):
    code = """
import importlib.abc,sys
class BlockOld(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith("qdrant_client"):
            raise AssertionError("production imported legacy client")
sys.meta_path.insert(0,BlockOld())
from backend.main import create_app
from backend.rag.runtime_probe import probe_local_vector_runtime
assert create_app().title
assert all(probe_local_vector_runtime().values())
from backend.api import knowledge_dependencies as kd
from types import SimpleNamespace
from tests.rag.graph.test_indexer import Embedding
kd.SettingsManager=lambda:SimpleNamespace(data={"rag":{"embedding":{"dimension":4},"vector_store":{"storage_path":sys.argv[1]},"visual_retrieval":{"enabled":True,"dimension":2}}})
kd.create_embedding_provider=lambda *a,**kw:Embedding()
kd.get_rag_model_manager=lambda:None
kd.Qwen3RerankerProvider=lambda *a,**kw:None
runtime=kd._build_runtime()
from backend.rag.models import DocumentChunk
from backend.rag.visual_retrieval import visual_retrieval_index_version
store=runtime.visual_vector_store
store.replace_document("d",[DocumentChunk(chunk_id="p",document_id="d",text="page",chunk_index=0)],[[[1.,0.]]],index_version=visual_retrieval_index_version(runtime.config.visual_retrieval))
assert store.search([[1.,0.]],top_k=1)[0].metadata["visual_score"]==1.
kd._runtime=runtime
kd.close_rag_runtime()
assert not any(name.startswith("qdrant_client") for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "faiss")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
