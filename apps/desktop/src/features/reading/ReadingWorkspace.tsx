import { BookOpenText, FileText, LibraryBig, LoaderCircle, Plus } from "lucide-react"
import { useNavigate, useSearchParams } from "react-router-dom"

import KnowledgePaperReaderPanel from "../knowledge/KnowledgePaperReaderPanel"
import { useKnowledgeLibrary } from "../knowledge/useKnowledgeLibrary"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import BrowserReadingContextPanel from "./BrowserReadingContextPanel"
import { resolveReadingPaperId } from "./reading-navigation"

export default function ReadingWorkspace({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const library = useKnowledgeLibrary()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedPaperId = resolveReadingPaperId(searchParams)
  const items = library.itemsQuery.data?.items ?? []
  const documents = library.documentsQuery.data?.documents ?? []
  const indexedDocumentIds = new Set(documents.map((document) => document.document_id))
  const readablePapers = items
    .filter((item) => item.item_type === "paper" && Boolean(item.resource_document_id) && indexedDocumentIds.has(item.resource_document_id as string))
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  const requestedPaper = readablePapers.find((paper) => paper.item_id === requestedPaperId)
  const activePaperId = requestedPaper?.item_id || readablePapers[0]?.item_id || ""
  const loading = library.itemsQuery.isPending || library.documentsQuery.isPending
  const loadError = library.itemsQuery.error ?? library.documentsQuery.error

  if (loading && !activePaperId) {
    return <ReadingLoadingState />
  }

  if (activePaperId) {
    return (
      <KnowledgePaperReaderPanel
        paperItemId={activePaperId}
        library={library}
        workspace={workspace}
        onBack={() => navigate("/knowledge?view=library")}
      />
    )
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[280px_minmax(0,1fr)_360px] overflow-hidden bg-white text-[#252525]">
      <aside className="border-r border-[#e6e6e6] p-4">
        <div className="flex items-center justify-between">
          <h1 className="text-[16px] font-semibold">Recent Documents</h1>
          <button
            type="button"
            aria-label="Add document"
            disabled={library.addMutation.isPending}
            onClick={() => library.addMutation.mutate()}
            className="flex h-9 w-9 items-center justify-center rounded-[9px] border border-[#e4e4e4] hover:bg-[#f6f6f6] disabled:opacity-40"
          >
            {library.addMutation.isPending ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={18} />}
          </button>
        </div>
        <div className="mt-5 border-t border-[#ececec] pt-5">
          <div className="flex items-center gap-3 rounded-[8px] px-3 py-3 text-[#888]">
            <FileText size={18} />
            <span className="text-[12px]">No indexed papers yet</span>
          </div>
        </div>
      </aside>

      <main className="flex min-h-0 flex-col bg-[#fafafa]">
        <div className="flex h-[68px] shrink-0 items-center border-b border-[#e6e6e6] bg-white px-5">
          <div>
            <h2 className="text-[18px] font-semibold">Reading</h2>
            <p className="mt-0.5 text-[11px] text-[#888]">Open an indexed paper to begin</p>
          </div>
        </div>
        <div className="flex min-h-0 flex-1 items-center justify-center p-8">
          <div className="max-w-md rounded-[12px] border border-[#e3e3e3] bg-white p-8 text-center shadow-sm">
            <BookOpenText size={28} className="mx-auto text-[#aaa]" />
            <h3 className="mt-4 text-[15px] font-semibold">No indexed paper is ready to read</h3>
            <p className="mt-2 text-[12px] leading-5 text-[#777]">
              Import a document and create or attach a paper card in Knowledge Library. Reading will reuse the existing document index, outline, section, evidence, translation, and Agent context APIs.
            </p>
            {loadError && <p className="mt-3 text-[11px] text-[#a34a4a]">{errorMessage(loadError)}</p>}
            <div className="mt-5 flex justify-center gap-2">
              <button type="button" onClick={() => library.addMutation.mutate()} className="rounded-[8px] border border-[#dedede] px-3 py-2 text-[11px] font-medium hover:bg-[#f6f6f6]">Import document</button>
              <button type="button" onClick={() => navigate("/knowledge?view=library")} className="rounded-[8px] bg-[#252525] px-3 py-2 text-[11px] font-medium text-white hover:bg-black">Open Knowledge Library</button>
            </div>
          </div>
        </div>
      </main>

      <aside className="min-h-0 overflow-y-auto border-l border-[#e6e6e6] bg-white p-5">
        <h2 className="text-[16px] font-semibold">Evidence &amp; Context</h2>
        <div className="mt-5 border-t border-[#ececec] pt-4">
          <p className="mb-3 text-[13px] font-semibold">Live Context</p>
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
        </div>
        <button type="button" onClick={() => navigate("/knowledge?view=library")} className="mt-5 flex w-full items-center justify-center gap-2 rounded-[8px] border border-[#e0e0e0] px-3 py-2 text-[11px] font-medium hover:bg-[#f7f7f7]"><LibraryBig size={14} />Manage Knowledge Library</button>
      </aside>
    </div>
  )
}

function ReadingLoadingState() {
  return (
    <div className="grid h-full min-h-0 grid-cols-[280px_minmax(0,1fr)_360px] overflow-hidden bg-white">
      <div className="border-r border-[#e6e6e6] p-5">
        <div className="h-5 w-36 animate-pulse rounded bg-[#ededed]" />
        <div className="mt-6 space-y-3">
          {[0, 1, 2, 3, 4].map((item) => <div key={item} className="h-14 animate-pulse rounded-[8px] bg-[#f2f2f2]" />)}
        </div>
      </div>
      <div className="flex items-center justify-center bg-[#fafafa] text-[12px] text-[#888]"><LoaderCircle size={16} className="mr-2 animate-spin" />Loading Reading workspace…</div>
      <div className="border-l border-[#e6e6e6] p-5">
        <div className="h-5 w-40 animate-pulse rounded bg-[#ededed]" />
        <div className="mt-6 h-32 animate-pulse rounded-[8px] bg-[#f3f3f3]" />
      </div>
    </div>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to reach the Knowledge API."
}
