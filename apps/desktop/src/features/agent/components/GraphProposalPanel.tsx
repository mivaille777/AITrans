import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Check, LoaderCircle, Save, X } from "lucide-react"

import type { AgentArtifact } from "../../../api/agent"
import { commitCuratorDraft, type CuratorCommitReceipt } from "../../../api/curator"
import { acceptKnowledgeRelationSuggestion, rejectKnowledgeRelationSuggestion } from "../../../api/knowledge"
import { Button } from "../../../shared/ui/Button"
import { queryKeys } from "../../../shared/query/query-keys"

interface Proposal {
  proposal_id: string
  source_draft_or_item_id: string
  target_draft_or_item_id: string
  relation_type: string
  rationale?: string
  evidence_ids?: string[]
  confidence?: number
}

export function GraphProposalPanel({ artifact, scope }: { artifact: AgentArtifact; scope: Record<string, unknown> }) {
  const client = useQueryClient()
  const [receipt, setReceipt] = useState<CuratorCommitReceipt | null>(null)
  const [phase, setPhase] = useState<"generated" | "saving" | "saved" | "failed">("generated")
  const [message, setMessage] = useState("")
  const proposals = Array.isArray(artifact.relation_proposals) ? artifact.relation_proposals as Proposal[] : []
  const notes = Array.isArray(artifact.notes) ? artifact.notes as Array<{ draft_id: string }> : []
  const items = Array.isArray(artifact.items) ? artifact.items as Array<{ draft_id: string }> : []
  const proposalIds = proposals.map((item) => item.proposal_id)
  const selected = [...notes.map((item) => item.draft_id), ...items.map((item) => item.draft_id), ...proposalIds]
  const savedSuggestions = receipt?.results.filter((item) => item.target_kind === "relation_proposal" && item.status === "committed") ?? []

  async function saveDraft() {
    setPhase("saving")
    setMessage("")
    try {
      const next = await commitCuratorDraft({
        artifact_id: artifact.artifact_id,
        artifact_version: artifact.version,
        operation_id: `curator-ui:${artifact.artifact_id}:${artifact.version}`,
        scope,
        selected_draft_ids: selected,
      })
      setReceipt(next)
      setPhase(next.status === "completed" ? "saved" : next.status === "failed" ? "failed" : "saved")
      setMessage(next.status === "completed" ? "草稿已保存；关系仍需逐条接受或拒绝。" : `保存结果：${next.status}`)
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.knowledge.items }),
        client.invalidateQueries({ queryKey: queryKeys.knowledge.relations }),
        client.invalidateQueries({ queryKey: ["research"] }),
      ])
    } catch (error) {
      setPhase("failed")
      setMessage(error instanceof Error ? error.message : "保存失败")
    }
  }

  async function decide(suggestionId: string, decision: "accept" | "reject") {
    try {
      if (decision === "accept") await acceptKnowledgeRelationSuggestion(suggestionId)
      else await rejectKnowledgeRelationSuggestion(suggestionId)
      setMessage(`关系建议已${decision === "accept" ? "接受" : "拒绝"}。`)
      await client.invalidateQueries({ queryKey: queryKeys.knowledge.relations })
    } catch (error) {
      setPhase("failed")
      setMessage(error instanceof Error ? error.message : "关系决策失败")
    }
  }

  return (
    <div className="mt-3 rounded-[14px] border border-amber-200 bg-amber-50/45 p-3" aria-label="Graph proposals">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-amber-950">图谱建议 · {phase === "generated" ? "已生成，待保存" : phase === "saving" ? "保存中" : phase === "saved" ? "已保存，待决策" : "保存失败"}</p>
        {phase === "generated" || phase === "failed" ? <Button size="xs" onClick={() => void saveDraft()}><Save size={11} />保存笔记与建议</Button> : null}
        {phase === "saving" ? <LoaderCircle size={13} className="animate-spin" /> : null}
      </div>
      <div className="mt-2 space-y-2">
        {proposals.map((proposal) => (
          <div key={proposal.proposal_id} className="rounded-lg bg-white/80 p-2.5 text-[11px] text-slate-600">
            <p className="font-semibold text-slate-800">{proposal.source_draft_or_item_id} → {proposal.relation_type} → {proposal.target_draft_or_item_id}</p>
            {proposal.rationale ? <p className="mt-1">{proposal.rationale}</p> : null}
            {proposal.evidence_ids?.length ? <p className="mt-1 text-[10px] text-slate-400">证据：{proposal.evidence_ids.join("、")}</p> : null}
          </div>
        ))}
      </div>
      {savedSuggestions.map((item) => (
        <div key={item.object_id} className="mt-2 flex items-center gap-2 text-[11px]">
          <span className="text-slate-500">建议 {item.object_id}</span>
          <Button size="xs" onClick={() => void decide(item.object_id, "accept")}><Check size={10} />接受</Button>
          <Button size="xs" variant="ghost" onClick={() => void decide(item.object_id, "reject")}><X size={10} />拒绝</Button>
        </div>
      ))}
      {message ? <p role="status" className={`mt-2 text-[11px] ${phase === "failed" ? "text-rose-700" : "text-slate-600"}`}>{message}</p> : null}
    </div>
  )
}
