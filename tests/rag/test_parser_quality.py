from __future__ import annotations

import os
import sys
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from backend.rag.config import RagAdvancedParsingConfig
from backend.rag.exceptions import RagParsingError
from backend.rag.parsers.docling import (
    DefaultDoclingBackend,
    DoclingConversion,
    DoclingDocumentParser,
)


class FakeDoclingBackend:
    def __init__(self, conversion: DoclingConversion) -> None:
        self.conversion = conversion
        self.configs: list[RagAdvancedParsingConfig] = []

    def convert(
        self,
        path: Path,
        config: RagAdvancedParsingConfig,
    ) -> DoclingConversion:
        self.configs.append(config)
        return self.conversion


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.pdf"
    path.write_bytes(b"%PDF parser quality fixture")
    return path


def _write_docling_quality_pdf(path: Path) -> None:
    """Build a PDF with columns, a ruled table, and a raster-text scan page."""
    from PIL import Image, ImageDraw

    def stream_object(data: bytes) -> bytes:
        return (
            b"<< /Length "
            + str(len(data)).encode()
            + b" >>\nstream\n"
            + data
            + b"\nendstream"
        )

    columns = (
        b"BT /F1 12 Tf 45 745 Td (Two column paper) Tj "
        b"0 -28 Td (LEFT A) Tj 0 -20 Td (LEFT B) Tj 0 -20 Td (LEFT C) Tj "
        b"210 40 Td (RIGHT A) Tj 0 -20 Td (RIGHT B) Tj 0 -20 Td (RIGHT C) Tj ET"
    )
    table = (
        b"q 1 w 45 700 m 350 700 l 45 660 m 350 660 l 45 620 m 350 620 l "
        b"45 580 m 350 580 l 45 700 m 45 580 l 190 700 m 190 580 l "
        b"350 700 m 350 580 l S Q "
        b"BT /F1 12 Tf 55 680 Td (Method) Tj 155 0 Td (Score) Tj "
        b"-155 -40 Td (Alpha) Tj 155 0 Td (0.9) Tj "
        b"-155 -40 Td (Beta) Tj 155 0 Td (0.8) Tj ET"
    )
    image_bytes = BytesIO()
    scanned_page = Image.new("RGB", (300, 100), "white")
    ImageDraw.Draw(scanned_page).text((10, 35), "SCANNED PAGE 3", fill="black")
    scanned_page.save(image_bytes, format="JPEG")
    image_data = image_bytes.getvalue()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 6 0 R 8 0 R] /Count 3 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        stream_object(columns),
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 7 0 R >>"
        ),
        stream_object(table),
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im0 10 0 R >> >> /Contents 9 0 R >>"
        ),
        stream_object(b"q 300 0 0 300 100 300 cm /Im0 Do Q"),
        b"<< /Type /XObject /Subtype /Image /Width 100 /Height 100 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
        + str(len(image_data)).encode()
        + b" >>\nstream\n"
        + image_data
        + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(item)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


def test_scanned_page_is_flagged_with_source_page_and_ocr_profile(
    tmp_path: Path,
) -> None:
    backend = FakeDoclingBackend(DoclingConversion(pages=((3, ""), (4, "Short title"))))
    config = RagAdvancedParsingConfig(enabled=True, ocr_enabled=False)

    result = DoclingDocumentParser(config, backend=backend).parse(_source(tmp_path))

    diagnostics = result.metadata["parse_diagnostics"]
    assert diagnostics["quality_status"] == "low_text"
    assert diagnostics["source_page_numbers"] == [3, 4]
    assert diagnostics["no_text_source_pages"] == [3]
    assert diagnostics["scan_suspect_source_pages"] == [3]
    assert diagnostics["ocr_status"] == "disabled"
    assert result.pages[0].page_number == 3
    assert result.pages[0].text == ""
    assert backend.configs == [config]


def test_empty_scanned_document_is_rejected_with_parser_diagnostics(
    tmp_path: Path,
) -> None:
    parser = DoclingDocumentParser(
        RagAdvancedParsingConfig(enabled=True, ocr_enabled=False),
        backend=FakeDoclingBackend(DoclingConversion(pages=((7, ""), (8, "")))),
    )

    with pytest.raises(RagParsingError) as error:
        parser.parse(_source(tmp_path))

    message = str(error.value)
    assert "quality_status': 'empty'" in message
    assert "no_text_source_pages': [7, 8]" in message
    assert "ocr_status': 'disabled'" in message


def test_double_column_output_retains_export_order_and_physical_page(
    tmp_path: Path,
) -> None:
    page_text = (
        "# Two column paper\n\n"
        "LEFT COLUMN FIRST\n\nLEFT COLUMN SECOND\n\n"
        "RIGHT COLUMN FIRST\n\nRIGHT COLUMN SECOND"
    )
    parser = DoclingDocumentParser(
        RagAdvancedParsingConfig(enabled=True, layout_enabled=True),
        backend=FakeDoclingBackend(
            DoclingConversion(
                pages=((6, page_text),),
                source_page_numbers=(6,),
                page_order_status="ordered",
            )
        ),
    )

    result = parser.parse(_source(tmp_path))

    diagnostics = result.metadata["parse_diagnostics"]
    assert result.text.index("LEFT COLUMN FIRST") < result.text.index(
        "RIGHT COLUMN FIRST"
    )
    assert result.pages[0].page_number == 6
    assert diagnostics["source_page_numbers"] == [6]
    assert diagnostics["reading_order_status"] == "docling_export_order_unverified"


