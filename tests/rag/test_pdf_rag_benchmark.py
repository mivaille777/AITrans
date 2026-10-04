from backend.rag.models import DocumentPage, KnowledgeDocument, NormalizedDocument
from backend.rag.source_span import resolve_source_span
from scripts.run_pdf_rag_benchmark import canonical, locate_gold


def test_source_anchor_normalization_preserves_numeric_meaning():
    assert canonical("1e-4")[0] != canonical("1e4")[0]
    assert canonical("1.10M")[0] != canonical("110M")[0]
    assert canonical("15%")[0] != canonical("15")[0]
    assert canonical("0 . 1")[0] == canonical("0.1")[0]
    assert canonical("ﬁne-tuning")[0] == canonical("fine tuning")[0]


def test_source_gold_resolves_unicode_page_offsets_and_rejects_ambiguity():
    text = "前一页\n\nWe use ﬁne tuning with 1e-4."
    page = DocumentPage(page_number=2, text=text[6:], start_char=6, end_char=len(text))
    document = NormalizedDocument(text=text, pages=[page], document=KnowledgeDocument(
        document_id="doc", title="source", source_uri="file:///source.pdf", content_hash="source-hash"))
    case = {"page": 2, "anchors": ["fine tuning", "1e-4"]}
    span = locate_gold(document, case)
    assert span is not None
    assert resolve_source_span(span, text) == "ﬁne tuning with 1e-4"
    assert locate_gold(document, {"page": 1, "anchors": ["fine tuning"]}) is None
    duplicate = "same fact. same fact."
    document.text = duplicate
    document.pages = [DocumentPage(page_number=2, text=duplicate, start_char=0, end_char=len(duplicate))]
    assert locate_gold(document, {"page": 2, "anchors": ["same fact"]}) is None
