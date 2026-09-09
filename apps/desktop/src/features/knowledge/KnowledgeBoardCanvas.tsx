import { Link2, Maximize2, Minus, Plus, Trash2 } from "lucide-react"
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent,
} from "react"

import { knowledgeBoardCardDragType } from "./knowledge-board-dnd"
import {
  boardEdgePath,
  clampBoardZoom,
  DEFAULT_BOARD_VIEWPORT,
  fitBoardNodes,
  screenToBoard,
  type BoardViewport,
} from "./knowledge-board-layout"
import KnowledgeCardRenderer from "./KnowledgeCardRenderer"
import type { KnowledgeBoardNode, KnowledgeItem, KnowledgeRelation } from "./knowledge-types"

const MIN_CARD_WIDTH = 180
const MIN_CARD_HEIGHT = 100
const MAX_CARD_WIDTH = 720
const MAX_CARD_HEIGHT = 600

interface NodeInteraction {
  kind: "move" | "resize"
  itemId: string
  startClientX: number
  startClientY: number
  startNode: KnowledgeBoardNode
}

interface LocalNodeState {
  sourceNodes: KnowledgeBoardNode[]
  nodes: KnowledgeBoardNode[]
}

export default function KnowledgeBoardCanvas({
  items,
  nodes,
  relations,
  selectedItemIds,
  onSelectionChange,
  onAddNode,
  onPersistNode,
  onRemoveNode,
  onLinkRequest,
}: {
  items: KnowledgeItem[]
  nodes: KnowledgeBoardNode[]
  relations: KnowledgeRelation[]
  selectedItemIds: string[]
  onSelectionChange: (itemIds: string[]) => void
  onAddNode: (itemId: string, position: { x: number; y: number }) => void
  onPersistNode: (node: KnowledgeBoardNode) => void
  onRemoveNode: (itemId: string) => void
  onLinkRequest: (sourceItemId: string, targetItemId: string) => void
}) {
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const interactionRef = useRef<NodeInteraction | null>(null)
  const panRef = useRef<{ x: number; y: number; clientX: number; clientY: number } | null>(null)
  const [localNodeState, setLocalNodeState] = useState<LocalNodeState>(() => ({ sourceNodes: nodes, nodes }))
  const [viewport, setViewport] = useState<BoardViewport>(DEFAULT_BOARD_VIEWPORT)
  const [linkingSourceId, setLinkingSourceId] = useState<string | null>(null)

  const localNodes = localNodeState.sourceNodes === nodes ? localNodeState.nodes : nodes
  const itemById = useMemo(() => new Map(items.map((item) => [item.item_id, item] as const)), [items])
  const nodeById = useMemo(() => new Map(localNodes.map((node) => [node.item_id, node] as const)), [localNodes])
  const selectedSet = useMemo(() => new Set(selectedItemIds), [selectedItemIds])

  useEffect(() => {
    function move(event: PointerEvent) {
      const interaction = interactionRef.current
      if (interaction) {
        const dx = (event.clientX - interaction.startClientX) / viewport.zoom
        const dy = (event.clientY - interaction.startClientY) / viewport.zoom
        setLocalNodeState((current) => {
          const baseNodes = current.sourceNodes === nodes ? current.nodes : nodes
          return {
            sourceNodes: nodes,
            nodes: baseNodes.map((node) => {
              if (node.item_id !== interaction.itemId) return node
              if (interaction.kind === "move") {
                return { ...node, x: interaction.startNode.x + dx, y: interaction.startNode.y + dy }
              }
              return {
                ...node,
                width: Math.min(MAX_CARD_WIDTH, Math.max(MIN_CARD_WIDTH, interaction.startNode.width + dx)),
                height: Math.min(MAX_CARD_HEIGHT, Math.max(MIN_CARD_HEIGHT, interaction.startNode.height + dy)),
              }
            }),
          }
        })
        return
      }

      const pan = panRef.current
      if (!pan) return
      setViewport((current) => ({
        ...current,
        x: pan.x + event.clientX - pan.clientX,
        y: pan.y + event.clientY - pan.clientY,
      }))
    }

    function up() {
      const interaction = interactionRef.current
      if (interaction) {
        const node = localNodes.find((candidate) => candidate.item_id === interaction.itemId)
        if (node) onPersistNode(node)
      }
      interactionRef.current = null
      panRef.current = null
    }

    window.addEventListener("pointermove", move)
    window.addEventListener("pointerup", up)
    return () => {
      window.removeEventListener("pointermove", move)
      window.removeEventListener("pointerup", up)
    }
  }, [localNodes, nodes, onPersistNode, viewport.zoom])

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setLinkingSourceId(null)
        return
      }
      if (event.key !== "Delete" && event.key !== "Backspace") return
      const target = event.target as HTMLElement | null
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return
      if (selectedItemIds.length === 0) return
      event.preventDefault()
      selectedItemIds.forEach(onRemoveNode)
      onSelectionChange([])
    }

    window.addEventListener("keydown", keydown)
    return () => window.removeEventListener("keydown", keydown)
  }, [onRemoveNode, onSelectionChange, selectedItemIds])

  function beginNodeInteraction(
    event: ReactPointerEvent,
    node: KnowledgeBoardNode,
    kind: NodeInteraction["kind"],
  ) {
    event.stopPropagation()
    interactionRef.current = {
      kind,
      itemId: node.item_id,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startNode: { ...node },
    }
  }

  function selectNode(event: MouseEvent, itemId: string) {
    event.stopPropagation()
    if (linkingSourceId && linkingSourceId !== itemId) {
      onLinkRequest(linkingSourceId, itemId)
      setLinkingSourceId(null)
      return
    }
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      onSelectionChange(
        selectedSet.has(itemId)
          ? selectedItemIds.filter((id) => id !== itemId)
          : [...selectedItemIds, itemId],
      )
      return
    }
    onSelectionChange([itemId])
  }

  function handleCanvasPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return
    const target = event.target as HTMLElement
    if (target.closest("[data-knowledge-node], button")) return
    onSelectionChange([])
    setLinkingSourceId(null)
    panRef.current = {
      x: viewport.x,
      y: viewport.y,
      clientX: event.clientX,
      clientY: event.clientY,
    }
  }

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    event.preventDefault()
    const bounds = canvasRef.current?.getBoundingClientRect()
    if (!bounds) return
    const before = screenToBoard(
      event.clientX,
      event.clientY,
      { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height },
      viewport,
    )
    const nextZoom = clampBoardZoom(viewport.zoom * (event.deltaY < 0 ? 1.08 : 0.92))
    setViewport({
      zoom: nextZoom,
      x: event.clientX - bounds.left - before.x * nextZoom,
      y: event.clientY - bounds.top - before.y * nextZoom,
    })
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    const itemId = event.dataTransfer.getData(knowledgeBoardCardDragType)
    if (!itemId || nodeById.has(itemId)) return
    const bounds = canvasRef.current?.getBoundingClientRect()
    if (!bounds) return
    const position = screenToBoard(
      event.clientX,
      event.clientY,
      { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height },
      viewport,
    )
    onAddNode(itemId, { x: position.x - 124, y: position.y - 78 })
  }

  function fitView() {
    const bounds = canvasRef.current?.getBoundingClientRect()
    if (!bounds) return
    setViewport(fitBoardNodes(localNodes, bounds.width, bounds.height))
  }

  const visibleRelations = relations.filter(
    (relation) => nodeById.has(relation.source_item_id) && nodeById.has(relation.target_item_id),
  )

  return (
    <div className="relative h-full min-h-[620px] overflow-hidden rounded-[18px] border border-slate-200 bg-slate-50" data-testid="knowledge-board-canvas">
      <div className="absolute left-3 top-3 z-30 flex items-center gap-1 rounded-[12px] border border-slate-200 bg-white/95 p-1 shadow-sm backdrop-blur">
        <button type="button" className="flex h-8 w-8 items-center justify-center rounded-[8px] text-slate-500 hover:bg-slate-100" aria-label="Zoom out" onClick={() => setViewport((current) => ({ ...current, zoom: clampBoardZoom(current.zoom / 1.15) }))}><Minus size={14} /></button>
        <span className="min-w-12 text-center text-[10px] font-semibold text-slate-500">{Math.round(viewport.zoom * 100)}%</span>
        <button type="button" className="flex h-8 w-8 items-center justify-center rounded-[8px] text-slate-500 hover:bg-slate-100" aria-label="Zoom in" onClick={() => setViewport((current) => ({ ...current, zoom: clampBoardZoom(current.zoom * 1.15) }))}><Plus size={14} /></button>
        <button type="button" className="flex h-8 w-8 items-center justify-center rounded-[8px] text-slate-500 hover:bg-slate-100" aria-label="Fit board" onClick={fitView}><Maximize2 size={14} /></button>
      </div>

      {linkingSourceId ? (
        <div className="absolute left-1/2 top-3 z-30 -translate-x-1/2 rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-[10px] font-semibold text-cyan-800 shadow-sm">
          Select a target card to create a relation · Esc/canvas to cancel
        </div>
      ) : null}

      <div
        ref={canvasRef}
        className="absolute inset-0 cursor-grab overflow-hidden active:cursor-grabbing"
        onPointerDown={handleCanvasPointerDown}
        onWheel={handleWheel}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
        style={{
          backgroundImage: "radial-gradient(circle, rgba(100,116,139,0.22) 1px, transparent 1px)",
          backgroundPosition: `${viewport.x}px ${viewport.y}px`,
          backgroundSize: `${24 * viewport.zoom}px ${24 * viewport.zoom}px`,
        }}
      >
        <div className="absolute left-0 top-0 origin-top-left" style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})` }}>
          <svg className="pointer-events-none absolute left-0 top-0 overflow-visible" width="1" height="1" aria-hidden="true">
            <defs><marker id="knowledge-edge-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" className="fill-slate-400" /></marker></defs>
            {visibleRelations.map((relation) => {
              const source = nodeById.get(relation.source_item_id)
              const target = nodeById.get(relation.target_item_id)
              if (!source || !target) return null
              const edge = boardEdgePath(source, target)
              return (
                <g key={relation.relation_id}>
                  <path d={edge.path} fill="none" stroke="rgb(148 163 184)" strokeWidth="1.5" markerEnd="url(#knowledge-edge-arrow)" />
                  <text x={edge.labelX} y={edge.labelY - 7} textAnchor="middle" className="fill-slate-500 text-[10px] font-semibold">{relation.label || relation.relation_type.replaceAll("_", " ")}</text>
                </g>
              )
            })}
          </svg>

          {localNodes.map((node) => {
            const item = itemById.get(node.item_id)
            if (!item) return null
            const selected = selectedSet.has(node.item_id)
            return (
              <article
                key={node.item_id}
                data-knowledge-node
                className={`absolute select-none overflow-hidden rounded-[18px] border bg-white shadow-[0_10px_30px_rgba(15,23,42,0.08)] transition-shadow ${selected ? "border-cyan-400 ring-2 ring-cyan-100" : "border-slate-200 hover:border-slate-300"}`}
                style={{ left: node.x, top: node.y, width: node.width, height: node.height, zIndex: selected ? Math.max(node.z_index, 1000) : node.z_index }}
                onClick={(event) => selectNode(event, node.item_id)}
              >
                <div
                  className="absolute left-0 right-20 top-0 z-10 h-12 cursor-move"
                  aria-hidden="true"
                  onPointerDown={(event) => beginNodeInteraction(event, node, "move")}
                />
                <KnowledgeCardRenderer item={item} />
                <div className="absolute right-2 top-2 z-20 flex items-center gap-1">
                  <button
                    type="button"
                    className={`flex h-7 w-7 items-center justify-center rounded-[8px] transition ${linkingSourceId === item.item_id ? "bg-cyan-100 text-cyan-800" : "text-slate-400 hover:bg-slate-100 hover:text-slate-700"}`}
                    title="Connect card"
                    aria-label={`Connect ${item.title}`}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.stopPropagation()
                      setLinkingSourceId((current) => current === item.item_id ? null : item.item_id)
                    }}
                  >
                    <Link2 size={13} />
                  </button>
                  <button
                    type="button"
                    className="flex h-7 w-7 items-center justify-center rounded-[8px] text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                    title="Remove from canvas"
                    aria-label={`Remove ${item.title} from canvas`}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.stopPropagation()
                      onRemoveNode(item.item_id)
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
                <button
                  type="button"
                  className="absolute bottom-0 right-0 z-20 h-5 w-5 cursor-se-resize rounded-tl-[8px] text-transparent"
                  aria-label={`Resize ${item.title}`}
                  onPointerDown={(event) => beginNodeInteraction(event, node, "resize")}
                >
                  Resize
                </button>
              </article>
            )
          })}
        </div>
      </div>

      {localNodes.length === 0 ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="max-w-sm rounded-[18px] border border-dashed border-slate-300 bg-white/80 px-6 py-5 text-center shadow-sm backdrop-blur">
            <p className="text-sm font-semibold text-slate-800">Build your knowledge canvas</p>
            <p className="mt-2 text-xs leading-5 text-slate-500">Drag a paper, note, concept, or highlight from the left tray. Arrange cards visually and connect related knowledge.</p>
          </div>
        </div>
      ) : null}

      <div className="absolute bottom-3 right-3 z-30 h-28 w-40 overflow-hidden rounded-[12px] border border-slate-200 bg-white/90 shadow-sm backdrop-blur" aria-label="Board minimap">
        <div className="relative h-full w-full bg-slate-50">
          {localNodes.length > 0 ? (() => {
            const minX = Math.min(...localNodes.map((node) => node.x))
            const minY = Math.min(...localNodes.map((node) => node.y))
            const maxX = Math.max(...localNodes.map((node) => node.x + node.width))
            const maxY = Math.max(...localNodes.map((node) => node.y + node.height))
            const scale = Math.min(132 / Math.max(1, maxX - minX), 84 / Math.max(1, maxY - minY), 0.25)
            return localNodes.map((node) => (
              <span
                key={node.item_id}
                className={`absolute rounded-[2px] ${selectedSet.has(node.item_id) ? "bg-cyan-500" : "bg-slate-400"}`}
                style={{
                  left: 4 + (node.x - minX) * scale,
                  top: 4 + (node.y - minY) * scale,
                  width: Math.max(4, node.width * scale),
                  height: Math.max(3, node.height * scale),
                }}
              />
            ))
          })() : null}
        </div>
      </div>
    </div>
  )
}
