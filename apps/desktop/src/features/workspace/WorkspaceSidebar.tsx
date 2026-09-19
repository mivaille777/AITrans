import {
  Bot,
  BookOpen,
  ChevronDown,
  CircleHelp,
  FileText,
  LayoutGrid,
  Library,
  MessageCircle,
  NotebookTabs,
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
} from "lucide-react"
import { NavLink } from "react-router-dom"

import type { WorkspaceRoutePath } from "./workspace-navigation"
import { workspaceSidebarRoutes } from "./workspace-navigation"

const icons: Record<WorkspaceRoutePath, typeof MessageCircle> = {
  "/chat": MessageCircle,
  "/agent": Bot,
  "/reading": BookOpen,
  "/research": NotebookTabs,
  "/knowledge": Library,
  "/translation": FileText,
  "/settings": Settings2,
}

const recentResearch = [
  "Global AI Governance",
  "Climate Change Policy",
  "Multilingual Education",
]

export default function WorkspaceSidebar({
  collapsed,
  onToggleCollapsed,
}: {
  collapsed: boolean
  onToggleCollapsed: () => void
}) {
  if (collapsed) {
    return (
      <aside className="ait-global-nav min-h-0 overflow-hidden p-3">
        <div className="ait-sidebar ait-sidebar-collapsed flex h-full min-h-0 flex-col overflow-hidden rounded-[18px]">
          <header className="ait-sidebar-collapsed-header shrink-0">
            <span className="ait-sidebar-monogram" aria-label="AITrans">A</span>
            <button
              type="button"
              className="ait-sidebar-toggle"
              onClick={onToggleCollapsed}
              aria-label="Expand sidebar"
              title="Expand sidebar"
            >
              <PanelLeftOpen size={17} strokeWidth={1.7} aria-hidden="true" />
            </button>
          </header>

          <nav className="ait-scroll-dark min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-3" aria-label="Workspace navigation">
            <div className="flex min-h-max flex-col items-center gap-1">
              {workspaceSidebarRoutes.map((route) => {
                const Icon = icons[route.path]
                return (
                  <NavLink
                    key={route.path}
                    to={route.path}
                    className={({ isActive }) => `ait-sidebar-item ait-sidebar-item-collapsed${isActive ? " is-active" : ""}`}
                    aria-label={route.sidebarLabel ?? route.label}
                    title={route.sidebarLabel ?? route.label}
                  >
                    <Icon className="ait-sidebar-item-icon" size={17} strokeWidth={1.7} aria-hidden="true" />
                  </NavLink>
                )
              })}
            </div>
          </nav>

          <footer className="shrink-0 px-3 pb-4 pt-2">
            <div className="ait-sidebar-footer-divider" />
            <div className="space-y-1 pt-2">
              <NavLink
                to="/settings"
                className={({ isActive }) => `ait-sidebar-item ait-sidebar-item-collapsed${isActive ? " is-active" : ""}`}
                aria-label="Settings"
                title="Settings"
              >
                <Settings2 className="ait-sidebar-item-icon" size={17} strokeWidth={1.7} aria-hidden="true" />
              </NavLink>
              <span className="ait-sidebar-item ait-sidebar-item-collapsed" role="note" aria-label="Help" title="Help">
                <CircleHelp className="ait-sidebar-item-icon" size={17} strokeWidth={1.7} aria-hidden="true" />
              </span>
            </div>
            <div className="ait-sidebar-local-status ait-sidebar-local-status-collapsed" title="Local-first · All data stays on this device">
              <span className="ait-sidebar-local-dot" aria-hidden="true" />
            </div>
          </footer>
        </div>
      </aside>
    )
  }

  return (
    <aside className="ait-global-nav min-h-0 overflow-hidden p-3 pr-0">
      <div className="ait-sidebar flex h-full min-h-0 flex-col overflow-hidden rounded-[18px]">
        <header className="shrink-0 px-4 pb-4 pt-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="ait-sidebar-wordmark">AITrans</p>
              <p className="ait-sidebar-tagline">Think deeper. Keep it yours.</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="ait-sidebar-brand-icon" aria-hidden="true">
                <LayoutGrid size={16} strokeWidth={1.7} />
              </span>
              <button
                type="button"
                className="ait-sidebar-toggle"
                onClick={onToggleCollapsed}
                aria-label="Collapse sidebar"
                title="Collapse sidebar"
              >
                <PanelLeftClose size={17} strokeWidth={1.7} aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="ait-sidebar-workspace" aria-label="Current workspace">
            <span className="ait-sidebar-workspace-mark" aria-hidden="true">M</span>
            <span className="min-w-0 flex-1 truncate">My Workspace</span>
            <ChevronDown size={14} strokeWidth={1.8} aria-hidden="true" />
          </div>
        </header>

        <nav className="ait-scroll-dark min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-3" aria-label="Workspace navigation">
          <div className="flex min-h-max flex-col gap-1">
            {workspaceSidebarRoutes.map((route) => {
              const Icon = icons[route.path]
              return (
                <NavLink
                  key={route.path}
                  to={route.path}
                  className={({ isActive }) => `ait-sidebar-item${isActive ? " is-active" : ""}`}
                >
                  <Icon className="ait-sidebar-item-icon" size={17} strokeWidth={1.7} aria-hidden="true" />
                  <span className="truncate">{route.sidebarLabel ?? route.label}</span>
                </NavLink>
              )
            })}
          </div>

          <section className="ait-sidebar-recent" aria-label="Recent research">
            <p className="ait-sidebar-section-label">Recent research</p>
            <div className="space-y-0.5">
              {recentResearch.map((item) => (
                <NavLink key={item} to="/research" className="ait-sidebar-recent-item">
                  <FileText size={14} strokeWidth={1.7} aria-hidden="true" />
                  <span className="truncate">{item}</span>
                </NavLink>
              ))}
            </div>
            <NavLink to="/research" className="ait-sidebar-more">
              <span>Show more</span>
              <ChevronDown size={13} strokeWidth={1.8} aria-hidden="true" />
            </NavLink>
          </section>
        </nav>

        <footer className="shrink-0 px-3 pb-4 pt-2">
          <div className="ait-sidebar-footer-divider" />
          <div className="space-y-1 pt-2">
            <NavLink
              to="/settings"
              className={({ isActive }) => `ait-sidebar-item${isActive ? " is-active" : ""}`}
            >
              <Settings2 className="ait-sidebar-item-icon" size={17} strokeWidth={1.7} aria-hidden="true" />
              <span>Settings</span>
            </NavLink>
            <span className="ait-sidebar-item" role="note">
              <CircleHelp className="ait-sidebar-item-icon" size={17} strokeWidth={1.7} aria-hidden="true" />
              <span>Help</span>
            </span>
          </div>

          <div className="ait-sidebar-local-status">
            <span className="ait-sidebar-local-dot" aria-hidden="true" />
            <span>Local-first · All data stays on this device</span>
          </div>
        </footer>
      </div>
    </aside>
  )
}
