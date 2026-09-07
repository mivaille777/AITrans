import {
  ArrowDownLeft,
  ArrowUpRight,
  BookOpenText,
  CircleDot,
  Filter,
  Focus,
  Highlighter,
  Lightbulb,
  Link2,
  Network,
  Save,
  StickyNote,
  Trash2,
} from "lucide-react"
import { useEffect, useMemo, useState, type ReactNode } from "react"

import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import {
  ALL_KNOWLEDGE_ITEM_TYPES,
  ALL_KNOWLEDGE_RELATION_ORIGINS,
  buildLocalKnowledgeGraph,
  localGraphRelationTypes,
} from "./knowledge-graph-state"
import type {
  KnowledgeItem,
  KnowledgeItemType,
  KnowledgeRelation,
  KnowledgeRelationOrigin,
} from "./knowledge-types"
import type { KnowledgeBoardController } from "./useKnowledgeBoard"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

const itemTypeLabels: Record<KnowledgeItemType, string> = {
  paper: "Papers",
  note: "Notes",
  concept: "Concepts",
  highlight: "Highlights",
  document: "Documents",
  web: "Web",
}

const originLabels: Record<KnowledgeRelationOrigin, string> = {
  manual: "Manual",
  imported: "Imported",
  ai: "AI",
  citation: "Citation",
  rag: "RAG",
}

