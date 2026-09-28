"""Secret lookup and Windows Credential Manager persistence for AI providers."""

from __future__ import annotations

import ctypes
import importlib
import os
from collections.abc import Mapping
from ctypes import wintypes
from typing import Any

from app.ai.errors import AIConfigurationError

CREDENTIAL_TARGET_PREFIX = "AITranslator/ai"
SUPPORTED_SECRET_PROVIDERS = frozenset(
    {
        "deepseek",
        "openai",
        "google",
        "mistral",
        "groq",
        "openrouter",
        "together",
        "qwen",
        "openai_compatible",
    }
)
_WINDOWS_CREDENTIAL_NOT_FOUND = 1168


class _WindowsCredential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _read_windows_credential(target_name: str) -> str | None:
    """Read the same vault target as the Electron and Tauri shells.

    The standard Windows API avoids a broken pywin32 installation preventing
    backend access to a credential that the desktop shell successfully saved.
    """

    try:
        api = ctypes.WinDLL("advapi32", use_last_error=True)
    except OSError as exc:
        raise AIConfigurationError(
            "Windows Credential Manager is unavailable."
        ) from exc
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_WindowsCredential)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None

    credential = ctypes.POINTER(_WindowsCredential)()
    if not api.CredReadW(target_name, 1, 0, ctypes.byref(credential)):
        if ctypes.get_last_error() == _WINDOWS_CREDENTIAL_NOT_FOUND:
            return None
        raise AIConfigurationError(
            "Unable to read the stored AI provider credential."
        )
    try:
        if not credential:
            return None
        size = int(credential.contents.CredentialBlobSize)
        blob = credential.contents.CredentialBlob
        if not blob or size <= 0:
            return None
        return _decode_credential_blob(ctypes.string_at(blob, size)).strip() or None
    finally:
        api.CredFree(credential)


def normalize_provider_name(provider: object) -> str:
    candidate = str(provider).strip().lower().replace("-", "_")
    if candidate not in SUPPORTED_SECRET_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_SECRET_PROVIDERS))
        raise AIConfigurationError(
            f"Unsupported AI provider credential namespace: {candidate or '<empty>'}. "
            f"Supported providers: {supported}."
        )
    return candidate


def _error_code(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    if isinstance(value, int):
        return value
    if exc.args and isinstance(exc.args[0], int):
        return int(exc.args[0])
    return None


def _decode_credential_blob(value: object) -> str:
    if isinstance(value, str):
        return value.rstrip("\x00")
    if isinstance(value, bytes):
        if not value:
            return ""
        try:
            decoded = value.decode("utf-8")
            if "\x00" not in decoded:
                return decoded.rstrip("\x00")
        except UnicodeDecodeError:
            pass
        try:
            return value.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise AIConfigurationError(
                "Stored AI credential could not be decoded."
            ) from exc
    return ""


class ProviderCredentialStore:
    """Persist provider API keys in the current user's Windows Credential Manager."""

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend

    def _module(self) -> Any:
        if self._backend is not None:
            return self._backend
        try:
            return importlib.import_module("win32cred")
        except Exception as exc:
            raise AIConfigurationError(
                "Windows Credential Manager is unavailable."
            ) from exc

    @staticmethod
    def target_name(provider: object) -> str:
        normalized = normalize_provider_name(provider)
        return f"{CREDENTIAL_TARGET_PREFIX}/{normalized}"

    def get(self, provider: object) -> str | None:
        normalized = normalize_provider_name(provider)
        if self._backend is None and os.name == "nt":
            return _read_windows_credential(self.target_name(normalized))
        backend = self._module()
        try:
            credential = backend.CredRead(
                self.target_name(normalized),
                backend.CRED_TYPE_GENERIC,
                0,
            )
        except Exception as exc:
            if _error_code(exc) == _WINDOWS_CREDENTIAL_NOT_FOUND:
                return None
            raise AIConfigurationError(
                "Unable to read the stored AI provider credential."
            ) from exc

        if not isinstance(credential, Mapping):
            return None
        value = _decode_credential_blob(credential.get("CredentialBlob"))
        return value.strip() or None

def get_provider_api_key(
    provider: object,
    *,
    credential_store: ProviderCredentialStore | Any | None = None,
) -> str:
    """Read an API key from the local desktop credential vault only."""

    normalized = normalize_provider_name(provider)
    store = credential_store or ProviderCredentialStore()
    stored = store.get(normalized)
    if isinstance(stored, str) and stored.strip():
        return stored.strip()

    raise AIConfigurationError(
        f"API key for provider '{normalized}' is not configured. "
        "Open Settings -> Cloud LLM and save the key in the desktop app."
    )


def get_deepseek_api_key(
    *,
    credential_store: ProviderCredentialStore | Any | None = None,
) -> str:
    """Read the DeepSeek key from the local desktop credential vault."""

    return get_provider_api_key(
        "deepseek",
        credential_store=credential_store,
    )


__all__ = [
    "CREDENTIAL_TARGET_PREFIX",
    "SUPPORTED_SECRET_PROVIDERS",
    "ProviderCredentialStore",
    "get_deepseek_api_key",
    "get_provider_api_key",
    "normalize_provider_name",
]
