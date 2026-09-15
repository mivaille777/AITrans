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


def test_tokenizer_returns_empty_for_punctuation_only() -> None:
    assert SparseTokenizer().tokenize("... !!!") == []
