import OverlayPreferencesPanel from "../../components/OverlayPreferencesPanel"
import TranslationProviderSelector from "../translation/TranslationProviderSelector"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { LocalModelManager } from "./LocalModelManager"
import { LlmProviderSettings } from "./LlmProviderSettings"

export default function SettingsWorkspace({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const providerDisabled =
    workspace.backendState !== "connected" ||
    workspace.providerSwitching ||
    workspace.manualTranslating ||
    workspace.autoTranslating

  return (
    <div className="mx-auto max-w-[1180px] overflow-hidden rounded-[18px] border border-slate-200/70 bg-white shadow-[0_8px_28px_rgba(15,23,42,0.04)]">
      <section className="px-6 py-6 lg:px-8">
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

      <div className="border-t border-slate-200/70 px-6 py-6 lg:px-8">
        <LlmProviderSettings />
      </div>

      <div className="border-t border-slate-200/70 px-6 py-6 lg:px-8">
        <LocalModelManager />
      </div>

      <div className="border-t border-slate-200/70 px-6 py-6 lg:px-8">
        <OverlayPreferencesPanel />
      </div>
    </div>
  )
}
