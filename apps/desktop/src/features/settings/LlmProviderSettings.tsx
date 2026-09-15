import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Eye, EyeOff, KeyRound, LoaderCircle, Save, ServerCog, ShieldCheck } from "lucide-react"
import { useMemo, useState } from "react"

import {
  getLlmSettings,
  updateLlmSettings,
  type LlmProviderId,
  type LlmSettings,
} from "../../api/llm-settings"
import {
  deleteLlmCredential,
  getLlmCredentialStatus,
  hasTauriCredentialVault,
  saveLlmCredential,
} from "../../desktop/tauri/llm-credential-vault"
import { Button } from "../../shared/ui/Button"

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

export function LlmProviderSettings() {
  const settingsQuery = useQuery({ queryKey: QUERY_KEY, queryFn: getLlmSettings })

  if (settingsQuery.isPending) {
    return <section className="ait-surface p-6 lg:p-7"><div className="ait-skeleton h-44 rounded-[17px]" /></section>
  }

  if (settingsQuery.isError || !settingsQuery.data) {
    return (
      <section className="ait-surface p-6 lg:p-7">
        <p className="text-sm text-slate-700">Cloud LLM settings are unavailable.</p>
        <Button className="mt-3" size="xs" onClick={() => void settingsQuery.refetch()}>Retry</Button>
      </section>
    )
  }

  const settings = settingsQuery.data
  return (
    <LlmProviderSettingsForm
      key={`${settings.provider}:${settings.model}:${settings.base_url}`}
      settings={settings}
    />
  )
}

