import type { FormEvent } from "react"
import { ArrowLeftRight, Copy, Download, Sparkles } from "lucide-react"

import AITButton from "../../shared/components/AITButton"
import AITInput from "../../shared/components/AITInput"
import { LanguageSelect } from "../../shared/components/LanguageSelect"
import { sourceLanguages, targetLanguages } from "./languages"
import TranslationProviderSelector from "./TranslationProviderSelector"
import type { TranslationWorkspaceController } from "./useTranslationWorkspace"

export default function TranslationWorkspace({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const selection = workspace.readingSelection
  const providerDisabled =
    workspace.backendState !== "connected" ||
    workspace.providerSwitching ||
    workspace.manualTranslating ||
    workspace.autoTranslating

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    workspace.translateManual()
  }

  async function copyResult() {
    const text = workspace.translation?.translated_text
    if (!text) return
    await navigator.clipboard?.writeText(text)
  }

  function downloadResult() {
    const text = workspace.translation?.translated_text
    if (!text) return
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = "translation.txt"
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="overflow-hidden rounded-[18px] border border-slate-200/70 bg-white shadow-[0_8px_28px_rgba(15,23,42,0.045)]">
      <div className="grid min-h-[560px] xl:grid-cols-2">
        <form className="p-5 lg:p-6 xl:border-r xl:border-slate-200/70" onSubmit={handleSubmit}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400">Source</p>
              <h2 className="mt-2 text-base font-semibold tracking-tight text-slate-950">Text to translate</h2>
              <p className="mt-1 text-xs text-slate-500">Enter text manually or use the latest unified reading selection.</p>
            </div>
            <AITButton variant="secondary" type="button" onClick={workspace.clear}>Clear</AITButton>
          </div>

          <AITInput
            className="mt-4 min-h-60"
            placeholder="Enter text, or select text in a browser, PDF, Word document, or another native app…"
            value={workspace.sourceText}
            onChange={(event) => workspace.updateSourceText(event.target.value)}
          />

          {selection && (
            <div className="mt-3 flex items-center justify-between gap-3 text-[11px] text-slate-500">
              <span className="truncate">Latest reading selection · {selection.text.length} chars · {selection.source_kind || selection.provider}</span>
              {!workspace.followBrowserSelection && (
                <button type="button" className="ait-control-motion shrink-0 rounded-lg px-2 py-1 font-medium text-blue-700 hover:bg-blue-50" onClick={workspace.useLatestSelection}>
                  Use selection
                </button>
              )}
            </div>
          )}

          <div className="mt-4 rounded-[14px] border border-slate-200/70 bg-slate-50/60 p-3">
            <TranslationProviderSelector
              value={workspace.translationProvider}
              switching={workspace.providerSwitching}
              disabled={providerDisabled}
              description="Quick switch for manual and reading translations. The choice is also saved as your default."
              onChange={workspace.setTranslationProvider}
            />
          </div>

          <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-end gap-2">
            <LanguageSelect label="Source language" value={workspace.sourceLanguage} options={sourceLanguages} onChange={workspace.setSourceLanguage} />
            <button type="button" className="ait-control-motion mb-0.5 flex h-10 w-10 items-center justify-center rounded-[11px] border border-slate-200 bg-white text-slate-600 shadow-sm hover:bg-slate-50" onClick={workspace.swapLanguages} title="Swap languages">
              <ArrowLeftRight size={15} />
            </button>
            <LanguageSelect label="Target language" value={workspace.targetLanguage} options={targetLanguages} onChange={workspace.setTargetLanguage} />
          </div>

          {workspace.translationError && <p className="mt-4 rounded-[12px] border border-rose-100 bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700">{workspace.translationError}</p>}

          <AITButton
            className="mt-5 w-full"
            variant="primary"
            type="submit"
            disabled={workspace.backendState !== "connected" || workspace.manualTranslating || workspace.providerSwitching}
          >
            <Sparkles size={14} />
            {workspace.manualTranslating ? "Translating…" : "Translate"}
          </AITButton>
        </form>

        <section className="flex min-h-0 flex-col bg-slate-50/35 p-5 lg:p-6">
          <div>
            <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400">Translation</p>
            <h2 className="mt-2 text-base font-semibold tracking-tight text-slate-950">Result</h2>
          </div>
          <div className="mt-4 flex min-h-[420px] flex-1 flex-col overflow-hidden rounded-[15px] border border-slate-200/70 bg-white">
            <div className="ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-contain p-5">
              {workspace.translation ? (
                <p className="whitespace-pre-wrap text-sm leading-7 text-slate-900">{workspace.translation.translated_text}</p>
              ) : (
                <p className="text-sm leading-6 text-slate-400">{workspace.autoTranslating ? "The current reading selection is being translated…" : "The translated text will appear here after the backend completes the request."}</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2 border-t border-slate-100 px-3 py-2.5">
              <button type="button" disabled={!workspace.translation} onClick={() => void copyResult()} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-35">
                <Copy size={13} /> Copy
              </button>
              <button type="button" disabled={!workspace.translation} onClick={downloadResult} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-35">
                <Download size={13} /> Download
              </button>
            </div>
          </div>
        </section>
      </div>
    </section>
  )
}
