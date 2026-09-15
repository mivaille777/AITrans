from __future__ import annotations

import logging
import math
import os
import shutil
from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol, runtime_checkable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.exceptions import RagConfigurationError, RagRetrievalError, RagVectorStoreError
from backend.rag.index_manifest import IndexManifest, IndexManifestRecord, IndexStatus
from backend.rag.index_service import IndexDocumentResult, IndexService
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult, build_stable_chunk_id
from backend.rag.stores.base import VectorSearchFilter

LOGGER = logging.getLogger(__name__)
VISUAL_RETRIEVAL_VERSION = "visual-retrieval-v1"

_DISTANCE = {
    "cosine": qdrant_models.Distance.COSINE,
    "dot": qdrant_models.Distance.DOT,
}

_MODEL_FAMILIES = {
    "colqwen2_5": ("ColQwen2_5", "ColQwen2_5_Processor"),
    "colqwen2": ("ColQwen2", "ColQwen2Processor"),
    "colpali": ("ColPali", "ColPaliProcessor"),
}


@runtime_checkable
class VisualEmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_images(self, image_paths: Sequence[Path]) -> list[list[list[float]]]: ...

    def embed_query(self, query: str) -> list[list[float]]: ...

    def close(self) -> None: ...


class ColPaliEngineVisualEmbeddingProvider:
    """Lazy ColPali/ColQwen late-interaction encoder.

    Heavy visual-retrieval dependencies are imported only when the feature is
    enabled and the first page/query is encoded. The default text RAG runtime
    therefore has no torch/Pillow/colpali import or model-loading overhead.
    """

    def __init__(self, config: RagVisualRetrievalConfig) -> None:
        self._config = config.model_copy(deep=True)
        self._model: Any | None = None
        self._processor: Any | None = None
        self._torch: Any | None = None
        self._device = ""

    @property
    def model_name(self) -> str:
        return (self._config.model_path or self._config.model).strip()

    @property
    def dimension(self) -> int:
        return self._config.dimension

    def embed_images(self, image_paths: Sequence[Path]) -> list[list[list[float]]]:
        paths = [Path(path).expanduser().resolve() for path in image_paths]
        if not paths:
            return []
        self._ensure_loaded()
        assert self._torch is not None and self._model is not None and self._processor is not None
        from PIL import Image

        output: list[list[list[float]]] = []
        batch_size = self._config.batch_size
        for start in range(0, len(paths), batch_size):
            batch_paths = paths[start : start + batch_size]
            images = []
            try:
                for path in batch_paths:
                    if not path.is_file():
                        raise RagRetrievalError(f"visual asset not found: {path}")
                    with Image.open(path) as image:
                        images.append(image.convert("RGB"))
                inputs = self._processor.process_images(images).to(self._model.device)
                with self._torch.no_grad():
                    encoded = self._model(**inputs)
                output.extend(self._to_multivectors(encoded))
            finally:
                for image in images:
                    close = getattr(image, "close", None)
                    if callable(close):
                        close()
        if len(output) != len(paths):
            raise RagRetrievalError(
                f"visual embedding count mismatch: expected {len(paths)}, got {len(output)}"
            )
        return output

    def embed_query(self, query: str) -> list[list[float]]:
        if not query or not query.strip():
            raise RagRetrievalError("visual retrieval query must not be empty")
        self._ensure_loaded()
        assert self._torch is not None and self._model is not None and self._processor is not None
        inputs = self._processor.process_queries([query.strip()]).to(self._model.device)
        with self._torch.no_grad():
            encoded = self._model(**inputs)
        vectors = self._to_multivectors(encoded)
        if len(vectors) != 1:
            raise RagRetrievalError("visual query encoder returned an invalid batch")
        return vectors[0]

    def close(self) -> None:
        self._model = None
        self._processor = None
        if self._torch is not None and self._device.startswith("cuda"):
            try:
                self._torch.cuda.empty_cache()
            except Exception:
                pass

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        try:
            import torch
            from colpali_engine import models as colpali_models
        except Exception as exc:
            raise RagConfigurationError(
                "native visual retrieval requires the optional ColPali dependencies; "
                "install aitranslator-rag-visual-requirements.txt"
            ) from exc

        family = self._config.model_family
        model_class_name, processor_class_name = _MODEL_FAMILIES[family]
        model_class = getattr(colpali_models, model_class_name, None)
        processor_class = getattr(colpali_models, processor_class_name, None)
        if model_class is None or processor_class is None:
            raise RagConfigurationError(
                f"installed colpali-engine does not provide model family {family!r}"
            )

        source = self.model_name
        if not source:
            raise RagConfigurationError("visual retrieval model must not be empty")
        device = self._resolve_device(torch)
        dtype = self._resolve_dtype(torch, device)
        load_kwargs: dict[str, Any] = {
            "local_files_only": self._config.local_files_only,
            "device_map": device,
            "torch_dtype": dtype,
        }
        try:
            model = model_class.from_pretrained(source, **load_kwargs).eval()
            processor = processor_class.from_pretrained(
                source,
                local_files_only=self._config.local_files_only,
            )
        except Exception as exc:
            raise RagConfigurationError(
                f"failed to load native visual retrieval model: {source}"
            ) from exc

        if self._config.query_prefix and hasattr(processor, "query_prefix"):
            processor.query_prefix = self._config.query_prefix
        self._torch = torch
        self._model = model
        self._processor = processor
        self._device = device

    def _resolve_device(self, torch: Any) -> str:
        configured = self._config.device
        if configured != "auto":
            return "cuda:0" if configured == "cuda" else configured
        if bool(getattr(torch.cuda, "is_available", lambda: False)()):
            return "cuda:0"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and bool(getattr(mps, "is_available", lambda: False)()):
            return "mps"
        return "cpu"

    def _resolve_dtype(self, torch: Any, device: str) -> Any:
        if self._config.precision == "fp16":
            return torch.float16
        if self._config.precision == "bf16":
            return torch.bfloat16
        return torch.bfloat16 if device.startswith("cuda") else torch.float32

    def _to_multivectors(self, encoded: Any) -> list[list[list[float]]]:
        assert self._torch is not None
        tensor = encoded
        for attribute in ("embeddings", "last_hidden_state"):
            value = getattr(encoded, attribute, None)
            if value is not None:
                tensor = value
                break
        if isinstance(tensor, (tuple, list)) and tensor:
            tensor = tensor[0]
        if not hasattr(tensor, "detach") or getattr(tensor, "ndim", 0) != 3:
            raise RagRetrievalError("visual encoder returned an invalid tensor")
        result: list[list[list[float]]] = []
        for sample in tensor.detach().float().cpu():
            # Col* processors may pad token rows to the longest sample. Zero rows
            # carry no MaxSim evidence and only waste Qdrant storage.
            mask = sample.abs().sum(dim=-1) > 0
            sample = sample[mask]
            rows = sample.tolist()
            result.append(_validate_multivector(rows, self.dimension))
        return result


