from __future__ import annotations

import os
import re
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from backend.rag.models import (
    DocumentChunk,
    DocumentElement,
    NormalizedDocument,
    build_stable_chunk_id,
)

MULTIMODAL_INDEX_VERSION = "multimodal-v1"
DEFAULT_ASSET_STORAGE_PATH = "config/rag/assets"
_FIGURE_CAPTION = re.compile(
    r"(?im)^\s*((?:fig(?:ure)?\.?|图)\s*\d+[A-Za-z]?\s*[:.\-]?\s*[^\n]{0,400})"
)
_SAFE_EXTENSION = re.compile(r"^\.[a-zA-Z0-9]{1,8}$")


def _asset_root(asset_root: str | Path | None = None) -> Path:
    configured = asset_root or os.environ.get(
        "AITRANS_RAG_ASSET_DIR", DEFAULT_ASSET_STORAGE_PATH
    )
    return Path(configured).expanduser().resolve()


def _source_uri(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.expanduser().resolve().as_uri()
    value = str(source)
    parsed = urlparse(value)
    if parsed.scheme:
        return value
    return Path(value).expanduser().resolve().as_uri()


def _document_asset_root(
    source: str | Path,
    asset_root: str | Path | None = None,
) -> Path:
    identity = sha256(_source_uri(source).casefold().encode("utf-8")).hexdigest()[:24]
    return _asset_root(asset_root) / f"doc_{identity}"


def _asset_directory(
    source: str | Path,
    asset_root: str | Path | None = None,
    *,
    content_hash: str = "",
) -> Path:
    root = _document_asset_root(source, asset_root)
    fingerprint = (content_hash or "unversioned").strip()[:24]
    return root / fingerprint


def _safe_extension(name: str, *, fallback: str = ".bin") -> str:
    suffix = Path(name).suffix.lower()
    return suffix if _SAFE_EXTENSION.fullmatch(suffix) else fallback


def _persist_asset(
    *,
    directory: Path,
    element_id: str,
    data: bytes,
    source_name: str,
) -> str:
    if not data:
        return ""
    directory.mkdir(parents=True, exist_ok=True)
    extension = _safe_extension(source_name)
    target = directory / f"{element_id}{extension}"
    target.write_bytes(data)
    return target.resolve().as_uri()


def _captions(text: str) -> list[str]:
    return [match.group(1).strip() for match in _FIGURE_CAPTION.finditer(text or "")]


def _section_path_for_caption(document: NormalizedDocument, caption: str) -> list[str]:
    if not caption:
        return []
    for section in document.sections:
        if caption in section.text:
            return [section.heading] if section.heading.strip() else []
    return []


def _section_path_for_page(document: NormalizedDocument, page_number: int) -> list[str]:
    candidates: list[tuple[int, str]] = []
    for section in document.sections:
        raw_page = section.metadata.get("page_number")
        try:
            section_page = int(raw_page)
        except (TypeError, ValueError):
            continue
        if section_page <= page_number and section.heading.strip():
            candidates.append((section_page, section.heading.strip()))
    if not candidates:
        return []
    candidates.sort(key=lambda item: item[0])
    return [candidates[-1][1]]


def _surrogate_text(
    *,
    title: str,
    caption: str,
    page_number: int | None,
    section_path: list[str],
) -> str:
    parts = ["Figure"]
    if caption:
        parts.append(caption)
    if section_path:
        parts.append(f"Section: {' > '.join(section_path)}")
    if page_number is not None:
        parts.append(f"Page: {page_number}")
    if title:
        parts.append(f"Document: {title}")
    return ". ".join(parts).strip() + "."


def _element_id(
    document_id: str,
    *,
    page_number: int | None,
    index: int,
    source_name: str,
) -> str:
    payload = "\x1f".join(
        (document_id, str(page_number or 0), str(index), source_name)
    ).encode("utf-8")
    return f"element_{sha256(payload).hexdigest()[:24]}"


def _extract_pdf_elements(
    source: Path,
    document: NormalizedDocument,
    directory: Path,
) -> list[DocumentElement]:
    from pypdf import PdfReader

    reader = PdfReader(str(source))
    elements: list[DocumentElement] = []
    visual_index = 0
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = ""
        if page_number <= len(document.pages):
            page_text = document.pages[page_number - 1].text
        if not page_text:
            try:
                page_text = str(page.extract_text() or "")
            except Exception:
                page_text = ""
        captions = _captions(page_text)
        try:
            images: Iterable[object] = page.images
        except Exception:
            images = ()
        for page_image_index, image in enumerate(images):
            try:
                data = bytes(getattr(image, "data", b"") or b"")
            except Exception:
                continue
            if not data:
                continue
            source_name = str(getattr(image, "name", "") or f"image_{page_image_index}.bin")
            visual_index += 1
            element_id = _element_id(
                document.document.document_id,
                page_number=page_number,
                index=visual_index,
                source_name=source_name,
            )
            caption = captions[page_image_index] if page_image_index < len(captions) else ""
            section_path = (
                _section_path_for_caption(document, caption)
                or _section_path_for_page(document, page_number)
            )
            asset_uri = _persist_asset(
                directory=directory,
                element_id=element_id,
                data=data,
                source_name=source_name,
            )
            elements.append(
                DocumentElement(
                    element_id=element_id,
                    document_id=document.document.document_id,
                    modality="picture",
                    surrogate_text=_surrogate_text(
                        title=document.document.title,
                        caption=caption,
                        page_number=page_number,
                        section_path=section_path,
                    ),
                    page_number=page_number,
                    section_path=section_path,
                    caption=caption,
                    asset_uri=asset_uri,
                    metadata={
                        "source_kind": "pdf",
                        "asset_name": source_name,
                        "extraction_backend": "pypdf",
                        "layout_bbox_available": False,
                        "image_understanding_enabled": False,
                    },
                )
            )
    return elements


def _extract_docx_elements(
    source: Path,
    document: NormalizedDocument,
    directory: Path,
) -> list[DocumentElement]:
    from docx import Document

    docx = Document(str(source))
    captions = [
        paragraph.text.strip()
        for paragraph in docx.paragraphs
        if _FIGURE_CAPTION.match(paragraph.text or "")
    ]
    image_relationships = [
        (relationship_id, relationship)
        for relationship_id, relationship in docx.part.rels.items()
        if str(getattr(relationship, "reltype", "")).endswith("/image")
    ]
    elements: list[DocumentElement] = []
    for visual_index, (relationship_id, relationship) in enumerate(
        image_relationships, start=1
    ):
        try:
            part = relationship.target_part
            data = bytes(part.blob)
        except Exception:
            continue
        source_name = Path(str(getattr(part, "partname", ""))).name or f"image_{visual_index}.bin"
        element_id = _element_id(
            document.document.document_id,
            page_number=None,
            index=visual_index,
            source_name=source_name,
        )
        caption = captions[visual_index - 1] if visual_index <= len(captions) else ""
        section_path = _section_path_for_caption(document, caption)
        asset_uri = _persist_asset(
            directory=directory,
            element_id=element_id,
            data=data,
            source_name=source_name,
        )
        elements.append(
            DocumentElement(
                element_id=element_id,
                document_id=document.document.document_id,
                modality="picture",
                surrogate_text=_surrogate_text(
                    title=document.document.title,
                    caption=caption,
                    page_number=None,
                    section_path=section_path,
                ),
                section_path=section_path,
                caption=caption,
                asset_uri=asset_uri,
                metadata={
                    "source_kind": "docx",
                    "asset_name": source_name,
                    "relationship_id": relationship_id,
                    "extraction_backend": "python-docx",
                    "layout_stable": False,
                    "image_understanding_enabled": False,
                },
            )
        )
    return elements


def extract_visual_elements(
    source: str | Path,
    document: NormalizedDocument,
    *,
    asset_root: str | Path | None = None,
) -> list[DocumentElement]:
    """Best-effort extraction of original visual assets from PDF/DOCX sources.

    Extraction failures never invalidate an otherwise usable text index. This
    stage only creates retrieval surrogates and grounding assets; it does not
    claim VLM-based image understanding.
    """

    path = Path(source).expanduser().resolve()
    if path.suffix.lower() not in {".pdf", ".docx"}:
        return []
    directory = _asset_directory(
        path,
        asset_root,
        content_hash=document.document.content_hash,
    )
    try:
        if path.suffix.lower() == ".pdf":
            return _extract_pdf_elements(path, document, directory)
        return _extract_docx_elements(path, document, directory)
    except Exception:
        # Keep the previously committed content-addressed assets intact. A
        # failed extraction must not invalidate visual evidence referenced by
        # the last successful index.
        return []


def augment_document_with_visual_elements(
    document: NormalizedDocument,
    source: str | Path,
    *,
    asset_root: str | Path | None = None,
) -> NormalizedDocument:
    """Attach extracted visual elements while preserving the parser contract."""

    if Path(source).suffix.lower() not in {".pdf", ".docx"}:
        return document

    extracted = extract_visual_elements(source, document, asset_root=asset_root)
    if not extracted:
        return document.model_copy(
            update={
                "metadata": {
                    **document.metadata,
                    "multimodal_extraction_enabled": True,
                    "visual_element_count": len(document.elements),
                }
            }
        )

    existing_ids = {element.element_id for element in document.elements}
    combined = [*document.elements]
    combined.extend(
        element for element in extracted if element.element_id not in existing_ids
    )
    visual_mode = "surrogate_text_and_asset"
    return document.model_copy(
        update={
            "document": document.document.model_copy(
                update={
                    "metadata": {
                        **document.document.metadata,
                        "multimodal_extraction_enabled": True,
                        "visual_element_count": len(combined),
                        "visual_content_mode": visual_mode,
                        "image_understanding_enabled": False,
                    }
                }
            ),
            "elements": combined,
            "metadata": {
                **document.metadata,
                "multimodal_extraction_enabled": True,
                "visual_element_count": len(combined),
                "visual_content_mode": visual_mode,
                "image_understanding_enabled": False,
            },
        }
    )


def build_multimodal_chunks(
    document: NormalizedDocument,
    *,
    start_index: int,
    chunker_version: str,
) -> list[DocumentChunk]:
    """Turn element surrogate text into ordinary text-vector retrieval chunks."""

    chunks: list[DocumentChunk] = []
    for offset, element in enumerate(document.elements):
        text = element.surrogate_text.strip()
        if not text:
            continue
        chunk_index = start_index + offset
        section_heading = element.section_path[-1] if element.section_path else ""
        chunk_id = build_stable_chunk_id(
            document_hash=document.document.content_hash,
            section_heading=f"{section_heading}\x1f{element.element_id}",
            chunk_index=chunk_index,
            text=text,
        )
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                document_id=document.document.document_id,
                text=text,
                title=document.document.title,
                section_heading=section_heading,
                section_path=list(element.section_path),
                hierarchy_level=min(len(element.section_path), 6),
                parent_section_id=element.parent_id,
                chunk_type=f"{element.modality}_element",
                page_number=element.page_number,
                chunk_index=chunk_index,
                token_count=max(1, (len(text) + 3) // 4),
                language=document.document.language,
                source_uri=document.document.source_uri,
                document_hash=document.document.content_hash,
                parser_version=str(document.metadata.get("parser_version", "")),
                chunker_version=chunker_version,
                metadata={
                    "source_kind": document.document.source_kind,
                    "mime_type": document.document.mime_type,
                    "modality": element.modality,
                    "element_id": element.element_id,
                    "asset_uri": element.asset_uri,
                    "bbox": list(element.bbox) if element.bbox else None,
                    "caption": element.caption,
                    "related_ids": list(element.related_ids),
                    "retrieval_text_source": "surrogate_text",
                    "visual_grounding_available": bool(element.asset_uri),
                    "element_metadata": dict(element.metadata),
                },
            )
        )
    return chunks


def delete_document_assets(
    source: str | Path,
    *,
    asset_root: str | Path | None = None,
) -> None:
    """Remove persisted visual assets for one indexed source."""

    shutil.rmtree(_document_asset_root(source, asset_root), ignore_errors=True)


__all__ = [
    "DEFAULT_ASSET_STORAGE_PATH",
    "MULTIMODAL_INDEX_VERSION",
    "augment_document_with_visual_elements",
    "build_multimodal_chunks",
    "delete_document_assets",
    "extract_visual_elements",
]
