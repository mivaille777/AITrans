"""Translation-layer components."""

from app.models.translation import TranslationRequest, TranslationResult
from app.translation.base import TranslationProvider
from app.translation.cache import HistoryEntry, TranslationCache
from app.translation.errors import (
    TextNormalizationError,
    TranslationError,
    WebTranslationError,
)
from app.translation.fake_provider import FakeTranslationProvider
from app.translation.google_web_provider import GoogleWebTranslationProvider
from app.translation.manager import TranslationManager
from app.translation.request_version import RequestVersionController
from app.translation.normalizer import TextNormalizer
from app.translation.sqlite_cache import SQLiteTranslationStore, normalized_text_hash
from app.translation.token.google_tk import generate_token
from app.translation.youdao_web_provider import YoudaoWebTranslationProvider

__all__ = [
    "FakeTranslationProvider",
    "GoogleWebTranslationProvider",
    "YoudaoWebTranslationProvider",
    "TranslationCache",
    "HistoryEntry",
    "SQLiteTranslationStore",
    "normalized_text_hash",
    "TextNormalizationError",
    "TranslationError",
    "WebTranslationError",
    "TranslationManager",
    "RequestVersionController",
    "TextNormalizer",
    "TranslationProvider",
    "TranslationRequest",
    "TranslationResult",
    "generate_token",
]