def create_visual_embedding_provider(
    config: RagVisualRetrievalConfig,
) -> VisualEmbeddingProvider | None:
    if not config.enabled:
        return None
    if config.provider != "colpali_engine":
        raise RagConfigurationError(
            f"unsupported visual retrieval provider: {config.provider!r}"
        )
    return ColPaliEngineVisualEmbeddingProvider(config)


def visual_retrieval_index_version(config: RagVisualRetrievalConfig) -> str:
    """Stable semantic fingerprint for the native visual index."""

    payload = "\x1f".join(
        (
            VISUAL_RETRIEVAL_VERSION,
            str(bool(config.enabled)),
            config.provider,
            config.model_family,
            config.model_path or config.model,
            str(config.dimension),
            config.distance,
            config.query_prefix,
            str(config.render_dpi),
            str(config.max_pages_per_document),
            str(config.max_visual_items_per_document),
        )
    ).encode("utf-8")
    return f"{VISUAL_RETRIEVAL_VERSION}-{sha256(payload).hexdigest()[:16]}"


class QdrantVisualMultiVectorStore:
    """Dedicated Qdrant collection for ColPali/ColQwen MaxSim vectors."""

    def __init__(
        self,
        config: RagVisualRetrievalConfig,
        *,
        client: QdrantClient | None = None,
    ) -> None:
        self._config = config.model_copy(deep=True)
        self._owns_client = client is None
        self._client = client or QdrantClient(
            path=str(Path(self._config.storage_path).expanduser().resolve())
        )

    @property
    def collection_name(self) -> str:
        # Schema-sensitive suffix prevents a dimension/distance change from
        # colliding with an older MaxSim collection. Model changes that keep
        # the same schema reuse the collection and are handled by index_version.
        return f"{self._config.collection_name}_mv{self.dimension}_{self._config.distance}"

    @property
    def dimension(self) -> int:
        return self._config.dimension

    def ensure_collection(self) -> None:
        distance = _DISTANCE[self._config.distance]
        if not self._client.collection_exists(self.collection_name):
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=qdrant_models.VectorParams(
                    size=self.dimension,
                    distance=distance,
                    multivector_config=qdrant_models.MultiVectorConfig(
                        comparator=qdrant_models.MultiVectorComparator.MAX_SIM,
                    ),
                    hnsw_config=qdrant_models.HnswConfigDiff(m=0),
                    on_disk=self._config.on_disk,
                ),
            )
            return
        info = self._client.get_collection(self.collection_name)
        params = info.config.params.vectors
        if not isinstance(params, qdrant_models.VectorParams):
            raise RagConfigurationError(
                f"visual collection {self.collection_name!r} must use one multivector"
            )
        multivector = getattr(params, "multivector_config", None)
        comparator = getattr(multivector, "comparator", None)
        if (
            params.size != self.dimension
            or params.distance != distance
            or comparator != qdrant_models.MultiVectorComparator.MAX_SIM
        ):
            raise RagConfigurationError(
                "existing visual Qdrant collection schema mismatch: "
                f"expected size={self.dimension}, distance={distance.value}, comparator=max_sim"
            )

    def has_document(self, document_id: str, *, index_version: str) -> bool:
        self.ensure_collection()
        try:
            records, _offset = self._client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qdrant_models.Filter(
                    must=[
                        _match("document_id", document_id),
                        _match("visual_index_version", index_version),
                    ]
                ),
                limit=1,
                with_payload=False,
                with_vectors=False,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to inspect visual Qdrant index") from exc
        return bool(records)

    def replace_document(
        self,
        document_id: str,
        chunks: list[DocumentChunk],
        vectors: list[list[list[float]]],
        *,
        index_version: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise RagVectorStoreError(
                f"visual chunk/vector count mismatch: {len(chunks)} chunks, {len(vectors)} vectors"
            )
        self.ensure_collection()
        old_ids = self._document_point_ids(document_id)
        points = []
        new_ids: set[UUID] = set()
        for chunk, vector in zip(chunks, vectors, strict=True):
            point_id = self._point_id(chunk.chunk_id)
            new_ids.add(point_id)
            payload = chunk.model_dump(mode="json")
            payload["source_kind"] = str(chunk.metadata.get("source_kind", ""))
            payload["visual_index_version"] = index_version
            points.append(
                qdrant_models.PointStruct(
                    id=point_id,
                    vector=_validate_multivector(vector, self.dimension),
                    payload=payload,
                )
            )
        try:
            if points:
                self._client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                    wait=True,
                )
            stale = sorted(old_ids - new_ids, key=str)
            if stale:
                self._client.delete(
                    collection_name=self.collection_name,
                    points_selector=qdrant_models.PointIdsList(points=stale),
                    wait=True,
                )
        except Exception as exc:
            raise RagVectorStoreError("failed to replace visual Qdrant document") from exc

    def search(
        self,
        query: list[list[float]],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
    ) -> list[RetrievalCandidate]:
        if top_k <= 0:
            raise RagVectorStoreError("visual top_k must be positive")
        self.ensure_collection()
        multivector = _validate_multivector(query, self.dimension)
        try:
            response = self._client.query_points(
                collection_name=self.collection_name,
                query=multivector,
                query_filter=self._build_filter(filters),
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to search visual Qdrant collection") from exc

        results: list[RetrievalCandidate] = []
        for rank, point in enumerate(response.points, start=1):
            payload = dict(point.payload or {})
            payload.pop("source_kind", None)
            payload.pop("visual_index_version", None)
            try:
                chunk = DocumentChunk.model_validate(payload)
            except Exception as exc:
                raise RagVectorStoreError("visual Qdrant point has invalid payload") from exc
            results.append(
                RetrievalCandidate(
                    chunk=chunk,
                    fusion_score=None,
                    rank=rank,
                    metadata={
                        "retrieval_channel": "visual",
                        "visual_score": float(point.score),
                    },
                )
            )
        return results

    def delete_document(self, document_id: str) -> None:
        if not document_id:
            return
        self.ensure_collection()
        try:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=qdrant_models.FilterSelector(
                    filter=qdrant_models.Filter(must=[_match("document_id", document_id)])
                ),
                wait=True,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to delete visual Qdrant document") from exc

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _document_point_ids(self, document_id: str) -> set[UUID]:
        ids: set[UUID] = set()
        offset = None
        try:
            while True:
                records, offset = self._client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=qdrant_models.Filter(
                        must=[_match("document_id", document_id)]
                    ),
                    limit=256,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                for record in records:
                    try:
                        ids.add(UUID(str(record.id)))
                    except (TypeError, ValueError):
                        continue
                if offset is None:
                    return ids
        except Exception as exc:
            raise RagVectorStoreError("failed to enumerate visual Qdrant document") from exc

    @staticmethod
    def _point_id(chunk_id: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"aitrans-rag-visual:{chunk_id}")

    @staticmethod
    def _build_filter(filters: VectorSearchFilter | None) -> qdrant_models.Filter | None:
        if filters is None:
            return None
        conditions: list[qdrant_models.FieldCondition] = []
        if filters.document_ids:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="document_id",
                    match=qdrant_models.MatchAny(any=filters.document_ids),
                )
            )
        if filters.source_kind:
            conditions.append(_match("source_kind", filters.source_kind))
        if filters.language:
            conditions.append(_match("language", filters.language))
        for key, value in sorted(filters.metadata.items()):
            conditions.append(_match(f"metadata.{key}", value))
        return qdrant_models.Filter(must=conditions) if conditions else None


