import { Pencil, Trash2, X } from "lucide-react"
import { useState } from "react"

import { Button } from "../../shared/ui/Button"
import type { KnowledgeBoard, KnowledgeBoardUpdateInput } from "./knowledge-types"

export function KnowledgeBoardManageDialog({
  board,
  saving,
  deleting,
  onClose,
  onSave,
  onDelete,
}: {
  board: KnowledgeBoard | null
  saving: boolean
  deleting: boolean
  onClose: () => void
  onSave: (payload: KnowledgeBoardUpdateInput) => void
  onDelete: () => void
}) {
  if (!board) return null
  return (
    <KnowledgeBoardManageDialogContent
      key={board.board_id}
      board={board}
      saving={saving}
      deleting={deleting}
      onClose={onClose}
      onSave={onSave}
      onDelete={onDelete}
    />
  )
}

function KnowledgeBoardManageDialogContent({
  board,
  saving,
  deleting,
  onClose,
  onSave,
  onDelete,
}: {
  board: KnowledgeBoard
  saving: boolean
  deleting: boolean
  onClose: () => void
  onSave: (payload: KnowledgeBoardUpdateInput) => void
  onDelete: () => void
}) {
  const [name, setName] = useState(board.name)
  const [description, setDescription] = useState(board.description)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const busy = saving || deleting
  const defaultBoard = board.board_id === "kb_default"
  const valid = name.trim().length > 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/25 p-4 backdrop-blur-[2px]" role="presentation" onMouseDown={() => !busy && onClose()}>
      <section className="w-full max-w-lg rounded-[22px] border border-white/60 bg-white p-5 shadow-2xl" role="dialog" aria-modal="true" aria-label="Manage knowledge canvas" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4">
          <div>
            <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400"><Pencil size={12} />Canvas settings</p>
            <h3 className="mt-1.5 text-lg font-semibold text-slate-950">Manage canvas</h3>
          </div>
          <Button variant="ghost" size="xs" aria-label="Close canvas settings" disabled={busy} onClick={onClose}><X size={16} /></Button>
        </header>

        <label className="mt-5 block text-xs font-semibold text-slate-700">
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} className="mt-2 w-full rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300" placeholder="Canvas name" />
        </label>
        <label className="mt-4 block text-xs font-semibold text-slate-700">
          Description
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} className="mt-2 w-full resize-none rounded-[13px] border border-slate-200 px-3 py-2.5 text-sm font-normal outline-none transition focus:border-cyan-300" placeholder="What is this canvas for?" />
        </label>

        <div className="mt-5 flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <Button
              variant="ghost"
              disabled={busy || defaultBoard}
              onClick={() => setConfirmDelete((current) => !current)}
              className="text-rose-600 hover:bg-rose-50"
            >
              <Trash2 size={13} />{defaultBoard ? "Default canvas" : "Delete canvas"}
            </Button>
            {confirmDelete && !defaultBoard ? (
              <p className="mt-2 max-w-xs text-[10px] leading-4 text-rose-600">Delete this canvas layout? Knowledge cards and canonical relations are preserved.</p>
            ) : null}
          </div>
          <div className="flex justify-end gap-2">
            {confirmDelete && !defaultBoard ? (
              <Button variant="ghost" disabled={busy} onClick={onDelete}>{deleting ? "Deleting…" : "Confirm delete"}</Button>
            ) : null}
            <Button variant="primary" disabled={busy || !valid} onClick={() => onSave({ name: name.trim(), description: description.trim() })}>{saving ? "Saving…" : "Save changes"}</Button>
          </div>
        </div>
      </section>
    </div>
  )
}
