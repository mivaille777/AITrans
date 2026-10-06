import pytest

from backend.rag.models import DocumentChunk
from backend.rag.stores.base import is_reference_chunk


@pytest.mark.parametrize(
    "text",
    [
        "A second limitation: the Fixed-PID reference does not establish superiority over adaptive baselines.",
        "The tank tracks a constant reference of 10 m.",
        "The model makes references to the Ziegler-Nichols method.",
        "Reference tracking is evaluated under nominal conditions.",
    ],
)
def test_reference_mentions_in_body_remain_retrievable(text):
    chunk = DocumentChunk(
        chunk_id="body",
        document_id="doc",
        chunk_index=0,
        text=text,
        section_heading="5.6. Limitations and Generalizability",
    )
    assert not is_reference_chunk(chunk)


@pytest.mark.parametrize(
    "heading",
    ["References", "6. References", "Bibliography", "Works Cited", "IV. References"],
)
def test_real_bibliography_heading_remains_excluded(heading):
    chunk = DocumentChunk(
        chunk_id="refs",
        document_id="doc",
        chunk_index=0,
        text="Smith et al. 2025.",
        section_heading=heading,
    )
    assert is_reference_chunk(chunk)


def test_unstructured_bibliography_and_structured_reference_entries():
    legacy = DocumentChunk(
        chunk_id="legacy",
        document_id="doc",
        chunk_index=0,
        text="References\nSmith et al. 2025.",
    )
    typed = legacy.model_copy(
        update={"text": "Smith et al. 2025.", "chunk_type": "reference_group"}
    )
    marked = legacy.model_copy(
        update={
            "text": "Smith et al. 2025.",
            "metadata": {"section_kind": "references"},
        }
    )
    assert all(is_reference_chunk(c) for c in (legacy, typed, marked))
