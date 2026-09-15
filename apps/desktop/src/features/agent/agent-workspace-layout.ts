export const agentWorkspaceAreas = [
  {
    id: "context",
    label: "Context",
    description: "See the reading selection and source identity the Agent is grounded on.",
  },
  {
    id: "execution",
    label: "Execution",
    description: "Follow planning and runtime progress without hiding the current run state.",
  },
  {
    id: "tools",
    label: "Tools",
    description: "Inspect tool activity, confirmation boundaries, retries, and fallbacks.",
  },
  {
    id: "result",
    label: "Result",
    description: "Review the final Agent response together with run and trace metadata.",
  },
] as const

export type AgentWorkspaceArea = (typeof agentWorkspaceAreas)[number]
