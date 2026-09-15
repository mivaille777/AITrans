import { invoke } from "@tauri-apps/api/core"

import type { LlmProviderId } from "../../api/llm-settings"

export type LlmCredentialStatus = {
  configured: boolean
}

export function hasTauriCredentialVault(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window
}

export function getLlmCredentialStatus(provider: LlmProviderId): Promise<LlmCredentialStatus> {
  return invoke<boolean>("get_llm_credential_status", { provider })
    .then((configured) => ({ configured }))
}

export function saveLlmCredential(provider: LlmProviderId, apiKey: string): Promise<void> {
  return invoke("save_llm_credential", { provider, apiKey })
}

export function deleteLlmCredential(provider: LlmProviderId): Promise<void> {
  return invoke("delete_llm_credential", { provider })
}
