import { X } from "lucide-react"
import { useState } from "react"

import { Button } from "../../shared/ui/Button"
import type { ResolvedCitation } from "./citation-model"
import { EvidenceList } from "./EvidenceList"

export function EvidenceDrawer({
  resolved,
  onClose,
}: {
  resolved: ResolvedCitation
  onClose: () => void
}) {
  const [openError, setOpenError] = useState("")

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/25 backdrop-blur-[2px]" role="presentation" onMouseDown={onClose}>
      <aside
        className="h-full w-full max-w-md overflow-y-auto border-l border-white/60 bg-white/95 p-5 shadow-[-24px_0_70px_rgba(15,23,42,0.18)] backdrop-blur-xl workspace-route-enter"
        role="dialog"
        aria-modal="true"
        aria-label={`Citation detail ${resolved.citation.label}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 pb-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Citation detail</p>
            <h3 className="mt-1.5 text-lg font-semibold text-slate-950">Source {resolved.citation.label}</h3>
          </div>
          <Button variant="ghost" size="xs" aria-label="Close citation detail" onClick={onClose}>
            <X size={16} />
          </Button>
        </header>

        <div className="mt-5">
          <EvidenceList evidence={resolved.evidence} onOpenError={setOpenError} />
        </div>

        {openError && <p role="alert" className="mt-4 rounded-[13px] bg-rose-50 px-3 py-2 text-xs text-rose-700">{openError}</p>}
      </aside>
    </div>
  )
}
