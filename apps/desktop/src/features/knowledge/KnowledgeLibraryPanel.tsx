import { AlertCircle, FilePlus2, LibraryBig, Plus, RefreshCw, Search } from "lucide-react"
import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"

import { desktop } from "../../desktop"
import { Button } from "../../shared/ui/Button"
import { EmptyState } from "../../shared/ui/EmptyState"
import { knowledgeCardLabel } from "./knowledge-card-model"
import { KnowledgeCreateCardDialog } from "./KnowledgeCreateCardDialog"
import { KnowledgeDeleteDialog } from "./KnowledgeDeleteDialog"
import { KnowledgeDocumentDetail } from "./KnowledgeDocumentDetail"
import KnowledgeItemCard from "./KnowledgeItemCard"
import { KnowledgeItemDetail } from "./KnowledgeItemDetail"
import { KnowledgeImportDialog } from "./KnowledgeImportDialog"
import { KnowledgeRuntimeCard } from "./KnowledgeRuntimeCard"
import type { KnowledgeDocument, KnowledgeItem, KnowledgeItemType } from "./knowledge-types"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

type CardFilter = "all" | KnowledgeItemType

const filters: CardFilter[] = [
  "all",
  "paper",
  "note",
  "concept",
  "evidence",
  "insight",
  "question",
  "highlight",
  "document",
  "web",
]
const EMPTY_DOCUMENTS: KnowledgeDocument[] = []
const EMPTY_ITEMS: KnowledgeItem[] = []

