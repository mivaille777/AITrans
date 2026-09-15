from __future__ import annotations

import re
from pathlib import Path

from backend.rag.exceptions import RagParsingError
from backend.rag.models import NormalizedDocument
from backend.rag.parsers.base import BaseFileParser, ParsedBlock, compose_blocks

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


class TextDocumentParser(BaseFileParser):
    name = "text"
    version = "text-v1"
    supported_suffixes = frozenset({".txt", ".md", ".markdown"})

    def parse(self, source: str | Path) -> NormalizedDocument:
        path = self._resolve_source(source)
        raw_bytes = self._read_bytes(path)
        text, encoding = self._decode(raw_bytes, path)
        text = self._normalize_text(text)
        if not text:
            raise RagParsingError(f"document contains no extractable text: {path}")

        is_markdown = path.suffix.lower() in {".md", ".markdown"}
        sections = []
        title = path.stem
        if is_markdown:
            blocks: list[ParsedBlock] = []
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                match = _MARKDOWN_HEADING.match(stripped)
                if match:
                    heading = match.group(2).strip()
                    blocks.append(ParsedBlock(heading, len(match.group(1))))
                    if title == path.stem and len(match.group(1)) == 1:
                        title = heading
                else:
                    blocks.append(ParsedBlock(stripped))
            rendered, sections = compose_blocks(blocks)
            if rendered:
                text = rendered

        document = self._build_document(
            path=path,
            raw_bytes=raw_bytes,
            title=title,
            source_kind="markdown" if is_markdown else "text",
            mime_type="text/markdown" if is_markdown else "text/plain",
            metadata={"encoding": encoding},
        )
        return NormalizedDocument(
            document=document,
            text=text,
            sections=sections,
            metadata={"parser_name": self.name, "parser_version": self.version},
        )

    @staticmethod
    def _decode(raw_bytes: bytes, path: Path) -> tuple[str, str]:
        for encoding in ("utf-8-sig", "utf-16", "gb18030"):
            try:
                return raw_bytes.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise RagParsingError(f"unsupported text encoding: {path}")


__all__ = ["TextDocumentParser"]
