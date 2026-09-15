from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.knowledge_dependencies import get_knowledge_library_service
from backend.models.knowledge_api import (
    KnowledgeDocumentDeleteResponse,
    KnowledgeDocumentImportRequest,
    KnowledgeDocumentImportResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentOutlineResponse,
    KnowledgeDocumentOutlineSection,
    KnowledgeDocumentResponse,
    KnowledgeDocumentSectionResponse,
    KnowledgeDocumentStatusResponse,
    KnowledgeRuntimeResponse,
)
from backend.rag.index_manifest import IndexManifestRecord, IndexStatus
from backend.rag.index_service import IndexDocumentResult
from backend.services.knowledge_library_service import KnowledgeLibraryService

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
KnowledgeLibraryDependency = Annotated[
    KnowledgeLibraryService,
    Depends(get_knowledge_library_service),
]


def _source_type(source_uri: str) -> str:
    suffix = Path(urlparse(source_uri).path).suffix.lower().lstrip(".")
    return suffix or "unknown"


def _document(record: IndexManifestRecord) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(
        document_id=record.document_id,
        title=record.title,
        source_uri=record.source_uri,
        source_type=_source_type(record.source_uri),
        status=record.status,
        chunk_count=len(record.chunk_ids),
        indexed_at=record.indexed_at,
        error=record.error,
        content_hash=record.content_hash,
        parser_version=record.parser_version,
        chunker_version=record.chunker_version,
        embedding_model=record.embedding_model,
        embedding_dimension=record.embedding_dimension,
        structure_quality=record.structure_quality,
        section_count=record.section_count,
        reindex_recommended=record.reindex_recommended,
    )


def _record_or_404(
    document_id: str,
    service: KnowledgeLibraryService,
) -> IndexManifestRecord:
    record = service.get_document(document_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )
    return record


def _raise_path_error(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge source file not found.",
        ) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    ) from exc


def _ensure_index_succeeded(result: IndexDocumentResult) -> None:
    if result.status is not IndexStatus.FAILED:
        return
    detail = result.error.strip() or "unknown indexing failure"
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Knowledge indexing failed: {detail}",
    )


@router.post(
    "/documents",
    response_model=KnowledgeDocumentImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_knowledge_document(
    payload: KnowledgeDocumentImportRequest,
    service: KnowledgeLibraryDependency,
) -> KnowledgeDocumentImportResponse:
    try:
        result = service.import_document(payload.path)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        _raise_path_error(exc)
    _ensure_index_succeeded(result)
    record = _record_or_404(result.document_id, service)
    return KnowledgeDocumentImportResponse(
        document=_document(record),
        reused_existing=result.reused_existing,
        elapsed_ms=result.elapsed_ms,
    )


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
def list_knowledge_documents(
    service: KnowledgeLibraryDependency,
) -> KnowledgeDocumentListResponse:
    documents = [_document(record) for record in service.list_documents()]
    return KnowledgeDocumentListResponse(total=len(documents), documents=documents)


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentResponse,
)
def get_knowledge_document(
    document_id: str,
    service: KnowledgeLibraryDependency,
) -> KnowledgeDocumentResponse:
    return _document(_record_or_404(document_id, service))


@router.get(
    "/documents/{document_id}/outline",
    response_model=KnowledgeDocumentOutlineResponse,
)
def get_knowledge_document_outline(
    document_id: str,
    service: KnowledgeLibraryDependency,
) -> KnowledgeDocumentOutlineResponse:
    _record_or_404(document_id, service)
    try:
        outline = service.get_document_outline(document_id)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        _raise_path_error(exc)
    if outline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )
    sections = [
        KnowledgeDocumentOutlineSection(
            section_id=section.section_id,
            heading=section.heading,
            level=section.level,
            parent_section_id=section.parent_section_id,
            section_path=list(section.section_path),
            page_start=section.page_start,
            page_end=section.page_end,
            block_count=section.block_count,
            has_equations=section.has_equations,
            has_tables=section.has_tables,
            has_figures=section.has_figures,
            reference_section=section.reference_section,
            synthetic=section.synthetic,
        )
        for section in outline.sections
    ]
    return KnowledgeDocumentOutlineResponse(
        document_id=outline.document_id,
        title=outline.title,
        page_count=outline.page_count,
        section_count=len(sections),
        sections=sections,
    )


@router.get(
    "/documents/{document_id}/sections/{section_id}",
    response_model=KnowledgeDocumentSectionResponse,
)
def get_knowledge_document_section(
    document_id: str,
    section_id: str,
    service: KnowledgeLibraryDependency,
) -> KnowledgeDocumentSectionResponse:
    _record_or_404(document_id, service)
    try:
        section = service.get_document_section(document_id, section_id)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        _raise_path_error(exc)
    if section is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document section not found.",
        )
    return KnowledgeDocumentSectionResponse(
        document_id=section.document_id,
        section_id=section.section_id,
        heading=section.heading,
        level=section.level,
        section_path=list(section.section_path),
        page_start=section.page_start,
        page_end=section.page_end,
        text=section.text,
        truncated=section.truncated,
    )


@router.delete(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentDeleteResponse,
)
def delete_knowledge_document(
    document_id: str,
    service: KnowledgeLibraryDependency,
) -> KnowledgeDocumentDeleteResponse:
    _record_or_404(document_id, service)
    deleted = service.delete_document(document_id)
    return KnowledgeDocumentDeleteResponse(
        document_id=document_id,
        deleted=deleted,
        source_file_preserved=True,
    )


@router.post(
    "/documents/{document_id}/reindex",
    response_model=KnowledgeDocumentImportResponse,
)
def reindex_knowledge_document(
    document_id: str,
    service: KnowledgeLibraryDependency,
) -> KnowledgeDocumentImportResponse:
    _record_or_404(document_id, service)
    try:
        result = service.reindex_document(document_id)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        _raise_path_error(exc)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )
    _ensure_index_succeeded(result)
    record = _record_or_404(result.document_id, service)
    return KnowledgeDocumentImportResponse(
        document=_document(record),
        reused_existing=result.reused_existing,
        elapsed_ms=result.elapsed_ms,
    )


@router.get(
    "/documents/{document_id}/status",
    response_model=KnowledgeDocumentStatusResponse,
)
def get_knowledge_document_status(
    document_id: str,
    service: KnowledgeLibraryDependency,
) -> KnowledgeDocumentStatusResponse:
    record = _record_or_404(document_id, service)
    return KnowledgeDocumentStatusResponse(
        document_id=record.document_id,
        status=record.status,
        chunk_count=len(record.chunk_ids),
        indexed_at=record.indexed_at,
        error=record.error,
    )


@router.get("/runtime", response_model=KnowledgeRuntimeResponse)
def get_knowledge_runtime(
    service: KnowledgeLibraryDependency,
) -> KnowledgeRuntimeResponse:
    runtime = service.runtime()
    return KnowledgeRuntimeResponse(
        enabled=runtime.enabled,
        embedding_provider=runtime.embedding_provider,
        embedding_model=runtime.embedding_model,
        embedding_status=runtime.embedding_status,
        device=runtime.device,
        dimension=runtime.dimension,
        vector_store_provider=runtime.vector_store_provider,
        collection_name=runtime.collection_name,
        document_count=runtime.document_count,
        ready_document_count=runtime.ready_document_count,
        indexed_chunk_count=runtime.indexed_chunk_count,
        max_file_bytes=runtime.max_file_bytes,
    )


__all__ = ["router"]
