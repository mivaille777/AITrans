import { ArrowRight, Check, LoaderCircle, Sparkles, X } from "lucide-react"
import { useMemo } from "react"

import type { KnowledgeItem, KnowledgeRelationSuggestion } from "./knowledge-types"
import type { KnowledgeRelationSuggestionController } from "./useKnowledgeRelationSuggestions"

export default function KnowledgeSuggestionInbox({
  focusItemId,
  items,
  controller,
  onSelectItem,
  onClose,
}: {
  focusItemId: string
  items: KnowledgeItem[]
  controller: KnowledgeRelationSuggestionController
  onSelectItem: (itemId: string) => void
  onClose: () => void
}) {
  const itemById = useMemo(() => new Map(items.map((item) => [item.item_id, item] as const)), [items])
  const suggestions = controller.suggestionsQuery.data?.suggestions ?? []
  const candidateItemIds = items.filter((item) => item.item_id !== focusItemId).map((item) => item.item_id).slice(0, 64)
  const actionError = controller.generateMutation.error ?? controller.acceptMutation.error ?? controller.rejectMutation.error
  const busy = controller.generateMutation.isPending || controller.acceptMutation.isPending || controller.rejectMutation.isPending

  return (
    <section className="knowledge-suggestion-inbox" aria-label="AI suggestion inbox">
      <div className="knowledge-suggestion-heading">
        <div className="knowledge-suggestion-heading-copy">
          <div className="flex items-center gap-2">
            <span className="knowledge-suggestion-icon" aria-hidden="true"><Sparkles size={20} strokeWidth={1.6} /></span>
            <h2>AI Suggestion Inbox</h2>
          </div>
          <p>Get AI suggestions for related papers, concepts, evidence, and connections. Review before adding.</p>
        </div>
        <button type="button" className="knowledge-suggestion-close" aria-label="Hide AI suggestion inbox" onClick={onClose}><X size={15} /></button>
      </div>

      <button
        type="button"
        className="knowledge-suggestion-button"
        disabled={!focusItemId || candidateItemIds.length === 0 || busy}
        onClick={() => controller.generateMutation.mutate({
          focus_item_id: focusItemId,
          candidate_item_ids: candidateItemIds,
          max_suggestions: 4,
        })}
      >
        {controller.generateMutation.isPending ? <LoaderCircle size={14} className="animate-spin" /> : <Sparkles size={14} />}
        {controller.generateMutation.isPending ? "Analyzing…" : "Suggest related items"}
        {!controller.generateMutation.isPending ? <ArrowRight size={14} /> : null}
      </button>

      {actionError ? <p role="alert" className="knowledge-suggestion-error">{errorMessage(actionError)}</p> : null}
      {controller.suggestionsQuery.isPending ? <p className="knowledge-suggestion-status">Loading pending suggestions…</p> : null}
      {suggestions.length > 0 ? (
        <div className="knowledge-suggestion-list">
          {suggestions.slice(0, 3).map((suggestion) => (
            <SuggestionRow
              key={suggestion.suggestion_id}
              suggestion={suggestion}
              source={itemById.get(suggestion.source_item_id)}
              target={itemById.get(suggestion.target_item_id)}
              accepting={controller.acceptMutation.isPending && controller.acceptMutation.variables === suggestion.suggestion_id}
              rejecting={controller.rejectMutation.isPending && controller.rejectMutation.variables === suggestion.suggestion_id}
              onAccept={() => controller.acceptMutation.mutate(suggestion.suggestion_id)}
              onReject={() => controller.rejectMutation.mutate(suggestion.suggestion_id)}
              onSelectItem={onSelectItem}
            />
          ))}
        </div>
      ) : null}
    </section>
  )
}

function SuggestionRow({
  suggestion,
  source,
  target,
  accepting,
  rejecting,
  onAccept,
  onReject,
  onSelectItem,
}: {
  suggestion: KnowledgeRelationSuggestion
  source?: KnowledgeItem
  target?: KnowledgeItem
  accepting: boolean
  rejecting: boolean
  onAccept: () => void
  onReject: () => void
  onSelectItem: (itemId: string) => void
}) {
  return (
    <article className="knowledge-suggestion-card">
      <div className="flex items-center justify-between gap-2">
        <button type="button" onClick={() => source && onSelectItem(source.item_id)}>{source?.title ?? suggestion.source_item_id}</button>
        <ArrowRight size={11} className="shrink-0 text-slate-400" />
        <button type="button" onClick={() => target && onSelectItem(target.item_id)}>{target?.title ?? suggestion.target_item_id}</button>
      </div>
      <p>{suggestion.label || suggestion.relation_type.replaceAll("_", " ")} · {Math.round(suggestion.confidence * 100)}% confidence</p>
      <div className="knowledge-suggestion-card-actions">
        <button type="button" disabled={accepting || rejecting} onClick={onAccept}>{accepting ? <LoaderCircle size={10} className="inline animate-spin" /> : <Check size={10} className="mr-1 inline" />}Accept</button>
        <button type="button" disabled={accepting || rejecting} onClick={onReject}>{rejecting ? <LoaderCircle size={10} className="inline animate-spin" /> : null}Dismiss</button>
      </div>
    </article>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to process AI relation suggestions."
}
