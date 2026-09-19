import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Box,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Database,
  Eye,
  EyeOff,
  ExternalLink,
  KeyRound,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  Search,
  ServerCog,
  ShieldCheck,
  X,
} from "lucide-react"
import { useMemo, useState, type ReactNode } from "react"

import {
  getAvailableLlmModels,
  getLlmSettings,
  updateLlmSettings,
  type LlmModelOption,
  type LlmProviderId,
  type LlmProviderOption,
  type LlmSettings,
} from "../../api/llm-settings"
import {
  deleteLlmCredential,
  getLlmCredentialPreview,
  getLlmCredentialStatus,
  hasTauriCredentialVault,
  saveLlmCredential,
} from "../../desktop/tauri/llm-credential-vault"

import "./LlmProviderSettings.css"

const QUERY_KEY = ["settings", "llm"] as const

type Draft = {
  provider: LlmProviderId
  model: string
  baseUrl: string
  apiKey: string
}

type SaveRequest = {
  draft: Draft
  clearApiKey: boolean
}

function draftFrom(settings: LlmSettings): Draft {
  return {
    provider: settings.provider,
    model: settings.model,
    baseUrl: settings.base_url,
    apiKey: "",
  }
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : null
}

export function LlmProviderSettings({ onClose }: { onClose: () => void }) {
  const settingsQuery = useQuery({ queryKey: QUERY_KEY, queryFn: getLlmSettings })

  if (settingsQuery.isPending) {
    return (
      <section className="ait-llm-connection" aria-busy="true" translate="no">
        <LlmHeader onClose={onClose} />
        <div className="ait-llm-loading-grid">
          <div className="ait-llm-loading-card" />
          <div className="ait-llm-loading-card" />
        </div>
      </section>
    )
  }

  if (settingsQuery.isError || !settingsQuery.data) {
    return (
      <section className="ait-llm-connection" translate="no">
        <LlmHeader onClose={onClose} />
        <div className="ait-llm-empty-state" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <div>
            <strong>AI model settings are unavailable.</strong>
            <p>{errorMessage(settingsQuery.error) || "The local settings service did not respond."}</p>
            <button type="button" className="ait-llm-outline-button" onClick={() => void settingsQuery.refetch()}>Retry</button>
          </div>
        </div>
      </section>
    )
  }

  return (
    <LlmProviderSettingsForm
      key={`${settingsQuery.data.provider}:${settingsQuery.data.model}:${settingsQuery.data.base_url}`}
      settings={settingsQuery.data}
      onClose={onClose}
    />
  )
}

