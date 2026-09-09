import {
  BookOpenText,
  FileText,
  Highlighter,
  LayoutDashboard,
  Lightbulb,
  Link2,
  Plus,
  Search,
  StickyNote,
  Trash2,
} from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "../../shared/ui/Button"
import { EmptyState } from "../../shared/ui/EmptyState"
import type { KnowledgeAction } from "./KnowledgeActionMenu"
import { knowledgeBoardCardDragType } from "./knowledge-board-dnd"
import KnowledgeBoardCanvas from "./KnowledgeBoardCanvas"
import { KnowledgeBoardCreateDialog } from "./KnowledgeBoardCreateDialog"
import KnowledgeInspector from "./KnowledgeInspector"
import { KnowledgeRelationDialog } from "./KnowledgeRelationDialog"
import { dispatchKnowledgeAction } from "./knowledge-action-dispatcher"
import type {
  KnowledgeBoardNode,
  KnowledgeItem,
  KnowledgeItemType,
  KnowledgeRelation,
} from "./knowledge-types"
import { emitKnowledgeWorkspaceEvent, type KnowledgeWorkspaceEvent } from "./knowledge-workspace-events"
import { useOptionalKnowledgeWorkspaceContext } from "./knowledge-workspace-provider"
import type { KnowledgeBoardController } from "./useKnowledgeBoard"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

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
  onDelete,
}: {
  relation: KnowledgeRelation
  itemById: Map<string, KnowledgeItem>
  deleting: boolean
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
        <button
          type="button"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px] text-slate-400 hover:bg-rose-50 hover:text-rose-600"
          aria-label="Delete relation"
          disabled={deleting}
          onClick={onDelete}
        >
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  )
}

