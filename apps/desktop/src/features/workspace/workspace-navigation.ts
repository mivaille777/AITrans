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
  sidebarLabel?: string
  description: string
}

export const workspaceRoutes: readonly WorkspaceRouteMeta[] = [
  {
    path: "/chat",
    label: "AI Chat",
    sidebarLabel: "Chat",
    description: "Continue reasoning from a frozen reading or research context.",
  },
  {
    path: "/agent",
    label: "Agent Workspace",
    sidebarLabel: "Agent",
    description: "Run Agent tasks with visible context, execution trace, tool activity, and results.",
  },
  {
    path: "/reading",
    label: "Reading",
    description: "Read indexed papers, inspect live selections, and turn passages into evidence, notes, translations, or AI context.",
  },
  {
    path: "/research",
    label: "Research",
    description: "Browse saved reading evidence and reopen it as chat context.",
  },
  {
    path: "/knowledge",
    label: "Knowledge",
    description: "Organize cards, documents, canvases, graphs, and relations while Reading owns document-reading actions.",
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

const sidebarRouteOrder: readonly WorkspaceRoutePath[] = [
  "/chat",
  "/reading",
  "/research",
  "/knowledge",
  "/agent",
]

export const workspaceSidebarRoutes: readonly WorkspaceRouteMeta[] = sidebarRouteOrder.map((path) => {
  const route = workspaceRoutes.find((candidate) => candidate.path === path)
  if (!route) throw new Error(`Missing workspace sidebar route: ${path}`)
  return route
})

const fallbackRoute = workspaceRoutes[0]

export function getWorkspaceRouteMeta(pathname: string): WorkspaceRouteMeta {
  return workspaceRoutes.find((route) => route.path === pathname) ?? fallbackRoute
}

/**
 * Routes that own their internal scroll containers instead of letting the
 * workspace <main> element scroll the whole page.
 */
export function workspaceRouteUsesFixedHeight(pathname: string): boolean {
  return pathname === "/chat" || pathname === "/research" || pathname === "/knowledge" || pathname === "/settings"
}
