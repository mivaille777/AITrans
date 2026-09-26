import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError, apiGet } from "./client"

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("api client errors", () => {
  it("preserves structured backend error codes", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({
        code: "sandbox_timeout",
        message: "Sandbox run timed out.",
      }), {
        status: 408,
        statusText: "Request Timeout",
        headers: { "Content-Type": "application/json" },
      }),
    ))

    await expect(apiGet("/test")).rejects.toMatchObject({
      name: "ApiError",
      status: 408,
      code: "sandbox_timeout",
      message: "Sandbox run timed out.",
    })
  })

  it("supports FastAPI nested detail objects", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({
        detail: {
          code: "sandbox_file_limit",
          message: "Output exceeded limit.",
        },
      }), {
        status: 422,
        statusText: "Unprocessable Entity",
        headers: { "Content-Type": "application/json" },
      }),
    ))

    try {
      await apiGet("/test")
      throw new Error("Expected ApiError")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect(error).toMatchObject({
        status: 422,
        code: "sandbox_file_limit",
        message: "Output exceeded limit.",
      })
    }
  })

  it("keeps legacy string detail responses working", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ detail: "Legacy backend error." }), {
        status: 400,
        statusText: "Bad Request",
        headers: { "Content-Type": "application/json" },
      }),
    ))

    await expect(apiGet("/test")).rejects.toMatchObject({
      status: 400,
      code: "",
      message: "Legacy backend error.",
    })
  })
})
