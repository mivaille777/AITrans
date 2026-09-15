"""AI service integration primitives."""

from app.ai.chunking import DEFAULT_CHUNK_SIZE, merge_chunks, split_text
from app.ai.client import (
    DEFAULT_DEEPSEEK_MODEL,
    DEEPSEEK_BASE_URL,
    DeepSeekClient,
    SUPPORTED_DEEPSEEK_MODELS,
)
from app.ai.errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIConnectionError,
    AIError,
    AIRateLimitError,
    AIResponseError,
    AITimeoutError,
)
from app.ai.factory import (
    AI_PROVIDER_LABELS,
    DEFAULT_AI_PROVIDER,
    OPENAI_COMPATIBLE_PROVIDER,
    SUPPORTED_AI_PROVIDERS,
    create_ai_text_service,
    normalize_ai_provider,
)
from app.ai.models import AITextAction, AITextRequest, AITextResult
from app.ai.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleTextProvider,
)
from app.ai.output_guard import OutputValidation, normalize_model_output, validate_model_output
from app.ai.prompts import (
    POLISH_STYLE_INSTRUCTIONS,
    build_polish_prompt,
    build_strict_retry_prompt,
    build_translate_prompt,
)
from app.ai.provider import AITextProvider, DeepSeekTextProvider
from app.ai.secrets import (
    ProviderCredentialStore,
    get_provider_api_key,
)
from app.ai.service import (
    AITextService,
    DEFAULT_AI_POLISH_STYLE,
    DEFAULT_AI_SOURCE_LANGUAGE,
    DEFAULT_AI_TARGET_LANGUAGE,
)


__all__ = [
    "AIAuthenticationError",
    "AIConfigurationError",
    "AIConnectionError",
    "AIError",
    "AI_PROVIDER_LABELS",
    "AIRateLimitError",
    "AIResponseError",
    "AITimeoutError",
    "AITextAction",
    "AITextProvider",
    "AITextRequest",
    "AITextResult",
    "AITextService",
    "DEFAULT_AI_POLISH_STYLE",
    "DEFAULT_AI_PROVIDER",
    "DEFAULT_AI_SOURCE_LANGUAGE",
    "DEFAULT_AI_TARGET_LANGUAGE",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_DEEPSEEK_MODEL",
    "DEEPSEEK_BASE_URL",
    "DeepSeekClient",
    "DeepSeekTextProvider",
    "OPENAI_COMPATIBLE_PROVIDER",
    "OpenAICompatibleClient",
    "OpenAICompatibleTextProvider",
    "OutputValidation",
    "POLISH_STYLE_INSTRUCTIONS",
    "ProviderCredentialStore",
    "SUPPORTED_AI_PROVIDERS",
    "SUPPORTED_DEEPSEEK_MODELS",
    "build_polish_prompt",
    "build_strict_retry_prompt",
    "build_translate_prompt",
    "create_ai_text_service",
    "get_provider_api_key",
    "merge_chunks",
    "normalize_ai_provider",
    "normalize_model_output",
    "split_text",
    "validate_model_output",
]
