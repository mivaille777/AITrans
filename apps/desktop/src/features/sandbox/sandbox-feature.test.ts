import { afterEach, describe, expect, it, vi } from "vitest"

import { resolveSandboxFeatureEnabled } from "./sandbox-feature"

afterEach(() => {
  vi.unstubAllEnvs()
})

describe("sandbox feature flag", () => {
  it("defaults to enabled for frontend development", () => {
    vi.stubEnv("VITE_AITRANS_SANDBOX_ENABLED", "")
    expect(resolveSandboxFeatureEnabled()).toBe(true)
  })

  it("accepts an explicit frontend disable switch", () => {
    vi.stubEnv("VITE_AITRANS_SANDBOX_ENABLED", "false")
    expect(resolveSandboxFeatureEnabled()).toBe(false)
  })

  it("lets the backend runtime value take precedence", () => {
    vi.stubEnv("VITE_AITRANS_SANDBOX_ENABLED", "true")
    expect(resolveSandboxFeatureEnabled(false)).toBe(false)
    expect(resolveSandboxFeatureEnabled(true)).toBe(true)
  })
})
