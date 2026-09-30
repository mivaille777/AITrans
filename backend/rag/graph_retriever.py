from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Any

from backend.rag.config import RagGraphConfig
from backend.rag.graph.query_entities import query_entities
from backend.rag.graph.repository import GraphRepository
from backend.rag.graph.scoring import path_score
from backend.rag.models import ChannelHit, DocumentChunk, GraphPath, RetrievalCandidate
from backend.rag.retrievers.base import RetrievalRequest
from backend.rag.source_span import SourceSpan
from backend.rag.stores.base import VectorStore, is_reference_chunk


@dataclass(frozen=True)
class GraphRetrievalResult:
    candidates: list[RetrievalCandidate]
    metadata: dict[str, Any]


class GraphRetriever:
    def __init__(
        self, *, repository: GraphRepository, store: VectorStore, config: RagGraphConfig
    ) -> None:
        self._repository, self._store = repository, store
        self._config = config.model_copy(deep=True)

    def retrieve(self, request: RetrievalRequest) -> list[RetrievalCandidate]:
        return self.retrieve_with_trace(request).candidates

    def retrieve_with_trace(self, request: RetrievalRequest) -> GraphRetrievalResult:
        started = perf_counter()
        deadline = started + self._config.deadline_ms / 1000
        metadata = {
            "seed_ids": [],
            "visited_nodes": 0,
            "examined_edges": 0,
            "path_count": 0,
            "rejected_sources": 0,
            "reason": "",
            "truncated": False,
        }
        if not self._config.enabled:
            return GraphRetrievalResult([], {**metadata, "reason": "disabled"})
        if request.active_generations is None or request.allowed_document_ids is None:
            return GraphRetrievalResult([], {**metadata, "reason": "unresolved_scope"})
        if not request.allowed_document_ids:
            return GraphRetrievalResult([], {**metadata, "reason": "empty_scope"})
        scope = {
            "scope_id": self._config.scope_id,
            "allowed_document_ids": request.allowed_document_ids,
            "active_generations": request.active_generations,
            "deadline": deadline,
        }
        candidates = {}
        seeds = {}

        def check_deadline():
            if perf_counter() >= deadline:
                raise TimeoutError("graph query deadline exceeded")

        def grounded(doc, generation, chunk_id, span=None):
            check_deadline()
            chunk = self._store.get_chunk(chunk_id, generation_id=generation)
            check_deadline()
            if chunk is None or not self._valid_chunk(
                chunk, doc, generation, request, span
            ):
                metadata["rejected_sources"] += 1
                return None
            return chunk

        def add(chunk, paths, confidences):
            key = chunk.document_id, chunk.metadata["index_generation"], chunk.chunk_id
            score = path_score(confidences)
            previous = candidates.get(key)
            if previous is None:
                candidates[key] = [chunk, score, list(paths)]
            else:
                previous[1] = max(previous[1], score)
                for path in paths:
                    if path not in previous[2]:
                        previous[2].append(path)

        try:
            for term in query_entities(request.query):
                check_deadline()
                matches = self._repository.find_entities(
                    term, limit=self._config.max_seeds + 1, **scope
                )
                if self._config.entity_types:
                    matches = [
                        entity
                        for entity in matches
                        if entity.entity_type in self._config.entity_types
                    ]
                # Unresolved homonyms cannot select an arbitrary first node.
                if len(matches) != 1:
                    continue
                entity = matches[0]
                seeds[entity.entity_id] = entity
                if len(seeds) >= min(self._config.max_seeds, self._config.max_nodes):
                    break
            check_deadline()
            metadata["seed_ids"] = list(seeds)
            if not seeds:
                return GraphRetrievalResult([], {**metadata, "reason": "no_seed"})
            queue = deque((node, (node,), (), (), ()) for node in seeds)
            visited = set(seeds)
            metadata["visited_nodes"] = len(visited)
            for seed in seeds:
                for doc, generation, chunk_id in self._repository.entity_chunks(
                    seed, limit=self._config.max_paths - metadata["path_count"], **scope
                ):
                    chunk = grounded(doc, generation, chunk_id)
                    if chunk is not None:
                        add(
                            chunk,
                            [GraphPath(node_ids=[seed], source_span=chunk.source_span)],
                            (),
                        )
                        metadata["path_count"] += 1
                    if metadata["path_count"] >= self._config.max_paths:
                        break
                if metadata["path_count"] >= self._config.max_paths:
                    break
            while (
                queue
                and metadata["path_count"] < self._config.max_paths
                and metadata["examined_edges"] < self._config.max_edges
            ):
                check_deadline()
                node, nodes, edges, proofs, confidences = queue.popleft()
                if len(edges) >= self._config.max_hops:
                    continue
                relations = self._repository.list_relations(
                    entity_ids=(node,),
                    limit=self._config.max_edges - metadata["examined_edges"],
                    **scope,
                )
                for relation in relations:
                    check_deadline()
                    metadata["examined_edges"] += 1
                    target = (
                        relation.target_entity_id
                        if relation.source_entity_id == node
                        else relation.source_entity_id
                    )
                    if target in nodes:
                        continue
                    if target not in visited and len(visited) >= self._config.max_nodes:
                        metadata["truncated"] = True
                        continue
                    next_nodes, next_edges = (
                        (*nodes, target),
                        (*edges, relation.relation_id),
                    )
                    next_confidences = (*confidences, relation.confidence)
                    next_proofs = None
                    for source in relation.sources:
                        chunk = grounded(
                            relation.document_id,
                            relation.generation_id,
                            source.chunk_id,
                            source.source_span,
                        )
                        if chunk is None:
                            continue
                        path = GraphPath(
                            node_ids=list(next_nodes),
                            edge_ids=list(next_edges),
                            source_span=source.source_span,
                        )
                        current_proofs = (*proofs, path)
                        add(chunk, current_proofs, next_confidences)
                        next_proofs = current_proofs
                        metadata["path_count"] += 1
                        if metadata["path_count"] >= self._config.max_paths:
                            break
                    if next_proofs is not None and target not in visited:
                        visited.add(target)
                        metadata["visited_nodes"] = len(visited)
                        queue.append(
                            (
                                target,
                                next_nodes,
                                next_edges,
                                next_proofs,
                                next_confidences,
                            )
                        )
                    if metadata["path_count"] >= self._config.max_paths:
                        break
            metadata["truncated"] |= bool(queue) and (
                metadata["path_count"] >= self._config.max_paths
                or metadata["examined_edges"] >= self._config.max_edges
            )
            check_deadline()
        except (TimeoutError, sqlite3.OperationalError) as exc:
            if not isinstance(exc, TimeoutError) and perf_counter() < deadline:
                raise
            return GraphRetrievalResult(
                [],
                {
                    **metadata,
                    "reason": "deadline_exceeded",
                    "elapsed_ms": (perf_counter() - started) * 1000,
                },
            )
        ordered = sorted(
            candidates.values(), key=lambda item: (-item[1], item[0].chunk_id)
        )[: min(request.top_k, self._config.top_k)]
        hits = [
            RetrievalCandidate(
                chunk=chunk,
                rank=rank,
                graph_paths=paths,
                channel_hits=[ChannelHit(channel="graph", raw_score=score, rank=rank)],
                index_generation=chunk.metadata["index_generation"],
                trace_id=request.trace_id,
            )
            for rank, (chunk, score, paths) in enumerate(ordered, start=1)
        ]
        return GraphRetrievalResult(
            hits,
            {
                **metadata,
                "reason": "grounded" if hits else "no_grounded_passage",
                "elapsed_ms": (perf_counter() - started) * 1000,
            },
        )

    @staticmethod
    def _valid_chunk(
        chunk: DocumentChunk,
        doc: str,
        generation: str,
        request: RetrievalRequest,
        span: SourceSpan | None,
    ) -> bool:
        if (
            chunk.document_id != doc
            or doc not in request.allowed_document_ids
            or request.active_generations.get(doc) != generation
            or chunk.metadata.get("index_generation") != generation
        ):
            return False
        filters = request.filters
        if (
            (
                filters.source_kind
                and chunk.metadata.get("source_kind") != filters.source_kind
            )
            or (filters.language and chunk.language != filters.language)
            or (filters.exclude_references and is_reference_chunk(chunk))
            or any(
                chunk.metadata.get(key) != value
                for key, value in filters.metadata.items()
            )
        ):
            return False
        anchor = chunk.source_span
        if (
            anchor is None
            or sha256(chunk.text.encode()).hexdigest() != anchor.quote_hash
        ):
            return False
        if chunk.document_hash and chunk.document_hash != anchor.document_hash:
            return False
        span = span or anchor
        start, end = (
            span.start_char - chunk.start_char,
            span.end_char - chunk.start_char,
        )
        return (
            span.document_hash == anchor.document_hash
            and span.document_text_hash == anchor.document_text_hash
            and span.source_uri == anchor.source_uri
            and 0 <= start < end <= len(chunk.text)
            and sha256(chunk.text[start:end].encode()).hexdigest() == span.quote_hash
        )
