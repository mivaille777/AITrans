import { lazy, Suspense } from "react"
import { Navigate, Route, Routes, useLocation } from "react-router-dom"

import AgentWorkspace from "./features/agent/AgentWorkspace"
import CompanionHandoffNavigator from "./features/companion/CompanionHandoffNavigator"
import BrowserReadingContextPanel from "./features/reading/BrowserReadingContextPanel"
import TranslationWorkspace from "./features/translation/TranslationWorkspace"
import { useTranslationWorkspace } from "./features/translation/useTranslationWorkspace"
import WorkspaceShell from "./features/workspace/WorkspaceShell"
import { workspaceRouteUsesFixedHeight } from "./features/workspace/workspace-navigation"
import WorkspaceRouteBoundary from "./shared/errors/WorkspaceRouteBoundary"

const ReadingWorkspace = lazy(() => import("./features/reading/ReadingWorkspace"))
const CompanionWorkspaceV2 = lazy(() => import("./features/companion/CompanionWorkspaceV2"))
const ResearchRoute = lazy(() => import("./features/research/ResearchRoute"))
const KnowledgeRoute = lazy(() => import("./features/knowledge/KnowledgeRoute"))
const SettingsWorkspace = lazy(() => import("./features/settings/SettingsWorkspace"))

function WorkspaceRouteFallback() {
  return (
    <section className="ait-surface overflow-hidden p-7" aria-busy="true" aria-label="Loading workspace">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-spin rounded-full border border-slate-300 border-t-slate-700" />
        Loading workspace…
      </div>
      <div className="mt-6 grid gap-3 lg:grid-cols-3">
        <div className="ait-skeleton h-44 rounded-[18px]" />
        <div className="ait-skeleton h-44 rounded-[18px]" />
        <div className="ait-skeleton h-44 rounded-[18px]" />
      </div>
    </section>
  )
}

function App() {
  const workspace = useTranslationWorkspace()
  const location = useLocation()
  const fixedHeightRoute = workspaceRouteUsesFixedHeight(location.pathname)

  return (
    <WorkspaceShell
      backendState={workspace.backendState}
      backendService={workspace.backendService}
      providerName={workspace.providerName}
      browserStatus={workspace.browserStatus}
      browserStatusChecking={workspace.browserStatusChecking}
    >
      <CompanionHandoffNavigator />
      <div
        key={location.pathname}
        className={`workspace-route-enter ${fixedHeightRoute ? "h-full min-h-0" : ""}`}
      >
        <WorkspaceRouteBoundary>
          <Suspense fallback={<WorkspaceRouteFallback />}>
            <Routes>
              <Route path="/" element={<Navigate to="/chat" replace />} />
              <Route
                path="/translation"
                element={(
                  <div className="space-y-4">
                    <BrowserReadingContextPanel
                      browserStatus={workspace.browserStatus}
                      readingSelection={workspace.readingSelection}
                      browserPage={workspace.browserPage}
                      followBrowserSelection={workspace.followBrowserSelection}
                      autoTranslateSelection={workspace.autoTranslateSelection}
                      autoTranslating={workspace.autoTranslating}
                      onFollowBrowserSelectionChange={workspace.setFollowBrowserSelection}
                      onAutoTranslateSelectionChange={workspace.setAutoTranslateSelection}
                    />
                    <TranslationWorkspace workspace={workspace} />
                  </div>
                )}
              />
              <Route path="/reading" element={<ReadingWorkspace workspace={workspace} />} />
              <Route path="/chat" element={<CompanionWorkspaceV2 />} />
              <Route path="/agent" element={<AgentWorkspace workspace={workspace} />} />
              <Route path="/knowledge" element={<KnowledgeRoute backendState={workspace.backendState} workspace={workspace} />} />
              <Route
                path="/research"
                element={<ResearchRoute backendState={workspace.backendState} workspace={workspace} />}
              />
              <Route path="/settings" element={<SettingsWorkspace workspace={workspace} />} />
              <Route path="*" element={<Navigate to="/chat" replace />} />
            </Routes>
          </Suspense>
        </WorkspaceRouteBoundary>
      </div>
    </WorkspaceShell>
  )
}

export default App
