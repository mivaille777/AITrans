"""Print non-secret diagnostics for the configured LLM provider."""

from __future__ import annotations

from app.ai.secrets import SUPPORTED_SECRET_PROVIDERS, ProviderCredentialStore
from app.infrastructure.settings import SettingsManager


def main() -> int:
    settings = SettingsManager()
    provider = str(settings.get("ai", "provider", "")).strip()
    model = str(settings.get("ai", "model", "")).strip()
    base_url = str(settings.get("ai", "base_url", "")).strip()

    print(f"Provider: {provider or '<not selected>'}")
    print(f"Model: {model or '<not selected>'}")
    print(f"Custom base URL configured: {bool(base_url)}")
    if provider in SUPPORTED_SECRET_PROVIDERS:
        configured = bool(ProviderCredentialStore().get(provider))
        print(f"Credential configured: {configured}")
    else:
        print("Credential configured: not applicable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
