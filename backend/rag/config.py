from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RagConfigModel(BaseModel):
    """Base model for stable RAG configuration contracts."""

    model_config = ConfigDict(extra="forbid")


class RagChunkingConfig(RagConfigModel):
    target_tokens: int = Field(default=512, ge=1)
    preferred_max_tokens: int | None = Field(default=None, ge=1)
    hard_max_tokens: int | None = Field(default=None, ge=1)
    overlap_tokens: int = Field(default=80, ge=0)
    minimum_tokens: int = Field(default=100, ge=1)

    @property
    def effective_preferred_max_tokens(self) -> int:
        return self.preferred_max_tokens or self.target_tokens

    @property
    def effective_hard_max_tokens(self) -> int:
        return self.hard_max_tokens or self.effective_preferred_max_tokens

    @model_validator(mode="after")
    def validate_chunk_bounds(self) -> "RagChunkingConfig":
        preferred = self.effective_preferred_max_tokens
        hard = self.effective_hard_max_tokens
        if self.minimum_tokens > self.target_tokens:
            raise ValueError("minimum_tokens must not exceed target_tokens")
        if preferred < self.target_tokens:
            raise ValueError("preferred_max_tokens must not be smaller than target_tokens")
        if hard < preferred:
            raise ValueError("hard_max_tokens must not be smaller than preferred_max_tokens")
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens")
        return self


class RagSemanticChunkingConfig(RagConfigModel):
    """Semantic paragraph grouping inside hard structural boundaries."""

    enabled: bool = False
    merge_similarity: float = Field(default=0.72, ge=-1.0, le=1.0)
    strong_merge_similarity: float = Field(default=0.82, ge=-1.0, le=1.0)
    strong_split_similarity: float = Field(default=0.58, ge=-1.0, le=1.0)
    small_chunk_merge_similarity: float = Field(default=0.78, ge=-1.0, le=1.0)
    adaptive_threshold_enabled: bool = True
    adaptive_std_factor: float = Field(default=1.0, ge=0.0, le=5.0)
    min_paragraphs_for_adaptive: int = Field(default=4, ge=2, le=128)
    centroid_window: int = Field(default=4, ge=1, le=32)
    semantic_sentence_fallback: bool = False

    @model_validator(mode="after")
    def validate_semantic_thresholds(self) -> "RagSemanticChunkingConfig":
        if self.strong_split_similarity > self.merge_similarity:
            raise ValueError("strong_split_similarity must not exceed merge_similarity")
        if self.merge_similarity > self.strong_merge_similarity:
            raise ValueError("merge_similarity must not exceed strong_merge_similarity")
        if self.merge_similarity > self.small_chunk_merge_similarity:
            raise ValueError("merge_similarity must not exceed small_chunk_merge_similarity")
        return self


class RagAdvancedParsingConfig(RagConfigModel):
    enabled: bool = False
    provider: str = "docling"
    device: str = "cpu"
    layout_enabled: bool = True
    table_enabled: bool = False
    ocr_enabled: bool = False
    formula_enabled: bool = False
    document_timeout_seconds: float = Field(default=120.0, gt=0.0, le=600.0)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "docling":
            raise ValueError("advanced parser provider must be docling")
        return normalized

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "cpu", "cuda"}:
            raise ValueError("advanced parser device must be one of: auto, cpu, cuda")
        return normalized


class RagVisualUnderstandingConfig(RagConfigModel):
    """Optional retrieval-oriented figure understanding."""

    enabled: bool = False
    provider: str = "openai_compatible"
    model: str = ""
    base_url: str = ""
    inherit_ai_settings: bool = True
    detail: str = "auto"
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    max_retries: int = Field(default=1, ge=0, le=5)
    max_images_per_document: int = Field(default=24, ge=1, le=256)
    max_asset_bytes: int = Field(default=8 * 1024 * 1024, ge=1024)
    max_output_tokens: int | None = Field(default=None, ge=1, le=4096)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_")
        if normalized != "openai_compatible":
            raise ValueError("visual understanding provider must be openai_compatible")
        return normalized

    @field_validator("detail")
    @classmethod
    def validate_detail(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "low", "high"}:
            raise ValueError("visual understanding detail must be one of: auto, low, high")
        return normalized


