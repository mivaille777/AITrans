from __future__ import annotations

from pathlib import Path

from lxml import html as lxml_html

from backend.rag.exceptions import RagParsingError
from backend.rag.models import NormalizedDocument
from backend.rag.parsers.base import BaseFileParser, ParsedBlock, compose_blocks


class HtmlDocumentParser(BaseFileParser):
    name = "html"
    version = "html-v1"
    supported_suffixes = frozenset({".html", ".htm"})

    def parse(self, source: str | Path) -> NormalizedDocument:
        path = self._resolve_source(source)
        raw_bytes = self._read_bytes(path)
        try:
            root = lxml_html.fromstring(raw_bytes)
        except Exception as exc:
            raise RagParsingError(f"failed to parse HTML document: {path}") from exc

        for element in root.xpath(
            "//script|//style|//nav|//header|//footer|//aside|//form|//noscript"
        ):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)

        title_nodes = root.xpath("//title")
        title = self._element_text(title_nodes[0]) if title_nodes else path.stem
        body_nodes = root.xpath("//body")
        container = body_nodes[0] if body_nodes else root

        blocks: list[ParsedBlock] = []
        xpath = (
            ".//*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or "
            "self::h6 or self::p or self::li or self::pre or self::blockquote]"
        )
        for element in container.xpath(xpath):
            text = self._element_text(element)
            if not text:
                continue
            tag = str(element.tag).lower()
            heading_level = (
                int(tag[1])
                if len(tag) == 2 and tag.startswith("h") and tag[1].isdigit()
                else None
            )
            blocks.append(ParsedBlock(text=text, heading_level=heading_level))

        text, sections = compose_blocks(blocks)
        if not text:
            text = self._normalize_text(container.text_content())
        if not text:
            raise RagParsingError(f"document contains no extractable text: {path}")

        document = self._build_document(
            path=path,
            raw_bytes=raw_bytes,
            title=title,
            source_kind="html",
            mime_type="text/html",
        )
        return NormalizedDocument(
            document=document,
            text=text,
            sections=sections,
            metadata={"parser_name": self.name, "parser_version": self.version},
        )

    @staticmethod
    def _element_text(element: object) -> str:
        text_content = getattr(element, "text_content", None)
        if not callable(text_content):
            return ""
        return " ".join(str(text_content()).split()).strip()


__all__ = ["HtmlDocumentParser"]
