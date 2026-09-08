import {
  ArrowLeft,
  Bot,
  BookOpenCheck,
  ExternalLink,
  FileText,
  Highlighter,
  Languages,
  Lightbulb,
  LoaderCircle,
  NotebookPen,
  Save,
  Sparkles,
  StickyNote,
} from "lucide-react"
import { useRef, useState, type ReactNode } from "react"
import { useNavigate } from "react-router-dom"

import { desktop } from "../../desktop"
import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { paperPageLabel } from "./paper-reader-state"
import type { KnowledgeItem } from "./knowledge-types"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"
import { usePaperReader } from "./usePaperReader"

type InspectorTab = "overview" | "notes" | "ai" | "translation"
type ReaderMode = "text" | "pdf"

interface TextSelectionState {
  text: string
  left: number
  top: number
}

interface KnowledgePaperReaderPanelProps {
  paperItemId: string
  library: KnowledgeLibraryController
  workspace: TranslationWorkspaceController
  onBack: () => void
}

export default function KnowledgePaperReaderPanel(props: KnowledgePaperReaderPanelProps) {
  return <KnowledgePaperReaderContent key={props.paperItemId} {...props} />
}

function KnowledgePaperReaderContent({
  paperItemId,
  library,
  workspace,
  onBack,
}: KnowledgePaperReaderPanelProps) {
  const navigate = useNavigate()
  const reader = usePaperReader(paperItemId, library, workspace)
  const articleRef = useRef<HTMLDivElement | null>(null)
  const [selection, setSelection] = useState<TextSelectionState | null>(null)
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("overview")
  const [readerMode, setReaderMode] = useState<ReaderMode>("text")
  const [aiQuestion, setAiQuestion] = useState("")
  const [openError, setOpenError] = useState("")

  const { paper, document, sectionQuery } = reader

  function captureSelection() {
    window.setTimeout(() => {
      const current = window.getSelection()
      if (!current || current.isCollapsed || current.rangeCount === 0) {
        setSelection(null)
        return
      }
      const range = current.getRangeAt(0)
      const article = articleRef.current
      if (!article || !article.contains(range.commonAncestorContainer)) {
        setSelection(null)
        return
      }
      const text = current.toString().trim()
      if (!text) {
        setSelection(null)
        return
      }
      const rect = range.getBoundingClientRect()
      setSelection({
        text,
        left: Math.min(window.innerWidth - 220, Math.max(220, rect.left + rect.width / 2)),
        top: Math.max(68, rect.top - 12),
      })
    }, 0)
  }

  function clearSelection() {
    window.getSelection()?.removeAllRanges()
    setSelection(null)
  }

  function createSelectionCard(itemType: "highlight" | "note" | "concept") {
    if (!selection) return
    reader.createDerivedMutation.mutate(
      { itemType, text: selection.text },
      {
        onSuccess: () => {
          setInspectorTab("notes")
          clearSelection()
        },
      },
    )
  }

  function askAi() {
    if (!selection) return
    if (reader.attachSelectionToAgent(selection.text)) {
      setInspectorTab("ai")
      setAiQuestion((current) => current || "Explain this passage in the context of the paper.")
    }
    clearSelection()
  }

  function translateSelection() {
    if (!selection) return
    reader.translationMutation.mutate(selection.text)
    setInspectorTab("translation")
    clearSelection()
  }

  function attachCurrentSection() {
    if (!reader.attachSectionToAgent()) return
    setInspectorTab("ai")
    setAiQuestion((current) => current || "Summarize this section and explain its main contribution.")
  }

  function openAgentWithQuestion(question: string) {
    const normalized = question.trim()
    if (!normalized) return
    navigate("/agent", {
      state: {
        agentDraftPrompt: normalized,
        autoSubmitAgentPrompt: true,
      },
    })
  }

  if (!paper || paper.item_type !== "paper") {
    return <ReaderMessage title="Paper unavailable" description="The requested knowledge card no longer exists or is not a paper." onBack={onBack} />
  }

  if (!document) {
    return <ReaderMessage title="No indexed source attached" description="This manual paper card does not have a local indexed document yet." onBack={onBack} />
  }

  const canPreviewPdf = document.source_type === "pdf" && Boolean(reader.previewUrl)
  const pdfPage = reader.activeOutlineSection?.page_start ?? sectionQuery.data?.page_start ?? 1
  const pdfPreviewUrl = canPreviewPdf ? `${reader.previewUrl}#page=${Math.max(1, pdfPage)}` : ""

  return (
    <section className="ait-surface overflow-hidden">
      <header className="flex flex-col gap-4 border-b border-slate-200/70 px-5 py-4 lg:flex-row lg:items-center lg:justify-between lg:px-6">
        <div className="flex min-w-0 items-start gap-3">
          <Button variant="ghost" size="xs" onClick={onBack}><ArrowLeft size={14} />Library</Button>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Paper reader</p>
            <h2 className="mt-1 truncate text-lg font-semibold text-slate-950">{paper.title}</h2>
            <p className="mt-1 text-xs text-slate-400">{document.source_type.toUpperCase()} · {document.chunk_count} indexed chunks · {document.status}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canPreviewPdf && (
            <div className="flex rounded-[10px] bg-slate-100 p-1" aria-label="Paper reader mode">
              <button type="button" className={`flex items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-[10px] font-semibold ${readerMode === "text" ? "bg-white text-slate-800 shadow-sm" : "text-slate-500"}`} onClick={() => setReaderMode("text")}><BookOpenCheck size={12} />Text</button>
              <button type="button" className={`flex items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-[10px] font-semibold ${readerMode === "pdf" ? "bg-white text-slate-800 shadow-sm" : "text-slate-500"}`} onClick={() => { clearSelection(); setReaderMode("pdf") }}><FileText size={12} />PDF</button>
            </div>
          )}
          <Button variant="ghost" size="sm" onClick={() => {
            setOpenError("")
            void desktop.files.openEvidenceSource(document.source_uri).catch((error: unknown) => setOpenError(error instanceof Error ? error.message : "Unable to open source."))
          }}><ExternalLink size={14} />Open externally</Button>
          <Button size="sm" onClick={attachCurrentSection} disabled={!sectionQuery.data}><BookOpenCheck size={14} />Use section in AI</Button>
        </div>
      </header>

      {openError && <div role="alert" className="border-b border-rose-100 bg-rose-50 px-5 py-2 text-xs text-rose-700 lg:px-6">{openError}</div>}

      <div className="grid min-h-[640px] xl:h-[calc(100vh-210px)] xl:min-h-[640px] xl:grid-cols-[250px_minmax(0,1fr)_300px] xl:grid-rows-[minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col border-b border-slate-200/70 bg-slate-50/45 p-4 xl:border-b-0 xl:border-r">
          <div className="flex items-center justify-between px-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Outline</p>
            {reader.outlineQuery.data && <span className="text-[10px] text-slate-400">{reader.outlineQuery.data.page_count || "—"} pages</span>}
          </div>
          <div className="ait-scroll-panel mt-3 min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain pr-1">
            {document.status !== "ready" ? (
              <p className="px-2 text-xs leading-5 text-slate-500">The paper is still {document.status}. Reader sections become available after indexing finishes.</p>
            ) : reader.outlineQuery.isPending ? (
              <p className="flex items-center gap-2 px-2 text-xs text-slate-500"><LoaderCircle size={13} className="animate-spin" />Loading outline…</p>
            ) : reader.sections.length === 0 ? (
              <p className="px-2 text-xs leading-5 text-slate-500">No structured sections were detected.</p>
            ) : reader.sections.map((section) => (
              <button
                key={section.section_id}
                type="button"
                onClick={() => {
                  reader.selectSection(section.section_id)
                  clearSelection()
                }}
                className={`w-full rounded-[10px] border px-2.5 py-2 text-left transition ${reader.activeSectionId === section.section_id ? "border-slate-300 bg-white shadow-sm" : "border-transparent hover:border-slate-200 hover:bg-white/70"}`}
                style={{ paddingLeft: `${10 + Math.min(Math.max(section.level - 1, 0), 4) * 10}px` }}
              >
                <p className={`line-clamp-2 text-xs ${section.reference_section ? "text-slate-400" : "font-medium text-slate-700"}`}>{section.heading || "Document introduction"}</p>
                <p className="mt-1 text-[10px] text-slate-400">{paperPageLabel(section.page_start, section.page_end)}</p>
              </button>
            ))}
          </div>
        </aside>

        <main className="flex min-h-0 flex-col border-b border-slate-200/70 bg-white xl:border-b-0 xl:border-r">
          {readerMode === "pdf" && canPreviewPdf ? (
            <>
              <div className="flex items-center justify-between border-b border-slate-100 px-5 py-2.5 text-[10px] text-slate-500">
                <span>Visual PDF preview · page {Math.max(1, pdfPage)}</span>
                <span>Switch to Text mode for Highlight, Note, Translate, and Ask AI selection actions.</span>
              </div>
              <iframe
                key={pdfPreviewUrl}
                title={`PDF preview · ${paper.title}`}
                src={pdfPreviewUrl}
                className="min-h-0 flex-1 border-0 bg-slate-100"
              />
            </>
          ) : sectionQuery.isPending ? (
            <div className="flex flex-1 items-center justify-center gap-2 text-sm text-slate-500"><LoaderCircle size={15} className="animate-spin" />Loading section…</div>
          ) : sectionQuery.data ? (
            <>
              <div className="border-b border-slate-100 px-6 py-4 lg:px-8">
                <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400">{paperPageLabel(sectionQuery.data.page_start, sectionQuery.data.page_end)}</p>
                <h3 className="mt-1.5 text-base font-semibold text-slate-900">{sectionQuery.data.heading || "Document introduction"}</h3>
                {sectionQuery.data.truncated && <Badge tone="warning" className="mt-2">Preview truncated</Badge>}
              </div>
              <div className="ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-6 lg:px-10 lg:py-8">
                <article
                  ref={articleRef}
                  className="mx-auto max-w-3xl select-text whitespace-pre-wrap text-[15px] leading-8 text-slate-700"
                  onMouseUp={captureSelection}
                  onKeyUp={captureSelection}
                >
                  {sectionQuery.data.text || "This section contains no extractable text."}
                </article>
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-slate-500">Choose a ready paper section from the outline.</div>
          )}
        </main>

        <aside className="flex min-h-0 flex-col bg-slate-50/35 p-4">
          <div className="grid grid-cols-4 gap-1 rounded-[12px] bg-slate-100 p-1">
            {(["overview", "notes", "ai", "translation"] as InspectorTab[]).map((tab) => (
              <button key={tab} type="button" className={`rounded-[9px] px-1.5 py-1.5 text-[9px] font-semibold capitalize ${inspectorTab === tab ? "bg-white text-slate-800 shadow-sm" : "text-slate-500"}`} onClick={() => setInspectorTab(tab)}>{tab === "translation" ? "Translate" : tab}</button>
            ))}
          </div>
          <div className="ait-scroll-panel mt-4 min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {inspectorTab === "overview" && <OverviewInspector paper={paper} document={document} sectionCount={reader.sections.length} />}
            {inspectorTab === "notes" && <NotesInspector reader={reader} />}
            {inspectorTab === "ai" && (
              <AiInspector
                workspace={workspace}
                documentId={document.document_id}
                question={aiQuestion}
                onQuestionChange={setAiQuestion}
                onAsk={openAgentWithQuestion}
              />
            )}
            {inspectorTab === "translation" && <TranslationInspector reader={reader} />}
          </div>
        </aside>
      </div>

      {selection && readerMode === "text" && (
        <div className="fixed z-[70] -translate-x-1/2 -translate-y-full rounded-[13px] border border-slate-200 bg-white p-1.5 shadow-2xl" style={{ left: selection.left, top: selection.top }} role="toolbar" aria-label="Paper selection actions">
          <div className="flex items-center gap-1">
            <SelectionAction icon={<Highlighter size={13} />} label="Highlight" onClick={() => createSelectionCard("highlight")} />
            <SelectionAction icon={<StickyNote size={13} />} label="Note" onClick={() => createSelectionCard("note")} />
            <SelectionAction icon={<Lightbulb size={13} />} label="Concept" onClick={() => createSelectionCard("concept")} />
            <SelectionAction icon={<Languages size={13} />} label="Translate" onClick={translateSelection} />
            <SelectionAction icon={<Sparkles size={13} />} label="Ask AI" onClick={askAi} />
          </div>
        </div>
      )}
    </section>
  )
}