export default function KnowledgeLibraryPanel({
  library,
  onOpenPaper,
  onOpenGraph,
}: {
  library: KnowledgeLibraryController
  onOpenPaper?: (itemId: string) => void
  onOpenGraph?: (itemId: string) => void
}) {
  const {
    documentsQuery,
    itemsQuery,
    runtimeQuery,
    addMutation,
    createItemMutation,
    deleteItemMutation,
    deleteMutation,
    reindexMutation,
  } = library
  const [searchParams, setSearchParams] = useSearchParams()
  const documents = documentsQuery.data?.documents ?? EMPTY_DOCUMENTS
  const items = itemsQuery.data?.items ?? EMPTY_ITEMS
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<CardFilter>("all")
  const [importOpen, setImportOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocument | null>(null)
  const [selectedItem, setSelectedItem] = useState<KnowledgeItem | null>(null)
  const [removeTarget, setRemoveTarget] = useState<KnowledgeDocument | null>(null)
  const [openError, setOpenError] = useState("")
  const actionError = addMutation.error ?? createItemMutation.error ?? deleteItemMutation.error ?? deleteMutation.error ?? reindexMutation.error
  const requestedDocument = documents.find((document) => document.document_id === searchParams.get("document")) ?? null
  const requestedItem = items.find((item) => item.item_id === searchParams.get("item")) ?? null
  const activeDocument = selectedDocument ?? requestedDocument
  const activeItem = selectedItem ?? requestedItem

  const documentsById = useMemo(
    () => new Map(documents.map((document) => [document.document_id, document] as const)),
    [documents],
  )

  const visibleItems = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase()
    return items.filter((item) => {
      const document = item.resource_document_id ? documentsById.get(item.resource_document_id) : undefined
      const matchesSearch = !normalized || [
        item.title,
        item.summary,
        item.item_type,
        item.source_uri,
        document?.source_type ?? "",
      ].join(" ").toLocaleLowerCase().includes(normalized)
      return matchesSearch && (filter === "all" || item.item_type === filter)
    })
  }, [documentsById, filter, items, search])

  function closeDocumentDetail() {
    setSelectedDocument(null)
    if (!searchParams.has("document")) return
    const next = new URLSearchParams(searchParams)
    next.delete("document")
    setSearchParams(next, { replace: true })
  }

  function closeItemDetail() {
    setSelectedItem(null)
    if (!searchParams.has("item")) return
    const next = new URLSearchParams(searchParams)
    next.delete("item")
    setSearchParams(next, { replace: true })
  }

  function openItem(item: KnowledgeItem) {
    const document = item.resource_document_id ? documentsById.get(item.resource_document_id) : undefined
    if (document && item.item_type === "paper" && onOpenPaper) {
      setSelectedDocument(null)
      setSelectedItem(null)
      onOpenPaper(item.item_id)
      return
    }
    if (document) {
      setSelectedItem(null)
      setSelectedDocument(document)
      return
    }
    setSelectedDocument(null)
    setSelectedItem(item)
  }

  if (documentsQuery.isPending || itemsQuery.isPending) return <KnowledgeLibrarySkeleton />

  const loadError = documentsQuery.error ?? itemsQuery.error

  return (
    <div className="space-y-4">
      <section className="ait-surface overflow-hidden">
        <header className="flex flex-col gap-4 border-b border-slate-100 px-5 py-5 sm:flex-row sm:items-center sm:justify-between lg:px-7">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Knowledge workspace</p>
            <h2 className="mt-1.5 text-xl font-semibold tracking-tight text-slate-950">Knowledge Library</h2>
            <p className="mt-1.5 max-w-2xl text-sm leading-6 text-slate-500">Keep papers, notes, concepts, evidence, insights, questions, and highlights in one card model while document resources remain available to RAG.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="md" disabled={createItemMutation.isPending} onClick={() => setCreateOpen(true)}><Plus size={16} />New card</Button>
            <Button variant="primary" size="md" disabled={addMutation.isPending} onClick={() => setImportOpen(true)}><FilePlus2 size={16} />Add document</Button>
          </div>
        </header>

        {runtimeQuery.data ? <KnowledgeRuntimeCard runtime={runtimeQuery.data} /> : runtimeQuery.isError ? <div className="border-b border-amber-100 bg-amber-50/60 px-5 py-3 text-xs text-amber-700 lg:px-7">Runtime summary is unavailable. Card management remains available.</div> : null}

        {(documentsQuery.isError || itemsQuery.isError || actionError || openError) && (
          <div role="alert" className="m-5 flex items-start gap-3 rounded-[15px] border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700 lg:mx-7">
            <AlertCircle size={17} className="mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1"><p className="font-semibold">Knowledge Library action failed</p><p className="mt-1 break-words text-xs leading-5">{openError || errorMessage(actionError ?? loadError)}</p></div>
            {(documentsQuery.isError || itemsQuery.isError) && <Button size="xs" onClick={() => { void documentsQuery.refetch(); void itemsQuery.refetch() }}><RefreshCw size={12} />Retry</Button>}
          </div>
        )}

        {items.length > 0 && (
          <div className="border-b border-slate-100 px-5 py-3 lg:px-7">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <label className="flex min-w-0 flex-1 items-center gap-2 rounded-[13px] border border-slate-200 bg-white px-3 py-2 lg:max-w-md"><Search size={14} className="text-slate-400" /><input className="min-w-0 flex-1 bg-transparent text-xs text-slate-700 outline-none placeholder:text-slate-400" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search cards, summaries and sources…" /></label>
              <div className="ait-scroll-panel flex max-w-full gap-1 overflow-x-auto rounded-[12px] bg-slate-100 p-1" aria-label="Knowledge card type filter">{filters.map((value) => <button key={value} type="button" className={`shrink-0 rounded-[9px] px-2.5 py-1.5 text-[10px] font-medium ${filter === value ? "bg-white text-slate-800 shadow-sm" : "text-slate-500"}`} onClick={() => setFilter(value)}>{value === "all" ? "All" : knowledgeCardLabel(value)}</button>)}</div>
            </div>
            <p className="mt-2 text-[10px] text-slate-400">{visibleItems.length} of {items.length} cards · {documents.length} indexed resources</p>
          </div>
        )}

        {items.length === 0 && !loadError ? (
          <div className="p-5 lg:p-7"><EmptyState icon={<LibraryBig size={25} strokeWidth={1.6} />} title="Build your knowledge workspace" description="Import a paper or document, or create a note, concept, evidence, insight, question, highlight, or manual paper card." actions={<div className="flex flex-wrap justify-center gap-2"><Button onClick={() => setCreateOpen(true)}><Plus size={15} />Create first card</Button><Button variant="primary" disabled={addMutation.isPending} onClick={() => setImportOpen(true)}><FilePlus2 size={15} />Import first document</Button></div>} /></div>
        ) : visibleItems.length === 0 ? (
          <div className="p-7"><EmptyState title="No cards match this view" description="Try a different search term or card type." /></div>
        ) : (
          <div className="ait-scroll-panel max-h-[min(64vh,760px)] overflow-y-auto overscroll-contain p-5 lg:p-7" aria-label="Knowledge cards">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {visibleItems.map((item) => {
                const document = item.resource_document_id ? documentsById.get(item.resource_document_id) : undefined
                return <KnowledgeItemCard key={item.item_id} item={item} document={document} deleting={(document ? deleteMutation.isPending && deleteMutation.variables === document.document_id : deleteItemMutation.isPending && deleteItemMutation.variables === item.item_id)} reindexing={Boolean(document && reindexMutation.isPending && reindexMutation.variables === document.document_id)} onOpen={() => openItem(item)} onReveal={() => { if (!document) return; setOpenError(""); void desktop.files.openEvidenceSource(document.source_uri).catch((error: unknown) => setOpenError(errorMessage(error))) }} onRemoveSource={() => document && setRemoveTarget(document)} onDeleteItem={() => deleteItemMutation.mutate(item.item_id, { onSuccess: () => { if (selectedItem?.item_id === item.item_id) setSelectedItem(null) } })} onReindex={() => document && reindexMutation.mutate(document.document_id)} />
              })}
            </div>
          </div>
        )}
      </section>

      <p className="px-2 text-[11px] leading-5 text-slate-400">Cards are stored locally in SQLite. Parsed chunks and embeddings remain in the existing local RAG index.</p>
      <KnowledgeImportDialog open={importOpen} adding={addMutation.isPending} onClose={() => !addMutation.isPending && setImportOpen(false)} onBrowse={() => addMutation.mutate(undefined, { onSuccess: (result) => { if (result) setImportOpen(false) } })} />
      <KnowledgeCreateCardDialog open={createOpen} creating={createItemMutation.isPending} onClose={() => !createItemMutation.isPending && setCreateOpen(false)} onCreate={(payload) => createItemMutation.mutate(payload, { onSuccess: () => setCreateOpen(false) })} />
      {activeDocument && <KnowledgeDocumentDetail document={activeDocument} reindexing={reindexMutation.isPending && reindexMutation.variables === activeDocument.document_id} onClose={closeDocumentDetail} onReindex={() => reindexMutation.mutate(activeDocument.document_id)} onRemove={() => setRemoveTarget(activeDocument)} />}
      {activeItem && <KnowledgeItemDetail item={activeItem} deleting={deleteItemMutation.isPending && deleteItemMutation.variables === activeItem.item_id} onClose={closeItemDetail} onDelete={() => deleteItemMutation.mutate(activeItem.item_id, { onSuccess: closeItemDetail })} onOpenGraph={onOpenGraph ? () => onOpenGraph(activeItem.item_id) : undefined} />}
      <KnowledgeDeleteDialog document={removeTarget} deleting={deleteMutation.isPending} onCancel={() => !deleteMutation.isPending && setRemoveTarget(null)} onConfirm={() => removeTarget && deleteMutation.mutate(removeTarget.document_id, { onSuccess: () => { if (activeDocument?.document_id === removeTarget.document_id) closeDocumentDetail(); setRemoveTarget(null) } })} />
    </div>
  )
}

function KnowledgeLibrarySkeleton() {
  return <section className="ait-surface overflow-hidden p-7" aria-busy="true" aria-label="Loading Knowledge Library"><div className="ait-skeleton h-5 w-40 rounded-full" /><div className="ait-skeleton mt-4 h-3 w-[55%] rounded-full" /><div className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><div className="ait-skeleton h-52 rounded-[18px]" /><div className="ait-skeleton h-52 rounded-[18px]" /><div className="ait-skeleton h-52 rounded-[18px]" /></div></section>
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to reach the Knowledge Library API."
}