def test_table_diagnostics_include_count_and_source_page(tmp_path: Path) -> None:
    table_text = "# Results\n\n| Method | Score |\n|---|---|\n| A | 0.9 |"
    parser = DoclingDocumentParser(
        RagAdvancedParsingConfig(enabled=True, table_enabled=True),
        backend=FakeDoclingBackend(
            DoclingConversion(
                pages=((2, table_text),),
                source_page_numbers=(2,),
                table_count=1,
                table_source_page_numbers=(2,),
            )
        ),
    )

    result = parser.parse(_source(tmp_path))

    diagnostics = result.metadata["parse_diagnostics"]
    assert "| A | 0.9 |" in result.text
    assert diagnostics["table_status"] == "detected"
    assert diagnostics["table_count"] == 1
    assert diagnostics["table_source_page_numbers"] == [2]
    assert diagnostics["table_source_page_mapping_status"] == "available"


def test_backend_extracts_docling_page_order_table_provenance_and_ocr_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_pipeline_options: list[object] = []
    page_text = {1: "Page one text.", 2: "| A | B |\n|---|---|"}

    class FakeDocument:
        def __init__(self) -> None:
            self.pages = {
                2: SimpleNamespace(page_no=2),
                1: SimpleNamespace(page_no=1),
            }
            self.tables = [SimpleNamespace(prov=[SimpleNamespace(page_no=2)])]

        def export_to_markdown(
            self,
            *,
            page_no: int | None = None,
            image_placeholder: str,
            traverse_pictures: bool,
        ) -> str:
            assert image_placeholder
            assert traverse_pictures is True
            return (
                "\n\n".join(page_text.values())
                if page_no is None
                else page_text[page_no]
            )

        def export_to_text(self) -> str:
            return " ".join(page_text.values())

    fake_document = FakeDocument()

    class FakeAcceleratorOptions:
        def __init__(self, *, device: str) -> None:
            self.device = device

    class FakePdfPipelineOptions:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)
            captured_pipeline_options.append(self)

    class FakePdfFormatOption:
        def __init__(self, *, pipeline_options: object) -> None:
            self.pipeline_options = pipeline_options

    class FakeDocumentConverter:
        def __init__(self, *, format_options: dict[object, object]) -> None:
            self.format_options = format_options

        def convert(self, path: Path) -> SimpleNamespace:
            return SimpleNamespace(document=fake_document)

    modules = {
        "docling.datamodel.accelerator_options": ModuleType(
            "docling.datamodel.accelerator_options"
        ),
        "docling.datamodel.base_models": ModuleType("docling.datamodel.base_models"),
        "docling.datamodel.pipeline_options": ModuleType(
            "docling.datamodel.pipeline_options"
        ),
        "docling.document_converter": ModuleType("docling.document_converter"),
    }
    modules[
        "docling.datamodel.accelerator_options"
    ].AcceleratorOptions = FakeAcceleratorOptions
    modules["docling.datamodel.base_models"].InputFormat = SimpleNamespace(PDF="pdf")
    modules[
        "docling.datamodel.pipeline_options"
    ].PdfPipelineOptions = FakePdfPipelineOptions
    modules["docling.document_converter"].DocumentConverter = FakeDocumentConverter
    modules["docling.document_converter"].PdfFormatOption = FakePdfFormatOption
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    source = _source(tmp_path)
    backend = DefaultDoclingBackend()
    disabled = backend.convert(
        source,
        RagAdvancedParsingConfig(enabled=True, ocr_enabled=False),
    )
    enabled = backend.convert(
        source,
        RagAdvancedParsingConfig(enabled=True, ocr_enabled=True),
    )

    assert disabled.source_page_numbers == (1, 2)
    assert disabled.page_order_status == "reordered_to_source_page"
    assert disabled.table_count == 1
    assert disabled.table_source_page_numbers == (2,)
    assert enabled.page_order_status == "reordered_to_source_page"
    assert [options.do_ocr for options in captured_pipeline_options] == [False, True]


@pytest.mark.skipif(
    os.environ.get("AITRANS_RUN_DOCLING_INTEGRATION_TESTS") != "1",
    reason="set AITRANS_RUN_DOCLING_INTEGRATION_TESTS=1 to load Docling models",
)
def test_real_docling_quality_fixture_reports_columns_table_and_scan_page(
    tmp_path: Path,
) -> None:
    pytest.importorskip("docling")
    pytest.importorskip("PIL")
    source = tmp_path / "docling-quality-fixture.pdf"
    _write_docling_quality_pdf(source)
    config = RagAdvancedParsingConfig(
        enabled=True,
        layout_enabled=True,
        table_enabled=True,
        ocr_enabled=False,
    )

    result = DoclingDocumentParser(config).parse(source)

    diagnostics = result.metadata["parse_diagnostics"]
    ordered_markers = [
        result.text.index(marker)
        for marker in (
            "LEFT A",
            "LEFT B",
            "LEFT C",
            "RIGHT A",
            "RIGHT B",
            "RIGHT C",
        )
    ]
    assert ordered_markers == sorted(ordered_markers)
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert diagnostics["reading_order_status"] == "docling_export_order_unverified"
    assert diagnostics["table_status"] == "detected"
    assert diagnostics["table_count"] == 1
    assert diagnostics["table_source_page_numbers"] == [2]
    assert diagnostics["ocr_status"] == "disabled"
    assert diagnostics["no_text_source_pages"] == [3]
    assert diagnostics["scan_suspect_source_pages"] == [3]
    assert diagnostics["quality_status"] == "low_text"
