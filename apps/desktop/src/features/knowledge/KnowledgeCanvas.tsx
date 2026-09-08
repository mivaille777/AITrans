import { Brain, FileText, Link2, StickyNote } from "lucide-react"

type NodeType = "paper" | "concept" | "note"

type CanvasNode = {
  id: string
  title: string
  type: NodeType
  x: string
  y: string
  description: string
}

const nodes: CanvasNode[] = [
  {
    id: "paper-1",
    title: "Agent Planning Research",
    type: "paper",
    x: "18%",
    y: "20%",
    description: "Paper knowledge object",
  },
  {
    id: "concept-1",
    title: "Supervisor Routing",
    type: "concept",
    x: "48%",
    y: "42%",
    description: "Agent architecture concept",
  },
  {
    id: "note-1",
    title: "Implementation Notes",
    type: "note",
    x: "72%",
    y: "25%",
    description: "Engineering decision record",
  },
]

function NodeIcon({ type }: { type: NodeType }) {
  if (type === "paper") return <FileText size={16} />
  if (type === "concept") return <Brain size={16} />
  return <StickyNote size={16} />
}

export default function KnowledgeCanvas() {
  return (
    <section className="relative h-[640px] overflow-hidden rounded-3xl border border-slate-200 bg-slate-50">
      <div className="absolute left-5 top-5 z-10 flex items-center gap-2 rounded-xl bg-white px-4 py-2 text-sm shadow-sm">
        <Link2 size={16} />
        Knowledge Canvas
      </div>

      <svg className="absolute inset-0 h-full w-full">
        <line x1="32%" y1="30%" x2="52%" y2="45%" stroke="currentColor" strokeWidth="1.5" />
        <line x1="55%" y1="45%" x2="75%" y2="30%" stroke="currentColor" strokeWidth="1.5" />
      </svg>

      {nodes.map((node) => (
        <article
          key={node.id}
          className="absolute w-56 rounded-2xl border border-slate-200 bg-white p-4 shadow-md"
          style={{ left: node.x, top: node.y }}
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <NodeIcon type={node.type} />
            {node.title}
          </div>
          <p className="mt-3 text-xs text-slate-500">{node.description}</p>
        </article>
      ))}
    </section>
  )
}
