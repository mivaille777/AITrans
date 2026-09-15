from __future__ import annotations

import pytest

from app.ai.errors import AIConfigurationError
from app.ai.secrets import ProviderCredentialStore, get_provider_api_key


class NotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__(1168, "not found")
        self.winerror = 1168


class FakeWin32Cred:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    def CredWrite(self, credential, _flags=0):
        self.values[credential["TargetName"]] = dict(credential)

    def CredRead(self, target_name, _credential_type, _flags=0):
        if target_name not in self.values:
            raise NotFoundError()
        credential = dict(self.values[target_name])
        blob = credential.get("CredentialBlob", "")
        if isinstance(blob, str):
            credential["CredentialBlob"] = blob.encode("utf-16-le")
        return credential

    def CredDelete(self, target_name, _credential_type, _flags=0):
        if target_name not in self.values:
            raise NotFoundError()
        del self.values[target_name]


def test_windows_credential_store_round_trip_and_delete() -> None:
    backend = FakeWin32Cred()
    first = ProviderCredentialStore(backend=backend)
    second = ProviderCredentialStore(backend=backend)

    target_name = ProviderCredentialStore.target_name("deepseek")
    backend.CredWrite(
        {
            "Type": backend.CRED_TYPE_GENERIC,
            "TargetName": target_name,
            "CredentialBlob": "sk-persisted",
        }
    )

    assert second.get("deepseek") == "sk-persisted"

    backend.CredDelete(target_name, backend.CRED_TYPE_GENERIC)
    assert first.get("deepseek") is None


def test_provider_api_key_reads_persisted_credential() -> None:
    backend = FakeWin32Cred()
    store = ProviderCredentialStore(backend=backend)
    backend.CredWrite(
        {
            "Type": backend.CRED_TYPE_GENERIC,
            "TargetName": ProviderCredentialStore.target_name("deepseek"),
            "CredentialBlob": "sk-persisted",
        }
    )

    value = get_provider_api_key("deepseek", credential_store=store)

    assert value == "sk-persisted"


def test_environment_value_is_not_used_as_a_fallback(monkeypatch) -> None:
    backend = FakeWin32Cred()
    store = ProviderCredentialStore(backend=backend)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    with pytest.raises(AIConfigurationError, match="Cloud LLM"):
        get_provider_api_key("deepseek", credential_store=store)


def test_missing_provider_credential_raises_configuration_error() -> None:
    backend = FakeWin32Cred()
    store = ProviderCredentialStore(backend=backend)

    with pytest.raises(AIConfigurationError):
        get_provider_api_key(
            "openai_compatible",
            credential_store=store,
        )
