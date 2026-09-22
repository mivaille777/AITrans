import { lazy, Suspense, useEffect, useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { Navigate, useLocation } from "react-router-dom"

import AgentWorkspace from "./features/agent/AgentWorkspace"
import CompanionHandoffNavigator from "./features/companion/CompanionHandoffNavigator"
import BrowserReadingContextPanel from "./features/reading/BrowserReadingContextPanel"
import TranslationWorkspace from "./features/translation/TranslationWorkspace"
import { useTranslationWorkspace } from "./features/translation/useTranslationWorkspace"
import WorkspaceShell from "./features/workspace/WorkspaceShell"
import { type WorkspaceRoutePath, workspaceRouteUsesFixedHeight } from "./features/workspace/workspace-navigation"
import WorkspaceRouteBoundary from "./shared/errors/WorkspaceRouteBoundary"
import { getLlmRuntimeStatus, type LlmRuntimeStatus } from "./api/llm-settings"
import { queryKeys, queryPolling } from "./shared/query/query-keys"

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

type CachedWorkspaceRoutePath = Exclude<WorkspaceRoutePath, "/chat">

const CACHED_WORKSPACE_PATHS: readonly CachedWorkspaceRoutePath[] = [
  "/translation",
  "/reading",
  "/agent",
  "/knowledge",
  "/research",
  "/settings",
]

function isCachedWorkspacePath(pathname: string): pathname is CachedWorkspaceRoutePath {
  return CACHED_WORKSPACE_PATHS.includes(pathname as CachedWorkspaceRoutePath)
}

function renderCachedWorkspaceRoute(
  path: CachedWorkspaceRoutePath,
  workspace: ReturnType<typeof useTranslationWorkspace>,
): ReactNode {
  if (path === "/translation") {
    return (
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
    )
  }
  if (path === "/reading") return <ReadingWorkspace workspace={workspace} />
  if (path === "/agent") return <AgentWorkspace workspace={workspace} />
  if (path === "/knowledge") {
    return <KnowledgeRoute backendState={workspace.backendState} workspace={workspace} />
  }
  if (path === "/research") {
    return <ResearchRoute backendState={workspace.backendState} workspace={workspace} />
  }
  return <SettingsWorkspace workspace={workspace} />
}

function WorkspaceRouteCache({
  activePath,
  fixedHeight,
  workspace,
}: {
  activePath: CachedWorkspaceRoutePath | null
  fixedHeight: boolean
  workspace: ReturnType<typeof useTranslationWorkspace>
}) {
  const [visitedPaths, setVisitedPaths] = useState<Set<CachedWorkspaceRoutePath>>(
    () => (activePath ? new Set([activePath]) : new Set()),
  )

  /* oxlint-disable react/set-state-in-effect -- remember visited routes after router navigation so their local state survives */
  useEffect(() => {
    if (!activePath) return
    setVisitedPaths((current) => {
      if (current.has(activePath)) return current
      return new Set(current).add(activePath)
    })
  }, [activePath])
  /* oxlint-enable react/set-state-in-effect */

  return (
    <div className={fixedHeight ? "h-full min-h-0" : "min-h-0"}>
      {CACHED_WORKSPACE_PATHS.map((path) => {
        const visible = path === activePath
        if (!visible && !visitedPaths.has(path)) return null
        return (
          <div
            key={path}
            className={visible
              ? `${fixedHeight ? "h-full min-h-0 " : ""}workspace-route-enter`
              : "hidden"}
            aria-hidden={!visible}
            data-workspace-route={path}
          >
            <WorkspaceRouteBoundary>
              <Suspense fallback={<WorkspaceRouteFallback />}>
                {renderCachedWorkspaceRoute(path, workspace)}
              </Suspense>
            </WorkspaceRouteBoundary>
          </div>
        )
      })}
    </div>
  )
}

function App() {
  const workspace = useTranslationWorkspace()
  const location = useLocation()
  const [chatMounted, setChatMounted] = useState(() => location.pathname === "/chat")
  const showingChat = location.pathname === "/chat"
  const activeCachedPath = isCachedWorkspacePath(location.pathname) ? location.pathname : null

  /* oxlint-disable react/set-state-in-effect -- remember the first Chat mount so its active stream survives route changes */
  useEffect(() => {
    if (showingChat) setChatMounted(true)
  }, [showingChat])
  /* oxlint-enable react/set-state-in-effect */

  const llmStatusQuery = useQuery({
    queryKey: queryKeys.llm.status,
    queryFn: getLlmRuntimeStatus,
    enabled: workspace.backendState === "connected",
    refetchInterval: queryPolling.llmStatus,
    retry: 0,
  })
  const unavailableStatus: LlmRuntimeStatus = {
    state: "unavailable",
    provider: "",
    model: "",
    detail: workspace.backendState === "offline"
      ? "Backend is unavailable."
      : "Checking the configured LLM API…",
    active_requests: 0,
  }
  const llmStatus = llmStatusQuery.isError
    ? { ...unavailableStatus, detail: "Unable to read LLM status." }
    : llmStatusQuery.data ?? unavailableStatus

  return (
    <WorkspaceShell
      llmStatus={llmStatus}
    >
      <CompanionHandoffNavigator />
      {(showingChat || chatMounted) && (
        <div
          className={showingChat ? "h-full min-h-0 overflow-hidden" : "hidden"}
          aria-hidden={!showingChat}
        >
          <Suspense fallback={<WorkspaceRouteFallback />}>
            <CompanionWorkspaceV2 />
          </Suspense>
        </div>
      )}
      <WorkspaceRouteCache
        activePath={showingChat ? null : activeCachedPath}
        fixedHeight={workspaceRouteUsesFixedHeight(location.pathname)}
        workspace={workspace}
      />
      {showingChat === false && activeCachedPath === null && <Navigate to="/chat" replace />}
    </WorkspaceShell>
  )
}

export default App
