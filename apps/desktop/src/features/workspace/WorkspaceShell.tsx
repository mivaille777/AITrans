import type { ReactNode } from "react"
import { useState } from "react"
import { useLocation } from "react-router-dom"

import type { LlmRuntimeStatus } from "../../api/llm-settings"
import WindowFrame from "../../components/WindowFrame"
import WorkspaceHeader from "../system/WorkspaceHeader"
import WorkspaceSidebar from "./WorkspaceSidebar"
import {
  getWorkspaceRouteMeta,
  workspaceRouteUsesFixedHeight,
} from "./workspace-navigation"

export default function WorkspaceShell({ children, llmStatus }: {
  children: ReactNode
  llmStatus: LlmRuntimeStatus
}) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const location = useLocation()
  const routeMeta = getWorkspaceRouteMeta(location.pathname)
  const fixedHeightRoute = workspaceRouteUsesFixedHeight(location.pathname)

  return (
    <WindowFrame>
      <div className={`ait-app-shell grid h-full min-h-0 grid-rows-[minmax(0,1fr)] overflow-hidden bg-transparent text-slate-950 ${sidebarCollapsed ? "md:grid-cols-[72px_minmax(0,1fr)]" : "md:grid-cols-[240px_minmax(0,1fr)]"}`}>
        <WorkspaceSidebar collapsed={sidebarCollapsed} onToggleCollapsed={() => setSidebarCollapsed((value) => !value)} />

        <div className="min-h-0 min-w-0 overflow-hidden p-3">
          <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[22px] border border-slate-200/70 bg-white shadow-[0_16px_44px_rgba(15,23,42,0.08)]">
            <WorkspaceHeader
              title={routeMeta.label}
              description={routeMeta.description}
              llmStatus={llmStatus}
            />
            <main
              className={`min-h-0 flex-1 workspace-route-enter ${
                fixedHeightRoute
                  ? "overflow-hidden"
                  : "ait-scroll-page overflow-y-auto overflow-x-hidden overscroll-contain"
              }`}
            >
              <div className={fixedHeightRoute ? "h-full min-h-0 overflow-hidden" : "px-4 py-4 lg:px-5 lg:py-5 xl:px-6 xl:py-6"}>
                {children}
              </div>
            </main>
          </div>
        </div>
      </div>
    </WindowFrame>
  )
}
