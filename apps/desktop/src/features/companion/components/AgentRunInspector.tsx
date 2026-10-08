import { useMemo } from "react"
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  CircleAlert,
  CircleDot,
  FileText,
  LoaderCircle,
  Package,
  Wrench,
} from "lucide-react"

import type { AgentRunSnapshot, AgentTraceEvent } from "../../../api/agent"
import type { AgentCitationRef, AgentEvidenceItem } from "../../evidence/evidence-types"
import type {
  CompanionAgentPhase,
  CompanionContextSnapshot,
} from "../companion-runtime"

type ProgressStatus = "pending" | "active" | "complete" | "warning" | "failed"

interface ProgressItem {
  id: string
  sequence: number
  label: string
  detail: string
  status: ProgressStatus
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function titleCase(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ")
}

function eventKey(event: AgentTraceEvent): string {
  const payload = event.payload
  const callId = text(event.tool_call_id) || text(payload.tool_call_id)
  const taskId = text(event.task_id) || text(payload.task_id)
  if (["tool_call", "tool_result", "retry"].includes(event.event_type) && callId) return `call:${callId}`
  if (event.event_type.startsWith("task_") && taskId) return `task:${taskId}`
  const specialistId = text(event.agent_id) || text(payload.agent_id)
  if (event.event_type.startsWith("multi_agent_specialist_") && specialistId) return `specialist:${taskId}:${specialistId}`
  return `${event.event_type}:${event.sequence}`
}

function eventLabel(event: AgentTraceEvent): string {
  const payload = event.payload
  if (event.event_type === "decision_ready") return "确定下一步"
  if (event.event_type === "observation_ready") return "检查工具结果"
  const task = text(payload.title) || text(payload.objective) || text(payload.task_name)
  const tool = text(payload.tool_name) || text(payload.name)
  if (task) return task
  if (tool) return titleCase(tool)
  switch (event.event_type) {
    case "capability_routed": return "识别目标与可用工具"
    case "tool_verification": return "验证工具结果"
    case "task_verification": return "任务验收"
    case "artifact_delivery": return "文档下载"
    case "agent_start": return "Prepare Agent run"
    case "context_ready": return "Read context"
    case "plan_ready": return text(payload.user_visible_reason) || "Plan next action"
    case "synthesis_ready": return "Synthesize response"
    case "grounding_verification_evaluated": return "Verify grounding"
    case "failure": return "Agent failure"
    case "cancelled": return "Stop Agent run"
    default: return titleCase(event.event_type)
  }
}

function eventDetail(event: AgentTraceEvent): string {
  const payload = event.payload
  if (event.event_type === "tool_verification") return `结果验证：${verificationLabel(text(payload.status))}`
  if (event.event_type === "task_verification") return `必要验收 ${count(payload.passed)}/${count(payload.total)} · ${verificationLabel(text(payload.status))}`
  const raw = text(payload.detail)
    || text(payload.message)
    || text(payload.reason)
    || text(payload.user_visible_reason)
    || text(payload.output_text)
    || text(payload.action_summary)
  if (raw) return raw.length > 130 ? `${raw.slice(0, 127)}…` : raw
  const evidence = count(payload.evidence_count) || count(payload.final_count)
  if (evidence > 0) return `${evidence} evidence items reported.`
  if (event.event_type === "tool_call") return "工具调用已开始，等待结果。"
  if (event.event_type === "tool_result") return "工具已返回结果。"
  if (event.event_type === "observation_ready") return "工具返回内容已整理。"
  if (event.event_type === "decision_ready") return payload.kind === "final" ? "已决定生成最终回答。" : "下一步操作已确定。"
  if (event.event_type === "knowledge_decision") return payload.should_retrieve ? "已决定检索知识库。" : "已完成检索需求判断。"
  if (event.event_type === "plan_ready") return payload.mode === "plan_execute" ? "执行计划已准备。" : "处理路径已确定。"
  if (event.event_type === "react_started") return "常规模式已启动。"
  if (event.event_type === "agent_start") return "运行已创建。"
  if (event.event_type === "context_ready") return "会话上下文已准备。"
  if (event.event_type === "agent_end") return "运行已结束。"
  if (event.event_type === "synthesis_ready") return "回答已生成。"
  if (event.event_type === "grounding_verification_evaluated") return "来源核验已结束。"
  return `已记录：${eventLabel(event)}。`
}

function eventStatus(event: AgentTraceEvent): ProgressStatus {
  if (["tool_verification", "task_verification", "tool_result", "artifact_delivery"].includes(event.event_type)) {
    const status = text(event.payload.status)
    if (status === "failed") return "failed"
    if (["partial", "unknown", "cancelled"].includes(status)) return "warning"
    if (status === "pending") return "pending"
  }
  if (["task_failed", "failure", "artifact_rejected", "multi_agent_specialist_failed"].includes(event.event_type)) return "failed"
  if (["task_partial", "task_blocked", "task_cancelled", "cancelled", "write_rejected", "rag_fallback", "budget_exhausted", "react_limit_reached", "workflow_partial"].includes(event.event_type)) return "warning"
  if (["task_planned", "task_ready", "write_confirmation_required"].includes(event.event_type)) return "pending"
  if (["tool_call", "retry", "task_started", "task_progress", "task_retrying", "knowledge_retrieval_started", "multi_agent_started", "multi_agent_knowledge_started", "multi_agent_specialist_started", "rag_query_started"].includes(event.event_type)) return "active"
  return "complete"
}

function verificationLabel(status: string): string {
  return ({ passed: "通过", completed: "全部通过", failed: "未通过", partial: "部分完成", unknown: "结果待核对", pending: "待验证", cancelled: "已取消" } as Record<string, string>)[status] || "尚无验收记录"
}

export function deriveChatTaskAcceptance(events: AgentTraceEvent[]): Record<string, unknown> | null {
  return [...events].sort((a, b) => b.sequence - a.sequence).find(event => event.event_type === "task_verification")?.payload ?? null
}

export function deriveChatAgentProgress(
  events: AgentTraceEvent[],
  phase: CompanionAgentPhase,
): ProgressItem[] {
  const grouped = new Map<string, ProgressItem>()
  const legacyCalls = new Map<string, string>()
  const seen = new Set<string>()
  let retrievalId = ""
  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) {
    const fingerprint = event.event_id || `${event.sequence}:${event.event_type}`
    if (seen.has(fingerprint)) continue
    seen.add(fingerprint)
    let id = eventKey(event)
    if (event.event_type === "rag_query_started") retrievalId = id
    if (event.event_type === "rag_evidence_selected" && retrievalId) {
      id = retrievalId
      retrievalId = ""
    }
    const name = text(event.payload.tool_name) || text(event.payload.name)
    if (["tool_call", "tool_result", "retry"].includes(event.event_type) && !text(event.tool_call_id) && !text(event.payload.tool_call_id)) {
      if (event.event_type === "tool_call") legacyCalls.set(name, id)
      else id = legacyCalls.get(name) || id
      if (event.event_type === "tool_result") legacyCalls.delete(name)
    }
    // Paired activity events use one row, while each tool invocation has its own row.
    const pairs: Record<string, string> = {
      knowledge_retrieval_started: "knowledge-retrieval", knowledge_retrieved: "knowledge-retrieval",
      multi_agent_started: "multi-agent-run", multi_agent_completed: "multi-agent-run",
      multi_agent_knowledge_started: "multi-agent-knowledge", multi_agent_knowledge_ready: "multi-agent-knowledge",
    }
    if (pairs[event.event_type]) id = `${pairs[event.event_type]}:${text(event.task_id)}`
    const next: ProgressItem = {
      id,
      sequence: event.sequence,
      label: eventLabel(event),
      detail: eventDetail(event),
      status: eventStatus(event),
    }
    const previous = grouped.get(id)
    grouped.set(id, previous ? { ...next, sequence: previous.sequence, label: previous.label, status: previous.status === "failed" && event.event_type === "task_progress" ? "failed" : next.status } : next)
  }

