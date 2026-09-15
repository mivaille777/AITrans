from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol, runtime_checkable

from backend.rag.exceptions import RagParsingError
from backend.rag.models import DocumentSection, KnowledgeDocument, NormalizedDocument


@runtime_checkable
class DocumentParser(Protocol):
    name: str
    version: str
    supported_suffixes: frozenset[str]

    def supports(self, source: str | Path) -> bool: ...
    def parse(self, source: str | Path) -> NormalizedDocument: ...


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    text: str
    heading_level: int | None = None


class BaseFileParser:
    name = "base"
    version = "1"
    supported_suffixes: frozenset[str] = frozenset()

    def supports(self, source: str | Path) -> bool:
        return Path(source).suffix.lower() in self.supported_suffixes

    def _resolve_source(self, source: str | Path) -> Path:
        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise RagParsingError(f"document does not exist: {path}")
        if not path.is_file():
            raise RagParsingError(f"document source is not a file: {path}")
        if not self.supports(path):
            suffix = path.suffix or "<none>"
            raise RagParsingError(f"{self.name} does not support document type: {suffix}")
        return path

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise RagParsingError(f"failed to read document: {path}") from exc

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()

    def _build_document(
        self,
        *,
        path: Path,
        raw_bytes: bytes,
        title: str,
        source_kind: str,
        mime_type: str,
        language: str = "unknown",
        metadata: dict[str, object] | None = None,
    ) -> KnowledgeDocument:
        content_hash = sha256(raw_bytes).hexdigest()
        source_uri = path.as_uri()
        source_identity = sha256(source_uri.casefold().encode("utf-8")).hexdigest()
        document_metadata: dict[str, object] = {
            "file_name": path.name,
            "size_bytes": len(raw_bytes),
        }
        if metadata:
            document_metadata.update(metadata)
        return KnowledgeDocument(
            document_id=f"doc_{source_identity[:24]}",
            title=title.strip() or path.stem,
            source_uri=source_uri,
            source_kind=source_kind,
            mime_type=mime_type,
            language=language,
            content_hash=content_hash,
            metadata=document_metadata,
        )


def compose_blocks(blocks: list[ParsedBlock]) -> tuple[str, list[DocumentSection]]:
    """Render linear blocks and derive section spans from heading blocks."""
    clean_blocks = [
        ParsedBlock(text=block.text.strip(), heading_level=block.heading_level)
        for block in blocks
        if block.text.strip()
    ]
    if not clean_blocks:
        return "", []

    parts: list[str] = []
    positions: list[tuple[int, int]] = []
    cursor = 0
    for index, block in enumerate(clean_blocks):
        if index:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(block.text)
        cursor += len(block.text)
        positions.append((start, cursor))
    text = "".join(parts)

    heading_indices = [
        index for index, block in enumerate(clean_blocks) if block.heading_level is not None
    ]
    sections: list[DocumentSection] = []
    for heading_position, block_index in enumerate(heading_indices):
        block = clean_blocks[block_index]
        start = positions[block_index][0]
        if heading_position + 1 < len(heading_indices):
            next_start = positions[heading_indices[heading_position + 1]][0]
            end = len(text[:next_start].rstrip())
        else:
            end = len(text)
        sections.append(
            DocumentSection(
                heading=block.text,
                level=block.heading_level or 1,
                text=text[start:end],
                start_char=start,
                end_char=end,
            )
        )
    return text, sections


__all__ = ["BaseFileParser", "DocumentParser", "ParsedBlock", "compose_blocks"]
