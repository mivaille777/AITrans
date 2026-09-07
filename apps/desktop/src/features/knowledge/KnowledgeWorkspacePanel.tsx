import { BookOpenText, LayoutDashboard, LibraryBig } from "lucide-react"
import { useSearchParams } from "react-router-dom"

import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import KnowledgeBoardPanel from "./KnowledgeBoardPanel"
import KnowledgeLibraryPanel from "./KnowledgeLibraryPanel"
import KnowledgePaperReaderPanel from "./KnowledgePaperReaderPanel"
import type { KnowledgeBoardController } from "./useKnowledgeBoard"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

type KnowledgeView = "board" | "library" | "reader"

export default function KnowledgeWorkspacePanel({
  library,
  board,
  workspace,
}: {
  library: KnowledgeLibraryController
  board: KnowledgeBoardController
  workspace: TranslationWorkspaceController
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedView = searchParams.get("view")
  const paperItemId = searchParams.get("paper") ?? ""
  const view: KnowledgeView = paperItemId && requestedView === "reader"
    ? "reader"
    : searchParams.has("document") || requestedView === "library"
      ? "library"
      : "board"

  function setView(nextView: Exclude<KnowledgeView, "reader">) {
    const next = new URLSearchParams(searchParams)
    next.delete("paper")
    next.delete("document")
    if (nextView === "board") next.delete("view")
    else next.set("view", "library")
    setSearchParams(next, { replace: true })
  }

  function openPaper(itemId: string) {
    const next = new URLSearchParams(searchParams)
    next.set("view", "reader")
    next.set("paper", itemId)
    next.delete("document")
    setSearchParams(next)
  }

  function closeReader() {
    const next = new URLSearchParams(searchParams)
    next.set("view", "library")
    next.delete("paper")
    setSearchParams(next, { replace: true })
  }

  return (
    <div className="space-y-3">
      <nav className="flex items-center gap-1 rounded-[14px] border border-slate-200 bg-white p-1 shadow-sm" aria-label="Knowledge workspace view">
        <button type="button" className={`flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs font-semibold transition ${view === "board" ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`} onClick={() => setView("board")}><LayoutDashboard size={14} />Board</button>
        <button type="button" className={`flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs font-semibold transition ${view === "library" ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`} onClick={() => setView("library")}><LibraryBig size={14} />Library</button>
        {view === "reader" && <button type="button" className="flex items-center gap-2 rounded-[10px] bg-slate-950 px-3 py-2 text-xs font-semibold text-white shadow-sm"><BookOpenText size={14} />Reader</button>}
        <span className="ml-auto hidden pr-2 text-[10px] text-slate-400 sm:inline">{view === "board" ? "Arrange cards and create explicit knowledge relations." : view === "reader" ? "Read structured paper text, capture knowledge, and attach bounded AI context." : "Manage knowledge cards and local document resources."}</span>
      </nav>
      {view === "board" && <KnowledgeBoardPanel library={library} board={board} />}
      {view === "library" && <KnowledgeLibraryPanel library={library} onOpenPaper={openPaper} />}
      {view === "reader" && <KnowledgePaperReaderPanel paperItemId={paperItemId} library={library} workspace={workspace} onBack={closeReader} />}
    </div>
  )
}