export default function KnowledgeGraphPanel({
  library,
  board,
  focusItemId,
  onFocusChange,
  onOpenItem,
}: {
  library: KnowledgeLibraryController
  board: KnowledgeBoardController
  focusItemId: string
  onFocusChange: (itemId: string) => void
  onOpenItem: (item: KnowledgeItem) => void
}) {
  const items = library.itemsQuery.data?.items ?? []
  const relations = board.relationsQuery.data?.relations ?? []
  const [depth, setDepth] = useState<1 | 2 | 3>(1)
  const [visibleItemTypes, setVisibleItemTypes] = useState<KnowledgeItemType[]>(ALL_KNOWLEDGE_ITEM_TYPES)
  const [visibleOrigins, setVisibleOrigins] = useState<KnowledgeRelationOrigin[]>(ALL_KNOWLEDGE_RELATION_ORIGINS)
  const [relationType, setRelationType] = useState("all")
  const [selectedItemId, setSelectedItemId] = useState(focusItemId)
  const [selectedRelationId, setSelectedRelationId] = useState("")

  const resolvedFocusId = items.some((item) => item.item_id === focusItemId)
    ? focusItemId
    : items.find((item) => item.item_type === "paper")?.item_id ?? items[0]?.item_id ?? ""
  const relationTypes = useMemo(() => localGraphRelationTypes(relations), [relations])
  const snapshot = useMemo(() => buildLocalKnowledgeGraph(items, relations, resolvedFocusId, depth, {
    itemTypes: visibleItemTypes,
    relationTypes: relationType === "all" ? [] : [relationType],
    origins: visibleOrigins,
  }), [depth, items, relationType, relations, resolvedFocusId, visibleItemTypes, visibleOrigins])
  const positions = useMemo(() => layoutGraph(snapshot.nodes.map((node) => ({ id: node.item.item_id, depth: node.depth }))), [snapshot.nodes])
  const itemById = useMemo(() => new Map(items.map((item) => [item.item_id, item] as const)), [items])
  const selectedItem = itemById.get(selectedItemId) ?? snapshot.focus
  const selectedRelation = snapshot.edges.find((edge) => edge.relation.relation_id === selectedRelationId)?.relation ?? null

  useEffect(() => {
    setSelectedItemId(resolvedFocusId)
    setSelectedRelationId("")
  }, [resolvedFocusId])

  useEffect(() => {
    if (relationType !== "all" && !relationTypes.includes(relationType)) setRelationType("all")
  }, [relationType, relationTypes])

  if (library.itemsQuery.isPending || board.relationsQuery.isPending) {
    return <section className="ait-surface min-h-[660px] p-7" aria-busy="true"><div className="ait-skeleton h-5 w-44 rounded-full" /><div className="ait-skeleton mt-5 h-[560px] rounded-[18px]" /></section>
  }

  if (items.length === 0) {
    return <section className="ait-surface min-h-[560px] p-8 text-center"><Network size={30} className="mx-auto mt-20 text-slate-300" /><h2 className="mt-4 text-lg font-semibold text-slate-900">No knowledge graph yet</h2><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">Import a paper or create knowledge cards first. Existing Reader and Board relations will appear here automatically.</p></section>
  }

  return (
    <section className="ait-surface overflow-hidden">
      <header className="flex flex-col gap-4 border-b border-slate-200/70 px-5 py-5 lg:flex-row lg:items-center lg:justify-between lg:px-6">
        <div>
          <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400"><Network size={12} />Local knowledge graph</p>
          <h2 className="mt-1.5 text-xl font-semibold tracking-tight text-slate-950">Explore relations around one knowledge object</h2>
          <p className="mt-1.5 text-xs leading-5 text-slate-500">The graph reads the canonical relation store directly. Board placement is not required.</p>
        </div>
        <label className="min-w-0 lg:w-80"><span className="sr-only">Graph focus</span><select value={resolvedFocusId} onChange={(event) => onFocusChange(event.target.value)} className="w-full rounded-[13px] border border-slate-200 bg-white px-3 py-2.5 text-xs font-semibold text-slate-700 outline-none focus:border-cyan-300">{items.slice().sort((a, b) => a.title.localeCompare(b.title)).map((item) => <option key={item.item_id} value={item.item_id}>{item.item_type} · {item.title}</option>)}</select></label>
      </header>

      <div className="grid min-h-[680px] xl:h-[calc(100vh-220px)] xl:min-h-[680px] xl:grid-cols-[230px_minmax(0,1fr)_310px] xl:grid-rows-[minmax(0,1fr)]">
        <aside className="border-b border-slate-200/70 bg-slate-50/45 p-4 xl:border-b-0 xl:border-r">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400"><Filter size={12} />Graph filters</div>
          <FilterSection label="Depth"><div className="grid grid-cols-3 gap-1 rounded-[10px] bg-slate-100 p-1">{([1, 2, 3] as const).map((value) => <button key={value} type="button" className={`rounded-[8px] py-1.5 text-[10px] font-semibold ${depth === value ? "bg-white text-slate-800 shadow-sm" : "text-slate-500"}`} onClick={() => setDepth(value)}>{value}</button>)}</div></FilterSection>
          <FilterSection label="Relation type"><select value={relationType} onChange={(event) => setRelationType(event.target.value)} className="w-full rounded-[10px] border border-slate-200 bg-white px-2.5 py-2 text-[11px] text-slate-600 outline-none"><option value="all">All relation types</option>{relationTypes.map((type) => <option key={type} value={type}>{type.replaceAll("_", " ")}</option>)}</select></FilterSection>
          <FilterSection label="Knowledge types"><div className="space-y-1">{ALL_KNOWLEDGE_ITEM_TYPES.map((type) => <FilterToggle key={type} checked={visibleItemTypes.includes(type)} label={itemTypeLabels[type]} onChange={() => setVisibleItemTypes(toggleValue(visibleItemTypes, type))} />)}</div></FilterSection>
          <FilterSection label="Origins"><div className="space-y-1">{ALL_KNOWLEDGE_RELATION_ORIGINS.map((origin) => <FilterToggle key={origin} checked={visibleOrigins.includes(origin)} label={originLabels[origin]} onChange={() => setVisibleOrigins(toggleValue(visibleOrigins, origin))} />)}</div></FilterSection>
          <div className="mt-5 rounded-[12px] border border-slate-200 bg-white p-3 text-[10px] leading-5 text-slate-500"><span className="font-semibold text-slate-700">{snapshot.nodes.length}</span> nodes · <span className="font-semibold text-slate-700">{snapshot.edges.length}</span> relations<br />Double-click a node to make it the new focus.</div>
        </aside>

        <main className="relative min-h-[560px] overflow-hidden border-b border-slate-200/70 bg-slate-50/30 xl:border-b-0 xl:border-r" aria-label="Local knowledge graph canvas">
          {snapshot.edges.length === 0 && snapshot.nodes.length === 1 && <div className="pointer-events-none absolute left-1/2 top-6 z-20 -translate-x-1/2 rounded-full border border-slate-200 bg-white/90 px-3 py-1.5 text-[10px] text-slate-500 shadow-sm">No visible relations for the current filters.</div>}
          <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
            <defs><marker id="local-graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" className="fill-slate-400" /></marker></defs>
            {snapshot.edges.map((edge) => {
              const source = positions.get(edge.source.item_id)
              const target = positions.get(edge.target.item_id)
              if (!source || !target) return null
              const selected = selectedRelationId === edge.relation.relation_id
              return <g key={edge.relation.relation_id} className="pointer-events-auto cursor-pointer" onClick={() => { setSelectedRelationId(edge.relation.relation_id); setSelectedItemId("") }}><line x1={`${source.x}%`} y1={`${source.y}%`} x2={`${target.x}%`} y2={`${target.y}%`} stroke={selected ? "rgb(8 145 178)" : "rgb(148 163 184)"} strokeWidth={selected ? 2.5 : 1.5} markerEnd="url(#local-graph-arrow)" /><text x={`${(source.x + target.x) / 2}%`} y={`${(source.y + target.y) / 2}%`} textAnchor="middle" dy="-6" className={`${selected ? "fill-cyan-700" : "fill-slate-500"} text-[10px] font-semibold`}>{edge.relation.label || edge.relation.relation_type.replaceAll("_", " ")}</text></g>
            })}
          </svg>
          {snapshot.nodes.map((node) => {
            const position = positions.get(node.item.item_id)
            if (!position) return null
            const focus = node.item.item_id === resolvedFocusId
            const selected = node.item.item_id === selectedItem?.item_id && !selectedRelation
            return <button key={node.item.item_id} type="button" className={`absolute z-10 w-40 -translate-x-1/2 -translate-y-1/2 rounded-[16px] border bg-white p-3 text-left shadow-[0_8px_24px_rgba(15,23,42,0.08)] transition hover:-translate-y-[53%] hover:shadow-[0_12px_30px_rgba(15,23,42,0.12)] ${focus ? "border-cyan-400 ring-2 ring-cyan-100" : selected ? "border-slate-400 ring-2 ring-slate-100" : "border-slate-200"}`} style={{ left: `${position.x}%`, top: `${position.y}%` }} onClick={() => { setSelectedItemId(node.item.item_id); setSelectedRelationId("") }} onDoubleClick={() => onFocusChange(node.item.item_id)}><div className="flex items-center gap-2"><span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px] ${focus ? "bg-cyan-50 text-cyan-700" : "bg-slate-50 text-slate-600"}`}>{itemIcon(node.item.item_type)}</span><div className="min-w-0"><p className="text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-400">{node.item.item_type} · d{node.depth}</p><p className="mt-0.5 line-clamp-2 text-[11px] font-semibold leading-4 text-slate-800">{node.item.title}</p></div></div><div className="mt-2 flex items-center gap-2 text-[9px] text-slate-400"><span>↑ {node.inboundCount}</span><span>↓ {node.outboundCount}</span>{focus && <span className="ml-auto font-semibold text-cyan-700">Focus</span>}</div></button>
          })}
        </main>

        <aside className="ait-scroll-panel min-h-0 overflow-y-auto bg-white p-4">
          <RelationInspector
            focusItemId={resolvedFocusId}
            selectedItem={selectedItem ?? null}
            selectedRelation={selectedRelation}
            items={items}
            relations={snapshot.edges.map((edge) => edge.relation)}
            board={board}
            onSelectItem={(itemId) => { setSelectedItemId(itemId); setSelectedRelationId("") }}
            onSelectRelation={(relationId) => { setSelectedRelationId(relationId); setSelectedItemId("") }}
            onFocusChange={onFocusChange}
            onOpenItem={onOpenItem}
          />
        </aside>
      </div>
    </section>
  )
}

function RelationInspector({
  focusItemId,
  selectedItem,
  selectedRelation,
  items,
  relations,
  board,
  onSelectItem,
  onSelectRelation,
  onFocusChange,
  onOpenItem,
}: {
  focusItemId: string
  selectedItem: KnowledgeItem | null
  selectedRelation: KnowledgeRelation | null
  items: KnowledgeItem[]
  relations: KnowledgeRelation[]
  board: KnowledgeBoardController
  onSelectItem: (itemId: string) => void
  onSelectRelation: (relationId: string) => void
  onFocusChange: (itemId: string) => void
  onOpenItem: (item: KnowledgeItem) => void
}) {
  const itemById = useMemo(() => new Map(items.map((item) => [item.item_id, item] as const)), [items])
  const [draftType, setDraftType] = useState("")
  const [draftLabel, setDraftLabel] = useState("")

  useEffect(() => {
    setDraftType(selectedRelation?.relation_type ?? "")
    setDraftLabel(selectedRelation?.label ?? "")
  }, [selectedRelation?.relation_id, selectedRelation?.label, selectedRelation?.relation_type])

  if (selectedRelation) {
    const source = itemById.get(selectedRelation.source_item_id)
    const target = itemById.get(selectedRelation.target_item_id)
    const workflowRelation = Boolean(source && typeof source.metadata.provenance === "string" && source.metadata.provenance.startsWith("paper_reader"))
    const editable = selectedRelation.origin === "manual" && !workflowRelation
    return <div><InspectorTitle icon={<Link2 size={14} />} eyebrow="Relation inspector" title={selectedRelation.label || selectedRelation.relation_type.replaceAll("_", " ")} /><div className="mt-4 space-y-3"><RelationEndpoint label="Source" item={source} onSelect={onSelectItem} /><div className="flex justify-center text-slate-300"><ArrowDownLeft size={15} className="rotate-[-45deg]" /></div><RelationEndpoint label="Target" item={target} onSelect={onSelectItem} /></div><div className="mt-5 grid grid-cols-2 gap-2"><MetaCard label="Origin" value={workflowRelation ? "Reader workflow" : originLabels[selectedRelation.origin]} /><MetaCard label="Confidence" value={selectedRelation.confidence == null ? "—" : `${Math.round(selectedRelation.confidence * 100)}%`} /></div>{editable ? <div className="mt-5 space-y-3 border-t border-slate-100 pt-4"><label className="block text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Relation type<input value={draftType} onChange={(event) => setDraftType(event.target.value)} className="mt-2 w-full rounded-[10px] border border-slate-200 px-2.5 py-2 text-xs font-normal text-slate-700 outline-none focus:border-cyan-300" /></label><label className="block text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Label<input value={draftLabel} onChange={(event) => setDraftLabel(event.target.value)} className="mt-2 w-full rounded-[10px] border border-slate-200 px-2.5 py-2 text-xs font-normal text-slate-700 outline-none focus:border-cyan-300" /></label><div className="flex gap-2"><Button size="xs" variant="primary" disabled={board.updateRelationMutation.isPending || !draftType.trim()} onClick={() => board.updateRelationMutation.mutate({ relationId: selectedRelation.relation_id, payload: { relation_type: draftType.trim(), label: draftLabel.trim() } })}><Save size={11} />Save</Button><Button size="xs" variant="ghost" disabled={board.deleteRelationMutation.isPending} onClick={() => board.deleteRelationMutation.mutate(selectedRelation.relation_id)}><Trash2 size={11} />Delete</Button></div></div> : <p className="mt-5 rounded-[12px] border border-slate-200 bg-slate-50 p-3 text-[10px] leading-5 text-slate-500">This relation is provenance or system evidence. It is read-only here so the graph cannot silently rewrite how a knowledge object was produced.</p>}</div>
  }

  if (!selectedItem) return <div className="text-xs text-slate-500">Select a node or relation.</div>
  const connected = relations.filter((relation) => relation.source_item_id === selectedItem.item_id || relation.target_item_id === selectedItem.item_id)
  return <div><InspectorTitle icon={<CircleDot size={14} />} eyebrow="Knowledge object" title={selectedItem.title} /><div className="mt-3 flex flex-wrap gap-1.5"><Badge>{selectedItem.item_type}</Badge>{selectedItem.item_id === focusItemId && <Badge tone="info">focus</Badge>}</div><p className="mt-4 line-clamp-6 whitespace-pre-wrap text-xs leading-6 text-slate-500">{selectedItem.summary || "No summary yet."}</p><div className="mt-4 flex flex-wrap gap-2"><Button size="xs" disabled={selectedItem.item_id === focusItemId} onClick={() => onFocusChange(selectedItem.item_id)}><Focus size={11} />Focus graph</Button><Button size="xs" variant="ghost" onClick={() => onOpenItem(selectedItem)}><BookOpenText size={11} />Open</Button></div><section className="mt-5 border-t border-slate-100 pt-4"><div className="flex items-center justify-between"><p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Visible relations</p><span className="text-[9px] text-slate-400">{connected.length}</span></div><div className="mt-2 space-y-2">{connected.length === 0 ? <p className="rounded-[10px] border border-dashed border-slate-200 p-3 text-[10px] leading-5 text-slate-500">No relations match the current graph filters.</p> : connected.map((relation) => { const outgoing = relation.source_item_id === selectedItem.item_id; const other = itemById.get(outgoing ? relation.target_item_id : relation.source_item_id); return <button key={relation.relation_id} type="button" className="w-full rounded-[11px] border border-slate-200 bg-white p-2.5 text-left hover:border-slate-300 hover:bg-slate-50" onClick={() => onSelectRelation(relation.relation_id)}><div className="flex items-center gap-2 text-[9px] font-semibold text-slate-400">{outgoing ? <ArrowUpRight size={11} /> : <ArrowDownLeft size={11} />}{relation.relation_type.replaceAll("_", " ")} · {originLabels[relation.origin]}</div><p className="mt-1 truncate text-[11px] font-semibold text-slate-700">{other?.title ?? "Missing knowledge object"}</p></button> })}</div></section></div>
}

function FilterSection({ label, children }: { label: string; children: ReactNode }) {
  return <section className="mt-5"><p className="mb-2 text-[9px] font-semibold uppercase tracking-[0.13em] text-slate-400">{label}</p>{children}</section>
}

function FilterToggle({ checked, label, onChange }: { checked: boolean; label: string; onChange: () => void }) {
  return <button type="button" className="flex w-full items-center justify-between rounded-[8px] px-2 py-1.5 text-[10px] text-slate-600 hover:bg-white" onClick={onChange}><span>{label}</span><span className={`h-3.5 w-3.5 rounded-[4px] border ${checked ? "border-cyan-500 bg-cyan-500 shadow-inner" : "border-slate-300 bg-white"}`} aria-hidden="true" /></button>
}

function RelationEndpoint({ label, item, onSelect }: { label: string; item: KnowledgeItem | undefined; onSelect: (itemId: string) => void }) {
  return <button type="button" disabled={!item} className="w-full rounded-[12px] border border-slate-200 bg-white p-3 text-left disabled:opacity-60" onClick={() => item && onSelect(item.item_id)}><p className="text-[9px] font-semibold uppercase tracking-[0.13em] text-slate-400">{label}</p><p className="mt-1 text-xs font-semibold text-slate-800">{item?.title ?? "Missing knowledge object"}</p>{item && <p className="mt-1 text-[9px] capitalize text-slate-400">{item.item_type}</p>}</button>
}

function MetaCard({ label, value }: { label: string; value: string }) {
  return <div className="rounded-[11px] border border-slate-200 bg-slate-50/60 p-2.5"><p className="text-[8px] font-semibold uppercase tracking-[0.12em] text-slate-400">{label}</p><p className="mt-1 text-[10px] font-semibold text-slate-700">{value}</p></div>
}

function InspectorTitle({ icon, eyebrow, title }: { icon: ReactNode; eyebrow: string; title: string }) {
  return <div><p className="flex items-center gap-2 text-[9px] font-semibold uppercase tracking-[0.15em] text-slate-400">{icon}{eyebrow}</p><h3 className="mt-1.5 text-base font-semibold leading-6 text-slate-900">{title}</h3></div>
}

function toggleValue<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((candidate) => candidate !== value) : [...values, value]
}

function itemIcon(type: KnowledgeItemType) {
  const props = { size: 14, strokeWidth: 1.8 }
  if (type === "paper") return <BookOpenText {...props} />
  if (type === "note") return <StickyNote {...props} />
  if (type === "concept") return <Lightbulb {...props} />
  if (type === "highlight") return <Highlighter {...props} />
  return <Network {...props} />
}

function layoutGraph(nodes: Array<{ id: string; depth: number }>): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>()
  const rings = new Map<number, string[]>()
  nodes.forEach((node) => rings.set(node.depth, [...(rings.get(node.depth) ?? []), node.id]))
  for (const [depth, ids] of rings) {
    if (depth === 0) {
      ids.forEach((id) => positions.set(id, { x: 50, y: 50 }))
      continue
    }
    const radiusX = Math.min(40, 17 + (depth - 1) * 11)
    const radiusY = Math.min(39, 16 + (depth - 1) * 10)
    ids.forEach((id, index) => {
      const angle = -Math.PI / 2 + (Math.PI * 2 * index) / Math.max(ids.length, 1)
      positions.set(id, {
        x: 50 + Math.cos(angle) * radiusX,
        y: 50 + Math.sin(angle) * radiusY,
      })
    })
  }
  return positions
}
