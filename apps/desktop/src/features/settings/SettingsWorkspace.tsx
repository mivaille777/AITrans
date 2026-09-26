import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Box,
  Cpu,
  Database,
  ExternalLink,
  FileText,
  FlaskConical,
  FolderOpen,
  Link2,
  LoaderCircle,
  LockKeyhole,
  Palette,
  RotateCcw,
  Settings2,
  SlidersHorizontal,
  X,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useLocation, useNavigate } from "react-router-dom"

import {
  getAvailableLlmModels,
  getLlmSettings,
  updateLlmSettings,
} from "../../api/llm-settings"
import {
  DEFAULT_OVERLAY_PREFERENCES,
  readOverlayPreferences,
  subscribeOverlayPreferences,
  updateOverlayPreferences,
} from "../../desktop/overlay-preferences"
import OverlayPreferencesPanel from "../../components/OverlayPreferencesPanel"
import TranslationProviderSelector from "../translation/TranslationProviderSelector"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { LocalModelManager } from "./LocalModelManager"
import { LlmProviderSettings } from "./LlmProviderSettings"
import RagDebugStudioTrace from "./RagDebugStudioTrace"
import SandboxDebugStudio from "./SandboxDebugStudio"
import { useLocalModels } from "./useLocalModels"

import "./SettingsWorkspace.css"

type SettingsSectionId =
  | "general"
  | "ai-model"
  | "reading"
  | "browser"
  | "appearance"
  | "research-data"
  | "advanced"

type SettingsDrawer = "llm" | "browser" | "research-data" | "advanced" | null
type SettingsStudio = "rag" | "sandbox" | null

interface SettingsNavigationState {
  studio?: "rag" | "sandbox"
  sandboxId?: string
}

const settingsSections: Array<{
  id: SettingsSectionId
  label: string
  description: string
  icon: typeof Settings2
}> = [
  { id: "general", label: "General", description: "Runtime defaults", icon: Settings2 },
  { id: "ai-model", label: "AI model", description: "Provider and model", icon: Cpu },
  { id: "reading", label: "Reading and selection", description: "Context behavior", icon: FileText },
  { id: "browser", label: "Browser integration", description: "Bridge status", icon: Link2 },
  { id: "appearance", label: "Appearance", description: "Visual preferences", icon: Palette },
  { id: "research-data", label: "Research data", description: "Local storage", icon: Database },
  { id: "advanced", label: "Advanced", description: "Power-user controls", icon: SlidersHorizontal },
]

const LLM_SETTINGS_QUERY_KEY = ["settings", "llm"] as const

