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
  const readingRoute = location.pathname === "/reading"
  const settingsRoute = location.pathname === "/settings"
  const defaultHeaderRoute = !readingRoute && !settingsRoute && location.pathname !== "/research" && location.pathname !== "/knowledge"
  const fixedHeightRoute = workspaceRouteUsesFixedHeight(location.pathname)
  const shellColumns = sidebarCollapsed
    ? "grid-cols-1 md:grid-cols-[72px_minmax(0,1fr)]"
    : "grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)]"
  const toggleSidebar = () => setSidebarCollapsed((value) => !value)

  return (
    <WindowFrame>
      <div className={`ait-app-shell${settingsRoute ? " ait-settings-shell" : ""} grid h-full min-h-0 grid-rows-[minmax(0,1fr)] overflow-hidden bg-transparent text-slate-950 ${shellColumns}`}>
        <WorkspaceSidebar collapsed={sidebarCollapsed} onToggleCollapsed={toggleSidebar} />

        <div className={`min-h-0 min-w-0 overflow-hidden ${settingsRoute ? "bg-white" : readingRoute ? "p-3 pl-0" : "p-3"}`}>
          <div className={settingsRoute
            ? "h-full min-h-0"
            : readingRoute
              ? "h-full min-h-0 overflow-hidden rounded-[22px] border border-slate-200/70 bg-white shadow-[0_16px_44px_rgba(15,23,42,0.08)]"
              : "flex h-full min-h-0 flex-col overflow-hidden rounded-[22px] border border-slate-200/70 bg-white shadow-[0_16px_44px_rgba(15,23,42,0.08)]"}
          >
            <div className={defaultHeaderRoute ? "block" : "hidden"}>
              {defaultHeaderRoute ? (
              <WorkspaceHeader
                title={routeMeta.label}
                description={routeMeta.description}
                llmStatus={llmStatus}
              />
              ) : null}
            </div>
            <main
              className={settingsRoute || readingRoute
                ? "h-full min-h-0 overflow-hidden"
                : `min-h-0 flex-1 workspace-route-enter ${fixedHeightRoute
                    ? "overflow-hidden"
                    : "ait-scroll-page overflow-y-auto overflow-x-hidden overscroll-contain"}`}
            >
              <div className={settingsRoute || readingRoute
                ? "h-full min-h-0"
                : fixedHeightRoute
                  ? "h-full min-h-0 overflow-hidden"
                  : "px-4 py-4 lg:px-5 lg:py-5 xl:px-6 xl:py-6"}
              >
                {children}
              </div>
            </main>
          </div>
        </div>
      </div>
    </WindowFrame>
  )
}
