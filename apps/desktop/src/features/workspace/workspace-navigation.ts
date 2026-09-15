export type WorkspaceRoutePath =
  | "/translation"
  | "/reading"
  | "/chat"
  | "/agent"
  | "/knowledge"
  | "/research"
  | "/settings"

export interface WorkspaceRouteMeta {
  path: WorkspaceRoutePath
  label: string
  description: string
}

export const workspaceRoutes: readonly WorkspaceRouteMeta[] = [
  {
    path: "/chat",
    label: "AI Chat",
    description: "Continue reasoning from a frozen reading or research context.",
  },
  {
    path: "/agent",
    label: "Agent Workspace",
    description: "Run Agent tasks with visible context, execution trace, tool activity, and results.",
  },
  {
    path: "/reading",
    label: "Reading",
    description: "Inspect the active selection, document identity, section, and nearby context.",
  },
  {
    path: "/research",
    label: "Research",
    description: "Browse saved reading evidence and reopen it as chat context.",
  },
  {
    path: "/knowledge",
    label: "Knowledge",
    description: "Import local documents and manage their retrieval index.",
  },
  {
    path: "/translation",
    label: "Translation",
    description: "Translate manual input or the latest reading selection.",
  },
  {
    path: "/settings",
    label: "Settings",
    description: "Configure native overlay placement and interaction behavior.",
  },
] as const

const fallbackRoute = workspaceRoutes[0]

export function getWorkspaceRouteMeta(pathname: string): WorkspaceRouteMeta {
  return workspaceRoutes.find((route) => route.path === pathname) ?? fallbackRoute
}

/**
 * Routes that own their internal scroll containers instead of letting the
 * workspace <main> element scroll the whole page.
 */
export function workspaceRouteUsesFixedHeight(pathname: string): boolean {
  return pathname === "/chat"
}
