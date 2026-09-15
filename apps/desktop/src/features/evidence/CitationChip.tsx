import type { AgentCitationRef, AgentEvidenceItem } from "./evidence-types"

export function CitationChip({
  citation,
  evidence,
  onClick,
}: {
  citation: AgentCitationRef
  evidence?: AgentEvidenceItem
  onClick: () => void
}) {
  const preview = evidence
    ? [evidence.title || "Untitled source", evidence.location, evidence.excerpt]
        .filter(Boolean)
        .join(" · ")
    : "Source unavailable"

  return (
    <button
      type="button"
      className="mx-0.5 inline-flex -translate-y-px items-center rounded-md border border-cyan-200 bg-cyan-50 px-1.5 py-0.5 text-[11px] font-semibold leading-none text-cyan-800 transition hover:border-cyan-300 hover:bg-cyan-100 focus:outline-none focus:ring-2 focus:ring-cyan-300/60"
      aria-label={`Open citation ${citation.label}`}
      title={preview}
      onClick={onClick}
    >
      {citation.label}
    </button>
  )
}
