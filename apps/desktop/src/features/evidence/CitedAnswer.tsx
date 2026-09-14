import { useState } from "react"

import { AnswerMarkdown } from "./AnswerMarkdown"
import { CitationGroup } from "./CitationGroup"
import { EvidenceDrawer } from "./EvidenceDrawer"
import type { ResolvedCitation } from "./citation-model"
import type { AgentCitationRef, AgentEvidenceItem } from "./evidence-types"

export function CitedAnswer({
  content,
  evidence,
  citations,
}: {
  content: string
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
}) {
  const [selected, setSelected] = useState<ResolvedCitation | null>(null)

  return (
    <>
      <AnswerMarkdown
        content={content}
        evidence={evidence}
        citations={citations}
        onCitation={setSelected}
      />

      <CitationGroup evidence={evidence} citations={citations} onSelect={setSelected} />

      {selected && <EvidenceDrawer resolved={selected} onClose={() => setSelected(null)} />}
    </>
  )
}