function SelectionAction({ icon, label, onClick }: { icon: ReactNode; label: string; onClick: () => void }) {
  return <button type="button" className="flex items-center gap-1.5 rounded-[9px] px-2.5 py-1.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-100 hover:text-slate-900" onMouseDown={(event) => event.preventDefault()} onClick={onClick}>{icon}{label}</button>
}

function OverviewInspector({ paper, document, sectionCount }: { paper: KnowledgeItem; document: { status: string; chunk_count: number; indexed_at: string | null; source_uri: string }; sectionCount: number }) {
  return <div className="space-y-4"><InspectorBlock label="Paper" value={paper.title} /><InspectorBlock label="Index" value={`${document.status} · ${document.chunk_count} chunks · ${sectionCount} sections`} /><InspectorBlock label="Source" value={document.source_uri} mono />{document.indexed_at && <InspectorBlock label="Last indexed" value={new Date(document.indexed_at).toLocaleString()} />}</div>
}

function NotesInspector({ reader }: { reader: ReturnType<typeof usePaperReader> }) {
  const derived = reader.linked.filter(({ relation, item }) => (
    relation.relation_type !== "reading_note"
    && (item.item_type === "note" || item.item_type === "highlight" || item.item_type === "concept")
  ))
  const createError = reader.createDerivedMutation.error
  const updateError = reader.updateReadingNoteMutation.error

  return (
    <div className="space-y-5">
      <section>
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Reading note</p>
          {!reader.readingNote && (
            <Button size="xs" disabled={reader.createDerivedMutation.isPending} onClick={() => reader.createDerivedMutation.mutate({ itemType: "note", text: "", relationType: "reading_note" })}><NotebookPen size={12} />Create</Button>
          )}
        </div>
        {reader.readingNote ? (
          <ReadingNoteEditor
            key={`${reader.readingNote.item_id}:${reader.readingNote.updated_at}`}
            reader={reader}
            note={reader.readingNote}
          />
        ) : (
          <p className="mt-2 rounded-[12px] border border-dashed border-slate-200 p-3 text-xs leading-5 text-slate-500">Create one persistent reading note for this paper. Selection notes remain separate derived cards.</p>
        )}
        {(createError || updateError) && <p className="mt-2 text-xs text-rose-600">{(createError ?? updateError) instanceof Error ? (createError ?? updateError as Error)?.message : "Unable to save reading note."}</p>}
      </section>

      <section>
        <div className="flex items-center justify-between gap-2"><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Derived knowledge</p><span className="text-[9px] text-slate-400">{derived.length}</span></div>
        <div className="mt-3 space-y-2">
          {derived.length === 0 ? <p className="rounded-[12px] border border-dashed border-slate-200 p-3 text-xs leading-5 text-slate-500">Select text in Text mode to create highlights, notes, or concept cards.</p> : derived.map(({ relation, item }) => <div key={relation.relation_id} className="rounded-[12px] border border-slate-200 bg-white p-3"><div className="flex items-center gap-2"><Badge>{item.item_type}</Badge><span className="text-[9px] text-slate-400">{relation.relation_type.replaceAll("_", " ")}</span></div><p className="mt-2 text-xs font-semibold text-slate-800">{item.title}</p><p className="mt-1 line-clamp-4 text-[11px] leading-5 text-slate-500">{item.summary || "Empty note."}</p></div>)}
        </div>
      </section>
    </div>
  )
}

