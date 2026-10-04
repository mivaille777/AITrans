from backend.rag.cache import EmbeddingCache, cache_key


def test_cache_separates_scope_generation_model_and_query_versions():
    base = {"query": "q", "scope": ["a"], "generations": {"a": "g"}, "model": "m", "query_version": "v"}
    keys = {cache_key(**base)}
    for field, value in (("scope", ["b"]), ("generations", {"a": "g2"}), ("model", "m2"), ("query_version", "v2")):
        keys.add(cache_key(**{**base, field: value}))
    assert len(keys) == 5


def test_cache_lru_ttl_and_copy_prevent_pollution():
    now = [0]
    cache = EmbeddingCache(2, ttl_seconds=10, clock=lambda: now[0])
    source = [1., 2.]
    cache.put("a", source)
    source[0] = 9
    assert cache.get("a") == (1., 2.)
    cache.put("b", [2.])
    cache.get("a")
    cache.put("c", [3.])
    assert cache.get("b") is None
    now[0] = 11
    assert cache.get("a") is None