export default function KnowledgeBoardPanel({
  library,
  board,
}: {
  library: KnowledgeLibraryController
  board: KnowledgeBoardController
}) {
  const items = library.itemsQuery.data?.items ?? EMPTY_ITEMS
  const boards = board.boardsQuery.data?.boards ?? []
  const snapshot = board.boardQuery.data
  const relations = board.relationsQuery.data?.relations ?? []
  const workspaceContext = useOptionalKnowledgeWorkspaceContext()
  const [search, setSearch] = useState("")
  const [fallbackSelectedIds, setFallbackSelectedIds] = useState<string[]>([])
  const [fallbackLastEvent, setFallbackLastEvent] = useState<KnowledgeWorkspaceEvent | null>(null)
  const [createBoardOpen, setCreateBoardOpen] = useState(false)
  const [relationPair, setRelationPair] = useState<{ source: KnowledgeItem; target: KnowledgeItem } | null>(null)

  const itemById = useMemo(
    () => new Map(items.map((item) => [item.item_id, item] as const)),
    [items],
  )
  const nodeItemIds = useMemo(
    () => new Set((snapshot?.nodes ?? []).map((node) => node.item_id)),
    [snapshot?.nodes],
  )
  const selectionSource = workspaceContext?.selectedKnowledgeIds ?? fallbackSelectedIds
  const selectedItemIds = selectionSource.filter((itemId) => nodeItemIds.has(itemId))

  const trayItems = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase()
    return items.filter((item) => (
      !normalized
      || [item.title, item.summary, item.item_type]
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalized)
    ))
  }, [items, search])

  const selectedItem = selectedItemIds.length === 1
    ? itemById.get(selectedItemIds[0]) ?? null
    : null
  const selectedRelations = selectedItem
    ? relations.filter((relation) => (
      relation.source_item_id === selectedItem.item_id
      || relation.target_item_id === selectedItem.item_id
    ))
    : []
  const relationsForBoard = relations.filter((relation) => (
    nodeItemIds.has(relation.source_item_id)
    && nodeItemIds.has(relation.target_item_id)
  ))
  const lastEvent = workspaceContext?.lastEvent ?? fallbackLastEvent
  const loadError = library.itemsQuery.error
    ?? board.boardsQuery.error
    ?? board.boardQuery.error
    ?? board.relationsQuery.error
  const actionError = board.upsertNodeMutation.error
    ?? board.removeNodeMutation.error
    ?? board.createRelationMutation.error
    ?? board.deleteRelationMutation.error
    ?? board.createBoardMutation.error

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
      payload: {
        x: position.x,
        y: position.y,
        width: 248,
        height: 156,
        z_index: (snapshot?.nodes.length ?? 0) + 1,
      },
    })
  }

  function persistNode(node: KnowledgeBoardNode) {
    board.upsertNodeMutation.mutate({
      itemId: node.item_id,
      payload: {
        x: node.x,
        y: node.y,
        width: node.width,
        height: node.height,
        collapsed: node.collapsed,
        z_index: node.z_index,
      },
    })
  }

  function removeNode(itemId: string) {
    updateSelection(selectedItemIds.filter((candidate) => candidate !== itemId))
    board.removeNodeMutation.mutate(itemId)
  }

  function requestRelation(sourceItemId: string, targetItemId: string) {
    const source = itemById.get(sourceItemId)
    const target = itemById.get(targetItemId)
    if (!source || !target) return
    setRelationPair({ source, target })
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

  if (
    library.itemsQuery.isPending
    || board.boardsQuery.isPending
    || (board.activeBoardId && board.boardQuery.isPending)
  ) {
    return (
      <section className="ait-surface h-[720px] overflow-hidden p-5" aria-busy="true" aria-label="Loading visual knowledge board">
        <div className="ait-skeleton h-10 w-full rounded-[14px]" />
        <div className="mt-4 grid h-[640px] grid-cols-[210px_1fr] gap-3">
          <div className="ait-skeleton rounded-[18px]" />
          <div className="ait-skeleton rounded-[18px]" />
        </div>
      </section>
    )
  }

  return (
    <section className="ait-surface overflow-hidden">
      <header className="flex flex-col gap-3 border-b border-slate-100 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[13px] bg-slate-950 text-white">
            <LayoutDashboard size={17} />
          </span>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Visual knowledge canvas</p>
            <div className="mt-1 flex items-center gap-2">
              <select
                value={board.activeBoardId ?? ""}
                onChange={(event) => {
                  updateSelection([])
                  board.setActiveBoardId(event.target.value || null)
                }}
                className="max-w-xs truncate bg-transparent text-base font-semibold text-slate-950 outline-none"
              >
                {boards.map((candidate) => (
                  <option key={candidate.board_id} value={candidate.board_id}>{candidate.name}</option>
                ))}
              </select>
              <span className="text-[10px] text-slate-400">
                {snapshot?.nodes.length ?? 0} cards · {relationsForBoard.length} relations
              </span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setCreateBoardOpen(true)}><Plus size={14} />New canvas</Button>
        </div>
      </header>

      {(loadError || actionError) ? (
        <div role="alert" className="mx-4 mt-4 rounded-[13px] border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {errorMessage(actionError ?? loadError)}
        </div>
      ) : null}

      {!snapshot && !loadError ? (
        <div className="p-7">
          <EmptyState
            icon={<LayoutDashboard size={24} />}
            title="No canvas is selected"
            description="Create or select a knowledge canvas to arrange papers, notes, concepts, and highlights."
            actions={<Button onClick={() => setCreateBoardOpen(true)}><Plus size={14} />New canvas</Button>}
          />
        </div>
      ) : snapshot ? (
        <div className="grid h-[min(74vh,820px)] min-h-[660px] grid-cols-[210px_minmax(0,1fr)] gap-0 xl:grid-cols-[210px_minmax(0,1fr)_290px]">
          <aside className="min-h-0 border-r border-slate-100 bg-white p-3">
            <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">Card tray</p>
            <label className="mt-3 flex items-center gap-2 rounded-[11px] border border-slate-200 px-2.5 py-2">
              <Search size={12} className="text-slate-400" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-[10px] text-slate-700 outline-none placeholder:text-slate-400"
                placeholder="Find cards…"
              />
            </label>
            <p className="mt-2 text-[9px] leading-4 text-slate-400">
              Drag a card into the canvas. The same knowledge object can appear in multiple canvases.
            </p>
            <div className="ait-scroll-panel mt-3 h-[calc(100%_-_92px)] space-y-2 overflow-y-auto pr-1">
              {trayItems.map((item) => (
                <article
                  key={item.item_id}
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = "copy"
                    event.dataTransfer.setData(knowledgeBoardCardDragType, item.item_id)
                  }}
                  className={`cursor-grab rounded-[12px] border p-2.5 active:cursor-grabbing ${nodeItemIds.has(item.item_id) ? "border-cyan-100 bg-cyan-50/40" : "border-slate-200 bg-white hover:border-slate-300"}`}
                >
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 text-slate-500"><TrayIcon type={item.item_type} /></span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[10px] font-semibold text-slate-800">{item.title}</p>
                      <p className="mt-1 text-[9px] capitalize text-slate-400">
                        {item.item_type}{nodeItemIds.has(item.item_id) ? " · On canvas" : ""}
                      </p>
                    </div>
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
            />
          </main>

          <aside className="hidden min-h-0 border-l border-slate-100 bg-white p-3 xl:block">
            <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">Knowledge inspector</p>
            <KnowledgeInspector
              item={selectedItem}
              relationCount={selectedRelations.length}
              lastEventType={lastEvent?.item.item_id === selectedItem?.item_id ? lastEvent?.type ?? null : null}
              onAction={handleKnowledgeAction}
              relations={selectedRelations.length > 0 ? selectedRelations.map((relation) => (
                <RelationRow
                  key={relation.relation_id}
                  relation={relation}
                  itemById={itemById}
                  deleting={
                    board.deleteRelationMutation.isPending
                    && board.deleteRelationMutation.variables === relation.relation_id
                  }
                  onDelete={() => board.deleteRelationMutation.mutate(relation.relation_id)}
                />
              )) : undefined}
            />
          </aside>
        </div>
      ) : null}

      <KnowledgeBoardCreateDialog
        open={createBoardOpen}
        creating={board.createBoardMutation.isPending}
        onClose={() => !board.createBoardMutation.isPending && setCreateBoardOpen(false)}
        onCreate={(payload) => board.createBoardMutation.mutate(payload, {
          onSuccess: () => {
            updateSelection([])
            setCreateBoardOpen(false)
          },
        })}
      />
      <KnowledgeRelationDialog
        source={relationPair?.source ?? null}
        target={relationPair?.target ?? null}
        creating={board.createRelationMutation.isPending}
        onClose={() => !board.createRelationMutation.isPending && setRelationPair(null)}
        onCreate={(payload) => board.createRelationMutation.mutate(payload, {
          onSuccess: () => setRelationPair(null),
        })}
      />
    </section>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to update the visual knowledge canvas."
}