function LlmProviderSettingsForm({ settings, onClose }: { settings: LlmSettings; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(() => draftFrom(settings))
  const [showKey, setShowKey] = useState(false)
  const [modelSearch, setModelSearch] = useState("")
  const [lastCheckedAt, setLastCheckedAt] = useState<string | null>(null)
  const [connectionTested, setConnectionTested] = useState(false)
  const [connectionNotice, setConnectionNotice] = useState<string | null>(null)
  const [isTesting, setIsTesting] = useState(false)
  const desktopVaultAvailable = hasTauriCredentialVault()

  const credentialQuery = useQuery({
    queryKey: ["settings", "llm", "credential", draft.provider],
    queryFn: () => getLlmCredentialStatus(draft.provider),
    enabled: desktopVaultAvailable,
  })
  const credentialPreviewQuery = useQuery({
    queryKey: ["settings", "llm", "credential-preview", draft.provider],
    queryFn: () => getLlmCredentialPreview(draft.provider),
    enabled: desktopVaultAvailable,
  })

  const modelsQuery = useQuery({
    queryKey: ["settings", "llm", "models", settings.provider, settings.base_url],
    queryFn: getAvailableLlmModels,
    enabled: draft.provider === settings.provider && draft.baseUrl.trim() === settings.base_url.trim(),
    staleTime: 60_000,
    retry: false,
  })

  const mutation = useMutation({
    mutationFn: async ({ draft: current, clearApiKey }: SaveRequest) => {
      const nextSettings = await updateLlmSettings({
        provider: current.provider,
        model: current.model.trim(),
        base_url: current.baseUrl.trim(),
      })

      if (clearApiKey) {
        if (!desktopVaultAvailable) throw new Error("API key can only be managed in the Tauri desktop app.")
        await deleteLlmCredential(current.provider)
      } else if (current.apiKey.trim()) {
        if (!desktopVaultAvailable) throw new Error("API key can only be managed in the Tauri desktop app.")
        await saveLlmCredential(current.provider, current.apiKey.trim())
      }

      return nextSettings
    },
    onSuccess: (nextSettings) => {
      setDraft(draftFrom(nextSettings))
      setShowKey(false)
      setConnectionTested(false)
      setConnectionNotice("Connection saved. Refresh the model list to verify the API key.")
      queryClient.setQueryData(QUERY_KEY, nextSettings)
      void queryClient.invalidateQueries({ queryKey: ["settings", "llm", "credential"] })
      void queryClient.invalidateQueries({ queryKey: ["settings", "llm", "credential-preview"] })
      void queryClient.invalidateQueries({ queryKey: ["settings", "llm", "models"] })
      void queryClient.invalidateQueries({ queryKey: ["agent", "runtime", "config"] })
    },
  })

  const selected = useMemo(
    () => settings.providers.find((provider) => provider.id === draft.provider),
    [draft.provider, settings.providers],
  )
  const configured = desktopVaultAvailable && Boolean(credentialQuery.data?.configured)
  const busy = mutation.isPending
  const savedDraft = draft.provider === settings.provider && draft.baseUrl.trim() === settings.base_url.trim()
  const error = errorMessage(mutation.error) ?? errorMessage(credentialQuery.error)
  const storageLabel = !desktopVaultAvailable
    ? "Open the Tauri desktop app to manage API keys"
    : credentialQuery.isPending
      ? "Checking Windows Credential Manager…"
      : configured
        ? "Saved in Windows Credential Manager"
        : "No API key saved"

  const modelOptions = useMemo(() => {
    const available = modelsQuery.data?.models ?? []
    const current: LlmModelOption = { id: draft.model.trim() }
    const unique = new Map<string, LlmModelOption>()
    for (const model of [current, ...available]) {
      if (model.id) unique.set(model.id, model)
    }
    return [...unique.values()]
  }, [draft.model, modelsQuery.data?.models])

  const filteredModels = useMemo(() => {
    const query = modelSearch.trim().toLowerCase()
    if (!query) return modelOptions
    return modelOptions.filter((model) => model.id.toLowerCase().includes(query))
  }, [modelOptions, modelSearch])

  const connectionDetail = modelsQuery.data?.available
    ? `${modelsQuery.data.models.length} model${modelsQuery.data.models.length === 1 ? "" : "s"} available`
    : modelsQuery.data?.detail || "Run a connection test to check the provider."

  function chooseProvider(provider: LlmProviderId) {
    const next = settings.providers.find((option) => option.id === provider)
    if (!next || busy || isTesting) return
    setDraft((current) => ({
      ...current,
      provider,
      model: next.default_model || current.model,
      baseUrl: next.default_base_url || current.baseUrl,
      apiKey: "",
    }))
    setModelSearch("")
    setConnectionTested(false)
    setLastCheckedAt(null)
    setConnectionNotice(null)
  }

  async function testConnection() {
    setConnectionNotice(null)
    setConnectionTested(false)
    if (!savedDraft) {
      setConnectionNotice("Save the provider and endpoint before testing this connection.")
      return
    }
    setIsTesting(true)
    try {
      const result = await modelsQuery.refetch()
      const checkedAt = new Date().toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
      setLastCheckedAt(checkedAt)
      setConnectionTested(Boolean(result.data?.available))
      setConnectionNotice(result.data?.available ? "Connection reachable and model catalog loaded." : result.data?.detail || "The provider did not return a model catalog.")
    } finally {
      setIsTesting(false)
    }
  }

  function save(clearApiKey = false) {
    mutation.mutate({ draft, clearApiKey })
  }

  return (
    <section className="ait-llm-connection" translate="no">
      <LlmHeader onClose={onClose} />

      <div className="ait-llm-summary" aria-label="Connection summary">
        <SummaryItem icon={<Database size={28} strokeWidth={1.8} />} label="Provider" value={selected?.label || draft.provider} />
        <SummaryItem icon={<Box size={28} strokeWidth={1.8} />} label="Active model" value={draft.model || "Not configured"} />
        <SummaryItem icon={<ServerCog size={28} strokeWidth={1.8} />} label="Connection" value={configured ? "Configured" : "API key required"} />
      </div>

      <div className="ait-llm-content">
        <section className="ait-llm-card ait-llm-provider-card">
          <div className="ait-llm-card-header">
            <CardHeading icon={<Database size={27} strokeWidth={1.8} />} eyebrow="1. Select provider" title="Select provider" description="Choose an AI provider to configure. You can add multiple providers." />
            <button type="button" className="ait-llm-outline-button" disabled aria-disabled="true"><Plus size={16} /> Add provider</button>
          </div>
          <div className="ait-llm-provider-list" role="list" aria-label="AI providers">
            {settings.providers.map((provider) => (
              <ProviderRow key={provider.id} provider={provider} active={provider.id === draft.provider} credentialConfigured={configured} disabled={busy || isTesting} onClick={() => chooseProvider(provider.id)} />
            ))}
          </div>
          <StoredCredentialPanel
            providerLabel={selected?.label || draft.provider}
            preview={credentialPreviewQuery.data?.masked || ""}
            loading={desktopVaultAvailable && (credentialPreviewQuery.isPending || credentialPreviewQuery.isFetching)}
            configured={configured}
            savedDraft={savedDraft}
            models={modelsQuery.data?.models ?? []}
            modelsAvailable={Boolean(modelsQuery.data?.available)}
            modelsLoading={modelsQuery.isFetching}
            modelsDetail={modelsQuery.data?.detail || "Save this provider to discover models."}
          />
        </section>

        <div className="ait-llm-right-column">
          <section className="ait-llm-card ait-llm-model-card">
            <div className="ait-llm-card-header">
              <CardHeading icon={<Box size={27} strokeWidth={1.8} />} eyebrow="2. Models from current provider" title="Models from current provider" description="Select a model to use. Models are fetched from your API key." />
              <button type="button" className="ait-llm-outline-button" onClick={() => void testConnection()} disabled={modelsQuery.isFetching || busy || !savedDraft} title={!savedDraft ? "Save provider settings before refreshing" : "Refresh models"}>
                {modelsQuery.isFetching ? <LoaderCircle size={16} className="ait-llm-spin" /> : <RefreshCw size={16} />} Refresh
              </button>
            </div>
            <label className="ait-llm-search">
              <Search size={17} aria-hidden="true" />
              <span className="ait-sr-only">Search models</span>
              <input value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} placeholder="Search models…" aria-label="Search models" />
            </label>
            <div className="ait-llm-model-list" role="radiogroup" aria-label="Available models">
              {modelsQuery.isFetching && <div className="ait-llm-list-state"><LoaderCircle size={16} className="ait-llm-spin" /> Loading available models…</div>}
              {!modelsQuery.isFetching && filteredModels.length === 0 && <div className="ait-llm-list-state"><CircleAlert size={16} /> No matching models.</div>}
              {!modelsQuery.isFetching && filteredModels.map((model) => (
                <button key={model.id} type="button" role="radio" aria-checked={draft.model === model.id} className={`ait-llm-model-row${draft.model === model.id ? " is-active" : ""}`} onClick={() => { setDraft((current) => ({ ...current, model: model.id })); setConnectionNotice(null) }} disabled={busy || isTesting}>
                  <span className={`ait-llm-radio${draft.model === model.id ? " is-selected" : ""}`} aria-hidden="true"><span /></span>
                  <span className="ait-llm-model-name">{model.id}</span>
                  {model.id === settings.model && <span className="ait-llm-badge">Current</span>}
                </button>
              ))}
            </div>
            <div className="ait-llm-card-footer"><span>{modelsQuery.data?.available ? `Showing ${modelsQuery.data.models.length} model${modelsQuery.data.models.length === 1 ? "" : "s"}` : connectionDetail}</span><a href="https://platform.deepseek.com/api-docs/" target="_blank" rel="noreferrer">Learn more about models <ExternalLink size={14} /></a></div>
          </section>

          <section className="ait-llm-card ait-llm-key-card">
            <CardHeading icon={<KeyRound size={27} strokeWidth={1.8} />} eyebrow="3. API key & connection" title="API key & connection" description="Enter your API key, test the connection, and save it for this provider." />
            {selected?.requires_base_url && (
              <>
                <label className="ait-llm-key-label" htmlFor="ait-llm-base-url">Base URL</label>
                <div className="ait-llm-key-input-wrap">
                  <input id="ait-llm-base-url" type="url" value={draft.baseUrl} disabled={busy} onChange={(event) => setDraft((current) => ({ ...current, baseUrl: event.target.value }))} placeholder="https://api.example.com/v1" />
                </div>
              </>
            )}
            <label className="ait-llm-key-label" htmlFor="ait-llm-api-key">API key</label>
            <div className="ait-llm-key-input-wrap">
              <input id="ait-llm-api-key" type={showKey ? "text" : "password"} autoComplete="new-password" value={draft.apiKey} disabled={busy || !desktopVaultAvailable} onChange={(event) => setDraft((current) => ({ ...current, apiKey: event.target.value }))} placeholder={configured ? "Enter a new key to replace" : "Paste API key"} aria-describedby="ait-llm-vault-note" />
              <button type="button" disabled={!desktopVaultAvailable} onClick={() => setShowKey((visible) => !visible)} aria-label={showKey ? "Hide API key" : "Show API key"} title={showKey ? "Hide API key" : "Show API key"}>{showKey ? <EyeOff size={16} /> : <Eye size={16} />}</button>
            </div>
            {error && <p className="ait-llm-error" role="alert"><CircleAlert size={15} /> {error}</p>}
            {connectionNotice && <p className={`ait-llm-notice${connectionTested ? " is-success" : ""}`} role="status"><CheckCircle2 size={15} /> {connectionNotice}</p>}
            <div className="ait-llm-key-actions">
              <button type="button" className="ait-llm-primary-button" onClick={() => void testConnection()} disabled={busy || isTesting || modelsQuery.isFetching || !savedDraft}><Play size={16} />{isTesting ? "Testing connection…" : "Test connection"}</button>
              <button type="button" className="ait-llm-save-button" onClick={() => save()} disabled={busy || !draft.model.trim()}>{busy ? <LoaderCircle size={16} className="ait-llm-spin" /> : <Check size={16} />}{busy ? "Saving…" : "Save API key"}</button>
            </div>
            <div className="ait-llm-status">
              <div className="ait-llm-status-heading"><strong>Connection status</strong><span>Results from your latest connection test.</span></div>
              <StatusRow label="Endpoint reachable" value={connectionTested ? "Yes" : savedDraft && modelsQuery.data?.available ? "Yes" : "Not checked"} checked={connectionTested || Boolean(savedDraft && modelsQuery.data?.available)} />
              <StatusRow label="Last checked" value={lastCheckedAt || "Not checked"} />
              <StatusRow label="Models available" value={modelsQuery.data?.available ? `${modelsQuery.data.models.length} available` : "Not checked"} checked={Boolean(modelsQuery.data?.available)} />
              <StatusRow label="Selected model" value={draft.model || "Not configured"} checked={Boolean(draft.model.trim())} />
            </div>
            {configured && <button type="button" className="ait-llm-remove-button" onClick={() => save(true)} disabled={busy}>Remove saved key</button>}
            <p id="ait-llm-vault-note" className="ait-llm-vault-note"><ShieldCheck size={15} />{storageLabel}. API keys are kept in the desktop credential vault and are never written to the local settings API.</p>
          </section>
        </div>
      </div>
    </section>
  )
}

