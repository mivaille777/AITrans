import { Brain, FileText, Link2, StickyNote } from "lucide-react"
import { useEffect } from "react"

import { fetchKnowledgeCanvas } from "./knowledgeCanvasApi"
import { useKnowledgeCanvasStore } from "./knowledgeCanvasStore"

type NodeType = "paper" | "concept" | "note"

function NodeIcon({ type }: { type: NodeType }) {
  if (type === "paper") return <FileText size={16} />
  if (type === "concept") return <Brain size={16} />
  return <StickyNote size={16} />
}

export default function KnowledgeCanvas() {
  const { nodes, edges, setGraph } = useKnowledgeCanvasStore()

  useEffect(() => {
    fetchKnowledgeCanvas()
      .then((graph) => setGraph(graph.nodes, graph.edges))
      .catch(() => undefined)
  }, [setGraph])

  return (
    <section className="relative h-[640px] overflow-hidden rounded-3xl border border-slate-200 bg-slate-50">
      <div className="absolute left-5 top-5 z-10 flex items-center gap-2 rounded-xl bg-white px-4 py-2 text-sm shadow-sm">
        <Link2 size={16} />
        Knowledge Canvas
      </div>

      <svg className="absolute inset-0 h-full w-full">
        {edges.map((edge) => (
          <line key={`${edge.source}-${edge.target}`} x1="32%" y1="30%" x2="62%" y2="45%" stroke="currentColor" strokeWidth="1.5" />
        ))}
      </svg>

      {nodes.map((node, index) => (
        <article
          key={node.id}
          className="absolute w-56 rounded-2xl border border-slate-200 bg-white p-4 shadow-md"
          style={{ left: `${18 + index * 24}%`, top: `${22 + (index % 2) * 18}%` }}
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <NodeIcon type={node.type} />
            {node.title}
          </div>
          <p className="mt-3 text-xs text-slate-500">{node.summary ?? "Knowledge object"}</p>
        </article>
      ))}
    </section>
  )
}