def _match(key: str, value: Any) -> qdrant_models.FieldCondition:
    return qdrant_models.FieldCondition(
        key=key,
        match=qdrant_models.MatchValue(value=value),
    )


def _validate_multivector(
    vector: Sequence[Sequence[float]],
    dimension: int,
) -> list[list[float]]:
    if not vector:
        raise RagVectorStoreError("multivector must contain at least one token vector")
    converted: list[list[float]] = []
    for row in vector:
        if len(row) != dimension:
            raise RagVectorStoreError(
                f"multivector dimension mismatch: expected {dimension}, got {len(row)}"
            )
        try:
            values = [float(value) for value in row]
        except (TypeError, ValueError) as exc:
            raise RagVectorStoreError("multivector contains a non-numeric value") from exc
        if not all(math.isfinite(value) for value in values):
            raise RagVectorStoreError("multivector contains non-finite values")
        converted.append(values)
    return converted


VisualItemBuilder = Callable[
    [Path, IndexManifestRecord, RagVisualRetrievalConfig],
    list[tuple[DocumentChunk, Path]],
]


class VisualIndexCoordinator:
    """Build native visual assets and their multivectors independently of text RAG."""

    def __init__(
        self,
        *,
        config: RagVisualRetrievalConfig,
        provider: VisualEmbeddingProvider,
        store: QdrantVisualMultiVectorStore,
        manifest: IndexManifest,
        item_builder: VisualItemBuilder | None = None,
    ) -> None:
        self._config = config.model_copy(deep=True)
        self._provider = provider
        self._store = store
        self._manifest = manifest
        self._item_builder = item_builder or build_visual_index_items

    @property
    def index_version(self) -> str:
        return visual_retrieval_index_version(self._config)

    def ensure_document(
        self,
        source: str | Path,
        document_id: str,
        *,
        force: bool = False,
    ) -> int:
        record = self._manifest.get(document_id)
        if record is None or record.status is not IndexStatus.READY:
            return 0
        if not force and self._store.has_document(
            document_id,
            index_version=self.index_version,
        ):
            return 0
        source_path = Path(source).expanduser().resolve()
        items = self._item_builder(source_path, record, self._config)
        if not items:
            self._store.delete_document(document_id)
            return 0
        chunks = [item[0] for item in items]
        image_paths = [item[1] for item in items]
        vectors = self._provider.embed_images(image_paths)
        self._store.replace_document(
            document_id,
            chunks,
            vectors,
            index_version=self.index_version,
        )
        return len(chunks)

    def delete_document(self, document_id: str) -> None:
        self._store.delete_document(document_id)
        shutil.rmtree(
            _document_asset_root(document_id, self._config.asset_storage_path),
            ignore_errors=True,
        )