  const items = [...grouped.values()].sort((left, right) => left.sequence - right.sequence)
  if (["completed", "cancelled", "error"].includes(phase)) {
    for (const item of items) {
      if (item.status !== "active" && item.status !== "pending") continue
      item.status = phase === "error" ? "failed" : "warning"
      item.detail = phase === "cancelled" ? "运行已停止，此步骤未完成。" : phase === "error" ? "运行失败，未收到此步骤的完成结果。" : "运行已结束，未收到此步骤的完成结果。"
    }
  }
  return items
}

function StatusIcon({ status }: { status: ProgressStatus }) {
  if (status === "complete") return <span className="ait-chat-run-status is-complete"><Check size={12} /></span>
  if (status === "failed") return <span className="ait-chat-run-status is-failed"><CircleAlert size={12} /></span>
  if (status === "warning") return <span className="ait-chat-run-status is-warning"><CircleAlert size={12} /></span>
  if (status === "active") return <span className="ait-chat-run-status is-active"><LoaderCircle size={12} /></span>
  return <span className="ait-chat-run-status"><CircleDot size={11} /></span>
}

function ArtifactCard({ artifact }: { artifact: AgentRunSnapshot["artifacts"][number] }) {
  const title = text(artifact.content.title) || text(artifact.content.name) || titleCase(artifact.kind) || "Verified artifact"
  const coverage = artifact.source_coverage?.complete
    ? "Source coverage complete"
    : artifact.source_coverage?.missing_refs?.length
      ? `${artifact.source_coverage.missing_refs.length} source gaps`
      : "Verification reported"
  return (
    <div className="ait-chat-run-artifact">
      <span className="ait-chat-run-artifact-icon"><Package size={16} /></span>
      <span className="ait-chat-run-artifact-copy">
        <strong>{title}</strong>
        <small>{titleCase(artifact.kind)} · v{artifact.version} · {coverage}</small>
      </span>
      <span className={`ait-chat-run-artifact-status ${artifact.verification_status === "verified" ? "is-good" : ""}`}>
        {artifact.verification_status || "pending"}
      </span>
    </div>
  )
}

