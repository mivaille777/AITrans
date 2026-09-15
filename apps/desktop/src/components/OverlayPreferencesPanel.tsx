import { useEffect, useState } from "react"

import { desktop } from "../desktop"
import { applyOverlayNativeVisualTheme } from "../desktop/overlay-native-theme"
import type { OverlayPositionMode } from "../desktop"
import {
  readOverlayPreferences,
  subscribeOverlayPreferences,
  updateOverlayPreferences,
  type OverlayPreferences,
} from "../desktop/overlay-preferences"

const positionOptions: Array<[OverlayPositionMode, string]> = [
  ["mouse_follow", "Near cursor"],
  ["custom_fixed_position", "Fixed position"],
  ["desktop_lyrics_top", "Screen top"],
  ["desktop_lyrics_center", "Screen center"],
  ["desktop_lyrics_bottom", "Screen bottom"],
]

export default function OverlayPreferencesPanel() {
  const [preferences, setPreferences] = useState(readOverlayPreferences)

  useEffect(() => subscribeOverlayPreferences(setPreferences), [])

  async function apply(patch: Partial<OverlayPreferences>) {
    const next = updateOverlayPreferences(patch)
    setPreferences(next)

    if ("alwaysOnTop" in patch) {
      await desktop.overlay.setAlwaysOnTop(next.alwaysOnTop)
    }
    if ("clickThrough" in patch) {
      await desktop.overlay.setClickThrough(next.clickThrough)
    }
    if ("theme" in patch) {
      await applyOverlayNativeVisualTheme(next.theme).catch(() => undefined)
    }
    if ("positionMode" in patch || "customPosition" in patch) {
      await desktop.overlay.place(next.positionMode, next.customPosition)
    }
  }

  async function toggleLock(locked: boolean) {
    if (!locked) {
      await apply({ locked: false })
      return
    }

    const position = await desktop.overlay.getPosition()
    if (!position) {
      await apply({ locked: true })
      return
    }

    await apply({
      locked: true,
      positionMode: "custom_fixed_position",
      customPosition: position,
    })
  }

  async function resetInteraction() {
    const next = updateOverlayPreferences({
      positionMode: "mouse_follow",
      locked: false,
      clickThrough: false,
      smartAutoDismiss: true,
    })
    setPreferences(next)
    await desktop.overlay.setClickThrough(false)
    await desktop.overlay.setAlwaysOnTop(next.alwaysOnTop)
    await desktop.overlay.place(next.positionMode, next.customPosition)
  }

  return (
    <section className="ait-surface overflow-hidden">
      <div className="p-6 lg:p-7">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Native Overlay
            </p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">Placement and interaction</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
              Tune where the overlay appears, how it behaves, and whether it uses the light Liquid Glass or classic dark appearance.
            </p>
          </div>

          <button
            type="button"
            className="ait-control-motion rounded-[14px] border border-slate-200/80 bg-white px-3.5 py-2.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            onClick={() => void resetInteraction()}
          >
            Reset near cursor
          </button>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-[1.35fr_repeat(4,1fr)]">
          <label className="grid gap-2 rounded-[18px] border border-slate-200/60 bg-slate-50/70 p-4 text-xs font-medium text-slate-600">
            <span className="flex items-center justify-between gap-2">
              Position mode
              {preferences.locked && <span className="text-[10px] font-normal text-slate-400">Unlock to change</span>}
            </span>
            <select
              className="rounded-[13px] border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-slate-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
              value={preferences.positionMode}
              disabled={preferences.locked}
              onChange={(event) => void apply({ positionMode: event.target.value as OverlayPositionMode })}
            >
              {positionOptions.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>

          <label className="grid gap-2 rounded-[18px] border border-slate-200/60 bg-slate-50/70 p-4 text-xs font-medium text-slate-600">
            <span>Appearance</span>
            <select
              className="rounded-[13px] border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-slate-400"
              value={preferences.theme}
              onChange={(event) => void apply({ theme: event.target.value as OverlayPreferences["theme"] })}
            >
              <option value="light">Light · Liquid Glass</option>
              <option value="dark">Dark · Classic</option>
            </select>
          </label>

          <PreferenceToggle
            label="Always on top"
            description="Keep the overlay above normal windows."
            checked={preferences.alwaysOnTop}
            onChange={(checked) => void apply({ alwaysOnTop: checked })}
          />
          <PreferenceToggle
            label="Lock position"
            description="Freeze the overlay at its current location."
            checked={preferences.locked}
            onChange={(checked) => void toggleLock(checked)}
          />
          <PreferenceToggle
            label="Click-through"
            description="Let pointer input pass through the overlay."
            checked={preferences.clickThrough}
            onChange={(checked) => void apply({ clickThrough: checked })}
            warning={preferences.clickThrough}
          />
          <PreferenceToggle
            label="Smart dismiss"
            description="Close after explicit completed actions such as copy or AI Chat handoff; never on idle reading."
            checked={preferences.smartAutoDismiss}
            onChange={(checked) => void apply({ smartAutoDismiss: checked })}
          />
        </div>

        {preferences.clickThrough && (
          <p className="mt-4 rounded-[15px] border border-amber-200/70 bg-amber-50 px-3.5 py-2.5 text-xs leading-5 text-amber-800">
            Click-through is active. The overlay ignores pointer input; disable it here to regain interaction.
          </p>
        )}
      </div>
    </section>
  )
}

function PreferenceToggle({
  label,
  description,
  checked,
  onChange,
  warning = false,
}: {
  label: string
  description: string
  checked: boolean
  onChange: (checked: boolean) => void
  warning?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`ait-control-motion flex min-h-[104px] flex-col items-start justify-between rounded-[18px] border p-4 text-left ${
        warning
          ? "border-amber-200 bg-amber-50 text-amber-950"
          : "border-slate-200/60 bg-slate-50/70 text-slate-700 hover:bg-white"
      }`}
      onClick={() => onChange(!checked)}
    >
      <span className="flex w-full items-center justify-between gap-3">
        <span className="text-sm font-semibold">{label}</span>
        <span
          aria-hidden="true"
          className={`relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200 ${
            checked ? (warning ? "bg-amber-500" : "bg-slate-900") : "bg-slate-300"
          }`}
        >
          <span
            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ease-out ${
              checked ? "translate-x-[18px]" : "translate-x-0.5"
            }`}
          />
        </span>
      </span>
      <span className={`mt-3 text-xs leading-5 ${warning ? "text-amber-800" : "text-slate-500"}`}>
        {description}
      </span>
    </button>
  )
}
