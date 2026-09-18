import {
  BookOpenText,
  ChevronDown,
  Cpu,
  Database,
  FlaskConical,
  Link2,
  Palette,
  Settings2,
  SlidersHorizontal,
} from "lucide-react"
import { useRef, useState } from "react"

import OverlayPreferencesPanel from "../../components/OverlayPreferencesPanel"
import TranslationProviderSelector from "../translation/TranslationProviderSelector"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { LlmProviderSettings } from "./LlmProviderSettings"
import { LocalModelManager } from "./LocalModelManager"
import RagDebugStudioTrace from "./RagDebugStudioTrace"

type SettingsSection = "general" | "ai-model" | "reading" | "browser" | "appearance" | "research-data"

type NavItem = {
  id: SettingsSection
  label: string
  icon: typeof Settings2
}

const navItems: NavItem[] = [
  { id: "general", label: "General", icon: Settings2 },
  { id: "ai-model", label: "AI model", icon: Cpu },
  { id: "reading", label: "Reading and selection", icon: BookOpenText },
  { id: "browser", label: "Browser integration", icon: Link2 },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "research-data", label: "Research data", icon: Database },
]

export default function SettingsWorkspace({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const [showRagDebug, setShowRagDebug] = useState(false)
  const [activeSection, setActiveSection] = useState<SettingsSection>("general")
  const [advancedExpanded, setAdvancedExpanded] = useState(true)
  const generalRef = useRef<HTMLDivElement>(null)
  const llmRef = useRef<HTMLDivElement>(null)
  const localModelsRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)

  const providerDisabled =
    workspace.backendState !== "connected" ||
    workspace.providerSwitching ||
    workspace.manualTranslating ||
    workspace.autoTranslating

  function openSettingsSection(section: SettingsSection) {
    setShowRagDebug(false)
    setActiveSection(section)

    window.requestAnimationFrame(() => {
      const target = section === "general"
        ? generalRef.current
        : section === "ai-model"
          ? llmRef.current
          : section === "research-data"
            ? localModelsRef.current
            : overlayRef.current
      target?.scrollIntoView({ behavior: "smooth", block: "start" })
    })
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[258px_minmax(0,1fr)] overflow-hidden bg-white">
      <aside className="flex min-h-0 flex-col border-r border-slate-200/80 bg-white">
        <div className="shrink-0 px-6 pb-4 pt-7">
          <h1 className="text-[25px] font-semibold tracking-[-0.035em] text-slate-950">Settings</h1>
          <p className="mt-1.5 text-[12px] leading-5 text-slate-500">Configure AITrans for your workflow.</p>
        </div>

        <nav className="ait-scroll-page min-h-0 flex-1 overflow-y-auto px-4 py-2" aria-label="Settings navigation">
          <div className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon
              const active = !showRagDebug && activeSection === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => openSettingsSection(item.id)}
                  className={`flex w-full items-center gap-3 rounded-[8px] px-3 py-2.5 text-left text-[12px] font-medium transition-all duration-150 ${
                    active
                      ? "bg-slate-100 text-slate-950"
                      : "text-slate-700 hover:bg-slate-50 hover:text-slate-950"
                  }`}
                >
                  <Icon size={16} strokeWidth={1.7} className="shrink-0" aria-hidden="true" />
                  <span className="truncate">{item.label}</span>
                </button>
              )
            })}
          </div>

          <div className="mt-2">
            <button
              type="button"
              onClick={() => setAdvancedExpanded((value) => !value)}
              className="flex w-full items-center gap-3 rounded-[8px] px-3 py-2.5 text-left text-[12px] font-semibold text-slate-800 transition hover:bg-slate-50"
              aria-expanded={advancedExpanded}
            >
              <SlidersHorizontal size={16} strokeWidth={1.7} className="shrink-0" aria-hidden="true" />
              <span className="min-w-0 flex-1">Advanced</span>
              <ChevronDown size={14} strokeWidth={1.8} className={`transition-transform duration-200 ${advancedExpanded ? "rotate-0" : "-rotate-90"}`} aria-hidden="true" />
            </button>

            <div className={`grid transition-[grid-template-rows,opacity] duration-200 ease-out ${advancedExpanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
              <div className="overflow-hidden">
                <button
                  type="button"
                  onClick={() => {
                    setAdvancedExpanded(true)
                    setShowRagDebug(true)
                  }}
                  className={`ml-4 mt-1 flex w-[calc(100%_-_1rem)] items-center gap-2.5 rounded-[8px] px-3 py-2.5 text-left text-[12px] font-medium transition-all duration-150 ${
                    showRagDebug
                      ? "bg-slate-100 text-slate-950"
                      : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
                  }`}
                >
                  <FlaskConical size={15} strokeWidth={1.7} className="shrink-0" aria-hidden="true" />
                  <span>RAG Debug Studio</span>
                </button>
              </div>
            </div>
          </div>
        </nav>

        <div className="shrink-0 border-t border-slate-200/80 px-6 py-4">
          <p className="flex items-center gap-2 text-[10px] text-slate-400">
            <span className="flex h-4 w-4 items-center justify-center rounded-full border border-slate-300 text-[9px]">?</span>
            Changes save as you make them.
          </p>
        </div>
      </aside>

      <div className="min-h-0 min-w-0 overflow-hidden">
        {showRagDebug ? (
          <RagDebugStudioTrace />
        ) : (
          <div className="ait-scroll-page h-full min-h-0 overflow-y-auto px-7 py-7 lg:px-8">
            <div className="mx-auto max-w-[1120px] overflow-hidden rounded-[18px] border border-slate-200/70 bg-white shadow-[0_8px_28px_rgba(15,23,42,0.04)]">
              <section ref={generalRef} className="scroll-mt-6 px-6 py-6 lg:px-8">
                <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,.72fr)] xl:items-center">
                  <div>
                    <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400">Translation</p>
                    <h2 className="mt-2 text-lg font-semibold tracking-tight text-slate-950">Default translation provider</h2>
                    <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
                      Used by manual translation, automatic reading translation, and the native overlay.
                    </p>
                  </div>
                  <div>
                    <TranslationProviderSelector
                      value={workspace.translationProvider}
                      switching={workspace.providerSwitching}
                      disabled={providerDisabled}
                      title="Provider"
                      description="Saved to your user settings and restored when the backend starts again."
                      onChange={workspace.setTranslationProvider}
                    />
                    {workspace.translationError && (
                      <p className="mt-3 rounded-[12px] border border-rose-100 bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700">
                        {workspace.translationError}
                      </p>
                    )}
                  </div>
                </div>
              </section>

              <div ref={llmRef} className="scroll-mt-6 border-t border-slate-200/70 px-6 py-6 lg:px-8">
                <LlmProviderSettings />
              </div>

              <div ref={localModelsRef} className="scroll-mt-6 border-t border-slate-200/70 px-6 py-6 lg:px-8">
                <LocalModelManager />
              </div>

              <div ref={overlayRef} className="scroll-mt-6 border-t border-slate-200/70 px-6 py-6 lg:px-8">
                <OverlayPreferencesPanel />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
