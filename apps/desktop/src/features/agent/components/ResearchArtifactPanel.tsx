import { AlertTriangle, CheckCircle2, ExternalLink, FileText } from "lucide-react"

import type { AgentArtifact, AgentRunSnapshot } from "../../../api/agent"
import { GraphProposalPanel } from "./GraphProposalPanel"

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : []
}

function EvidenceLinks({ ids }: { ids: string[] }) {
  if (ids.length === 0) return <span className="text-amber-700">无可跳转来源</span>
  return (
    <span className="inline-flex flex-wrap gap-1">
      {ids.map((id) => <a key={id} href={`#evidence-${encodeURIComponent(id)}`} className="rounded bg-cyan-50 px-1.5 py-0.5 text-cyan-800"><ExternalLink size={9} className="mr-1 inline" />{id}</a>)}
    </span>
  )
}

function ComparisonView({ artifact }: { artifact: AgentArtifact }) {
  const cells = Array.isArray(artifact.cells) ? artifact.cells as Array<Record<string, unknown>> : []
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[620px] border-separate border-spacing-0 text-left text-[11px]">
        <thead><tr className="text-slate-400"><th className="border-b p-2">维度</th><th className="border-b p-2">来源</th><th className="border-b p-2">值与条件</th><th className="border-b p-2">证据</th></tr></thead>
        <tbody>{cells.map((cell, index) => (
          <tr key={`${String(cell.dimension)}-${String(cell.source_label)}-${index}`}>
            <td className="border-b border-slate-100 p-2 font-medium text-slate-700">{String(cell.dimension ?? "")}</td>
            <td className="border-b border-slate-100 p-2">{String(cell.source_label ?? "")}</td>
            <td className="border-b border-slate-100 p-2">{cell.unknown ? "unknown" : String(cell.value ?? "")} {cell.conditions ? <span className="block text-slate-400">{String(cell.conditions)}</span> : null}</td>
            <td className="border-b border-slate-100 p-2"><EvidenceLinks ids={strings(cell.evidence_ids)} /></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

function ManuscriptView({ artifact }: { artifact: AgentArtifact }) {
  const markdown = String(artifact.markdown ?? "")
  const paragraphs = markdown.split(/\n\s*\n/).filter(Boolean)
  const paragraphIds = strings(artifact.paragraph_ids)
  const map = artifact.claim_source_map && typeof artifact.claim_source_map === "object" ? artifact.claim_source_map as Record<string, unknown> : {}
  return (
    <div className="mt-3 space-y-2">
      {paragraphs.map((paragraph, index) => {
        const id = paragraphIds[index] ?? `paragraph-${index + 1}`
        return <div key={id} className="rounded-xl border border-slate-100 bg-white p-3"><p className="whitespace-pre-wrap text-xs leading-6 text-slate-700">{paragraph}</p><p className="mt-2 text-[10px] text-slate-400">{id} · 来源 <EvidenceLinks ids={strings(map[id])} /></p></div>
      })}
      {strings(artifact.missing_inputs).length ? <p className="text-[11px] text-amber-700">待补项：{strings(artifact.missing_inputs).join("、")}</p> : null}
    </div>
  )
}

function GenericView({ artifact }: { artifact: AgentArtifact }) {
  const fields = ["contributions", "methods", "datasets", "experiments", "limitations", "open_questions"]
  return <div className="mt-3 grid gap-2 sm:grid-cols-2">{fields.map((field) => strings(artifact[field]).length ? <div key={field} className="rounded-xl border border-slate-100 bg-white p-3"><p className="text-[10px] font-semibold uppercase text-slate-400">{field.replaceAll("_", " ")}</p><ul className="mt-1 list-disc space-y-1 pl-4 text-[11px] text-slate-600">{strings(artifact[field]).map((item) => <li key={item}>{item}</li>)}</ul></div> : null)}</div>
}

function ArtifactCard({ artifact, scope }: { artifact: AgentArtifact; scope: Record<string, unknown> }) {
  const passed = artifact.verification_status === "passed"
  return (
    <article className="rounded-[16px] border border-slate-200 bg-slate-50/45 p-4" data-artifact-id={artifact.artifact_id}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">{artifact.kind.replaceAll("_", " ")} · v{artifact.version}</p><h3 className="mt-1 text-xs font-semibold text-slate-800">{artifact.artifact_id}</h3></div>
        <span className={`flex items-center gap-1 text-[10px] font-semibold ${passed ? "text-emerald-700" : "text-amber-700"}`}>{passed ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}{artifact.verification_status}</span>
      </div>
      <div className="mt-2 grid gap-1 text-[10px] text-slate-500 sm:grid-cols-2">
        <p>覆盖：{artifact.source_coverage.complete ? "完整" : "部分"}</p>
        <p>来源：{artifact.source_coverage.covered_refs.join("、") || "未记录"}</p>
      </div>
      {artifact.source_coverage.missing_refs.length ? <p className="mt-1 text-[10px] text-amber-700">待补来源：{artifact.source_coverage.missing_refs.join("、")}</p> : null}
      {artifact.kind === "comparison" ? <ComparisonView artifact={artifact} /> : null}
      {artifact.kind === "manuscript_section" ? <ManuscriptView artifact={artifact} /> : null}
      {artifact.kind === "document_analysis" ? <GenericView artifact={artifact} /> : null}
      {artifact.kind === "knowledge_draft" ? <GraphProposalPanel artifact={artifact} scope={scope} /> : null}
    </article>
  )
}

export function ResearchArtifactPanel({ snapshot }: { snapshot: AgentRunSnapshot | null }) {
  if (!snapshot || snapshot.artifacts.length === 0) return null
  return (
    <section className="ait-surface p-5" aria-label="Research artifacts">
      <div className="flex items-center gap-2"><FileText size={15} /><h2 className="text-sm font-semibold text-slate-900">科研产物</h2></div>
      <p className="mt-1 text-xs text-slate-500">版本、覆盖范围、验证状态和来源均来自权威 run snapshot。</p>
      <div className="mt-4 space-y-3">{snapshot.artifacts.map((artifact) => <ArtifactCard key={`${artifact.artifact_id}:${artifact.version}`} artifact={artifact} scope={snapshot.scope} />)}</div>
    </section>
  )
}