class VisualAwareIndexService:
    """Non-fatal native-visual sidecar around the established IndexService."""

    def __init__(
        self,
        base: IndexService,
        coordinator: VisualIndexCoordinator,
        manifest: IndexManifest,
    ) -> None:
        self._base = base
        self._visual = coordinator
        self._manifest = manifest

    def index_document(self, path: str | Path) -> IndexDocumentResult:
        result = self._base.index_document(path)
        self._try_visual(path, result.document_id, result.status, force=False)
        return result

    def reindex_document(self, path_or_document_id: str | Path) -> IndexDocumentResult:
        candidate = Path(path_or_document_id)
        result = self._base.reindex_document(path_or_document_id)
        source: str | Path | None = candidate if candidate.exists() else None
        if source is None:
            record = self._manifest.get(result.document_id)
            if record is not None and record.source_uri:
                source = _path_from_file_uri(record.source_uri)
        if source is not None:
            self._try_visual(source, result.document_id, result.status, force=True)
        return result

    def delete_document(self, document_id: str) -> bool:
        try:
            self._visual.delete_document(document_id)
        except Exception as exc:  # noqa: BLE001 - text deletion must still proceed
            LOGGER.warning("visual index deletion failed for %s: %s", document_id, exc)
        return self._base.delete_document(document_id)

    def get_index_status(self, document_id: str):
        return self._base.get_index_status(document_id)

    def _try_visual(
        self,
        source: str | Path,
        document_id: str,
        status: IndexStatus,
        *,
        force: bool,
    ) -> None:
        if status is not IndexStatus.READY:
            return
        try:
            self._visual.ensure_document(source, document_id, force=force)
        except Exception as exc:  # noqa: BLE001 - native visual retrieval is additive
            LOGGER.warning(
                "native visual indexing degraded to text-only for %s: %s",
                document_id,
                exc,
            )


