from __future__ import annotations

from pathlib import Path

import pytest

from backend.rag.config import RagAdvancedParsingConfig, RagConfig
from backend.rag.exceptions import RagParsingError
from backend.rag.models import KnowledgeDocument, NormalizedDocument
from backend.rag.parsers import (
    AdvancedParserWithFallback,
    DoclingDocumentParser,
    DocxDocumentParser,
    PdfDocumentParser,
    get_parser_for_path,
)
from backend.rag.parsers.docling import DoclingConversion


class FakeDoclingBackend:
    def __init__(
        self,
        text: str | DoclingConversion = "# Paper title\n\nIntroduction text.",
    ) -> None:
        self.text = text
        self.calls: list[tuple[Path, RagAdvancedParsingConfig]] = []

    def convert(
        self,
        path: Path,
        config: RagAdvancedParsingConfig,
    ) -> str | DoclingConversion:
        self.calls.append((path, config))
        return self.text


class StubParser:
    name = "stub"
    version = "1"
    supported_suffixes = frozenset({".pdf"})

    def __init__(
        self,
        *,
        result: NormalizedDocument | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def supports(self, source: str | Path) -> bool:
        return Path(source).suffix.lower() == ".pdf"

    def parse(self, source: str | Path) -> NormalizedDocument:
        self.calls += 1
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


def _basic_result(path: Path) -> NormalizedDocument:
    return NormalizedDocument(
        document=KnowledgeDocument(
            document_id="doc-basic",
            title="Basic",
            source_uri=path.as_uri(),
            source_kind="pdf",
        ),
        text="Basic parser text",
        metadata={"parser_name": "pdf"},
    )


def test_advanced_parsing_model_defaults_remain_safe_and_ocr_is_disabled() -> None:
    config = RagConfig()

    assert config.advanced_parsing.enabled is False
    assert config.advanced_parsing.device == "cpu"
    assert config.advanced_parsing.layout_enabled is True
    assert config.advanced_parsing.table_enabled is False
    assert config.advanced_parsing.ocr_enabled is False
    assert config.advanced_parsing.formula_enabled is False


def test_docling_parser_preserves_reading_order_sections_and_feature_flags(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF mock")
    backend = FakeDoclingBackend(
        "# Paper title\n\nIntro text.\n\n## Results\n\n| A | B |\n|---|---|\n| 1 | 2 |"
    )
    config = RagAdvancedParsingConfig(
        enabled=True,
        table_enabled=True,
        formula_enabled=True,
    )

    result = DoclingDocumentParser(config, backend=backend).parse(source)

    assert result.document.title == "Paper title"
    assert [section.heading for section in result.sections] == [
        "Paper title",
        "Results",
    ]
    assert result.text.index("Intro text.") < result.text.index("Results")
    assert "| 1 | 2 |" in result.text
    assert result.metadata["parser_name"] == "docling"
    assert result.metadata["parser_version"].startswith("docling-v4;")
    assert "device=cpu" in result.metadata["parser_version"]
    assert "table=1" in result.metadata["parser_version"]
    assert "formula=1" in result.metadata["parser_version"]
    assert result.metadata["parser_device"] == "cpu"
    assert result.metadata["section_count"] == 2
    assert result.metadata["table_enabled"] is True
    assert result.metadata["ocr_enabled"] is False
    assert result.metadata["formula_enabled"] is True
    assert result.metadata["image_understanding_enabled"] is False
    assert result.metadata["visual_content_mode"] == "caption_and_text_only"
    assert result.document.metadata["layout_preserved"] is True
    assert result.document.metadata["table_structure_enabled"] is True
    assert backend.calls == [(source.resolve(), config)]


def test_docling_parser_preserves_page_offsets_and_figure_caption_text(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF mock")
    backend = FakeDoclingBackend(
        DoclingConversion(
            pages=(
                (1, "# Paper title\n\nIntroduction text."),
                (
                    2,
                    "## Results\n\n<!-- image -->\n\n"
                    "Fig. 1. Controller comparison.\n\nResult text.",
                ),
            )
        )
    )

    result = DoclingDocumentParser(
        RagAdvancedParsingConfig(enabled=True, layout_enabled=True),
        backend=backend,
    ).parse(source)

    assert [page.page_number for page in result.pages] == [1, 2]
    assert result.metadata["page_count"] == 2
    assert "<!-- image -->" not in result.text
    assert "Fig. 1. Controller comparison." in result.text
    assert result.text[
        result.pages[0].start_char : result.pages[0].end_char
    ] == result.pages[0].text
    assert result.text[
        result.pages[1].start_char : result.pages[1].end_char
    ] == result.pages[1].text
    assert result.pages[0].end_char <= result.pages[1].start_char
    assert result.sections[1].metadata["page_number"] == 2


def test_docling_parser_version_changes_when_parsing_profile_changes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF mock")
    backend = FakeDoclingBackend()

    basic_profile = DoclingDocumentParser(
        RagAdvancedParsingConfig(enabled=True, table_enabled=False),
        backend=backend,
    ).parse(source)
    table_profile = DoclingDocumentParser(
        RagAdvancedParsingConfig(enabled=True, table_enabled=True),
        backend=backend,
    ).parse(source)
    cuda_profile = DoclingDocumentParser(
        RagAdvancedParsingConfig(enabled=True, device="cuda", table_enabled=True),
        backend=backend,
    ).parse(source)

    assert basic_profile.metadata["parser_version"] != table_profile.metadata["parser_version"]
    assert table_profile.metadata["parser_version"] != cuda_profile.metadata["parser_version"]
    assert "table=0" in basic_profile.metadata["parser_version"]
    assert "table=1" in table_profile.metadata["parser_version"]
    assert "device=cuda" in cuda_profile.metadata["parser_version"]


def test_registry_keeps_basic_parser_by_default_and_wraps_opt_in_pdf() -> None:
    assert isinstance(get_parser_for_path("paper.pdf"), PdfDocumentParser)

    parser = get_parser_for_path(
        "paper.pdf",
        advanced_config=RagAdvancedParsingConfig(enabled=True),
    )

    assert isinstance(parser, AdvancedParserWithFallback)
    assert isinstance(parser.primary, DoclingDocumentParser)
    assert isinstance(parser.fallback, PdfDocumentParser)
    assert isinstance(
        get_parser_for_path(
            "paper.docx",
            advanced_config=RagAdvancedParsingConfig(enabled=True),
        ),
        DocxDocumentParser,
    )


def test_advanced_parser_failure_falls_back_and_records_bounded_reason(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF mock")
    primary = StubParser(error=RagParsingError("advanced failed: " + "x" * 500))
    fallback = StubParser(result=_basic_result(source))
    parser = AdvancedParserWithFallback(primary, fallback)

    result = parser.parse(source)

    assert primary.calls == 1
    assert fallback.calls == 1
    assert result.text == "Basic parser text"
    assert result.metadata["advanced_parser_enabled"] is True
    assert result.metadata["advanced_parser_fallback"] is True
    assert result.metadata["advanced_parser_name"] == "stub"
    assert len(result.metadata["advanced_parser_error"]) == 300


def test_docling_empty_output_is_a_parse_error(tmp_path: Path) -> None:
    source = tmp_path / "empty.pdf"
    source.write_bytes(b"%PDF mock")

    with pytest.raises(RagParsingError, match="no extractable text"):
        DoclingDocumentParser(backend=FakeDoclingBackend(" \n ")).parse(source)
