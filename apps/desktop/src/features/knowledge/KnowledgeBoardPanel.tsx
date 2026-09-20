import {
  BookOpenText,
  Bot,
  ChevronRight,
  ExternalLink,
  FileText,
  Filter,
  Highlighter,
  LayoutDashboard,
  Lightbulb,
  Link2,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Sparkles,
  StickyNote,
  Trash2,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { ResearchWorkflowActions } from "../agent/components/ResearchWorkflowActions"
import { knowledgeCardLabel } from "./knowledge-card-model"
import type {
  KnowledgeAgentCardContext,
  KnowledgeAgentRelationContext,
} from "../agent/runtime/knowledge-agent-context"
import type { KnowledgeAction } from "./KnowledgeActionMenu"
import { knowledgeBoardCardDragType } from "./knowledge-board-dnd"
import { nodeSnapshot, useKnowledgeBoardHistory, type KnowledgeBoardNodeSnapshot } from "./knowledge-board-history"
import KnowledgeBoardCanvas from "./KnowledgeBoardCanvas"
import { KnowledgeBoardCreateDialog } from "./KnowledgeBoardCreateDialog"
import { KnowledgeBoardManageDialog } from "./KnowledgeBoardManageDialog"
import { KnowledgeCreateCardDialog } from "./KnowledgeCreateCardDialog"
import KnowledgeInspector from "./KnowledgeInspector"
import { KnowledgeRelationDialog } from "./KnowledgeRelationDialog"
import { KnowledgeRelationEditDialog } from "./KnowledgeRelationEditDialog"
import { KnowledgeRelationInspector } from "./KnowledgeRelationInspector"
import KnowledgeSuggestionInbox from "./KnowledgeSuggestionInbox"
import { dispatchKnowledgeAction } from "./knowledge-action-dispatcher"
import type {
  KnowledgeBoardNode,
  KnowledgeItem,
  KnowledgeItemType,
  KnowledgeRelation,
} from "./knowledge-types"
import { buildOpenLibraryItemParams } from "./knowledge-workspace-navigation"
import { emitKnowledgeWorkspaceEvent, type KnowledgeWorkspaceEvent } from "./knowledge-workspace-events"
import type { KnowledgeBoardController } from "./useKnowledgeBoard"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"
import { useKnowledgeRelationSuggestions } from "./useKnowledgeRelationSuggestions"
import { useOptionalKnowledgeWorkspaceContext } from "./useKnowledgeWorkspaceContext"

const EMPTY_ITEMS: KnowledgeItem[] = []
type CanvasFilter = "all" | "paper" | "note" | "evidence" | "concept"

const canvasFilters: Array<{ value: CanvasFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "paper", label: "Papers" },
  { value: "note", label: "Notes" },
  { value: "evidence", label: "Evidence" },
  { value: "concept", label: "Concepts" },
]

function TrayIcon({ type }: { type: KnowledgeItemType }) {
  const props = { size: 14, strokeWidth: 1.7 }
  if (type === "paper") return <BookOpenText {...props} />
  if (type === "note") return <StickyNote {...props} />
  if (type === "concept") return <Lightbulb {...props} />
  if (type === "highlight") return <Highlighter {...props} />
  return <FileText {...props} />
}

function RelationRow({
  relation,
  itemById,
  deleting,
  onEdit,
  onDelete,
}: {
  relation: KnowledgeRelation
  itemById: Map<string, KnowledgeItem>
  deleting: boolean
  onEdit: () => void
  onDelete: () => void
}) {
  const source = itemById.get(relation.source_item_id)
  const target = itemById.get(relation.target_item_id)

  return (
    <div className="min-w-0 max-w-full rounded-[12px] border border-slate-200 bg-white p-2.5">
      <div className="flex items-start gap-2">
        <Link2 size={12} className="mt-0.5 shrink-0 text-slate-400" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[10px] font-semibold text-slate-700">
            {source?.title ?? "Unknown"} → {target?.title ?? "Unknown"}
          </p>
          <p className="mt-1 text-[9px] capitalize text-slate-400">
            {relation.relation_type.replaceAll("_", " ")} · {relation.origin}
          </p>
          {relation.label ? (
            <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-500">{relation.label}</p>
          ) : null}
        </div>
        <button type="button" className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px] text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Edit relation" onClick={onEdit}><Pencil size={11} /></button>
        <button type="button" className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px] text-slate-400 hover:bg-rose-50 hover:text-rose-600" aria-label="Delete relation" disabled={deleting} onClick={onDelete}><Trash2 size={11} /></button>
      </div>
    </div>
  )
}