class VisualRetrievalService:
    """Fuse established text retrieval with native visual MaxSim retrieval."""

    def __init__(
        self,
        *,
        base: Any,
        provider: VisualEmbeddingProvider,
        store: QdrantVisualMultiVectorStore,
        config: RagVisualRetrievalConfig,
        default_final_top_k: int,
    ) -> None:
        self._base = base
        self._provider = provider
        self._store = store
        self._config = config.model_copy(deep=True)
        self._default_final_top_k = default_final_top_k

    def retrieve(
        self,
        query: str,
        *,
        filters: VectorSearchFilter | None = None,
        section_hints: tuple[str, ...] = (),
        final_top_k: int | None = None,
        include_references: bool = False,
    ) -> RetrievalResult:
        desired_top_k = final_top_k or self._default_final_top_k
        text_pool = max(desired_top_k, self._config.text_candidate_pool)
        text_result = self._base.retrieve(
            query,
            filters=filters,
            section_hints=section_hints,
            final_top_k=text_pool,
            include_references=include_references,
        )
        visual_started = perf_counter()
        try:
            query_vectors = self._provider.embed_query(query)
            visual = self._store.search(
                query_vectors,
                top_k=self._config.visual_top_k,
                filters=filters,
            )
            visual_error = ""
        except Exception as exc:  # noqa: BLE001 - text-only fallback is intentional
            visual = []
            visual_error = str(exc) or exc.__class__.__name__
        visual_ms = (perf_counter() - visual_started) * 1000

        if not visual:
            selected = _rerank_slice(text_result.candidates, desired_top_k)
            metadata = {
                **text_result.metadata,
                "visual_retrieval_enabled": True,
                "visual_count": 0,
                "visual_search_ms": visual_ms,
                "visual_fallback_reason": visual_error,
                "text_pool_count": len(text_result.candidates),
                "final_count": len(selected),
            }
            strategy = (
                f"{text_result.retrieval_strategy}+visual-fallback"
                if visual_error
                else text_result.retrieval_strategy
            )
            return text_result.model_copy(
                update={
                    "candidates": selected,
                    "retrieval_strategy": strategy,
                    "metadata": metadata,
                }
            )

        fusion_started = perf_counter()
        fused = weighted_rrf_fuse(
            [
                (text_result.candidates, self._config.text_weight, "text"),
                (visual, self._config.visual_weight, "visual"),
            ],
            limit=max(desired_top_k, self._config.fusion_top_k),
            k=self._config.rrf_k,
        )
        selected = _rerank_slice(fused, desired_top_k)
        visual_fusion_ms = (perf_counter() - fusion_started) * 1000
        metadata = {
            **text_result.metadata,
            "visual_retrieval_enabled": True,
            "visual_count": len(visual),
            "visual_search_ms": visual_ms,
            "visual_fusion_ms": visual_fusion_ms,
            "visual_fallback_reason": "",
            "text_pool_count": len(text_result.candidates),
            "visual_rrf_k": self._config.rrf_k,
            "visual_text_weight": self._config.text_weight,
            "visual_weight": self._config.visual_weight,
            "final_count": len(selected),
        }
        return text_result.model_copy(
            update={
                "candidates": selected,
                "retrieval_strategy": f"{text_result.retrieval_strategy}+visual-rrf",
                "metadata": metadata,
            }
        )


