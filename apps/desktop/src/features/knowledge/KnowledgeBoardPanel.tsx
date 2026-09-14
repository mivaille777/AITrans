import {
  BookOpenText,
  Bot,
  Check,
  ExternalLink,
  FileText,
  Highlighter,
  LayoutDashboard,
  Lightbulb,
  Link2,
  Pencil,
  Plus,
  Search,
  StickyNote,
  Trash2,
} from "lucide-react"
import { useMemo, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { Button } from "../../shared/ui/Button"
import { EmptyState } from "../../shared/ui/EmptyState"
import type { KnowledgeAction } from "./KnowledgeActionMenu"
import { knowledgeBoardCardDragType } from "./knowledge-board-dnd"
import { nodeSnapshot, useKnowledgeBoardHistory, type KnowledgeBoardNodeSnapshot } from "./knowledge-board-history"
import KnowledgeBoardCanvas from "./KnowledgeBoardCanvas"
import { KnowledgeBoardCreateDialog } from "./KnowledgeBoardCreateDialog"
import { KnowledgeBoardManageDialog } from "./KnowledgeBoardManageDialog"
import KnowledgeInspector from "./KnowledgeInspector"
import { KnowledgeRelationDialog } from "./KnowledgeRelationDialog"
import { KnowledgeRelationEditDialog } from "./KnowledgeRelationEditDialog"
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
import { useOptionalKnowledgeWorkspaceContext } from "./useKnowledgeWorkspaceContext"

const EMPTY_ITEMS: KnowledgeItem[] = []

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
    <div className="rounded-[12px] border border-slate-200 bg-white p-2.5">
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
}: {
  library: KnowledgeLibraryController
  board: KnowledgeBoardController
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
  const [manageBoardOpen, setManageBoardOpen] = useState(false)
  const [relationPair, setRelationPair] = useState<{ source: KnowledgeItem; target: KnowledgeItem } | null>(null)
  const [editingRelation, setEditingRelation] = useState<KnowledgeRelation | null>(null)

  const itemById = useMemo(() => new Map(items.map((item) => [item.item_id, item] as const)), [items])
  const nodeItemIds = useMemo(() => new Set((snapshot?.nodes ?? []).map((node) => node.item_id)), [snapshot?.nodes])
  const selectionSource = workspaceContext?.selectedKnowledgeIds ?? fallbackSelectedIds
  const selectedItemIds = selectionSource.filter((itemId) => nodeItemIds.has(itemId))
  const selectedItems = selectedItemIds.map((itemId) => itemById.get(itemId)).filter((item): item is KnowledgeItem => Boolean(item))

  const trayItems = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase()
    return items.filter((item) => (
      !normalized
      || [item.title, item.summary, item.item_type].join(" ").toLocaleLowerCase().includes(normalized)
    ))
  }, [items, search])

  const selectedItem = selectedItems.length === 1 ? selectedItems[0] : null
  const selectedRelations = selectedItem
    ? relations.filter((relation) => relation.source_item_id === selectedItem.item_id || relation.target_item_id === selectedItem.item_id)
    : []
  const relationsForBoard = relations.filter((relation) => nodeItemIds.has(relation.source_item_id) && nodeItemIds.has(relation.target_item_id))
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

  function updateSelection(ids: string[]) {
    const validIds = ids.filter((itemId) => nodeItemIds.has(itemId))
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
    if (!source || !target) return
    setRelationPair({ source, target })
  }

  function openLibraryItem(item: KnowledgeItem) {
    setSearchParams(buildOpenLibraryItemParams(searchParams, item.item_id))
  }

  function handleKnowledgeAction(action: KnowledgeAction) {
    if (!selectedItem) return
    if (workspaceContext) {
      workspaceContext.runKnowledgeAction(action, selectedItem)
      return
    }
    const request = dispatchKnowledgeAction(action, { item: selectedItem })
    if (!request) return
    setFallbackLastEvent(emitKnowledgeWorkspaceEvent(request))
  }

  function askAgentForItems(scopeItems: KnowledgeItem[], scopeLabel: string) {
    if (scopeItems.length === 0 || !snapshot) return
    if (scopeItems.length === 1 && workspaceContext) {
      workspaceContext.runKnowledgeAction("ask_agent", scopeItems[0])
      return
    }
    const scopeIds = new Set(scopeItems.map((item) => item.item_id))
    const scopedRelations = relationsForBoard.filter((relation) => scopeIds.has(relation.source_item_id) && scopeIds.has(relation.target_item_id))
    const sourceText = [
      `Canvas: ${snapshot.board.name}`,
      `Scope: ${scopeLabel}`,
      "",
      ...scopeItems.map((item, index) => `${index + 1}. [${item.item_type}] ${item.title}\n${item.summary || "No summary."}`),
      "",
      "Relations:",
      ...(scopedRelations.length > 0
        ? scopedRelations.map((relation) => `${itemById.get(relation.source_item_id)?.title ?? relation.source_item_id} --${relation.relation_type}--> ${itemById.get(relation.target_item_id)?.title ?? relation.target_item_id}${relation.label ? ` (${relation.label})` : ""}`)
        : ["No explicit relations inside this scope."]),
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
        agentDraftPrompt: `Analyze this ${scopeLabel.toLowerCase()} as one bounded knowledge context. Compare the cards, use their explicit relations, identify agreements or conflicts, and suggest the most useful next knowledge action.`,
        autoSubmitAgentPrompt: false,
        knowledgeAgentContext: { item: syntheticItem, writeback: null, sourceText, documentIds: [...new Set(documentIds)] },
      },
    })
  }

  if (library.itemsQuery.isPending || board.boardsQuery.isPending || (board.activeBoardId && board.boardQuery.isPending)) {
    return (
      <section className="ait-surface h-[720px] overflow-hidden p-5" aria-busy="true" aria-label="Loading visual knowledge board">
        <div className="ait-skeleton h-10 w-full rounded-[14px]" />
        <div className="mt-4 grid h-[640px] grid-cols-[210px_1fr] gap-3"><div className="ait-skeleton rounded-[18px]" /><div className="ait-skeleton rounded-[18px]" /></div>
      </section>
    )
  }

  return (
    <section className="ait-surface overflow-hidden">
      <header className="flex flex-col gap-3 border-b border-slate-100 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[13px] bg-slate-950 text-white"><LayoutDashboard size={17} /></span>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Visual knowledge canvas</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <select value={board.activeBoardId ?? ""} onChange={(event) => { updateSelection([]); history.clear(); board.setActiveBoardId(event.target.value || null) }} className="max-w-xs truncate bg-transparent text-base font-semibold text-slate-950 outline-none">
                {boards.map((candidate) => <option key={candidate.board_id} value={candidate.board_id}>{candidate.name}</option>)}
              </select>
              <span className="text-[10px] text-slate-400">{snapshot?.nodes.length ?? 0} cards · {relationsForBoard.length} relations</span>
              <span className={`flex items-center gap-1 text-[10px] ${actionError ? "text-rose-500" : saving ? "text-amber-500" : "text-emerald-600"}`}>{!saving && !actionError ? <Check size={11} /> : null}{actionError ? "Save failed" : saving ? "Saving…" : "Saved"}</span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {snapshot?.nodes.length ? <Button variant="ghost" size="sm" onClick={() => askAgentForItems(snapshot.nodes.map((node) => itemById.get(node.item_id)).filter((item): item is KnowledgeItem => Boolean(item)), "Canvas") }><Bot size={14} />Ask canvas</Button> : null}
          {snapshot ? <Button variant="ghost" size="sm" onClick={() => setManageBoardOpen(true)}><Pencil size={13} />Manage</Button> : null}
          <Button size="sm" onClick={() => setCreateBoardOpen(true)}><Plus size={14} />New canvas</Button>
        </div>
      </header>

      {(loadError || actionError) ? <div role="alert" className="mx-4 mt-4 rounded-[13px] border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{errorMessage(actionError ?? loadError)}</div> : null}

      {!snapshot && !loadError ? (
        <div className="p-7"><EmptyState icon={<LayoutDashboard size={24} />} title="No canvas is selected" description="Create or select a knowledge canvas to arrange papers, notes, concepts, and highlights." actions={<Button onClick={() => setCreateBoardOpen(true)}><Plus size={14} />New canvas</Button>} /></div>
      ) : snapshot ? (
        <div className="grid h-[min(74vh,820px)] min-h-[660px] grid-cols-[210px_minmax(0,1fr)] gap-0 xl:grid-cols-[210px_minmax(0,1fr)_290px]">
          <aside className="min-h-0 border-r border-slate-100 bg-white p-3">
            <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">Card tray</p>
            <label className="mt-3 flex items-center gap-2 rounded-[11px] border border-slate-200 px-2.5 py-2"><Search size={12} className="text-slate-400" /><input value={search} onChange={(event) => setSearch(event.target.value)} className="min-w-0 flex-1 bg-transparent text-[10px] text-slate-700 outline-none placeholder:text-slate-400" placeholder="Find cards…" /></label>
            <p className="mt-2 text-[9px] leading-4 text-slate-400">Drag a card into the canvas, or use the quick actions. The same knowledge object can appear in multiple canvases.</p>
            <div className="ait-scroll-panel mt-3 h-[calc(100%_-_92px)] space-y-2 overflow-y-auto pr-1">
              {trayItems.map((item) => (
                <article key={item.item_id} draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData(knowledgeBoardCardDragType, item.item_id) }} className={`cursor-grab rounded-[12px] border p-2.5 active:cursor-grabbing ${nodeItemIds.has(item.item_id) ? "border-cyan-100 bg-cyan-50/40" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 text-slate-500"><TrayIcon type={item.item_type} /></span>
                    <div className="min-w-0 flex-1"><p className="truncate text-[10px] font-semibold text-slate-800">{item.title}</p><p className="mt-1 text-[9px] capitalize text-slate-400">{item.item_type}{nodeItemIds.has(item.item_id) ? " · On canvas" : ""}</p></div>
                  </div>
                  <div className="mt-2 flex items-center gap-1 border-t border-slate-100 pt-2">
                    {!nodeItemIds.has(item.item_id) ? <button type="button" className="rounded-[7px] px-2 py-1 text-[9px] font-semibold text-slate-600 hover:bg-slate-100" onPointerDown={(event) => event.stopPropagation()} onClick={() => quickAddNode(item.item_id)}><Plus size={10} className="mr-1 inline" />Add</button> : null}
                    <button type="button" className="rounded-[7px] px-2 py-1 text-[9px] font-semibold text-slate-600 hover:bg-slate-100" onPointerDown={(event) => event.stopPropagation()} onClick={() => openLibraryItem(item)}><ExternalLink size={10} className="mr-1 inline" />Open</button>
                  </div>
                </article>
              ))}
            </div>
          </aside>

          <main className="min-w-0 bg-slate-50/60 p-3">
            <KnowledgeBoardCanvas
              items={items}
              nodes={snapshot.nodes}
              relations={relations}
              selectedItemIds={selectedItemIds}
              onSelectionChange={updateSelection}
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

          <aside className="hidden min-h-0 border-l border-slate-100 bg-white p-3 xl:block">
            <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">Knowledge inspector</p>
            <KnowledgeInspector item={selectedItem} relationCount={selectedRelations.length} lastEventType={lastEvent?.item.item_id === selectedItem?.item_id ? lastEvent?.type ?? null : null} onAction={handleKnowledgeAction} relations={selectedRelations.length > 0 ? selectedRelations.map((relation) => (
              <RelationRow key={relation.relation_id} relation={relation} itemById={itemById} deleting={board.deleteRelationMutation.isPending && board.deleteRelationMutation.variables === relation.relation_id} onEdit={() => setEditingRelation(relation)} onDelete={() => board.deleteRelationMutation.mutate(relation.relation_id)} />
            )) : undefined} />
          </aside>
        </div>
      ) : null}

      <KnowledgeBoardCreateDialog open={createBoardOpen} creating={board.createBoardMutation.isPending} onClose={() => !board.createBoardMutation.isPending && setCreateBoardOpen(false)} onCreate={(payload) => board.createBoardMutation.mutate(payload, { onSuccess: () => { updateSelection([]); history.clear(); setCreateBoardOpen(false) } })} />
      <KnowledgeBoardManageDialog board={manageBoardOpen ? snapshot?.board ?? null : null} saving={board.updateBoardMutation.isPending} deleting={board.deleteBoardMutation.isPending} onClose={() => !saving && setManageBoardOpen(false)} onSave={(payload) => snapshot && board.updateBoardMutation.mutate({ boardId: snapshot.board.board_id, payload }, { onSuccess: () => setManageBoardOpen(false) })} onDelete={() => snapshot && board.deleteBoardMutation.mutate(snapshot.board.board_id, { onSuccess: () => { updateSelection([]); history.clear(); setManageBoardOpen(false) } })} />
      <KnowledgeRelationDialog source={relationPair?.source ?? null} target={relationPair?.target ?? null} creating={board.createRelationMutation.isPending} onClose={() => !board.createRelationMutation.isPending && setRelationPair(null)} onCreate={(payload) => board.createRelationMutation.mutate(payload, { onSuccess: () => setRelationPair(null) })} />
      <KnowledgeRelationEditDialog relation={editingRelation} saving={board.updateRelationMutation.isPending} onClose={() => !board.updateRelationMutation.isPending && setEditingRelation(null)} onSave={(payload) => editingRelation && board.updateRelationMutation.mutate({ relationId: editingRelation.relation_id, payload }, { onSuccess: () => setEditingRelation(null) })} />
    </section>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to update the visual knowledge canvas."
}
