"""Provider model discovery using the locally stored API credential."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from openai import OpenAI

from app.ai.client import DEEPSEEK_BASE_URL
from app.ai.errors import AIConfigurationError
from app.ai.factory import OPENAI_COMPATIBLE_PROVIDER
from app.ai.secrets import ProviderCredentialStore, get_provider_api_key

MODEL_CATALOG_TIMEOUT_SECONDS = 10.0


def _model_id(item: object) -> str:
    if isinstance(item, Mapping):
        value = item.get("id", "")
    else:
        value = getattr(item, "id", "")
    return str(value or "").strip()


def _response_items(response: object) -> Iterable[object]:
    if isinstance(response, Mapping):
        value = response.get("data", ())
    else:
        value = getattr(response, "data", response)
    if isinstance(value, (str, bytes)):
        return ()
    try:
        return iter(value)  # type: ignore[arg-type]
    except TypeError:
        return ()


def list_available_model_ids(
    *,
    provider: str,
    base_url: str = "",
    credential_store: ProviderCredentialStore | Any | None = None,
) -> tuple[str, ...]:
    """Return model identifiers exposed by the configured provider account.

    The API key is resolved inside this function and is never returned to the
    caller. Providers using the OpenAI API shape expose the same ``/models``
    operation, so the SDK keeps discovery compatible with DeepSeek and custom
    gateways alike.
    """

    normalized_provider = str(provider or "").strip().lower().replace("-", "_")
    if normalized_provider == "deepseek":
        endpoint = DEEPSEEK_BASE_URL
    elif normalized_provider == OPENAI_COMPATIBLE_PROVIDER:
        endpoint = str(base_url or "").strip().rstrip("/")
        if not endpoint.startswith(("http://", "https://")):
            raise AIConfigurationError(
                "OpenAI-compatible provider requires a valid Base URL before models can be loaded."
            )
    else:
        raise AIConfigurationError("The configured AI provider does not support model discovery.")

    api_key = get_provider_api_key(
        normalized_provider,
        credential_store=credential_store,
    )
    client = OpenAI(
        api_key=api_key,
        base_url=endpoint,
        timeout=MODEL_CATALOG_TIMEOUT_SECONDS,
        max_retries=0,
    )
    try:
        response = client.models.list()
        model_ids = {_model_id(item) for item in _response_items(response)}
        return tuple(sorted(model_id for model_id in model_ids if model_id))
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


__all__ = ["MODEL_CATALOG_TIMEOUT_SECONDS", "list_available_model_ids"]