def weighted_rrf_fuse(
    ranked_lists: Sequence[tuple[Sequence[RetrievalCandidate], float, str]],
    *,
    limit: int,
    k: int = 60,
) -> list[RetrievalCandidate]:
    """Deterministic weighted RRF used at the text/native-visual boundary."""

    if limit <= 0 or k <= 0:
        raise ValueError("weighted RRF limit and k must be positive")
    scores: dict[str, float] = {}
    merged: dict[str, RetrievalCandidate] = {}
    channels: dict[str, set[str]] = {}
    for ranked, weight, channel in ranked_lists:
        if weight <= 0:
            raise ValueError("weighted RRF weights must be positive")
        for position, candidate in enumerate(ranked, start=1):
            chunk_id = candidate.chunk.chunk_id
            rank = candidate.rank or position
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (k + rank)
            channels.setdefault(chunk_id, set()).add(channel)
            if chunk_id not in merged:
                merged[chunk_id] = candidate.model_copy(deep=True)
            else:
                existing = merged[chunk_id]
                metadata = {**candidate.metadata, **existing.metadata}
                merged[chunk_id] = existing.model_copy(update={"metadata": metadata})
    ordered = sorted(scores, key=lambda item: (-scores[item], item))[:limit]
    return [
        merged[chunk_id].model_copy(
            update={
                "fusion_score": scores[chunk_id],
                "rank": rank,
                "metadata": {
                    **merged[chunk_id].metadata,
                    "fusion_channels": sorted(channels[chunk_id]),
                },
            }
        )
        for rank, chunk_id in enumerate(ordered, start=1)
    ]


def _rerank_slice(
    candidates: Sequence[RetrievalCandidate],
    limit: int,
) -> list[RetrievalCandidate]:
    return [
        candidate.model_copy(update={"rank": rank})
        for rank, candidate in enumerate(candidates[:limit], start=1)
    ]


def build_visual_index_items(
    source: Path,
    record: IndexManifestRecord,
    config: RagVisualRetrievalConfig,
) -> list[tuple[DocumentChunk, Path]]:
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        return _render_pdf_pages(source, record, config)
    if suffix == ".docx":
        return _extract_docx_pictures(source, record, config)
    return []


def _render_pdf_pages(
    source: Path,
    record: IndexManifestRecord,
    config: RagVisualRetrievalConfig,
) -> list[tuple[DocumentChunk, Path]]:
    try:
        import fitz
    except Exception as exc:
        raise RagConfigurationError(
            "PDF native visual retrieval requires PyMuPDF from the optional visual requirements"
        ) from exc

    directory = _document_asset_root(record.document_id, config.asset_storage_path) / record.content_hash[:24]
    directory.mkdir(parents=True, exist_ok=True)
    items: list[tuple[DocumentChunk, Path]] = []
    scale = config.render_dpi / 72.0
    document = fitz.open(str(source))
    try:
        page_count = min(len(document), config.max_pages_per_document)
        for page_index in range(page_count):
            if len(items) >= config.max_visual_items_per_document:
                break
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            asset = directory / f"page_{page_index + 1:04d}.png"
            pixmap.save(str(asset))
            page_text = " ".join(str(page.get_text("text") or "").split())[:1200]
            items.append(
                (
                    _visual_chunk(
                        record,
                        source=source,
                        identity=f"page:{page_index + 1}",
                        page_number=page_index + 1,
                        text_hint=page_text,
                        asset=asset,
                        kind="page",
                    ),
                    asset,
                )
            )
    finally:
        document.close()
    return items