export default function SettingsWorkspace({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
  const scrollRef = useRef<HTMLDivElement>(null)
  const sectionRefs = useRef<Partial<Record<SettingsSectionId, HTMLElement | null>>>({})
  const [activeSection, setActiveSection] = useState<SettingsSectionId>("general")
  const [drawer, setDrawer] = useState<SettingsDrawer>(null)
  const [notice, setNotice] = useState("")
  const [activeStudio, setActiveStudio] = useState<SettingsStudio>(null)
  const [sandboxIntentId, setSandboxIntentId] = useState("")
  const [, setOverlayPreferences] = useState(readOverlayPreferences)

  const llmSettingsQuery = useQuery({
    queryKey: LLM_SETTINGS_QUERY_KEY,
    queryFn: getLlmSettings,
  })
  const llmModelsQuery = useQuery({
    queryKey: ["settings", "llm", "models"],
    queryFn: getAvailableLlmModels,
    enabled: llmSettingsQuery.isSuccess,
    staleTime: 60_000,
  })
  const localModels = useLocalModels()

  const modelMutation = useMutation({
    mutationFn: (model: string) => {
      const settings = llmSettingsQuery.data
      if (!settings) throw new Error("LLM settings are not loaded yet.")
      return updateLlmSettings({
        provider: settings.provider,
        model,
        base_url: settings.base_url,
      })
    },
    onSuccess: (nextSettings) => {
      queryClient.setQueryData(LLM_SETTINGS_QUERY_KEY, nextSettings)
      void queryClient.invalidateQueries({ queryKey: ["settings", "llm", "models"] })
      void queryClient.invalidateQueries({ queryKey: ["agent", "runtime", "config"] })
      setNotice("AI model saved.")
    },
  })

  useEffect(() => subscribeOverlayPreferences(setOverlayPreferences), [])

  /* oxlint-disable react-hooks/set-state-in-effect -- router state intentionally selects a debug studio */
  useEffect(() => {
    const navigationState = (location.state ?? null) as SettingsNavigationState | null
    if (!navigationState?.studio) return

    if (navigationState.studio === "rag") {
      setActiveStudio("rag")
    } else if (workspace.sandboxEnabled) {
      setActiveStudio("sandbox")
      setSandboxIntentId(navigationState.sandboxId?.trim() ?? "")
    } else {
      setActiveStudio(null)
      setSandboxIntentId("")
    }

    navigate(
      {
        pathname: location.pathname,
        search: location.search,
        hash: location.hash,
      },
      { replace: true, state: null },
    )
  }, [
    location.hash,
    location.pathname,
    location.search,
    location.state,
    navigate,
    workspace.sandboxEnabled,
  ])
  /* oxlint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    const root = scrollRef.current
    if (!root) return

    // The desktop layout gives the content column its own scroll host. Derive the
    // active item from a stable activation line instead of relying on intersection
    // timing, so smooth navigation and manual wheel scrolling produce the same
    // result. On the compact layout the workspace itself becomes the scroll host.
    const scrollHost = root.scrollHeight > root.clientHeight ? root : root.parentElement ?? root
    let frame = 0

    function updateActiveSection() {
      const activationLine = scrollHost.getBoundingClientRect().top + 112
      let nextSection: SettingsSectionId = settingsSections[0].id

      for (const { id } of settingsSections) {
        const section = sectionRefs.current[id]
        if (!section) continue
        if (section.getBoundingClientRect().top <= activationLine) nextSection = id
      }

      // The final section cannot reach the activation line when the scroll host
      // is already at its maximum offset. Treat the bottom edge as an explicit
      // signal so the last navigation item is still reachable by wheel scrolling.
      if (scrollHost.scrollTop + scrollHost.clientHeight >= scrollHost.scrollHeight - 2) {
        nextSection = settingsSections.at(-1)?.id ?? nextSection
      }

      setActiveSection((current) => current === nextSection ? current : nextSection)
    }

    function handleScroll() {
      if (frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0
        updateActiveSection()
      })
    }

    scrollHost.addEventListener("scroll", handleScroll, { passive: true })
    updateActiveSection()

    return () => {
      scrollHost.removeEventListener("scroll", handleScroll)
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [])

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && drawer) setDrawer(null)
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [drawer])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(""), 3_500)
    return () => window.clearTimeout(timer)
  }, [notice])

  const llmSettings = llmSettingsQuery.data
  const currentModel = llmSettings?.model || llmModelsQuery.data?.current_model || "Not configured"
  const modelOptions = useMemo(() => {
    const ids = [currentModel, ...(llmModelsQuery.data?.models.map((model) => model.id) ?? [])]
    return [...new Set(ids.filter(Boolean))]
  }, [currentModel, llmModelsQuery.data?.models])

  const browserConnected = Boolean(workspace.browserStatus?.running)
  const localRuntimeReady = workspace.backendState === "connected"
  const localStoragePath = localModels.modelsQuery.data?.models_root || "AITrans local app storage"
  const llmError = llmSettingsQuery.error ?? llmModelsQuery.error ?? modelMutation.error

  function scrollToSection(id: SettingsSectionId) {
    setActiveStudio(null)
    sectionRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "start" })
    setActiveSection(id)
  }

  function resetDefaults() {
    const nextPreferences = updateOverlayPreferences(DEFAULT_OVERLAY_PREFERENCES)
    setOverlayPreferences(nextPreferences)
    workspace.setFollowBrowserSelection(true)
    workspace.setAutoTranslateSelection(false)
    setNotice("Overlay and reading defaults restored. Model settings were kept.")
  }

  return (
    <div className="ait-settings-workspace" translate="no">
      <aside className="ait-settings-nav" aria-label="Settings navigation">
        <div className="ait-settings-nav-heading">
          <h1>Settings</h1>
          <p>Configure AITrans for your workflow.</p>
        </div>

        <nav className="ait-settings-nav-list">
           {settingsSections.map(({ id, label, description, icon: Icon }) => (
            <button
              key={id}
              type="button"
               className={`ait-settings-nav-item${activeSection === id && activeStudio === null ? " is-active" : ""}`}
               aria-current={activeSection === id && activeStudio === null ? "page" : undefined}
               onClick={() => scrollToSection(id)}
            >
              <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
              <span className="ait-settings-nav-item-copy">
                <strong>{label}</strong>
                <small>{description}</small>
              </span>
              <ChevronRight className="ait-settings-nav-item-arrow" size={15} strokeWidth={1.7} aria-hidden="true" />
             </button>
           ))}
          <button
            type="button"
            className={`ait-settings-nav-item${activeStudio === "rag" ? " is-active" : ""}`}
            aria-current={activeStudio === "rag" ? "page" : undefined}
            onClick={() => setActiveStudio("rag")}
          >
            <FlaskConical size={18} strokeWidth={1.8} aria-hidden="true" />
            <span className="ait-settings-nav-item-copy">
              <strong>RAG Debug Studio</strong>
              <small>Trace retrieval runs</small>
            </span>
            <ChevronRight className="ait-settings-nav-item-arrow" size={15} strokeWidth={1.7} aria-hidden="true" />
          </button>
          <button
            type="button"
            className={`ait-settings-nav-item${activeStudio === "sandbox" ? " is-active" : ""}`}
            aria-current={activeStudio === "sandbox" ? "page" : undefined}
            disabled={!workspace.sandboxEnabled}
            aria-disabled={!workspace.sandboxEnabled}
            onClick={() => workspace.sandboxEnabled && setActiveStudio("sandbox")}
          >
            <Box size={18} strokeWidth={1.8} aria-hidden="true" />
            <span className="ait-settings-nav-item-copy">
              <strong>Sandbox Debug Studio</strong>
              <small>{workspace.sandboxEnabled ? "Inspect isolated execution" : "Disabled by feature flag"}</small>
            </span>
            <ChevronRight className="ait-settings-nav-item-arrow" size={15} strokeWidth={1.7} aria-hidden="true" />
          </button>
        </nav>

        <div className="ait-settings-nav-footer">
          <div className="ait-settings-nav-footer-rule" />
          <p><CircleHelp size={14} aria-hidden="true" /> Changes save as you make them.</p>
        </div>
      </aside>

      <div ref={scrollRef} className="ait-settings-content">
        <header className="ait-settings-content-header">
          <span className="ait-settings-mantra">Your ideas stay with you.</span>
        </header>

        <div className={activeStudio === null ? "block" : "hidden"}>
          <main className="ait-settings-content-body">
          <SettingsSection
            id="general"
            title="Local-first runtime"
            description="AITrans runs locally on your device. Your data never leaves your computer."
            sectionRef={(node) => { sectionRefs.current.general = node }}
          >
            <SettingRow label="Local runtime" description="Use local models and keep all data on this device.">
              <SettingsSwitch checked={localRuntimeReady} disabled label={localRuntimeReady ? "Enabled" : "Unavailable"} />
            </SettingRow>
          </SettingsSection>

          <SettingsSection
            id="ai-model"
            title="AI model"
            description="Choose the model used for chat, summaries and analysis."
            sectionRef={(node) => { sectionRefs.current["ai-model"] = node }}
          >
            <SettingRow label="Model" description="Select the active provider model.">
              <div className="ait-settings-control-group">
                <select
                  className="ait-settings-select"
                  aria-label="AI model"
                  value={currentModel}
                  disabled={llmSettingsQuery.isPending || modelMutation.isPending || modelOptions.length === 0}
                  onChange={(event) => modelMutation.mutate(event.target.value)}
                >
                  {modelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
                <button type="button" className="ait-settings-subtle-button" onClick={() => setDrawer("llm")}>
                  Manage connection
                </button>
              </div>
            </SettingRow>
            <SettingRow label="Context length" description="Maximum context window for this runtime.">
              <ReadOnlyControl value="8,192 tokens" />
            </SettingRow>
            <SettingRow label="Temperature" description="Higher values are more creative, lower values are more focused.">
              <ReadOnlyControl value="0.3" />
            </SettingRow>
            <div className="ait-settings-inline-status" aria-live="polite">
              {modelMutation.isPending && <><LoaderCircle size={14} className="ait-settings-spin" /> Saving model…</>}
              {!modelMutation.isPending && llmModelsQuery.isFetching && <><LoaderCircle size={14} className="ait-settings-spin" /> Checking available models…</>}
              {!modelMutation.isPending && !llmModelsQuery.isFetching && llmModelsQuery.data?.available && <><CheckCircle2 size={14} /> {llmModelsQuery.data.models.length} models available for {llmModelsQuery.data.provider}.</>}
              {!modelMutation.isPending && !llmModelsQuery.isFetching && !llmModelsQuery.data?.available && <><AlertCircle size={14} /> {llmModelsQuery.data?.detail || "No model catalog is available for this API key."}</>}
            </div>
            {llmError && <div className="ait-settings-error" role="alert"><AlertCircle size={14} />{llmError instanceof Error ? llmError.message : "Unable to load LLM settings."}</div>}
          </SettingsSection>

          <SettingsSection
            id="reading"
            title="Reading and selection"
            description="Customize how AITrans processes content you read and select."
            sectionRef={(node) => { sectionRefs.current.reading = node }}
          >
            <SettingRow label="Default action" description="What to do when you select text on a page.">
              <ReadOnlyControl value="Show quick actions" />
            </SettingRow>
            <SettingRow label="Follow browser selection" description="Keep the latest browser selection available to Reading and Chat.">
              <SettingsSwitch checked={workspace.followBrowserSelection} label={workspace.followBrowserSelection ? "Enabled" : "Disabled"} onChange={workspace.setFollowBrowserSelection} />
            </SettingRow>
            <SettingRow label="Auto-translate selection" description="Translate a new browser selection as soon as it arrives.">
              <SettingsSwitch checked={workspace.autoTranslateSelection} label={workspace.autoTranslateSelection ? "Enabled" : "Disabled"} onChange={workspace.setAutoTranslateSelection} />
            </SettingRow>
            <SettingRow label="Include surrounding context" description="Nearby page context is included automatically when the bridge provides it.">
              <SettingsSwitch checked disabled label="Included" />
            </SettingRow>
          </SettingsSection>

          <SettingsSection
            id="browser"
            title="Browser integration"
            description="Connect AITrans with your browser for seamless research."
            sectionRef={(node) => { sectionRefs.current.browser = node }}
          >
            <SettingRow label="Browser bridge" description="Status of the local browser extension.">
              <div className="ait-settings-control-group">
                <span className={`ait-settings-status${browserConnected ? " is-connected" : ""}`}>
                  <span className="ait-settings-status-dot" aria-hidden="true" />
                  {workspace.browserStatusChecking ? "Checking…" : browserConnected ? "Connected" : "Not connected"}
                </span>
                <button type="button" className="ait-settings-outline-button" onClick={() => setDrawer("browser")}>Manage</button>
              </div>
            </SettingRow>
            {workspace.browserStatus?.last_title && (
              <div className="ait-settings-detail-note">
                <span>Last active page</span>
                <strong>{workspace.browserStatus.last_title}</strong>
              </div>
            )}
          </SettingsSection>

          <SettingsSection
            id="appearance"
            title="Appearance"
            description="Adjust the look and feel of AITrans."
            sectionRef={(node) => { sectionRefs.current.appearance = node }}
          >
            <SettingRow label="Theme" description="Choose a visual theme for the workspace.">
              <ReadOnlyControl value="Monochrome" />
            </SettingRow>
            <SettingRow label="Typography scale" description="Adjust the size of text across the app.">
              <ReadOnlyControl value="Medium (100%)" />
            </SettingRow>
            <div className="ait-settings-section-action-row">
              <span>Native overlay appearance and placement</span>
              <button type="button" className="ait-settings-outline-button" onClick={() => setDrawer("advanced")}>Open advanced controls <ExternalLink size={14} /></button>
            </div>
          </SettingsSection>

          <SettingsSection
            id="research-data"
            title="Research data"
            description="Manage where your notes, summaries and local model data are stored."
            sectionRef={(node) => { sectionRefs.current["research-data"] = node }}
          >
            <SettingRow label="Storage location" description="Location of local AITrans data on this device.">
              <div className="ait-settings-control-group ait-settings-control-group-wide">
                <span className="ait-settings-path" title={localStoragePath}>{localStoragePath}</span>
                <button type="button" className="ait-settings-outline-button" onClick={() => setDrawer("research-data")}>Manage</button>
              </div>
            </SettingRow>
            <SettingRow label="Local model cache" description="Embedding and reranker files used by Knowledge.">
              <button type="button" className="ait-settings-outline-button" onClick={() => setDrawer("research-data")}>Open model manager <FolderOpen size={14} /></button>
            </SettingRow>
          </SettingsSection>

          <SettingsSection
            id="advanced"
            title="Advanced"
            description="Power-user controls for providers, the native overlay and local runtime."
            sectionRef={(node) => { sectionRefs.current.advanced = node }}
          >
            <SettingRow label="Translation provider" description="Used by manual translation, reading actions and the native overlay.">
              <button type="button" className="ait-settings-outline-button" onClick={() => setDrawer("advanced")}>Configure provider <ChevronRight size={14} /></button>
            </SettingRow>
            <SettingRow label="Native overlay" description="Placement, interaction and appearance controls for the desktop overlay.">
              <button type="button" className="ait-settings-outline-button" onClick={() => setDrawer("advanced")}>Open overlay settings <ChevronRight size={14} /></button>
            </SettingRow>
          </SettingsSection>
          </main>
        </div>
        <div className={activeStudio === "rag" ? "block h-full min-h-0" : "hidden"}>
          <RagDebugStudioTrace />
        </div>
        {workspace.sandboxEnabled ? (
          <div className={activeStudio === "sandbox" ? "block h-full min-h-0" : "hidden"}>
            <SandboxDebugStudio initialSandboxId={sandboxIntentId} />
          </div>
        ) : null}

        <footer className="ait-settings-actions">
          <button type="button" className="ait-settings-secondary-button" onClick={resetDefaults}><RotateCcw size={14} /> Reset to defaults</button>
          <button type="button" className="ait-settings-primary-button" onClick={() => setNotice("All settings are saved automatically.")}>Save changes</button>
        </footer>
      </div>

      {notice && <div className="ait-settings-toast" role="status"><Check size={15} /> {notice}</div>}

      {drawer && (
        <div className="ait-settings-drawer-backdrop" role="presentation" onMouseDown={() => setDrawer(null)}>
          <aside className={`ait-settings-drawer${drawer === "llm" ? " ait-settings-drawer-llm" : ""}`} role="dialog" aria-modal="true" aria-label={drawerTitle(drawer)} onMouseDown={(event) => event.stopPropagation()}>
            {drawer === "llm" ? (
              <LlmProviderSettings onClose={() => setDrawer(null)} />
            ) : (
              <>
                <header className="ait-settings-drawer-header">
                  <div>
                    <p className="ait-settings-eyebrow">AITrans / Settings</p>
                    <h2>{drawerTitle(drawer)}</h2>
                  </div>
                  <button type="button" className="ait-settings-icon-button" onClick={() => setDrawer(null)} aria-label="Close settings panel" title="Close settings panel"><X size={18} /></button>
                </header>
                <div className="ait-settings-drawer-body">
                  {drawer === "browser" && <BrowserIntegrationDrawer workspace={workspace} connected={browserConnected} />}
                  {drawer === "research-data" && <LocalModelManager />}
                  {drawer === "advanced" && (
                    <div className="ait-settings-drawer-stack">
                      <section className="ait-settings-drawer-card">
                        <div className="ait-settings-drawer-card-heading"><Settings2 size={17} /><div><h3>Translation provider</h3><p>Choose the web translation source used across Reading and the overlay.</p></div></div>
                        <TranslationProviderSelector
                          value={workspace.translationProvider}
                          switching={workspace.providerSwitching}
                          disabled={workspace.backendState !== "connected" || workspace.providerSwitching}
                          onChange={workspace.setTranslationProvider}
                        />
                        {workspace.translationError && <p className="ait-settings-error" role="alert"><AlertCircle size={14} />{workspace.translationError}</p>}
                      </section>
                      <OverlayPreferencesPanel />
                      <p className="ait-settings-drawer-note"><LockKeyhole size={14} /> API keys remain in the desktop credential vault and are never written into this page.</p>
                    </div>
                  )}
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}

function SettingsSection({
  id,
  title,
  description,
  sectionRef,
  children,
}: {
  id: SettingsSectionId
  title: string
  description: string
  sectionRef: (node: HTMLElement | null) => void
  children: ReactNode
}) {
  return (
    <section ref={sectionRef} data-settings-section={id} className="ait-settings-section">
      <header className="ait-settings-section-header">
        <h2>{title}</h2>
        <p>{description}</p>
      </header>
      <div className="ait-settings-rows">{children}</div>
    </section>
  )
}

function SettingRow({ label, description, children }: { label: string; description: string; children: ReactNode }) {
  return (
    <div className="ait-settings-row">
      <div className="ait-settings-row-copy">
        <strong>{label}</strong>
        <span>{description}</span>
      </div>
      <div className="ait-settings-row-control">{children}</div>
    </div>
  )
}

function SettingsSwitch({ checked, disabled = false, label, onChange }: { checked: boolean; disabled?: boolean; label: string; onChange?: (checked: boolean) => void }) {
  return (
    <button
      type="button"
      className={`ait-settings-switch${checked ? " is-checked" : ""}`}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
    >
      <span className="ait-settings-switch-track" aria-hidden="true"><span /></span>
      <span>{label}</span>
    </button>
  )
}

function ReadOnlyControl({ value }: { value: string }) {
  return <span className="ait-settings-readonly"><span>{value}</span><LockKeyhole size={13} aria-label="Managed by runtime" /></span>
}

function BrowserIntegrationDrawer({ workspace, connected }: { workspace: TranslationWorkspaceController; connected: boolean }) {
  return (
    <div className="ait-settings-drawer-stack">
      <section className="ait-settings-drawer-card">
        <div className="ait-settings-drawer-card-heading"><Link2 size={18} /><div><h3>Browser bridge</h3><p>Connect the local browser extension to keep reading selections and page context in sync.</p></div></div>
        <div className="ait-settings-drawer-status-line"><span className={`ait-settings-status${connected ? " is-connected" : ""}`}><span className="ait-settings-status-dot" />{workspace.browserStatusChecking ? "Checking…" : connected ? "Connected" : "Not connected"}</span><span className="ait-settings-drawer-muted">{workspace.browserStatus?.endpoint || "Local bridge"}</span></div>
        {workspace.browserStatus?.last_title ? <p className="ait-settings-drawer-detail">Last page: {workspace.browserStatus.last_title}</p> : <p className="ait-settings-drawer-detail">Open the AITrans browser extension on a page to begin sending context.</p>}
      </section>
      <section className="ait-settings-drawer-card">
        <div className="ait-settings-drawer-card-heading"><FileText size={18} /><div><h3>Reading behavior</h3><p>These controls decide whether browser selections follow into AITrans automatically.</p></div></div>
        <div className="ait-settings-drawer-toggle-list">
          <SettingsSwitch checked={workspace.followBrowserSelection} label="Follow browser selection" onChange={workspace.setFollowBrowserSelection} />
          <SettingsSwitch checked={workspace.autoTranslateSelection} label="Auto-translate selection" onChange={workspace.setAutoTranslateSelection} />
        </div>
      </section>
    </div>
  )
}

function drawerTitle(drawer: Exclude<SettingsDrawer, null>): string {
  if (drawer === "llm") return "AI model connection"
  if (drawer === "browser") return "Browser integration"
  if (drawer === "research-data") return "Research data"
  return "Advanced controls"
}
