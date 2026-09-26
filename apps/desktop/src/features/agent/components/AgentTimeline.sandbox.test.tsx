// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { AgentTimeline } from "./AgentTimeline"

function SettingsProbe() {
  const location = useLocation()
  return <pre>{JSON.stringify(location.state)}</pre>
}

describe("AgentTimeline sandbox links", () => {
  it("navigates a python tool result to the matching Sandbox trace", () => {
    render(
      <MemoryRouter initialEntries={["/agent"]}>
        <Routes>
          <Route
            path="/agent"
            element={
              <AgentTimeline
                activities={[
                  {
                    sequence: 1,
                    eventType: "tool_result",
                    label: "python_execute completed",
                    detail: "Tool result returned",
                    tone: "success",
                    payload: {
                      tool_name: "python_execute",
                      duration_ms: 842,
                      data: { sandbox_id: "sb-123" },
                    },
                    toolCallId: "tool-123",
                  },
                ]}
                running={false}
                runId="run-123"
                traceId="trace-123"
                totalDurationMs={842}
              />
            }
          />
          <Route path="/settings" element={<SettingsProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Inspect sandbox" }))

    expect(screen.getByText(/"studio":"sandbox"/)).toBeTruthy()
    expect(screen.getByText(/"sandboxId":"sb-123"/)).toBeTruthy()
  })

  it("does not render the link without a sandbox id", () => {
    render(
      <MemoryRouter>
        <AgentTimeline
          activities={[
            {
              sequence: 1,
              eventType: "tool_result",
              label: "search completed",
              detail: "done",
              tone: "success",
              payload: { tool_name: "search" },
            },
          ]}
          running={false}
          runId="run-1"
          traceId="trace-1"
          totalDurationMs={1}
        />
      </MemoryRouter>,
    )

    expect(screen.queryByRole("button", { name: "Inspect sandbox" })).toBeNull()
  })
})