function snapshotPayload(node: KnowledgeBoardNodeSnapshot) {
  return {
    x: node.x,
    y: node.y,
    width: node.width,
    height: node.height,
    collapsed: node.collapsed,
    z_index: node.z_index,
  }
}

export default function KnowledgeBoardPanel({
  library,
  board,
  focusSearchRequest = 0,
  createCardRequest = 0,
}: {
  library: KnowledgeLibraryController
  board: KnowledgeBoardController
  focusSearchRequest?: number
  createCardRequest?: number
}) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const items = library.itemsQuery.data?.items ?? EMPTY_ITEMS
  const boards = board.boardsQuery.data?.boards ?? []
  const snapshot = board.boardQuery.data
  const relations = board.relationsQuery.data?.relations ?? []
  const workspaceContext = useOptionalKnowledgeWorkspaceContext()
  const history = useKnowledgeBoardHistory()
  const [search, setSearch] = useState("")
  const [fallbackSelectedIds, setFallbackSelectedIds] = useState<string[]>([])
  const [fallbackLastEvent, setFallbackLastEvent] = useState<KnowledgeWorkspaceEvent | null>(null)
  const [createBoardOpen, setCreateBoardOpen] = useState(false)
  const [createCardOpen, setCreateCardOpen] = useState(false)
  const [manageBoardOpen, setManageBoardOpen] = useState(false)
  const [filter, setFilter] = useState<CanvasFilter>("all")
  const [filterMenuOpen, setFilterMenuOpen] = useState(false)
  const [suggestionInboxOpen, setSuggestionInboxOpen] = useState(true)
  const [selectionTouched, setSelectionTouched] = useState(false)
  const [relationPair, setRelationPair] = useState<{ source: KnowledgeItem; target: KnowledgeItem } | null>(null)
  const [editingRelation, setEditingRelation] = useState<KnowledgeRelation | null>(null)
  const [selectedRelationId, setSelectedRelationId] = useState<string | null>(null)
  const searchInputRef = useRef<HTMLInputElement | null>(null)

  const itemById = useMemo(() => new Map(items.map((item) => [item.item_id, item] as const)), [items])
  const nodeItemIds = useMemo(() => new Set((snapshot?.nodes ?? []).map((node) => node.item_id)), [snapshot?.nodes])
  const selectionSource = workspaceContext?.selectedKnowledgeIds ?? fallbackSelectedIds
  const storedSelectedItemIds = selectionSource.filter((itemId) => nodeItemIds.has(itemId))
  const selectedItemIds = storedSelectedItemIds.length > 0
    ? storedSelectedItemIds
    : !selectionTouched
      ? (snapshot?.nodes[0]?.item_id ? [snapshot.nodes[0].item_id] : [])
      : []
  const selectedItems = selectedItemIds.map((itemId) => itemById.get(itemId)).filter((item): item is KnowledgeItem => Boolean(item))

  const trayItems = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase()
    return items.filter((item) => (
      (filter === "all" || item.item_type === filter)
      && (!normalized
        || [item.title, item.summary, item.item_type].join(" ").toLocaleLowerCase().includes(normalized))
    ))
  }, [filter, items, search])

  const selectedItem = selectedItems.length === 1 ? selectedItems[0] : null
  const selectedRelations = selectedItem
    ? relations.filter((relation) => relation.source_item_id === selectedItem.item_id || relation.target_item_id === selectedItem.item_id)
    : []
  const relationsForBoard = relations.filter((relation) => nodeItemIds.has(relation.source_item_id) && nodeItemIds.has(relation.target_item_id))
  const selectedRelation = selectedRelationId
    ? relationsForBoard.find((relation) => relation.relation_id === selectedRelationId) ?? null
    : null
  const suggestionFocusId = selectedItem?.item_id ?? snapshot?.nodes[0]?.item_id ?? items[0]?.item_id ?? ""
  const suggestions = useKnowledgeRelationSuggestions(suggestionFocusId)
  const lastEvent = workspaceContext?.lastEvent ?? fallbackLastEvent
  const loadError = library.itemsQuery.error ?? board.boardsQuery.error ?? board.boardQuery.error ?? board.relationsQuery.error
  const actionError = board.upsertNodeMutation.error
    ?? board.removeNodeMutation.error
    ?? board.createRelationMutation.error
    ?? board.updateRelationMutation.error
    ?? board.deleteRelationMutation.error
    ?? board.createBoardMutation.error
    ?? board.updateBoardMutation.error
    ?? board.deleteBoardMutation.error
  const saving = board.upsertNodeMutation.isPending
    || board.removeNodeMutation.isPending
    || board.createRelationMutation.isPending
    || board.updateRelationMutation.isPending
    || board.deleteRelationMutation.isPending
    || board.createBoardMutation.isPending
    || board.updateBoardMutation.isPending
    || board.deleteBoardMutation.isPending

  useEffect(() => {
    if (focusSearchRequest > 0) searchInputRef.current?.focus()
  }, [focusSearchRequest])

  useEffect(() => {
    if (createCardRequest > 0) setCreateCardOpen(true)
  }, [createCardRequest])

  function updateSelection(ids: string[]) {
    setSelectionTouched(true)
    const validIds = ids.filter((itemId) => nodeItemIds.has(itemId))
    if (validIds.length > 0) setSelectedRelationId(null)
    const nextItem = validIds.length === 1 ? itemById.get(validIds[0]) ?? null : null
    if (workspaceContext) {
      workspaceContext.setSelectedKnowledgeIds(validIds)
      workspaceContext.selectKnowledgeItem(nextItem)
      return
    }
    setFallbackSelectedIds(validIds)
  }

  function addNode(itemId: string, position: { x: number; y: number }) {
    if (nodeItemIds.has(itemId)) return
    board.upsertNodeMutation.mutate({
      itemId,
      payload: { x: position.x, y: position.y, width: 248, height: 156, z_index: (snapshot?.nodes.length ?? 0) + 1 },
    }, {
      onSuccess: (node) => history.record({ label: "add card", itemId, before: null, after: nodeSnapshot(node) }),
    })
  }

  function quickAddNode(itemId: string) {
    const index = snapshot?.nodes.length ?? 0
    addNode(itemId, { x: 80 + (index % 3) * 280, y: 100 + Math.floor(index / 3) * 190 })
  }

  function persistNode(node: KnowledgeBoardNode) {
    const before = snapshot?.nodes.find((candidate) => candidate.item_id === node.item_id)
    board.upsertNodeMutation.mutate({ itemId: node.item_id, payload: snapshotPayload(nodeSnapshot(node)) }, {
      onSuccess: (stored) => history.record({ label: "move or resize card", itemId: node.item_id, before: before ? nodeSnapshot(before) : null, after: nodeSnapshot(stored) }),
    })
  }

  function removeNode(itemId: string) {
    const before = snapshot?.nodes.find((candidate) => candidate.item_id === itemId)
    updateSelection(selectedItemIds.filter((candidate) => candidate !== itemId))
    board.removeNodeMutation.mutate(itemId, {
      onSuccess: () => {
        if (before) history.record({ label: "remove card", itemId, before: nodeSnapshot(before), after: null })
      },
    })
  }

  function applyHistory(itemId: string, target: KnowledgeBoardNodeSnapshot | null) {
    if (!target) {
      board.removeNodeMutation.mutate(itemId)
      return
    }
    board.upsertNodeMutation.mutate({ itemId, payload: snapshotPayload(target) })
  }

  function undo() {
    const entry = history.undoEntry
    if (!entry || saving) return
    history.commitUndo()
    applyHistory(entry.itemId, entry.before)
  }

  function redo() {
    const entry = history.redoEntry
    if (!entry || saving) return
    history.commitRedo()
    applyHistory(entry.itemId, entry.after)
  }

  function requestRelation(sourceItemId: string, targetItemId: string) {
    const source = itemById.get(sourceItemId)
    const target = itemById.get(targetItemId)
    if (!source || !target || sourceItemId === targetItemId) return
    setSelectedRelationId(null)
    setRelationPair({ source, target })
  }

  function openLibraryItem(item: KnowledgeItem) {
    setSearchParams(buildOpenLibraryItemParams(searchParams, item.item_id))
  }

  function relationContextsFor(scopeItems: KnowledgeItem[], scopeLabel: string): KnowledgeAgentRelationContext[] {
    const scopeIds = new Set(scopeItems.map((item) => item.item_id))
    const scopedRelations = scopeLabel === "Canvas"
      ? relationsForBoard
      : scopeItems.length === 1
        ? relationsForBoard.filter((relation) => scopeIds.has(relation.source_item_id) || scopeIds.has(relation.target_item_id))
        : relationsForBoard.filter((relation) => scopeIds.has(relation.source_item_id) && scopeIds.has(relation.target_item_id))

    return scopedRelations.slice(0, 60).map((relation) => ({
      relationId: relation.relation_id,
      sourceItemId: relation.source_item_id,
      sourceTitle: itemById.get(relation.source_item_id)?.title ?? relation.source_item_id,
      targetItemId: relation.target_item_id,
      targetTitle: itemById.get(relation.target_item_id)?.title ?? relation.target_item_id,
      relationType: relation.relation_type,
      label: relation.label,
      origin: relation.origin,
      confidence: relation.confidence,
    }))
  }

  function cardContextsFor(scopeItems: KnowledgeItem[]): KnowledgeAgentCardContext[] {
    return scopeItems.slice(0, 60).map((item) => {
      const metadataDocumentId = typeof item.metadata?.document_id === "string" ? item.metadata.document_id : ""
      return {
        itemId: item.item_id,
        itemType: item.item_type,
        title: item.title,
        summary: item.summary,
        documentId: item.resource_document_id ?? metadataDocumentId,
      }
    })
  }

  function askAgentForItems(scopeItems: KnowledgeItem[], scopeLabel: string) {
    if (scopeItems.length === 0 || !snapshot) return
    const relationContexts = relationContextsFor(scopeItems, scopeLabel)
    const cardContexts = cardContextsFor(scopeItems)
    const sourceText = [
      `Canvas: ${snapshot.board.name}`,
      `Scope: ${scopeLabel}`,
      "",
      "Knowledge cards:",
      ...scopeItems.map((item, index) => `[K${index + 1}] [${item.item_type}] ${item.title}\n${item.summary || "No summary."}`),
    ].join("\n")
    const documentIds = scopeItems.flatMap((item) => {
      const metadataDocumentId = typeof item.metadata?.document_id === "string" ? item.metadata.document_id : ""
      return [item.resource_document_id ?? "", metadataDocumentId]
    }).filter(Boolean)
    const now = new Date().toISOString()
    const syntheticItem: KnowledgeItem = {
      item_id: `canvas-selection-${snapshot.board.board_id}`,
      item_type: "concept",
      title: `${snapshot.board.name} · ${scopeLabel}`,
      summary: sourceText,
      resource_document_id: null,
      source_uri: "",
      metadata: { tags: ["canvas-context"], provenance: "canvas-selection" },
      created_at: now,
      updated_at: now,
    }
    navigate("/agent", {
      state: {
        agentDraftPrompt: `Analyze this ${scopeLabel.toLowerCase()} as one bounded knowledge context. Explicit Canvas relations are user/AI-authored organizational context, not independent factual evidence. Use the relations to explain structure and conflicts, but rely on Evidence/Paper retrieval for factual claims. Refer to relation ids such as R1 when discussing the Canvas structure.`,
        autoSubmitAgentPrompt: false,
        knowledgeAgentContext: {
          item: syntheticItem,
          writeback: null,
          sourceText,
          documentIds: [...new Set(documentIds)],
          cards: cardContexts,
          relations: relationContexts,
          canvas: {
            boardId: snapshot.board.board_id,
            boardName: snapshot.board.name,
            scopeLabel,
          },
        },
      },
    })
  }

  function handleKnowledgeAction(action: KnowledgeAction) {
    if (!selectedItem) return
    if (action === "ask_agent") {
      askAgentForItems([selectedItem], "Selected card")
      return
    }
    if (workspaceContext) {
      workspaceContext.runKnowledgeAction(action, selectedItem)
      return
    }
    const request = dispatchKnowledgeAction(action, { item: selectedItem })
    if (!request) return
    setFallbackLastEvent(emitKnowledgeWorkspaceEvent(request))
  }

  if (library.itemsQuery.isPending || board.boardsQuery.isPending || (board.activeBoardId && board.boardQuery.isPending)) {
    return (
      <section className="knowledge-board-panel p-4" aria-busy="true" aria-label="Loading visual knowledge board">
        <div className="ait-skeleton h-9 w-full rounded-[10px]" />
        <div className="mt-3 grid min-h-0 flex-1 grid-cols-[minmax(260px,345px)_1fr_320px] gap-0"><div className="ait-skeleton rounded-[12px]" /><div className="ait-skeleton rounded-[12px]" /><div className="ait-skeleton rounded-[12px]" /></div>
      </section>
    )
  }

  function selectSuggestionItem(itemId: string) {
    const item = itemById.get(itemId)
    if (!item) return
    if (nodeItemIds.has(itemId)) updateSelection([itemId])
    else openLibraryItem(item)
  }

  return (
    <section className="knowledge-board-panel">
      {(loadError || actionError) ? <div role="alert" className="knowledge-board-error">{errorMessage(actionError ?? loadError)}</div> : null}

      {!snapshot && !loadError ? (
        <div className="knowledge-board-empty">
          <div className="knowledge-board-empty-card">
            <LayoutDashboard size={25} strokeWidth={1.6} />
            <h2>No canvas is selected</h2>
            <p>Create a canvas before arranging papers, notes, concepts, and evidence. Canvas data is stored by the Knowledge API.</p>
            <button type="button" onClick={() => setCreateBoardOpen(true)}><Plus size={14} />New canvas</button>
          </div>
        </div>
      ) : snapshot ? (
        <div className="knowledge-board-grid">
          <aside className="knowledge-object-pane">
            <div className="knowledge-object-heading">
              <div>
                <h2>Knowledge Objects <ChevronRight size={14} strokeWidth={1.8} /></h2>
                <p>Add papers, concepts, notes and more to your canvas.</p>
              </div>
              <select
                aria-label="Knowledge canvas"
                value={board.activeBoardId ?? ""}
                onChange={(event) => { updateSelection([]); setSelectedRelationId(null); history.clear(); board.setActiveBoardId(event.target.value || null) }}
                className="knowledge-board-select"
              >
                {boards.map((candidate) => <option key={candidate.board_id} value={candidate.board_id}>{candidate.name}</option>)}
              </select>
            </div>

            <div className="knowledge-object-filters" aria-label="Knowledge object type filter">
              {canvasFilters.map((entry) => <button key={entry.value} type="button" className={`knowledge-object-filter${filter === entry.value ? " is-active" : ""}`} onClick={() => setFilter(entry.value)}>{entry.label}</button>)}
            </div>

            <div className="knowledge-object-search-row">
              <label className="knowledge-object-search">
                <Search size={15} strokeWidth={1.8} />
                <input ref={searchInputRef} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search knowledge objects..." aria-label="Search knowledge objects" />
              </label>
              <button type="button" className={`knowledge-object-filter-trigger${filterMenuOpen ? " is-open" : ""}`} aria-label="More knowledge object filters" aria-expanded={filterMenuOpen} onClick={() => setFilterMenuOpen((open) => !open)}><Filter size={15} strokeWidth={1.8} /></button>
              {filterMenuOpen ? <div className="knowledge-object-filter-popover" role="menu">
                {(["all", "paper", "note", "evidence", "concept", "document", "web", "insight", "question", "highlight"] as const).map((value) => <button key={value} type="button" role="menuitem" className={filter === value ? "is-active" : ""} onClick={() => { setFilter(value as CanvasFilter); setFilterMenuOpen(false) }}>{value === "all" ? "All objects" : knowledgeCardLabel(value)}</button>)}
              </div> : null}
            </div>

            <p className="knowledge-object-count">{trayItems.length} objects · {snapshot.nodes.length} on canvas</p>

            <div className="knowledge-object-list" aria-label="Knowledge objects">
              {trayItems.map((item) => {
                const onCanvas = nodeItemIds.has(item.item_id)
                const selected = selectedItemIds.includes(item.item_id)
                return (
                  <article
                    key={item.item_id}
                    draggable
                    className={`knowledge-object-card${onCanvas ? " is-on-canvas" : ""}${selected ? " is-selected" : ""}`}
                    onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData(knowledgeBoardCardDragType, item.item_id) }}
                  >
                    <div className="knowledge-object-card-head">
                      <span className="knowledge-object-icon"><TrayIcon type={item.item_type} /></span>
                      <div className="knowledge-object-card-copy">
                        <p className="knowledge-object-type">{knowledgeCardLabel(item.item_type)}</p>
                        <p className="knowledge-object-title" title={item.title}>{item.title}</p>
                        <p className="knowledge-object-summary" title={item.summary}>{item.summary || (onCanvas ? "On canvas" : "Ready to add to canvas")}</p>
                      </div>
                      <button type="button" className="knowledge-object-more" aria-label={`More actions for ${item.title}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => openLibraryItem(item)}><MoreHorizontal size={15} /></button>
                    </div>
                    <div className="knowledge-object-actions">
                      {!onCanvas ? <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={() => quickAddNode(item.item_id)}><Plus size={12} />Add</button> : null}
                      <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={() => openLibraryItem(item)}><ExternalLink size={11} />Open</button>
                    </div>
                  </article>
                )
              })}
            </div>
          </aside>

          <main className="knowledge-canvas-pane" aria-label="Knowledge canvas">
            <KnowledgeBoardCanvas
              items={items}
              nodes={snapshot.nodes}
              relations={relations}
              selectedItemIds={selectedItemIds}
              selectedRelationId={selectedRelationId}
              onSelectionChange={updateSelection}
              onRelationSelectionChange={setSelectedRelationId}
              onAddNode={addNode}
              onPersistNode={persistNode}
              onRemoveNode={removeNode}
              onLinkRequest={requestRelation}
              canUndo={history.canUndo && !saving}
              canRedo={history.canRedo && !saving}
              undoLabel={history.undoLabel}
              redoLabel={history.redoLabel}
              onUndo={undo}
              onRedo={redo}
              onAskSelection={() => askAgentForItems(selectedItems, selectedItems.length > 1 ? "Selected cards" : "Selected card")}
              onOpenSelection={() => selectedItem && openLibraryItem(selectedItem)}
            />
          </main>

          <aside className="knowledge-inspector-pane">
            {suggestionInboxOpen ? (
              <KnowledgeSuggestionInbox focusItemId={suggestionFocusId} items={items} controller={suggestions} onSelectItem={selectSuggestionItem} onClose={() => setSuggestionInboxOpen(false)} />
            ) : (
              <button type="button" className="knowledge-suggestion-button" onClick={() => setSuggestionInboxOpen(true)}><Sparkles size={14} />Show AI suggestions</button>
            )}
            <div className="knowledge-inspector-divider" />
            {selectedRelation ? (
              <KnowledgeRelationInspector
                relation={selectedRelation}
                source={itemById.get(selectedRelation.source_item_id) ?? null}
                target={itemById.get(selectedRelation.target_item_id) ?? null}
                deleting={board.deleteRelationMutation.isPending && board.deleteRelationMutation.variables === selectedRelation.relation_id}
                onEdit={() => setEditingRelation(selectedRelation)}
                onDelete={() => board.deleteRelationMutation.mutate(selectedRelation.relation_id, { onSuccess: () => setSelectedRelationId(null) })}
              />
            ) : (
              <>
                <div className="knowledge-inspector-section-head"><span>Knowledge Object</span><button type="button" className="knowledge-object-more" aria-label="More knowledge object actions"><MoreHorizontal size={16} /></button></div>
                <KnowledgeInspector item={selectedItem} relationCount={selectedRelations.length} lastEventType={lastEvent?.item.item_id === selectedItem?.item_id ? lastEvent?.type ?? null : null} onAction={handleKnowledgeAction} onOpen={() => selectedItem && openLibraryItem(selectedItem)} onFocusCanvas={() => selectedItem && updateSelection([selectedItem.item_id])} relations={selectedRelations.length > 0 ? selectedRelations.map((relation) => (
                  <RelationRow key={relation.relation_id} relation={relation} itemById={itemById} deleting={board.deleteRelationMutation.isPending && board.deleteRelationMutation.variables === relation.relation_id} onEdit={() => setEditingRelation(relation)} onDelete={() => board.deleteRelationMutation.mutate(relation.relation_id, { onSuccess: () => { if (selectedRelationId === relation.relation_id) setSelectedRelationId(null) } })} />
                )) : undefined} />
              </>
            )}
            <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4">
              <span className="text-[9px] text-slate-400">{snapshot.nodes.length} cards · {relationsForBoard.length} relations</span>
              <div className="flex items-center gap-1">
                {snapshot.nodes.length ? <button type="button" className="knowledge-object-more" aria-label="Ask Agent about canvas" onClick={() => askAgentForItems(snapshot.nodes.map((node) => itemById.get(node.item_id)).filter((item): item is KnowledgeItem => Boolean(item)) , "Canvas")}><Bot size={15} /></button> : null}
                <button type="button" className="knowledge-object-more" aria-label="Manage canvas" onClick={() => setManageBoardOpen(true)}><Pencil size={15} /></button>
                <button type="button" className="knowledge-object-more" aria-label="Create canvas" onClick={() => setCreateBoardOpen(true)}><Plus size={15} /></button>
              </div>
            </div>
            <details className="knowledge-workflow-details">
              <summary>Research Agent workflows</summary>
              <ResearchWorkflowActions available={["compare_papers", "curate_knowledge", "draft_section"]} compact variant="inline" />
            </details>
          </aside>
        </div>
      ) : null}

      <KnowledgeBoardCreateDialog open={createBoardOpen} creating={board.createBoardMutation.isPending} onClose={() => !board.createBoardMutation.isPending && setCreateBoardOpen(false)} onCreate={(payload) => board.createBoardMutation.mutate(payload, { onSuccess: () => { updateSelection([]); setSelectedRelationId(null); history.clear(); setCreateBoardOpen(false) } })} />
      <KnowledgeCreateCardDialog open={createCardOpen} creating={library.createItemMutation.isPending} onClose={() => !library.createItemMutation.isPending && setCreateCardOpen(false)} onCreate={(payload) => library.createItemMutation.mutate(payload, { onSuccess: () => setCreateCardOpen(false) })} />
      <KnowledgeBoardManageDialog board={manageBoardOpen ? snapshot?.board ?? null : null} saving={board.updateBoardMutation.isPending} deleting={board.deleteBoardMutation.isPending} onClose={() => !saving && setManageBoardOpen(false)} onSave={(payload) => snapshot && board.updateBoardMutation.mutate({ boardId: snapshot.board.board_id, payload }, { onSuccess: () => setManageBoardOpen(false) })} onDelete={() => snapshot && board.deleteBoardMutation.mutate(snapshot.board.board_id, { onSuccess: () => { updateSelection([]); setSelectedRelationId(null); history.clear(); setManageBoardOpen(false) } })} />
      <KnowledgeRelationDialog source={relationPair?.source ?? null} target={relationPair?.target ?? null} creating={board.createRelationMutation.isPending} onClose={() => !board.createRelationMutation.isPending && setRelationPair(null)} onCreate={(payload) => board.createRelationMutation.mutate(payload, { onSuccess: (relation) => { setRelationPair(null); updateSelection([]); setSelectedRelationId(relation.relation_id) } })} />
      <KnowledgeRelationEditDialog relation={editingRelation} saving={board.updateRelationMutation.isPending} onClose={() => !board.updateRelationMutation.isPending && setEditingRelation(null)} onSave={(payload) => editingRelation && board.updateRelationMutation.mutate({ relationId: editingRelation.relation_id, payload }, { onSuccess: (relation) => { setEditingRelation(null); setSelectedRelationId(relation.relation_id) } })} />
    </section>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to update the visual knowledge canvas."
}
