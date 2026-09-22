import {
  BookOpenCheck,
  Highlighter,
  Languages,
  Lightbulb,
  Sparkles,
  StickyNote,
  type LucideIcon,
} from "lucide-react"

type SelectionAction = {
  label: string
  icon: LucideIcon
  onClick: () => void
}

export interface ReadingSelectionActionBarProps {
  left: number
  top: number
  onEvidence: () => void
  onHighlight: () => void
  onNote: () => void
  onConcept: () => void
  onTranslate: () => void
  onAskAi: () => void
}

export default function ReadingSelectionActionBar({
  left,
  top,
  onEvidence,
  onHighlight,
  onNote,
  onConcept,
  onTranslate,
  onAskAi,
}: ReadingSelectionActionBarProps) {
  const actions: SelectionAction[] = [
    { label: "Evidence", icon: BookOpenCheck, onClick: onEvidence },
    { label: "Highlight", icon: Highlighter, onClick: onHighlight },
    { label: "Note", icon: StickyNote, onClick: onNote },
    { label: "Concept", icon: Lightbulb, onClick: onConcept },
    { label: "Translate", icon: Languages, onClick: onTranslate },
    { label: "Ask AI", icon: Sparkles, onClick: onAskAi },
  ]

  return (
    <div
      role="toolbar"
      aria-label="Reading selection actions"
      data-testid="reading-selection-action-bar"
      className="fixed z-[140] flex -translate-x-1/2 -translate-y-full items-center overflow-hidden rounded-[14px] border border-[#dedede] bg-white/98 p-1 shadow-[0_14px_36px_rgba(0,0,0,.14)] backdrop-blur-xl"
      style={{ left, top }}
      onMouseDown={(event) => event.preventDefault()}
    >
      {actions.map(({ label, icon: Icon, onClick }, index) => (
        <button
          key={label}
          type="button"
          onClick={onClick}
          className={`flex h-9 items-center gap-1.5 whitespace-nowrap rounded-[9px] px-2.5 text-[10.5px] font-medium text-[#4c4c4c] transition hover:bg-[#f1f1f1] hover:text-[#171717] ${index > 0 ? "ml-0.5" : ""}`}
        >
          <Icon size={13} strokeWidth={1.7} />
          <span>{label}</span>
        </button>
      ))}
    </div>
  )
}
