function parseBooleanFlag(value: string | undefined): boolean | undefined {
  if (value === undefined || value.trim() === "") return undefined
  const normalized = value.trim().toLowerCase()
  if (["1", "true", "yes", "on", "enabled"].includes(normalized)) return true
  if (["0", "false", "no", "off", "disabled"].includes(normalized)) return false
  return undefined
}

export function resolveSandboxFeatureEnabled(runtimeEnabled?: boolean): boolean {
  if (typeof runtimeEnabled === "boolean") return runtimeEnabled
  return parseBooleanFlag(import.meta.env.VITE_AITRANS_SANDBOX_ENABLED) ?? true
}