export function AgentRunInspector({
  context,
  phase,
  runId,
  traceId,
  events,
  snapshot,
  confirmationTool,
  evidence,
  citations,
  knowledgeDocumentIds,
  onViewContext,
  onConfirmWrite,
}: {
  context: CompanionContextSnapshot
  phase: CompanionAgentPhase
  runId: string
  traceId: string
  events: AgentTraceEvent[]
  snapshot: AgentRunSnapshot | null
  selectedTools: string[]
  confirmationTool: string
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
  knowledgeDocumentIds: string[]
  onViewContext: () => void
  onConfirmWrite: () => void
}) {
  const progress = useMemo(() => deriveChatAgentProgress(events, phase), [events, phase])
  const acceptance = useMemo(() => deriveChatTaskAcceptance(events), [events])
  const calls = useMemo(() => events.filter(event => event.event_type === "tool_call"), [events])
  const actualTools = useMemo(() => {
    const names = events
      .filter((event) => ["tool_call", "tool_result"].includes(event.event_type))
      .map((event) => text(event.payload.tool_name) || text(event.payload.name))
      .filter(Boolean)
    return [...new Set(names)]
  }, [events])
  const contextTitle = context.resource_title || context.section_heading || "Reading context"
  const phaseLabel = phase === "cancelling" ? "Stopping" : phase === "confirmation_required" ? "Confirmation required" : phase === "error" ? "Run failed" : phase === "completed" ? progress.some(item => item.status === "failed" || item.status === "warning") ? "Completed with issues" : "Completed" : phase === "cancelled" ? "Cancelled" : "Working"
  const awaitingPlan = Boolean(snapshot?.pending_plan) || !confirmationTool

  return (
    <aside className="ait-chat-run-inspector ait-context-panel-enter" aria-label="Agent run inspector">
      <div className="ait-chat-run-header">
        <div>
          <p className="ait-chat-section-eyebrow">Agent run</p>
          <h2 className="ait-chat-run-title">{phaseLabel}</h2>
          <p className="ait-chat-run-meta">{runId ? `Run ${runId.slice(0, 12)}` : "Starting a bounded run"}</p>
          <p className="ait-chat-run-meta">任务验收：{verificationLabel(text(acceptance?.status))}</p>
        </div>
        <button type="button" className="ait-chat-run-context-button" onClick={onViewContext}>
          <ArrowLeft size={14} /> Context
        </button>
      </div>

      <section className="ait-chat-run-section">
        <div className="ait-chat-run-section-heading">
          <span><CircleDot size={16} /> Progress</span>
          <small>{progress.filter((item) => item.status === "complete").length}/{progress.length || 0}</small>
        </div>
        {progress.length > 0 ? (
          <div className="ait-chat-run-progress">
            {progress.map((item) => (
              <div key={item.id} className="ait-chat-run-progress-item">
                <StatusIcon status={item.status} />
                <div className="ait-chat-run-progress-copy">
                  <strong>{item.label}</strong>
                  <p>{item.detail}</p>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="ait-chat-run-empty">Waiting for the first Agent activity event…</p>
        )}
      </section>

      <section className="ait-chat-run-section" aria-label="任务验收">
        <div className="ait-chat-run-section-heading"><span><CheckCircle2 size={16} />必要验收</span><small>{count(acceptance?.passed)}/{count(acceptance?.total)}</small></div>
        {Array.isArray(acceptance?.criteria) ? acceptance.criteria.map((item: Record<string, unknown>, index: number) => <div className="ait-chat-run-progress-item" key={text(item.criterion_id) || index}>
          <StatusIcon status={item.status === "passed" ? "complete" : item.status === "failed" ? "failed" : "warning"} />
          <div className="ait-chat-run-progress-copy"><strong>{text(item.label)}</strong><p>{verificationLabel(text(item.status))}</p></div>
        </div>) : <p className="ait-chat-run-empty">运行结束后显示实际验收结论。历史记录缺少验证证据时，不推断验收通过。</p>}
        <p className="ait-chat-run-empty">这里核对执行与产物；开放性内容质量不等同于确定性检查。</p>
      </section>

      <section className="ait-chat-run-section" aria-label="工具调用详情">
        <div className="ait-chat-run-section-heading"><span><Wrench size={16} />工具调用</span><small>{calls.length}</small></div>
        {calls.map(call => {
          const id = text(call.tool_call_id) || text(call.payload.tool_call_id)
          const related = events.filter(event => id && (text(event.tool_call_id) || text(event.payload.tool_call_id)) === id)
          const result = related.find(event => event.event_type === "tool_result")
          const verification = related.find(event => event.event_type === "tool_verification")
          return <details className="ait-chat-run-context-card" key={id || call.sequence}>
            <summary>{text(call.payload.name)} · {verificationLabel(text(verification?.payload.status))}</summary>
            <p className="ait-chat-run-meta">调用 {id || "历史记录无 ID"} · {count(result?.payload.duration_ms)} ms · {count(result?.payload.attempt) || 1} 次尝试</p>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify({参数: call.payload.arguments, 权限: { effect: call.payload.effect, requires_confirmation: call.payload.requires_confirmation }, 结果: result?.payload, 验证: verification?.payload, 重试与错误: related.filter(event => ["retry", "failure"].includes(event.event_type)).map(event => event.payload)}, null, 2).slice(0, 12000)}</pre>
          </details>
        })}
      </section>

      <section className="ait-chat-run-section">
        <div className="ait-chat-run-section-heading">
          <span><Package size={16} /> Artifacts</span>
          <small>{snapshot?.artifacts.length ?? 0}</small>
        </div>
        {snapshot?.artifacts.length ? (
          <div className="ait-chat-run-artifacts">
            {snapshot.artifacts.map((artifact) => <ArtifactCard key={`${artifact.artifact_id}:${artifact.version}`} artifact={artifact} />)}
          </div>
        ) : (
          <p className="ait-chat-run-empty">Verified artifacts returned by this run will appear here.</p>
        )}
      </section>

      <section className="ait-chat-run-section">
        <div className="ait-chat-run-section-heading">
          <span><FileText size={16} /> Context</span>
          <small>{evidence.length + citations.length}</small>
        </div>
        {context.source_text && (
          <div className="ait-chat-run-context-card">
            <p className="ait-chat-card-eyebrow">{contextTitle}</p>
            <p>{context.source_text}</p>
          </div>
        )}
        <div className="ait-chat-run-context-list">
          <div><span>Evidence</span><strong>{evidence.length} items · {citations.length} citations</strong></div>
          <div><span>Knowledge</span><strong>{knowledgeDocumentIds.length > 0 ? `${knowledgeDocumentIds.length} selected documents` : "Automatic scope"}</strong></div>
          <div><span>Tools used</span><strong>{actualTools.length > 0 ? actualTools.join(", ") : "None yet"}</strong></div>
        </div>
        {traceId && <p className="ait-chat-run-trace">Trace {traceId.slice(0, 18)}</p>}
      </section>

      {phase === "confirmation_required" && (
        <div className="ait-chat-run-confirmation">
          <Wrench size={15} />
          <div>
            <strong>{awaitingPlan ? "执行计划等待确认" : "Approval required before write action"}</strong>
            <p>
              {awaitingPlan ? "请在输入框上方确认执行或取消计划。" : `${confirmationTool || "A write tool"} is waiting for your confirmation. No persistent change has been executed yet.`}
            </p>
            {(() => {
              const intent = [...events].reverse().find(event => event.event_type === "write_confirmation_required")?.payload.intent as {file_preview?: {relative_path: string; diff: string; diff_truncated: boolean; size_before: number; size_after: number}} | undefined
              const preview = intent?.file_preview
              return preview ? <div><p>{preview.relative_path} · {preview.size_before} → {preview.size_after} 字节</p>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{preview.diff}</pre>
                {preview.diff_truncated && <p>差异过长，仅显示部分内容。</p>}
              </div> : null
            })()}
            {!awaitingPlan && <button type="button" onClick={onConfirmWrite}>
              <CheckCircle2 size={14} /> Approve and execute
            </button>}
          </div>
        </div>
      )}
    </aside>
  )
}