def _extract_docx_pictures(
    source: Path,
    record: IndexManifestRecord,
    config: RagVisualRetrievalConfig,
) -> list[tuple[DocumentChunk, Path]]:
    try:
        from docx import Document
    except Exception as exc:
        raise RagConfigurationError("DOCX visual retrieval requires python-docx") from exc
    directory = _document_asset_root(record.document_id, config.asset_storage_path) / record.content_hash[:24]
    directory.mkdir(parents=True, exist_ok=True)
    document = Document(str(source))
    relationships = [
        relationship
        for relationship in document.part.rels.values()
        if str(getattr(relationship, "reltype", "")).endswith("/image")
    ]
    items: list[tuple[DocumentChunk, Path]] = []
    for index, relationship in enumerate(
        relationships[: config.max_visual_items_per_document],
        start=1,
    ):
        try:
            part = relationship.target_part
            data = bytes(part.blob)
        except Exception:
            continue
        if not data:
            continue
        original_name = Path(str(getattr(part, "partname", ""))).name
        suffix = Path(original_name).suffix.lower()
        # PIL-backed ColPali processors handle ordinary raster assets reliably.
        # Skip Office vector formats (EMF/WMF/SVG) instead of letting one asset
        # abort the entire DOCX visual sidecar batch.
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}:
            continue
        asset = directory / f"picture_{index:04d}{suffix}"
        asset.write_bytes(data)
        items.append(
            (
                _visual_chunk(
                    record,
                    source=source,
                    identity=f"picture:{index}:{original_name}",
                    page_number=None,
                    text_hint=f"Embedded picture {index}",
                    asset=asset,
                    kind="picture",
                ),
                asset,
            )
        )
    return items


def _visual_chunk(
    record: IndexManifestRecord,
    *,
    source: Path,
    identity: str,
    page_number: int | None,
    text_hint: str,
    asset: Path,
    kind: str,
) -> DocumentChunk:
    title = record.title or source.name
    label = f"Native visual {kind}"
    if page_number is not None:
        label += f" on page {page_number}"
    text = f"{label} from {title}."
    if text_hint:
        text += f" Text hint: {text_hint}"
    chunk_id = build_stable_chunk_id(
        document_hash=record.content_hash or sha256(record.source_uri.encode("utf-8")).hexdigest(),
        section_heading=f"native-visual\x1f{identity}",
        chunk_index=max(0, (page_number or 1) - 1),
        text=text,
    )
    source_kind = source.suffix.lower().lstrip(".") or "unknown"
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=record.document_id,
        text=text,
        title=title,
        chunk_type=f"visual_{kind}",
        page_number=page_number,
        chunk_index=max(0, (page_number or 1) - 1),
        token_count=max(1, (len(text) + 3) // 4),
        language="unknown",
        source_uri=record.source_uri,
        document_hash=record.content_hash,
        parser_version=record.parser_version,
        chunker_version=record.chunker_version,
        embedding_version="native-visual-multivector",
        metadata={
            "source_kind": source_kind,
            "modality": "page" if kind == "page" else "picture",
            "asset_uri": asset.resolve().as_uri(),
            "visual_grounding_available": True,
            "native_visual_retrieval": True,
            "visual_retrieval_kind": kind,
            "retrieval_text_source": "visual_anchor",
        },
    )


def _document_asset_root(document_id: str, root: str | Path) -> Path:
    safe_id = sha256(document_id.encode("utf-8")).hexdigest()[:24]
    return Path(root).expanduser().resolve() / f"doc_{safe_id}"


def _path_from_file_uri(source_uri: str) -> Path:
    parsed = urlparse(source_uri)
    if parsed.scheme != "file":
        raise ValueError(f"document source is not a file URI: {source_uri}")
    path = url2pathname(unquote(parsed.path))
    if os.name == "nt" and len(path) >= 3 and path[0] in "/\\" and path[2] == ":":
        path = path[1:]
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    return Path(path)


__all__ = [
    "ColPaliEngineVisualEmbeddingProvider",
    "QdrantVisualMultiVectorStore",
    "VISUAL_RETRIEVAL_VERSION",
    "VisualAwareIndexService",
    "VisualEmbeddingProvider",
    "VisualIndexCoordinator",
    "VisualRetrievalService",
    "build_visual_index_items",
    "create_visual_embedding_provider",
    "visual_retrieval_index_version",
    "weighted_rrf_fuse",
]
