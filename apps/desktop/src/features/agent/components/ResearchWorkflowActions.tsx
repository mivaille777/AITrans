import { BookOpenText, FilePenLine, Images, Network, NotebookPen } from "lucide-react"
import { useNavigate } from "react-router-dom"

import type { AgentWorkflowAction } from "../../../api/agent"

const actions: Array<{
  id: Exclude<AgentWorkflowAction, "">
  label: string
  description: string
  prompt: string
  icon: typeof BookOpenText
}> = [
  { id: "quick_read", label: "速读论文", description: "贡献、方法、实验、局限与覆盖范围", prompt: "请速读当前论文，并给出贡献、方法、实验、局限和待核查问题。", icon: BookOpenText },
  { id: "analyze_visuals", label: "分析图表", description: "按页码和图表来源解释，不补造缺失内容", prompt: "请分析当前范围内的表格和图片，并标注来源及无法确认的内容。", icon: Images },
  { id: "compare_papers", label: "比较论文", description: "生成带条件与证据的比较矩阵", prompt: "请比较当前项目中的论文，保留实验条件、分歧和不可比项。", icon: Network },
  { id: "curate_knowledge", label: "整理笔记/图谱", description: "先生成待保存草稿和关系建议", prompt: "请把当前研究结果整理为笔记、知识卡片和有依据的图谱建议。", icon: NotebookPen },
  { id: "draft_section", label: "起草章节", description: "生成带逐段来源和待补项的章节草稿", prompt: "请基于当前项目证据起草一个章节，逐段标注来源并保留待补项。", icon: FilePenLine },
]

export function ResearchWorkflowActions({
  available,
  compact = false,
}: {
  available?: Array<Exclude<AgentWorkflowAction, "">>
  compact?: boolean
}) {
  const navigate = useNavigate()
  const visible = available ? actions.filter((action) => available.includes(action.id)) : actions

  return (
    <section className="ait-surface p-4" aria-label="Research Agent actions">
      {!compact ? (
        <div className="mb-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Research Agent</p>
          <p className="mt-1 text-xs text-slate-500">动作、资源范围和交付类型会以结构化字段传给后端。</p>
        </div>
      ) : null}
      <div className={`grid gap-2 ${compact ? "sm:grid-cols-2" : "sm:grid-cols-2 xl:grid-cols-5"}`}>
        {visible.map((action) => {
          const Icon = action.icon
          return (
            <button
              key={action.id}
              type="button"
              className="rounded-[14px] border border-slate-200 bg-white px-3 py-3 text-left transition hover:border-cyan-300 hover:bg-cyan-50/40"
              onClick={() => navigate("/agent", {
                state: {
                  agentDraftPrompt: action.prompt,
                  agentWorkflowAction: action.id,
                  autoSubmitAgentPrompt: true,
                },
              })}
            >
              <span className="flex items-center gap-2 text-xs font-semibold text-slate-800"><Icon size={14} />{action.label}</span>
              <span className="mt-1.5 block text-[10px] leading-4 text-slate-500">{action.description}</span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