function ReadingNoteEditor({
  reader,
  note,
}: {
  reader: ReturnType<typeof usePaperReader>
  note: KnowledgeItem
}) {
  const [draft, setDraft] = useState(note.summary)

  return (
    <div className="mt-3 rounded-[13px] border border-slate-200 bg-white p-3">
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        className="min-h-36 w-full resize-y bg-transparent text-xs leading-6 text-slate-700 outline-none placeholder:text-slate-400"
        placeholder="Write your evolving understanding, questions, and synthesis for this paper…"
      />
      <div className="mt-2 flex items-center justify-between gap-2 border-t border-slate-100 pt-2">
        <span className="text-[9px] text-slate-400">Persistent paper-level note</span>
        <Button size="xs" disabled={reader.updateReadingNoteMutation.isPending || draft === note.summary} onClick={() => reader.updateReadingNoteMutation.mutate(draft)}><Save size={11} />{reader.updateReadingNoteMutation.isPending ? "Saving…" : "Save"}</Button>
      </div>
    </div>
  )
}

function AiInspector({
  workspace,
  documentId,
  question,
  onQuestionChange,
  onAsk,
}: {
  workspace: TranslationWorkspaceController
  documentId: string
  question: string
  onQuestionChange: (value: string) => void
  onAsk: (question: string) => void
}) {
  const attached = workspace.academicReadingContext?.document_id === documentId
  return (
    <div className="space-y-3">
      <div className="rounded-[14px] border border-slate-200 bg-white p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-800"><Bot size={14} />Reader context</div>
        <p className="mt-2 text-[11px] leading-5 text-slate-500">{attached ? "The current paper selection or section is frozen as Agent reading context." : "Select text and choose Ask AI, or attach the current section."}</p>
        {attached && <p className="mt-2 line-clamp-6 whitespace-pre-wrap rounded-[10px] bg-slate-50 p-2 text-[10px] leading-5 text-slate-600">{workspace.academicReadingContext?.text}</p>}
      </div>
      <label className="block text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Question<textarea value={question} onChange={(event) => onQuestionChange(event.target.value)} className="mt-2 min-h-24 w-full resize-y rounded-[12px] border border-slate-200 bg-white p-3 text-xs font-normal leading-5 text-slate-700 outline-none focus:border-cyan-300" placeholder="What do you want the Agent to explain, compare, critique, or extract?" /></label>
      <Button variant="primary" size="sm" disabled={!attached || !question.trim()} onClick={() => onAsk(question)}><Sparkles size={14} />Ask in Agent</Button>
      <p className="text-[9px] leading-4 text-slate-400">The Agent opens with this question and the frozen paper context, then starts the run automatically.</p>
    </div>
  )
}

