import { FileQuestion } from "lucide-react"

import { EvidenceCard } from "./EvidenceCard"
import type { AgentEvidenceItem } from "./evidence-types"

export function EvidenceList({
  evidence,
  compact = false,
  onOpenError,
}: {
  evidence: AgentEvidenceItem[]
  compact?: boolean
  onOpenError?: (message: string) => void
}) {
  if (evidence.length === 0) {
    return (
      <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50 p-6 text-center">
        <FileQuestion size={24} className="mx-auto text-slate-400" />
        <p className="mt-3 text-sm font-semibold text-slate-800">Source unavailable</p>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          This citation no longer has a matching verified evidence item.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {evidence.map((item) => (
        <EvidenceCard
          key={item.evidence_id}
          item={item}
          compact={compact}
          onOpenError={onOpenError}
        />
      ))}
    </div>
  )
}
