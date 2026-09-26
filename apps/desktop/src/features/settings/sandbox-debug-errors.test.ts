import { describe, expect, it } from "vitest"

import { sandboxDebugErrorFromCode, sandboxDebugErrorMessage } from "./sandbox-debug-errors"

describe("sandbox debug error sanitization", () => {
  it("maps known backend codes to stable user-facing messages", () => {
    expect(sandboxDebugErrorFromCode("SANDBOX_TIMEOUT", "fallback")).toBe("Sandbox run timed out.")
    expect(sandboxDebugErrorFromCode("SANDBOX_FILE_LIMIT", "fallback")).toBe("Sandbox output limit exceeded.")
    expect(sandboxDebugErrorFromCode("DOCKER_NOT_LINUX", "fallback")).toBe("Sandbox requires a Linux Docker runtime.")
    expect(sandboxDebugErrorFromCode("OOM_KILLED", "fallback")).toBe("Sandbox was terminated for memory use.")
  })

  it("does not surface unknown raw daemon or host-path details", () => {
    const error = new Error("Docker SDK stack trace: C:\\Users\\secret\\project")
    expect(sandboxDebugErrorMessage(error, "Sandbox execution failed.")).toBe("Sandbox execution failed.")
  })
})