function TranslationInspector({ reader }: { reader: ReturnType<typeof usePaperReader> }) {
  const mutation = reader.translationMutation
  const saveMutation = reader.saveTranslationAsNoteMutation
  const sourceText = typeof mutation.variables === "string" ? mutation.variables : ""
  return (
    <div className="space-y-3">
      <div className="rounded-[14px] border border-slate-200 bg-white p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-800"><Languages size={14} />Selection translation</div>
        {mutation.isPending ? <p className="mt-3 flex items-center gap-2 text-xs text-slate-500"><LoaderCircle size={13} className="animate-spin" />Translating…</p> : mutation.data ? <><p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{mutation.data.translated_text}</p><div className="mt-3 border-t border-slate-100 pt-3"><Button size="xs" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate({ sourceText, translatedText: mutation.data.translated_text })}><StickyNote size={11} />{saveMutation.isPending ? "Saving…" : "Save as note"}</Button>{saveMutation.data && <span className="ml-2 text-[9px] text-emerald-600">Saved to knowledge cards.</span>}</div></> : <p className="mt-2 text-[11px] leading-5 text-slate-500">Select text in Text mode and choose Translate. The configured translation provider is reused in-place.</p>}
        {mutation.error && <p className="mt-2 text-xs text-rose-600">{mutation.error instanceof Error ? mutation.error.message : "Translation failed."}</p>}
        {saveMutation.error && <p className="mt-2 text-xs text-rose-600">{saveMutation.error instanceof Error ? saveMutation.error.message : "Unable to save translation note."}</p>}
      </div>
    </div>
  )
}

function InspectorBlock({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">{label}</p><p className={`mt-1 break-words text-xs leading-5 text-slate-600 ${mono ? "font-mono text-[10px]" : ""}`}>{value}</p></div>
}

function ReaderMessage({ title, description, onBack }: { title: string; description: string; onBack: () => void }) {
  return <section className="ait-surface p-8"><Button variant="ghost" size="xs" onClick={onBack}><ArrowLeft size={14} />Library</Button><div className="mx-auto max-w-md py-16 text-center"><BookOpenCheck size={28} className="mx-auto text-slate-300" /><h2 className="mt-4 text-lg font-semibold text-slate-900">{title}</h2><p className="mt-2 text-sm leading-6 text-slate-500">{description}</p></div></section>
}
