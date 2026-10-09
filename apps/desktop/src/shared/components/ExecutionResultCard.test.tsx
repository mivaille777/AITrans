// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { ExecutionResultCard } from "./ExecutionResultCard"
import type { ExecutionResult } from "../../api/execution-results"

const result: ExecutionResult = {
  sandbox_id: "sb_test", status: "succeeded", exit_code: 0, duration_ms: 123,
  stdout: "<script>bad()</script>", stderr: "", source_file_id: "source",
  output_files: [
    { file_id: "image", relative_path: "heart.png", size_bytes: 100, sha256: "hash" },
    { file_id: "source", relative_path: "heart.py", size_bytes: 100, sha256: "hash" },
  ],
}
const artifactUrl = (id: string, inline = false) => `/verified/${id}${inline ? "?inline=true" : ""}`
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it("uses verified artifact URLs and loads code on demand as plain text", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => '<img src=x onerror="bad()">' })
  vi.stubGlobal("fetch", fetchMock)
  const { container } = render(<ExecutionResultCard result={result} artifactUrl={artifactUrl} />)
  expect(screen.getByRole("img")).toHaveAttribute("src", "/verified/image?inline=true")
  expect(screen.getByRole("link", { name: "下载脚本" })).toHaveAttribute("href", "/verified/source")
  expect(fetchMock).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "查看代码" }))
  await waitFor(() => expect(container.querySelector("code")).toHaveTextContent('<img src=x onerror="bad()">'))
  expect(container.querySelectorAll("img")).toHaveLength(1)
  expect(container.querySelector("script")).toBeNull()
})

it("shows image expiry and failure without claiming successful execution", () => {
  render(<ExecutionResultCard result={{ ...result, status: "failed", exit_code: 1 }} artifactUrl={artifactUrl} />)
  expect(screen.getByText("运行未成功")).toBeInTheDocument()
  fireEvent.error(screen.getByRole("img"))
  expect(screen.getByRole("alert")).toHaveTextContent("可能已过期")
  expect(screen.queryByText("✓ 运行完成")).toBeNull()
})

it("aborts an in-flight code download when the card is removed", () => {
  let signal: AbortSignal | undefined
  vi.stubGlobal("fetch", vi.fn((_url, options) => { signal = options.signal; return new Promise(() => {}) }))
  const view = render(<ExecutionResultCard result={result} artifactUrl={artifactUrl} />)
  fireEvent.click(screen.getByRole("button", { name: "查看代码" }))
  view.unmount()
  expect(signal?.aborted).toBe(true)
})
