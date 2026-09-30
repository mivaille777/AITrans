from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter

from backend.rag.graph.extractor import GraphExtractor
from backend.rag.graph.models import (
    GRAPH_SCHEMA_VERSION,
    GraphEntity,
    GraphGeneration,
    GraphRelation,
    RelationSource,
)
from backend.rag.graph.repository import GraphRepository
from backend.rag.graph.resolver import EntityResolver
from backend.rag.index_manifest import (
    IndexGenerationStatus,
    IndexManifest,
    IndexManifestRecord,
)
from backend.rag.models import DocumentChunk, NormalizedDocument


@dataclass(frozen=True)
class GraphBuildResult:
    generation: GraphGeneration
    entity_count: int
    relation_count: int
    rejected: dict[str, int]
    elapsed_ms: float


class GraphIndexer:
    def __init__(
        self,
        *,
        repository: GraphRepository,
        extractor: GraphExtractor,
        scope_id: str,
        resolver: EntityResolver | None = None,
    ) -> None:
        if not scope_id.strip():
            raise ValueError("graph indexing scope must be explicit")
        self.repository, self.extractor, self.scope_id = repository, extractor, scope_id
        self.resolver = resolver or EntityResolver()
        self.version = (
            f"graph-v{GRAPH_SCHEMA_VERSION}:{extractor.version}:{self.resolver.version}"
        )

    def build_generation(
        self,
        document: NormalizedDocument,
        chunks: list[DocumentChunk],
        generation_id: str,
    ) -> GraphBuildResult:
        started = perf_counter()
        entities: dict[str, GraphEntity] = {}
        relations: dict[str, GraphRelation] = {}
        chunk_entities: dict[str, list[str]] = {}
        rejected: Counter[str] = Counter()
        for chunk in chunks:
            if chunk.document_id != document.document.document_id:
                raise ValueError("graph chunk belongs to another document")
            extraction = self.extractor.extract(chunk, document)
            rejected.update(extraction.rejected)
            resolved = [
                self.resolver.resolve(
                    entity, scope_id=self.scope_id, document_id=chunk.document_id
                )
                for entity in extraction.entities
            ]
            for entity in resolved:
                existing = entities.get(entity.entity_id)
                if existing is not None:
                    entity = entity.model_copy(
                        update={
                            "aliases": sorted(set(existing.aliases + entity.aliases))
                        }
                    )
                entities[entity.entity_id] = entity
            chunk_entities[chunk.chunk_id] = sorted(
                {entity.entity_id for entity in resolved}
            )
            for relation in extraction.relations:
                source, target = (
                    resolved[relation.source_index],
                    resolved[relation.target_index],
                )
                key = json.dumps(
                    [
                        self.scope_id,
                        chunk.document_id,
                        generation_id,
                        chunk.chunk_id,
                        source.entity_id,
                        target.entity_id,
                        relation.predicate,
                        relation.source_span.start_char,
                        relation.source_span.end_char,
                    ]
                )
                relation_id = "relation_" + sha256(key.encode()).hexdigest()[:32]
                relations[relation_id] = GraphRelation(
                    relation_id=relation_id,
                    scope_id=self.scope_id,
                    document_id=chunk.document_id,
                    generation_id=generation_id,
                    source_entity_id=source.entity_id,
                    target_entity_id=target.entity_id,
                    predicate=relation.predicate,
                    confidence=relation.confidence,
                    extractor_version=self.extractor.version,
                    sources=[
                        RelationSource(
                            chunk_id=chunk.chunk_id, source_span=relation.source_span
                        )
                    ],
                )
        record = GraphGeneration(
            scope_id=self.scope_id,
            document_id=document.document.document_id,
            generation_id=generation_id,
            index_version=self.version,
            chunk_ids=[chunk.chunk_id for chunk in chunks],
        )
        self.repository.write_generation(
            record,
            entities=list(entities.values()),
            relations=list(relations.values()),
            chunk_entities=chunk_entities,
            chunks=chunks,
        )
        stored = self.repository.get_generation(
            self.scope_id, record.document_id, generation_id
        )
        if stored != record:
            raise ValueError("graph generation failed persisted identity validation")
        return GraphBuildResult(
            stored,
            len(entities),
            len(relations),
            dict(rejected),
            (perf_counter() - started) * 1000,
        )

    def can_reuse(self, record: IndexManifestRecord) -> bool:
        if (
            record.graph_scope_id != self.scope_id
            or record.graph_index_version != self.version
        ):
            return False
        graph = self.repository.get_generation(
            self.scope_id, record.document_id, record.generation_id
        )
        return bool(
            graph
            and graph.status == "ready"
            and graph.index_version == self.version
            and set(graph.chunk_ids) == set(record.chunk_ids)
        )

    def delete_generation(self, document_id: str, generation_id: str) -> None:
        self.repository.delete_generation(self.scope_id, document_id, generation_id)

    def delete_document(self, document_id: str) -> None:
        self.repository.delete_document(self.scope_id, document_id)

    def recover(self, manifest: IndexManifest) -> list[tuple[str, str]]:
        removed = []
        for graph in self.repository.list_generations(self.scope_id):
            generation = manifest.get_generation(graph.document_id, graph.generation_id)
            if generation is None or generation.status is IndexGenerationStatus.FAILED:
                self.delete_generation(graph.document_id, graph.generation_id)
                removed.append((graph.document_id, graph.generation_id))
        return removed
