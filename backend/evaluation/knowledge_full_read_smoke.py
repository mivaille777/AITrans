"""Read-only local-index smoke check; no online model calls or library writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from app.ai.tool_calling import ToolCompletion
from backend.agent_tools.knowledge import KnowledgeAgentTools
from backend.models.knowledge_access import KnowledgeAccessPolicy
from backend.rag.config import RagVectorStoreConfig
from backend.rag.index_manifest import IndexManifest
from backend.rag.models import DocumentChunk
from backend.rag.retrieval_service import RetrievalService
from backend.rag.stores.faiss import FaissVectorStore
from backend.rag.stores.local_repository import LocalVectorRepository
from backend.services.knowledge_function_calling import KnowledgeFunctionState, run_knowledge_functions
from backend.services.knowledge_function_recovery import FULL_BATCH_CHARS
from backend.services.knowledge_scope_resolver import KnowledgeScopeResolver


class _RecordingModel:
    """Checks the application context boundary, not model comprehension/quality."""

    def __init__(self):
        self.prompts: list[str] = []

    def complete_tools(self, **kwargs):
        assert kwargs["tools"] == [] and kwargs["tool_choice"] == "none"
        self.prompts.append(kwargs["messages"][-1]["content"])
        return ToolCompletion({"role": "assistant", "content": "本批已处理，证据不足时应保留限制。"})


def check_full_read(rag_dir: Path, collection_name: str) -> dict:
    payload = json.loads((rag_dir / "bm25_index.json").read_text(encoding="utf-8"))
    chunks = [DocumentChunk.model_validate(item) for item in payload["chunks"].values()]
    lookup = {(chunk.chunk_id, chunk.metadata.get("index_generation") or None): chunk for chunk in chunks}

    def get_chunk(identifier, *, generation_id=None):
        chunk = lookup.get((identifier, generation_id))
        return chunk.model_copy(deep=True) if chunk else None

    # Avoid BM25SparseRetriever.__init__: tokenizer migrations could write to the
    # user's actual sparse index. No embeddings or FAISS search caches are needed.
    repository = LocalVectorRepository(rag_dir / "faiss", read_only=True)
    try:
        collection = repository.connection.execute(
            "SELECT name, dimension, distance FROM collections WHERE name=? AND kind='text'",
            (collection_name,),
        ).fetchone()
        if collection is None:
            raise LookupError("Configured text collection is unavailable")
        vector = FaissVectorStore(
            RagVectorStoreConfig(collection_name=collection["name"], distance=collection["distance"]),
            dimension=collection["dimension"], repository=repository,
        )
        manifest = IndexManifest(rag_dir / "index_manifest.json")
        retrieval = RetrievalService(
            embedding_provider=None, vector_store=vector,
            sparse_retriever=SimpleNamespace(get_chunk=get_chunk), manifest=manifest,
        )
        tools = KnowledgeAgentTools(
            retrieval_service=retrieval, chunk_store=None, jit_search_read_enabled=True,
            library_service=SimpleNamespace(list_documents=manifest.list_records),
        )
        reports = []
        for number, document_id in enumerate(manifest.list_active_generations(), 1):
            _, document = retrieval.snapshot_document_chunks(document_id)
            client = _RecordingModel()
            state = KnowledgeFunctionState(
                scope=KnowledgeScopeResolver().resolve(
                    context_mode="general", explicit_document_ids=[document_id], global_allowed=False,
                ),
                policy=KnowledgeAccessPolicy.AUTO, trace_id=f"local-full-read-{number}",
                original_query="请读取全文", full_read_requested=True,
            )
            list(run_knowledge_functions(
                client=client, messages=[], state=state, tools_factory=lambda: tools,
                request_id=1, stream=False, on_state=lambda _: None, reset_output=lambda: None,
            ))
            coverage = state.recovery["full_read"]
            if not coverage["complete"]:
                raise AssertionError(f"Document {number}: full reading incomplete")
            assert coverage["processed_chars"] == sum(len(chunk.text) for chunk in document)
            batch_prompts = client.prompts[:-1]
            for chunk in document:
                for offset in range(0, len(chunk.text), FULL_BATCH_CHARS):
                    piece = chunk.text[offset:offset + FULL_BATCH_CHARS]
                    assert any(piece in prompt for prompt in batch_prompts)
            reports.append({
                "document_number": number, "chunks": coverage["processed_chunks"],
                "characters": coverage["processed_chars"], "batches": coverage["processed_batches"],
                "tool_calls": len(state.calls), "complete": coverage["complete"],
            })
        if not reports:
            raise AssertionError("No active documents to check")
        return {"mode": "real-index-recording-model-no-network", "documents": reports}
    finally:
        repository.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rag-dir", type=Path, default=Path("config/rag"))
    parser.add_argument("--collection-name", default=RagVectorStoreConfig().collection_name)
    args = parser.parse_args()
    print(json.dumps(check_full_read(args.rag_dir, args.collection_name), ensure_ascii=False))


if __name__ == "__main__":
    main()

