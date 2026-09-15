import { BookOpenText, ChevronDown } from "lucide-react"
import { useState } from "react"

import { resolveCitation, type ResolvedCitation } from "./citation-model"
import type { AgentCitationRef, AgentEvidenceItem } from "./evidence-types"

export function CitationGroup({
  evidence,
  citations,
  onSelect,
}: {
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
  onSelect: (resolved: ResolvedCitation) => void
}) {
  const [expanded, setExpanded] = useState(false)

  if (citations.length === 0) return null

  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 text-left text-[11px] font-semibold text-slate-500 transition hover:text-slate-800"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="flex items-center gap-2">
          <BookOpenText size={13} />
          Sources <span className="tabular-nums text-slate-400">{citations.length}</span>
        </span>
        <ChevronDown size={13} className={`transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <ol className="mt-3 space-y-2" aria-label="Answer sources">
          {citations.map((citation) => {
            const resolved = resolveCitation(citation, evidence)
            const source = resolved.evidence[0]
            return (
              <li key={citation.citation_id}>
                <button
                  type="button"
                  className="w-full rounded-[13px] border border-slate-200 bg-slate-50 px-3 py-2.5 text-left transition hover:border-cyan-200 hover:bg-cyan-50/70"
                  onClick={() => onSelect(resolved)}
                >
                  <span className="flex items-start gap-2">
                    <strong className="text-xs text-cyan-700">{citation.label}</strong>
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-semibold text-slate-700">
                        {source?.title || "Source unavailable"}
                      </span>
                      <span className="mt-0.5 block text-[10px] text-slate-500">
                        {source?.location || "Location unavailable"}
                      </span>
                      {source?.excerpt && (
                        <span className="mt-1 block line-clamp-2 text-[11px] leading-4 text-slate-500">
                          {source.excerpt}
                        </span>
                      )}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
