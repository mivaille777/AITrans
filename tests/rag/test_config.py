from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.rag.config import (
    RagAdvancedParsingConfig,
    RagChunkingConfig,
    RagConfig,
    RagEmbeddingConfig,
    RagRetrievalConfig,
    RagSemanticChunkingConfig,
)


def test_rag_config_defaults_match_v1_contract() -> None:
    config = RagConfig()

    assert config.enabled is True
    assert config.advanced_parsing.device == "cpu"
    assert config.chunking.target_tokens == 512
    assert config.chunking.preferred_max_tokens is None
    assert config.chunking.hard_max_tokens is None
    assert config.chunking.overlap_tokens == 80
    assert config.semantic_chunking.enabled is False
    assert config.semantic_chunking.merge_similarity == pytest.approx(0.72)
    assert config.semantic_chunking.strong_merge_similarity == pytest.approx(0.82)
    assert config.semantic_chunking.strong_split_similarity == pytest.approx(0.58)
    assert config.semantic_chunking.centroid_window == 4
    assert config.embedding.model == "Qwen/Qwen3-Embedding-0.6B"
    assert config.embedding.dimension == 1024
    assert config.embedding.batch_size == 8
    assert config.embedding.normalize is True
    assert config.vector_store.provider == "qdrant_local"
    assert config.vector_store.collection_name == "aitrans_knowledge"
    assert config.vector_store.distance == "cosine"
    assert config.vector_store.storage_path == "config/rag/qdrant"
    assert config.retrieval.fusion == "rrf"
    assert config.retrieval.final_top_k == 8
    assert config.retrieval.small_to_big_enabled is True
    assert config.retrieval.small_to_big_top_k == 4
    assert config.retrieval.small_to_big_neighbor_radius == 1
    assert config.retrieval.small_to_big_max_tokens_per_anchor == 1200


def test_embedding_dimension_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        RagEmbeddingConfig(dimension=0)


def test_advanced_parser_device_is_bounded() -> None:
    with pytest.raises(ValidationError):
        RagAdvancedParsingConfig(device="metal")


def test_chunk_overlap_must_be_smaller_than_target() -> None:
    with pytest.raises(ValidationError):
        RagChunkingConfig(target_tokens=128, overlap_tokens=128, minimum_tokens=64)


def test_chunk_minimum_must_not_exceed_target() -> None:
    with pytest.raises(ValidationError):
        RagChunkingConfig(target_tokens=128, overlap_tokens=16, minimum_tokens=129)


def test_hierarchical_chunk_bounds_must_be_monotonic() -> None:
    with pytest.raises(ValidationError):
        RagChunkingConfig(
            target_tokens=420,
            preferred_max_tokens=400,
            hard_max_tokens=750,
            overlap_tokens=80,
            minimum_tokens=80,
        )
    with pytest.raises(ValidationError):
        RagChunkingConfig(
            target_tokens=420,
            preferred_max_tokens=550,
            hard_max_tokens=500,
            overlap_tokens=80,
            minimum_tokens=80,
        )


def test_semantic_thresholds_must_be_monotonic() -> None:
    with pytest.raises(ValidationError):
        RagSemanticChunkingConfig(
            strong_split_similarity=0.80,
            merge_similarity=0.72,
        )
    with pytest.raises(ValidationError):
        RagSemanticChunkingConfig(
            merge_similarity=0.85,
            strong_merge_similarity=0.82,
        )
    with pytest.raises(ValidationError):
        RagSemanticChunkingConfig(
            merge_similarity=0.80,
            small_chunk_merge_similarity=0.75,
        )


def test_final_top_k_must_not_exceed_fusion_top_k() -> None:
    with pytest.raises(ValidationError):
        RagRetrievalConfig(fusion_top_k=4, final_top_k=8)


def test_default_toml_rag_section_validates_against_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    with (root / "config" / "default.toml").open("rb") as handle:
        raw = tomllib.load(handle)

    config = RagConfig.model_validate(raw["rag"])

    assert config.advanced_parsing.enabled is True
    assert config.advanced_parsing.provider == "docling"
    assert config.advanced_parsing.device == "cpu"
    assert config.advanced_parsing.layout_enabled is True
    assert config.advanced_parsing.table_enabled is True
    assert config.advanced_parsing.ocr_enabled is False
    assert config.advanced_parsing.formula_enabled is False
    assert config.chunking.target_tokens == 420
    assert config.chunking.preferred_max_tokens == 550
    assert config.chunking.hard_max_tokens == 750
    assert config.chunking.minimum_tokens == 80
    assert config.semantic_chunking.enabled is True
    assert config.semantic_chunking.merge_similarity == pytest.approx(0.72)
    assert config.semantic_chunking.strong_merge_similarity == pytest.approx(0.82)
    assert config.semantic_chunking.strong_split_similarity == pytest.approx(0.58)
    assert config.semantic_chunking.small_chunk_merge_similarity == pytest.approx(0.78)
    assert config.semantic_chunking.adaptive_threshold_enabled is True
    assert config.semantic_chunking.adaptive_std_factor == pytest.approx(1.0)
    assert config.semantic_chunking.min_paragraphs_for_adaptive == 4
    assert config.semantic_chunking.centroid_window == 4
    assert config.semantic_chunking.semantic_sentence_fallback is False
    assert config.embedding.dimension == 1024
    assert config.retrieval.dense_top_k == 30
    assert config.retrieval.small_to_big_enabled is True
    assert config.retrieval.small_to_big_top_k == 4
    assert config.retrieval.small_to_big_neighbor_radius == 1
    assert config.retrieval.small_to_big_max_tokens_per_anchor == 1200
