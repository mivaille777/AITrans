import pytest

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.visual_prefetch import create_visual_vector_store


def test_prefetch_config_requires_oversampling():
    with pytest.raises(ValueError, match="prefetch_top_k"):
        RagVisualRetrievalConfig(visual_top_k=8, prefetch_top_k=4)


def test_factory_preserves_full_scan_setting(tmp_path):
    store = create_visual_vector_store(
        RagVisualRetrievalConfig(storage_path=str(tmp_path), prefetch_enabled=False)
    )
    try:
        assert not store._config.prefetch_enabled
        assert not store.prefetch_policy.enabled
    finally:
        store.close()
