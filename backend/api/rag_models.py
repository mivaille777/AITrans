from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.rag_model_dependencies import (
    get_rag_model_manager,
    get_rag_model_runtime_health,
    set_rag_model_runtime_health,
)
from backend.api.knowledge_dependencies import get_rag_runtime
from backend.models.rag_runtime import (
    RagModelListResponse,
    RagModelOperationResponse,
    RagModelStatusResponse,
)
from backend.rag.exceptions import RagModelManagerError
from backend.rag.model_manager import ModelManager
from backend.rag.model_manager import EMBEDDING_MODEL_ID, RERANKER_MODEL_ID
from backend.rag.models import DocumentChunk, RetrievalCandidate

router = APIRouter(prefix="/api/rag/models", tags=["rag-models"])
ModelManagerDependency = Annotated[ModelManager, Depends(get_rag_model_manager)]


def _raise_model_error(exc: RagModelManagerError) -> None:
    detail = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if detail.startswith("unknown managed RAG model")
        else status.HTTP_409_CONFLICT
    )
    raise HTTPException(status_code=code, detail=detail) from exc


def _with_runtime_health(model: RagModelStatusResponse) -> RagModelStatusResponse:
    health = get_rag_model_runtime_health(model.model_id)
    return model.model_copy(
        update={"runtime_ready": health.ready, "runtime_error": health.error}
    )


def _probe_runtime(model_id: str) -> RagModelStatusResponse:
    """Load the requested model in the serving process and exercise it once."""

    runtime = get_rag_runtime()
    if model_id == EMBEDDING_MODEL_ID:
        vector = runtime.embedding_provider.embed_query("RAG runtime health check")
        if len(vector) != runtime.embedding_provider.dimension:
            raise RuntimeError("embedding health check returned an unexpected dimension")
        if not all(isinstance(value, (float, int)) for value in vector):
            raise RuntimeError("embedding health check returned non-numeric values")
    elif model_id == RERANKER_MODEL_ID:
        candidate = RetrievalCandidate(
            chunk=DocumentChunk(
                chunk_id="runtime-health-reranker",
                document_id="runtime-health",
                text="A model health check verifies that reranking is available.",
                chunk_index=0,
            ),
            rank=1,
        )
        ranked = runtime.retrieval_service._reranker.rerank(  # noqa: SLF001 - same runtime probe
            "model health check",
            [candidate],
            top_k=1,
        )
        if len(ranked) != 1 or ranked[0].rerank_score is None:
            raise RuntimeError("reranker health check returned no score")
    else:
        raise RagModelManagerError(f"unknown managed RAG model: {model_id}")
    return _with_runtime_health(get_rag_model_manager().status(model_id))


@router.get("", response_model=RagModelListResponse)
def list_rag_models(manager: ModelManagerDependency) -> RagModelListResponse:
    return RagModelListResponse(
        models_root=str(manager.models_root),
        models=[_with_runtime_health(model) for model in manager.statuses()],
    )


@router.get("/{model_id}", response_model=RagModelStatusResponse)
def get_rag_model(
    model_id: str,
    manager: ModelManagerDependency,
) -> RagModelStatusResponse:
    try:
        return _with_runtime_health(manager.status(model_id))
    except RagModelManagerError as exc:
        _raise_model_error(exc)


@router.post(
    "/{model_id}/download",
    response_model=RagModelOperationResponse,
)
def download_rag_model(
    model_id: str,
    manager: ModelManagerDependency,
) -> RagModelOperationResponse:
    try:
        changed = not manager.is_installed(model_id)
        manager.download(model_id)
        return RagModelOperationResponse(
            model=_with_runtime_health(manager.status(model_id)), changed=changed
        )
    except RagModelManagerError as exc:
        _raise_model_error(exc)


@router.post(
    "/{model_id}/verify",
    response_model=RagModelStatusResponse,
)
def verify_rag_model(
    model_id: str,
    manager: ModelManagerDependency,
) -> RagModelStatusResponse:
    try:
        if not manager.verify(model_id):
            raise RagModelManagerError("model files failed verification")
        try:
            response = _probe_runtime(model_id)
        except Exception as exc:  # noqa: BLE001 - endpoint returns actionable state
            set_rag_model_runtime_health(
                model_id,
                ready=False,
                error=str(exc) or exc.__class__.__name__,
            )
            return _with_runtime_health(manager.status(model_id))
        set_rag_model_runtime_health(model_id, ready=True)
        return _with_runtime_health(response)
    except RagModelManagerError as exc:
        _raise_model_error(exc)


@router.delete(
    "/{model_id}",
    response_model=RagModelOperationResponse,
)
def remove_rag_model(
    model_id: str,
    manager: ModelManagerDependency,
) -> RagModelOperationResponse:
    try:
        changed = manager.remove(model_id)
        return RagModelOperationResponse(
            model=_with_runtime_health(manager.status(model_id)), changed=changed
        )
    except RagModelManagerError as exc:
        _raise_model_error(exc)


__all__ = ["router"]
