import { app } from "electron"
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs"
import path from "node:path"

export type WindowCloseBehavior = "minimize_to_tray" | "exit"

const DEFAULT_CLOSE_BEHAVIOR: WindowCloseBehavior = "exit"
const PREFERENCES_FILE = "window-preferences.json"

export function isWindowCloseBehavior(value: unknown): value is WindowCloseBehavior {
  return value === "minimize_to_tray" || value === "exit"
}

function preferencesPath(): string {
  return path.join(app.getPath("userData"), PREFERENCES_FILE)
}

export function getWindowCloseBehavior(): WindowCloseBehavior {
  try {
    const parsed: unknown = JSON.parse(readFileSync(preferencesPath(), "utf8"))
    if (!parsed || typeof parsed !== "object") return DEFAULT_CLOSE_BEHAVIOR
    const value = (parsed as { close_behavior?: unknown }).close_behavior
    return isWindowCloseBehavior(value) ? value : DEFAULT_CLOSE_BEHAVIOR
  } catch {
    return DEFAULT_CLOSE_BEHAVIOR
  }
}

export function setWindowCloseBehavior(value: unknown): WindowCloseBehavior {
  if (!isWindowCloseBehavior(value)) {
    throw new TypeError("Window close behavior is invalid.")
  }

  const destination = preferencesPath()
  const temporary = destination + ".tmp"
  mkdirSync(path.dirname(destination), { recursive: true })
  writeFileSync(
    temporary,
    JSON.stringify({ schema_version: 1, close_behavior: value }) + "\n",
    "utf8",
  )
  renameSync(temporary, destination)
  return value
}
