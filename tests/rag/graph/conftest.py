from __future__ import annotations

from hashlib import sha256

import pytest

from backend.rag.chunking import StructureAwareChunker
from backend.rag.models import KnowledgeDocument, NormalizedDocument


@pytest.fixture
def graph_document():
    def make(text="Alpha uses Beta.", document_id="paper"):
        return NormalizedDocument(
            document=KnowledgeDocument(
                document_id=document_id,
                source_uri=f"file:///{document_id}.txt",
                content_hash=sha256(text.encode()).hexdigest(),
            ),
            text=text,
            metadata={"parser_version": "fixture-v1"},
        )

    return make


@pytest.fixture
def graph_chunk(graph_document):
    def make(text="Alpha uses Beta.", document_id="paper"):
        document = graph_document(text, document_id)
        return document, StructureAwareChunker().chunk(document)[0]

    return make
