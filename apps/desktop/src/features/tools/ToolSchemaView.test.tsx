// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it } from "vitest"
import { ToolSchemaView } from "./ToolSchemaView"

afterEach(cleanup)
it("renders referenced nested results and retains the full JSON contract", async () => {
  const schema = { type: "object", properties: { results: { type: "array", items: { $ref: "#/$defs/Result" } } }, required: ["results"], $defs: { Result: { type: "object", properties: { score: { type: "number", minimum: 0, maximum: 1 } }, required: ["score"] } } }
  render(<ToolSchemaView schema={schema} title="Output schema" />)
  expect(screen.getByText("results[].score")).toBeTruthy()
  expect(screen.getByText(/minimum: 0 maximum: 1/)).toBeTruthy()
  await userEvent.click(screen.getByRole("button", { name: "JSON" }))
  expect(screen.getByText(/#\/\$defs\/Result/)).toBeTruthy()
})