function LlmHeader({ onClose }: { onClose: () => void }) {
  return (
    <header className="ait-llm-header">
      <div>
        <p className="ait-llm-kicker">AITrans / Settings</p>
        <h1>AI model connection</h1>
        <p>Configure the global AI model used across your entire project.</p>
      </div>
      <button type="button" className="ait-llm-close" onClick={onClose} aria-label="Close AI model connection" title="Close"><X size={21} /></button>
    </header>
  )
}

function SummaryItem({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="ait-llm-summary-item">
      <span className="ait-llm-summary-icon" aria-hidden="true">{icon}</span>
      <span className="ait-llm-summary-copy"><span>{label}</span><strong title={value}>{value}</strong></span>
    </div>
  )
}

function CardHeading({ icon, eyebrow, title, description }: { icon: ReactNode; eyebrow: string; title: string; description: string }) {
  return (
    <div className="ait-llm-card-heading">
      <span className="ait-llm-card-icon" aria-hidden="true">{icon}</span>
      <div><p>{eyebrow}</p><h2>{title}</h2><span>{description}</span></div>
    </div>
  )
}

function ProviderRow({ provider, active, credentialConfigured, disabled, onClick }: { provider: LlmProviderOption; active: boolean; credentialConfigured: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`ait-llm-provider-row${active ? " is-active" : ""}`} onClick={onClick} disabled={disabled}>
      <span className="ait-llm-provider-icon" aria-hidden="true">{provider.id === "deepseek" ? <ServerCog size={24} strokeWidth={1.7} /> : <Database size={24} strokeWidth={1.7} />}</span>
      <span className="ait-llm-provider-copy"><strong>{provider.label}</strong><small>{active ? credentialConfigured ? "Configured" : "Selected · API key required" : provider.requires_base_url ? "Bring your endpoint and model." : "Official provider endpoint."}</small></span>
      <ChevronRight size={18} aria-hidden="true" />
    </button>
  )
}