function LlmProviderSettingsForm({ settings }: { settings: LlmSettings }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(() => draftFrom(settings))
  const [showKey, setShowKey] = useState(false)
  const desktopVaultAvailable = hasTauriCredentialVault()

  const credentialQuery = useQuery({
    queryKey: ["settings", "llm", "credential", draft.provider],
    queryFn: () => getLlmCredentialStatus(draft.provider),
    enabled: desktopVaultAvailable,
  })

  const mutation = useMutation({
    mutationFn: async ({ draft: current, clearApiKey }: SaveRequest) => {
      const nextSettings = await updateLlmSettings({
        provider: current.provider,
        model: current.model.trim(),
        base_url: current.baseUrl.trim(),
      })

      if (clearApiKey) {
        if (!desktopVaultAvailable) throw new Error("API Key 只能在 Tauri 桌面应用中保存或移除。")
        await deleteLlmCredential(current.provider)
      } else if (current.apiKey.trim()) {
        if (!desktopVaultAvailable) throw new Error("API Key 只能在 Tauri 桌面应用中保存。")
        await saveLlmCredential(current.provider, current.apiKey.trim())
      }

      return nextSettings
    },
    onSuccess: (nextSettings) => {
      setDraft(draftFrom(nextSettings))
      setShowKey(false)
      queryClient.setQueryData(QUERY_KEY, nextSettings)
      void queryClient.invalidateQueries({ queryKey: ["settings", "llm", "credential"] })
      void queryClient.invalidateQueries({ queryKey: ["agent", "runtime", "config"] })
    },
  })

  const selected = useMemo(
    () => settings.providers.find((provider) => provider.id === draft.provider),
    [draft.provider, settings.providers],
  )

  const configured = desktopVaultAvailable && Boolean(credentialQuery.data?.configured)
  const busy = mutation.isPending
  const error = errorMessage(mutation.error) ?? errorMessage(credentialQuery.error)
  const storageLabel = !desktopVaultAvailable
    ? "Open the Tauri desktop app to manage API keys"
    : credentialQuery.isPending
      ? "Checking Windows Credential Manager…"
      : configured
        ? "Saved in Windows Credential Manager"
        : "No API key saved"

  function chooseProvider(provider: LlmProviderId) {
    const next = settings.providers.find((option) => option.id === provider)
    if (!next) return
    setDraft((current) => ({
      ...current,
      provider,
      model: next.default_model || current.model,
      baseUrl: next.default_base_url || current.baseUrl,
      apiKey: "",
    }))
  }

  function save(clearApiKey = false) {
    mutation.mutate({ draft, clearApiKey })
  }

  return (
    <section className="ait-surface overflow-hidden">
      <header className="border-b border-slate-100 bg-[linear-gradient(105deg,#f8fafc_0%,#fff_60%,#ecfeff_100%)] p-6 lg:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-700">Cloud LLM</p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">Provider connection</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">One local connection powers chat, AI translation, reading actions, and agent workflows.</p>
          </div>
          <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold ${configured ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
            {configured ? <CheckCircle2 size={14} /> : <KeyRound size={14} />}
            {configured ? "Key ready" : "Key required"}
          </span>
        </div>
      </header>

      <div className="grid gap-6 p-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(260px,.75fr)] lg:p-7">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Choose provider</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {settings.providers.map((provider) => {
              const active = draft.provider === provider.id
              return (
                <button key={provider.id} type="button" disabled={busy} onClick={() => chooseProvider(provider.id)} className={`rounded-[15px] border p-4 text-left transition disabled:cursor-not-allowed disabled:opacity-60 ${active ? "border-cyan-500 bg-cyan-50/70 shadow-[0_8px_20px_rgba(8,145,178,.10)]" : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}`}>
                  <span className={`flex h-8 w-8 items-center justify-center rounded-[10px] ${active ? "bg-cyan-600 text-white" : "bg-slate-100 text-slate-500"}`}><ServerCog size={16} /></span>
                  <span className="mt-3 block text-sm font-semibold text-slate-900">{provider.label}</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500">{provider.requires_base_url ? "Bring your endpoint and model." : "Official DeepSeek endpoint."}</span>
                </button>
              )
            })}
          </div>

          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <label className="block"><span className="text-xs font-semibold text-slate-700">Model</span><input value={draft.model} disabled={busy} onChange={(event) => setDraft({ ...draft, model: event.target.value })} className="mt-2 w-full rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 font-mono text-sm text-slate-900 outline-none transition focus:border-cyan-500 focus:ring-4 focus:ring-cyan-500/10 disabled:bg-slate-50" placeholder={selected?.default_model || "model-id"} /></label>
            <label className="block"><span className="text-xs font-semibold text-slate-700">Base URL {selected?.requires_base_url ? "" : "(managed)"}</span><input value={draft.baseUrl} disabled={busy || !selected?.requires_base_url} onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })} className="mt-2 w-full rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 font-mono text-sm text-slate-900 outline-none transition focus:border-cyan-500 focus:ring-4 focus:ring-cyan-500/10 disabled:bg-slate-50" placeholder="https://api.example.com/v1" /></label>
          </div>
        </div>

        <aside className="rounded-[17px] border border-slate-200 bg-slate-50/70 p-4 sm:p-5">
          <div className="flex items-center gap-2 text-slate-900"><ShieldCheck size={17} className="text-cyan-700" /><h3 className="text-sm font-semibold">API key vault</h3></div>
          <p className="mt-2 text-xs leading-5 text-slate-500">The key is sent directly to the desktop credential vault, never to the local backend API. It is not written to user settings or shown again.</p>
          <p className="mt-3 rounded-[10px] bg-white px-3 py-2 text-[11px] font-medium text-slate-500">{storageLabel}</p>
          <div className="relative mt-4"><input type={showKey ? "text" : "password"} autoComplete="new-password" value={draft.apiKey} disabled={busy || !desktopVaultAvailable} onChange={(event) => setDraft({ ...draft, apiKey: event.target.value })} className="w-full rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 pr-10 font-mono text-sm text-slate-900 outline-none transition focus:border-cyan-500 focus:ring-4 focus:ring-cyan-500/10 disabled:bg-slate-100" placeholder={configured ? "Enter a new key to replace" : "Paste API key"} aria-label="API key" /><button type="button" disabled={!desktopVaultAvailable} className="absolute right-2 top-2 rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed" onClick={() => setShowKey((visible) => !visible)} aria-label={showKey ? "Hide API key" : "Show API key"}>{showKey ? <EyeOff size={16} /> : <Eye size={16} />}</button></div>
          {error && <p role="alert" className="mt-3 rounded-[10px] bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700">{error}</p>}
          <div className="mt-4 flex flex-wrap gap-2"><Button variant="primary" size="sm" disabled={busy || !draft.model.trim()} onClick={() => save()}>{busy ? <LoaderCircle size={14} className="animate-spin" /> : <Save size={14} />}{busy ? "Saving…" : "Save connection"}</Button>{configured && <Button variant="ghost" size="sm" disabled={busy} onClick={() => save(true)}>Remove saved key</Button>}</div>
        </aside>
      </div>
    </section>
  )
}
