from backend.rag.rerankers import Qwen3RerankerProvider, RerankerProvider


def test_qwen3_reranker_satisfies_protocol() -> None:
    provider = Qwen3RerankerProvider(
        model_factory=lambda *_args, **_kwargs: object(),
        torch_module=object(),
    )
    assert isinstance(provider, RerankerProvider)


def test_empty_candidates_do_not_load_model() -> None:
    calls = []
    provider = Qwen3RerankerProvider(
        model_factory=lambda *_args, **_kwargs: calls.append(1),
        torch_module=object(),
    )
    assert provider.rerank("query", [], top_k=8) == []
    assert calls == []
