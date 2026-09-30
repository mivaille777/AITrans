from pathlib import Path

import pytest

from backend.rag.models import DocumentChunk
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.sparse.tokenizer import SparseTokenizer


def test_tokenizer_preserves_scientific_identifiers() -> None:
    tokens = SparseTokenizer().tokenize(
        "M10 J_seg GP-UCB Algorithm 1 Eq.17 K_p K_i K_d PID DOI 10.1016/test.2024.01"
    )

    for expected in (
        "m10",
        "j_seg",
        "gp-ucb",
        "algorithm 1",
        "eq.17",
        "k_p",
        "k_i",
        "k_d",
        "pid",
        "doi",
        "10.1016/test.2024.01",
    ):
        assert expected in tokens


def test_tokenizer_emits_cjk_unigrams_and_bigrams() -> None:
    tokens = SparseTokenizer().tokenize("高斯过程")

    assert tokens == ["高", "斯", "过", "程", "高斯", "斯过", "过程"]


def test_tokenizer_handles_mixed_chinese_and_english() -> None:
    tokens = SparseTokenizer().tokenize("使用 GP-UCB 优化PID参数")

    assert "gp-ucb" in tokens
    assert "pid" in tokens
    assert "优化" in tokens


def test_tokenizer_preserves_doi_chemical_formula_and_dotted_abbreviation() -> None:
    tokens = SparseTokenizer().tokenize(
        "(https://doi.org/10.1038/s41586-020-2649-2). "
        "NaCl, H₂SO₄, CuSO₄·5H₂O, and U.S.A."
    )

    assert "10.1038/s41586-020-2649-2" in tokens
    assert "nacl" in tokens
    assert "h2so4" in tokens
    assert "h2" in tokens and "so4" in tokens
    assert "cuso4·5h2o" in tokens
    assert "u.s.a." in tokens


def test_tokenizer_version_is_explicit_and_stable() -> None:
    assert SparseTokenizer.VERSION == "scientific-v2"


def test_doi_stops_before_chinese_punctuation_and_preserves_balanced_brackets() -> None:
    tokens = SparseTokenizer().tokenize(
        "DOI:10.1234/study。中文证据 (10.1234/foo(bar))."
    )
    assert "10.1234/study" in tokens
    assert "中文" in tokens
    assert "10.1234/foo(bar)" in tokens


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("10.1038/s41586-020-2649-2", "doi"),
        ("(10.1038/s41586-020-2649-2).", "doi"),
        ("H₂SO₄", "formula"),
        ("h2so4", "formula"),
        ("Fe2O3", "oxide"),
        ("U.S.A.", "acronym"),
        ("GP-UCB 优化PID参数", "mixed"),
    ],
)
def test_identifier_fixture_recalls_correct_document(
    tmp_path: Path, query: str, expected: str
) -> None:
    texts = {
        "doi": "Evidence DOI:10.1038/s41586-020-2649-2。",
        "doi-near": "Evidence DOI:10.1038/s41586-020-2649-3。",
        "formula": "The compound is H2SO4.",
        "formula-near": "The compound is H2O.",
        "oxide": "The oxide is Fe2O3.",
        "oxide-near": "The oxide is Fe3O4.",
        "acronym": "The acronym U.S.A. is used here.",
        "mixed": "使用 GP-UCB 优化 PID 参数。",
        "mixed-near": "使用 GP-LCB 优化 PID 参数。",
    }
    retriever = BM25SparseRetriever(tmp_path / "identifiers.json")
    retriever.rebuild(
        [
            DocumentChunk(chunk_id=key, document_id=key, text=text, chunk_index=0)
            for key, text in texts.items()
        ]
    )
    assert retriever.search(query, 1)[0].chunk.document_id == expected


def test_tokenizer_returns_empty_for_punctuation_only() -> None:
    assert SparseTokenizer().tokenize("... !!!") == []
