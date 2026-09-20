import { useQuery } from "@tanstack/react-query"
import { ArrowUpRight, BookOpenCheck, LoaderCircle, MessageCircle, Sparkles } from "lucide-react"
import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"

import { createCompanionHandoff } from "../../api/companion"
import { queryKeys } from "../../shared/query/query-keys"
import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import {
  buildKnowledgeCompanionHandoff,
  knowledgeCardDocumentIds,
} from "../knowledge/knowledge-companion-handoff"
import { listKnowledgeItems } from "../knowledge/knowledge-api"
import type { KnowledgeItem } from "../knowledge/knowledge-types"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"

const RESEARCH_KNOWLEDGE_TYPES = new Set(["evidence", "insight", "question", "highlight"])

function metadataText(item: KnowledgeItem, key: string): string {
  const value = item.metadata?.[key]
  return typeof value === "string" ? value.trim() : ""
}

function pageLabel(item: KnowledgeItem): string {
  const start = item.metadata?.page_start
  const end = item.metadata?.page_end
  if (typeof start !== "number" && typeof end !== "number") return ""
  if (typeof start === "number" && typeof end === "number" && start !== end) return `pp. ${start}–${end}`
  return `p. ${typeof start === "number" ? start : end}`
}

export default function KnowledgeResearchBridgePanel({
  workspace,
  previewLimit = 3,
}: {
  workspace: TranslationWorkspaceController
  previewLimit?: number
}) {
  const navigate = useNavigate()
  const [openingItemId, setOpeningItemId] = useState("")
  const [errorMessage, setErrorMessage] = useState("")
  const [showAll, setShowAll] = useState(false)
  const itemsQuery = useQuery({
    queryKey: queryKeys.knowledge.items,
    queryFn: listKnowledgeItems,
  })

  const cards = useMemo(
    () => (itemsQuery.data?.items ?? [])
      .filter((item) => RESEARCH_KNOWLEDGE_TYPES.has(item.item_type))
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
      .slice(0, 12),
    [itemsQuery.data?.items],
  )
  const visibleCards = showAll ? cards : cards.slice(0, previewLimit)

  async function openInChat(item: KnowledgeItem) {
    setOpeningItemId(item.item_id)
    setErrorMessage("")
    try {
      const handoff = buildKnowledgeCompanionHandoff(item, {
        sourceLanguage: workspace.sourceLanguage,
        targetLanguage: workspace.targetLanguage,
      })
      const knowledgeDocumentIds = [...new Set([
        ...knowledgeCardDocumentIds(item),
        ...workspace.researchRetrievalScope.knowledgeDocumentIds,
      ])].slice(0, 100)
      const scopedHandoff = {
        ...handoff,
        knowledge_enabled: knowledgeDocumentIds.length > 0,
        knowledge_document_ids: knowledgeDocumentIds,
      }
      await createCompanionHandoff(scopedHandoff)
      navigate("/chat")
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to open this knowledge card in AI Chat.")
    } finally {
      setOpeningItemId("")
    }
  }

  return (
    <section className="rounded-[18px] border border-slate-200/70 bg-white p-5 shadow-[0_8px_28px_rgba(15,23,42,0.04)]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <BookOpenCheck size={16} className="text-slate-500" />
            Knowledge Evidence
          </div>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500">
            Canonical evidence and Agent insights from Paper Reader are available here without being copied into Research Notes. Open one in AI Chat to continue with its source paper and current document scope.
          </p>
        </div>
        <Badge>{cards.length} grounded cards</Badge>
      </div>

      {itemsQuery.isPending ? (
        <div className="mt-4 flex items-center gap-2 rounded-[13px] bg-slate-50 px-3 py-4 text-xs text-slate-500">
          <LoaderCircle size={13} className="animate-spin" />Loading Knowledge evidence…
        </div>
      ) : cards.length === 0 ? (
        <div className="mt-4 rounded-[13px] border border-dashed border-slate-200 bg-slate-50/40 px-4 py-5">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-700"><Sparkles size={13} />No grounded cards yet</div>
          <p className="mt-1 text-[11px] leading-5 text-slate-500">Open a paper in Knowledge, select a passage, and create Evidence or Ask AI. Saved Agent insights will appear here automatically.</p>
        </div>
      ) : (
        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {visibleCards.map((item) => {
            const section = metadataText(item, "section_heading")
            const page = pageLabel(item)
            const documents = knowledgeCardDocumentIds(item)
            const opening = openingItemId === item.item_id
            return (
              <article key={item.item_id} className="flex min-h-44 flex-col rounded-[14px] border border-slate-200/80 bg-slate-50/35 p-3.5">
                <div className="flex items-center justify-between gap-2">
                  <Badge>{item.item_type}</Badge>
                  <span className="text-[9px] text-slate-400">{documents.length > 0 ? `${documents.length} source doc${documents.length === 1 ? "" : "s"}` : "card-grounded"}</span>
                </div>
                <h3 className="mt-2 line-clamp-2 text-xs font-semibold leading-5 text-slate-800">{item.title}</h3>
                <p className="mt-1 line-clamp-3 flex-1 text-[11px] leading-5 text-slate-500">{item.summary || "No summary."}</p>
                {(section || page) && <p className="mt-2 truncate text-[9px] text-slate-400">{[section, page].filter(Boolean).join(" · ")}</p>}
                <div className="mt-3 border-t border-slate-200/70 pt-3">
                  <Button size="xs" disabled={Boolean(openingItemId)} onClick={() => void openInChat(item)}>
                    {opening ? <LoaderCircle size={11} className="animate-spin" /> : <MessageCircle size={11} />}
                    {opening ? "Opening…" : "Open in AI Chat"}
                  </Button>
                </div>
              </article>
            )
          })}
        </div>
      )}

      {cards.length > previewLimit && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
          <p className="text-[11px] text-slate-500">
            {showAll ? `Showing ${cards.length} recent cards.` : `${cards.length - visibleCards.length} more cards are available in Knowledge.`}
          </p>
          <div className="flex gap-2">
            <Button size="xs" variant="ghost" onClick={() => setShowAll((value) => !value)}>
              {showAll ? "Show preview" : `Show all ${cards.length}`}
            </Button>
            <Button size="xs" variant="ghost" onClick={() => navigate("/knowledge?view=library")}>
              <ArrowUpRight size={11} /> Knowledge
            </Button>
          </div>
        </div>
      )}

      {itemsQuery.error && <p role="alert" className="mt-3 text-xs text-rose-600">{itemsQuery.error instanceof Error ? itemsQuery.error.message : "Unable to load Knowledge cards."}</p>}
      {errorMessage && <p role="alert" className="mt-3 text-xs text-rose-600">{errorMessage}</p>}
    </section>
  )
}