function StoredCredentialPanel({
  providerLabel,
  preview,
  loading,
  configured,
  savedDraft,
  models,
  modelsAvailable,
  modelsLoading,
  modelsDetail,
}: {
  providerLabel: string
  preview: string
  loading: boolean
  configured: boolean
  savedDraft: boolean
  models: LlmModelOption[]
  modelsAvailable: boolean
  modelsLoading: boolean
  modelsDetail: string
}) {
  return (
    <section className="ait-llm-stored-card" aria-label="Current stored credential">
      <div className="ait-llm-stored-heading">
        <ShieldCheck size={18} aria-hidden="true" />
        <div><p>Current stored credential</p><h3>{providerLabel}</h3></div>
        <span className={`ait-llm-stored-status${configured ? " is-ready" : ""}`}>{configured ? "Ready" : "Not configured"}</span>
      </div>
      <div className="ait-llm-stored-row"><span>API key</span><strong>{loading ? "Checking…" : preview || "No saved key"}</strong></div>
      <div className="ait-llm-stored-row"><span>Models</span><strong>{modelsLoading ? "Detecting…" : modelsAvailable ? `${models.length} discovered` : savedDraft ? "Unavailable" : "Save provider first"}</strong></div>
      {modelsAvailable && models.length > 0 ? (
        <ul className="ait-llm-stored-models" aria-label="Discovered models">
          {models.slice(0, 5).map((model) => <li key={model.id} title={model.id}>{model.id}</li>)}
          {models.length > 5 && <li>+{models.length - 5} more</li>}
        </ul>
      ) : (
        <p className="ait-llm-stored-note">{modelsDetail}</p>
      )}
      <p className="ait-llm-stored-note">The key stays masked; only this local desktop window can access the credential vault.</p>
    </section>
  )
}

function StatusRow({ label, value, checked = false }: { label: string; value: string; checked?: boolean }) {
  return (
    <div className="ait-llm-status-row">
      <span className={`ait-llm-status-check${checked ? " is-checked" : ""}`} aria-hidden="true">{checked && <Check size={12} strokeWidth={2.8} />}</span>
      <strong>{label}</strong>
      <span title={value}>{value}</span>
    </div>
  )
}
