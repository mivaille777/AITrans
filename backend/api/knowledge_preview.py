from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from backend.api.knowledge_dependencies import get_knowledge_library_service
from backend.services.knowledge_library_service import KnowledgeLibraryService

router = APIRouter(prefix="/api/knowledge/documents", tags=["knowledge"])
KnowledgeLibraryDependency = Annotated[
    KnowledgeLibraryService,
    Depends(get_knowledge_library_service),
]


def _path_from_file_uri(source_uri: str) -> Path:
    parsed = urlparse(source_uri)
    if parsed.scheme != "file":
        raise ValueError("indexed document source is not a local file URI")
    path = url2pathname(unquote(parsed.path))
    if os.name == "nt" and len(path) >= 3 and path[0] in "/\\" and path[2] == ":":
        path = path[1:]
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    return Path(path)


@router.get("/{document_id}/preview", response_class=FileResponse)
def preview_knowledge_document(
    document_id: str,
    service: KnowledgeLibraryDependency,
) -> FileResponse:
    record = service.get_document(document_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )

    try:
        path = service.validate_source_path(_path_from_file_uri(record.source_uri))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge source file not found.",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    if path.suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Inline preview is currently available only for PDF knowledge documents.",
        )

    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["router"]
