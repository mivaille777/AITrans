import { Check, FolderOpen, LoaderCircle, ShieldCheck, X } from "lucide-react"

import type { FilesystemWorkspace } from "../../../api/filesystem-workspaces"

export function FilesystemWorkspaceControl({
  workspace,
  loading,
  choosing,
  error,
  disabled,
  onChoose,
  onClear,
}: {
  workspace: FilesystemWorkspace | null
  loading: boolean
  choosing: boolean
  error: string
  disabled: boolean
  onChoose: () => Promise<void>
  onClear: () => void
}) {
  if (loading) {
    return (
      <div className="rounded-[12px] border border-slate-200 bg-slate-50/70 px-3.5 py-3 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-2"><LoaderCircle size={13} className="animate-spin" />Checking filesystem workspace…</span>
      </div>
    )
  }

  if (!workspace) {
    return (
      <div className="rounded-[12px] border border-slate-200 bg-slate-50/70 px-3.5 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-[11px] font-semibold text-slate-800"><FolderOpen size={14} />No filesystem workspace</p>
            <p className="mt-1 text-[10px] leading-4 text-slate-500">Agent cannot access local files until you explicitly choose a folder.</p>
          </div>
          <button
            type="button"
            onClick={() => void onChoose()}
            disabled={disabled || choosing}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-[8px] border border-slate-300 bg-white px-2.5 py-1.5 text-[10px] font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {choosing ? <LoaderCircle size={12} className="animate-spin" /> : <FolderOpen size={12} />}
            Choose folder
          </button>
        </div>
        {error ? <p className="mt-2 text-[10px] text-rose-600" role="alert">{error}</p> : null}
      </div>
    )
  }

  return (
    <div className="rounded-[12px] border border-slate-200 bg-white px-3.5 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-[11px] font-semibold text-slate-900">
            <FolderOpen size={14} />
            <span className="truncate">{workspace.display_name}</span>
          </p>
          <p className="mt-1 text-[10px] text-slate-500">Agent file access is limited to this folder.</p>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <button
            type="button"
            onClick={() => void onChoose()}
            disabled={disabled || choosing}
            className="rounded-[7px] border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Change
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={disabled || choosing}
            aria-label="Clear filesystem workspace"
            className="inline-flex h-7 w-7 items-center justify-center rounded-[7px] border border-slate-200 bg-white text-slate-500 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      <div className="mt-3 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-5">
        <Permission label="Read files" allowed={workspace.readable} />
        <Permission label="Search files" allowed={workspace.readable} />
        <Permission label="Sandbox input" allowed={workspace.readable} />
        <Permission label="Write files" text={workspace.writable ? "Allowed" : "Confirmation required"} allowed={workspace.writable} neutral={!workspace.writable} />
        <Permission label="Outside folder" text="Denied" allowed={false} />
      </div>

      <p className="mt-2 flex items-center gap-1.5 text-[9px] text-slate-400">
        <ShieldCheck size={11} />
        Only the workspace ID is persisted in the UI; host paths are not injected into the Agent prompt.
      </p>
      {error ? <p className="mt-2 text-[10px] text-rose-600" role="alert">{error}</p> : null}
    </div>
  )
}

function Permission({
  label,
  allowed,
  text,
  neutral = false,
}: {
  label: string
  allowed: boolean
  text?: string
  neutral?: boolean
}) {
  const resolvedText = text ?? (allowed ? "Allowed" : "Denied")
  return (
    <div className="rounded-[8px] bg-slate-50 px-2.5 py-2">
      <p className="text-[9px] text-slate-400">{label}</p>
      <p className={`mt-0.5 flex items-center gap-1 text-[9px] font-medium ${neutral ? "text-amber-700" : allowed ? "text-emerald-700" : "text-slate-600"}`}>
        {allowed ? <Check size={10} /> : null}
        {resolvedText}
      </p>
    </div>
  )
}
