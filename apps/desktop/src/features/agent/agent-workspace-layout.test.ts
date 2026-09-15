import { describe, expect, it } from "vitest"

import { agentWorkspaceAreas } from "./agent-workspace-layout"

describe("Stage 9.1 Agent Workspace layout", () => {
  it("defines the four product-level Agent workspace areas in execution order", () => {
    expect(agentWorkspaceAreas.map((area) => area.id)).toEqual([
      "context",
      "execution",
      "tools",
      "result",
    ])
  })

  it("keeps workspace area ids unique and descriptions non-empty", () => {
    const ids = agentWorkspaceAreas.map((area) => area.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(agentWorkspaceAreas.every((area) => area.description.trim().length > 0)).toBe(true)
  })
})