class RagVisualRetrievalConfig(RagConfigModel):
    """Optional native page/image late-interaction retrieval.

    This path is isolated from the text collection. ColQwen/ColPali token
    embeddings are stored in a dedicated Qdrant MaxSim multivector collection
    and fused with the established text pipeline only at query time. Stage 3.1
    can prefetch with a cheap pooled vector before applying MaxSim.
    """

    enabled: bool = False
    provider: str = "colpali_engine"
    model_family: str = "colqwen2_5"
    model: str = "tsystems/colqwen2.5-3b-multilingual-v1.0"
    model_path: str = ""
    device: str = "auto"
    precision: str = "default"
    dimension: int = Field(default=128, ge=1)
    batch_size: int = Field(default=1, ge=1, le=16)
    local_files_only: bool = False
    query_prefix: str = "Query: "
    collection_name: str = Field(default="aitrans_knowledge_visual", min_length=1)
    storage_path: str = "config/rag/qdrant"
    distance: str = "dot"
    on_disk: bool = False
    asset_storage_path: str = "config/rag/visual_pages"
    render_dpi: int = Field(default=144, ge=72, le=300)
    max_pages_per_document: int = Field(default=64, ge=1, le=512)
    max_visual_items_per_document: int = Field(default=96, ge=1, le=1024)
    text_candidate_pool: int = Field(default=20, ge=1, le=200)
    visual_top_k: int = Field(default=12, ge=1, le=200)
    prefetch_enabled: bool = True
    prefetch_top_k: int = Field(default=48, ge=1, le=2000)
    prefetch_fallback_to_full_scan: bool = True
    fusion_top_k: int = Field(default=20, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    text_weight: float = Field(default=1.0, gt=0.0, le=10.0)
    visual_weight: float = Field(default=1.0, gt=0.0, le=10.0)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_")
        if normalized != "colpali_engine":
            raise ValueError("visual retrieval provider must be colpali_engine")
        return normalized

    @field_validator("model_family")
    @classmethod
    def validate_model_family(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_").replace(".", "_")
        aliases = {"colqwen2_5": "colqwen2_5", "colqwen25": "colqwen2_5", "colqwen2": "colqwen2", "colpali": "colpali"}
        if normalized not in aliases:
            raise ValueError("visual retrieval model_family must be one of: colqwen2_5, colqwen2, colpali")
        return aliases[normalized]

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "cuda", "cpu", "mps"}:
            raise ValueError("visual retrieval device must be one of: auto, cuda, cpu, mps")
        return normalized

    @field_validator("precision")
    @classmethod
    def validate_precision(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"default", "fp16", "bf16"}:
            raise ValueError("visual retrieval precision must be one of: default, fp16, bf16")
        return normalized

    @field_validator("distance")
    @classmethod
    def validate_distance(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"dot", "cosine"}:
            raise ValueError("visual retrieval distance must be one of: dot, cosine")
        return normalized

    @model_validator(mode="after")
    def validate_prefetch_bounds(self) -> "RagVisualRetrievalConfig":
        if self.prefetch_enabled and self.prefetch_top_k < self.visual_top_k:
            raise ValueError(
                "prefetch_top_k must be greater than or equal to visual_top_k "
                "when visual prefetch is enabled"
            )
        return self


class RagEmbeddingConfig(RagConfigModel):
    provider: str = "qwen3"
    model: str = "Qwen/Qwen3-Embedding-0.6B"
    device: str = "auto"
    dimension: int = Field(default=1024, ge=1)
    batch_size: int = Field(default=8, ge=1)
    normalize: bool = True
    max_input_tokens: int = Field(default=2048, ge=1)
    warmup: bool = True
    precision: str = "default"
    local_files_only: bool = False
    model_path: str = ""

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "cuda", "cpu"}:
            raise ValueError("device must be one of: auto, cuda, cpu")
        return normalized

    @field_validator("precision")
    @classmethod
    def validate_precision(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"default", "fp16", "bf16"}:
            raise ValueError("precision must be one of: default, fp16, bf16")
        return normalized


class RagVectorStoreConfig(RagConfigModel):
    provider: str = "qdrant_local"
    collection_name: str = Field(default="aitrans_knowledge", min_length=1)
    distance: str = "cosine"
    storage_path: str = "config/rag/qdrant"


class RagRetrievalConfig(RagConfigModel):
    dense_top_k: int = Field(default=30, ge=1)
    sparse_top_k: int = Field(default=30, ge=1)
    fusion_top_k: int = Field(default=20, ge=1)
    final_top_k: int = Field(default=8, ge=1)
    fusion: str = "rrf"
    small_to_big_enabled: bool = True
    small_to_big_top_k: int = Field(default=4, ge=1)
    small_to_big_neighbor_radius: int = Field(default=1, ge=0, le=3)
    small_to_big_max_tokens_per_anchor: int = Field(default=1200, ge=1, le=6000)

    @model_validator(mode="after")
    def validate_retrieval_bounds(self) -> "RagRetrievalConfig":
        if self.final_top_k > self.fusion_top_k:
            raise ValueError("final_top_k must not exceed fusion_top_k")
        return self


class RagRerankerConfig(RagConfigModel):
    provider: str = "qwen3"
    model: str = "Qwen/Qwen3-Reranker-0.6B"
    device: str = "auto"
    batch_size: int = Field(default=8, ge=1)
    lazy_load: bool = True
    local_files_only: bool = False
    model_path: str = ""

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "cuda", "cpu"}:
            raise ValueError("device must be one of: auto, cuda, cpu")
        return normalized


class RagConfig(RagConfigModel):
    enabled: bool = True
    advanced_parsing: RagAdvancedParsingConfig = Field(default_factory=RagAdvancedParsingConfig)
    visual_understanding: RagVisualUnderstandingConfig = Field(default_factory=RagVisualUnderstandingConfig)
    visual_retrieval: RagVisualRetrievalConfig = Field(default_factory=RagVisualRetrievalConfig)
    chunking: RagChunkingConfig = Field(default_factory=RagChunkingConfig)
    semantic_chunking: RagSemanticChunkingConfig = Field(default_factory=RagSemanticChunkingConfig)
    embedding: RagEmbeddingConfig = Field(default_factory=RagEmbeddingConfig)
    vector_store: RagVectorStoreConfig = Field(default_factory=RagVectorStoreConfig)
    retrieval: RagRetrievalConfig = Field(default_factory=RagRetrievalConfig)
    reranker: RagRerankerConfig = Field(default_factory=RagRerankerConfig)


__all__ = [
    "RagAdvancedParsingConfig",
    "RagChunkingConfig",
    "RagConfig",
    "RagEmbeddingConfig",
    "RagRerankerConfig",
    "RagRetrievalConfig",
    "RagSemanticChunkingConfig",
    "RagVectorStoreConfig",
    "RagVisualRetrievalConfig",
    "RagVisualUnderstandingConfig",
]
