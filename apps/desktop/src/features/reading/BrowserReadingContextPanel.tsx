import type { ReadingSelection } from "../../api/reading"
import type {
  BrowserBridgeStatusResponse,
  BrowserPage,
} from "../../api/types"
import { Toggle } from "../../shared/components/Toggle"

type BrowserReadingContextPanelProps = {
  browserStatus: BrowserBridgeStatusResponse | undefined
  browserPage: BrowserPage | null
  readingSelection: ReadingSelection | null
  followBrowserSelection: boolean
  autoTranslateSelection: boolean
  autoTranslating: boolean
  onFollowBrowserSelectionChange: (checked: boolean) => void
  onAutoTranslateSelectionChange: (checked: boolean) => void
}

export default function BrowserReadingContextPanel(props: BrowserReadingContextPanelProps) {
  const {
    browserStatus,
    browserPage,
    readingSelection,
    followBrowserSelection,
    onFollowBrowserSelectionChange,
  } = props
  const isBrowserSelection = readingSelection?.source_kind === "browser"
  const title =
    readingSelection?.resource_title ||
    (isBrowserSelection ? browserPage?.title : "") ||
    "Waiting for a reading selection…"
  const heading =
    readingSelection?.section_heading ||
    (isBrowserSelection ? browserPage?.heading : "") ||
    ""
  const captureLabel = readingSelection
    ? `${readingSelection.source_kind || "reading"} · ${readingSelection.provider}`
    : browserStatus?.has_extension_activity
      ? "Browser DOM bridge ready · native readers available"
      : "Waiting for Browser DOM / PDF UIA / Word / Desktop UIA"

  return (
    <section className="rounded-[16px] border border-slate-200/70 bg-white px-4 py-3 shadow-[0_6px_20px_rgba(15,23,42,0.035)]">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <span
              className={`h-2 w-2 rounded-full ${
                readingSelection || browserStatus?.has_extension_activity
                  ? "bg-emerald-500"
                  : "bg-slate-300"
              }`}
            />
            <h2 className="text-xs font-semibold tracking-tight text-slate-900">Unified Reading Context</h2>
            {readingSelection && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-slate-500">
                {readingSelection.source_kind || "reading"}
              </span>
            )}
          </div>
          <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <p className="max-w-[520px] truncate text-xs text-slate-600">{title}</p>
            {heading && <span className="text-[10px] text-slate-400">§ {heading}</span>}
            <span className="text-[9px] font-medium uppercase tracking-[0.1em] text-slate-400">{captureLabel}</span>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Toggle
            label="Follow selection"
            checked={followBrowserSelection}
            onChange={onFollowBrowserSelectionChange}
          />
          <span className="rounded-full border border-cyan-200/70 bg-cyan-50 px-3 py-1.5 text-[10px] font-medium text-cyan-700">
            Assistant-first overlay
          </span>
        </div>
      </div>
    </section>
  )
}
