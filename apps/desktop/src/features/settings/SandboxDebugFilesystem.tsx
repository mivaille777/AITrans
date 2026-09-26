import { Copy, FileInput, FileOutput, ShieldCheck } from "lucide-react"
import { useMemo, useState, type ReactNode } from "react"

import type {
  SandboxActivityEvent,
  SandboxDebugFile,
  SandboxDebugTrace,
} from "../../api/sandbox-debug"

type ActivityFilter = "all" | "file" | "network" | "process" | "denied"

const SAFE_CONTAINER_PATH_ROOTS = ["/input", "/workspace", "/output", "/tmp"] as const

export default function SandboxDebugFilesystem({ trace }: { trace: SandboxDebugTrace | null }) {
  const [filter, setFilter] = useState<ActivityFilter>("all")
  const [query, setQuery] = useState("")

  const activities = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return (trace?.activities ?? [])
      .slice(-500)
      .filter((item) => {
        if (filter === "denied" && item.decision !== "denied") return false
        if (filter !== "all" && filter !== "denied" && item.kind !== filter) return false
        if (!normalizedQuery) return true
        return safeDisplayPath(item.target).toLowerCase().includes(normalizedQuery)
      })
  }, [filter, query, trace?.activities])

  if (!trace) {
    return (
      <div className="flex h-full items-center justify-center overflow-auto px-8 py-10">
        <div className="w-full max-w-3xl rounded-[10px] border border-slate-200 bg-white px-8 py-10 text-center shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Sandbox / Filesystem</p>
          <h2 className="mt-3 text-[16px] font-semibold text-slate-900">No filesystem activity recorded</h2>
          <p className="mx-auto mt-2 max-w-xl text-[12px] leading-5 text-slate-500">
            Run a Sandbox trace with workspace input to inspect staged files and file access.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto bg-slate-50/40 px-8 py-6">
      <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-5">
        <section className="rounded-[10px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Filesystem Boundary</p>
              <h2 className="mt-1 text-[15px] font-semibold text-slate-900">
                {trace.run.workspace_name || "No workspace"}
              </h2>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-[10px] font-medium text-slate-600">
              <ShieldCheck size={12} />
              Direct host mount disabled
            </span>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <BoundaryCard label="Workspace" value={trace.run.workspace_name || "—"} />
            <BoundaryCard label="/input" value="Read only" />
            <BoundaryCard label="/workspace" value="Read / Write" />
            <BoundaryCard label="/output" value="Read / Write" />
          </div>
        </section>

        <FileSection title="Staged Inputs" icon={<FileInput size={14} />} files={trace.input_files} empty="No staged inputs" />

        <section className="rounded-[10px] border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Container Activity</p>
              <h2 className="mt-1 text-[15px] font-semibold text-slate-900">Observed file and runtime access</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {([
                ["all", "All"],
                ["file", "File"],
                ["network", "Network"],
                ["process", "Process"],
                ["denied", "Denied only"],
              ] as Array<[ActivityFilter, string]>).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setFilter(id)}
                  className={`rounded-[7px] border px-2.5 py-1.5 text-[10px] font-medium ${
                    filter === id ? "border-slate-300 bg-slate-100 text-slate-900" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                  }`}
                >
                  {label}
                </button>
              ))}
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search filesystem activity"
                placeholder="Search target"
                className="h-7 min-w-40 rounded-[7px] border border-slate-200 bg-white px-2.5 text-[10px] text-slate-700 outline-none focus:border-slate-400"
              />
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left">
              <thead>
                <tr className="border-b border-slate-100 text-[9px] uppercase tracking-[0.09em] text-slate-400">
                  <th className="px-5 py-2.5 font-medium">Time</th>
                  <th className="px-3 py-2.5 font-medium">Type</th>
                  <th className="px-3 py-2.5 font-medium">Target</th>
                  <th className="px-3 py-2.5 font-medium">Action</th>
                  <th className="px-5 py-2.5 font-medium">Decision</th>
                </tr>
              </thead>
              <tbody>
                {activities.map((activity) => <ActivityRow key={activity.sequence} activity={activity} />)}
                {activities.length === 0 && (
                  <tr><td colSpan={5} className="px-5 py-10 text-center text-[11px] text-slate-400">No activity matches the current filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <FileSection title="Collected Outputs" icon={<FileOutput size={14} />} files={trace.output_files} empty="No collected outputs" output />
      </div>
    </div>
  )
}

function BoundaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[8px] border border-slate-200 bg-slate-50 px-3 py-2.5">
      <p className="text-[9px] uppercase tracking-[0.09em] text-slate-400">{label}</p>
      <p className="mt-1 text-[11px] font-medium text-slate-700">{value}</p>
    </div>
  )
}

function FileSection({
  title,
  icon,
  files,
  empty,
  output = false,
}: {
  title: string
  icon: ReactNode
  files: SandboxDebugFile[]
  empty: string
  output?: boolean
}) {
  return (
    <section className="rounded-[10px] border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
      <div className="flex items-center gap-2 border-b border-slate-200 px-5 py-4">
        {icon}
        <h2 className="text-[12px] font-semibold text-slate-800">{title}</h2>
      </div>
      {files.length === 0 ? (
        <p className="px-5 py-8 text-center text-[11px] text-slate-400">{empty}</p>
      ) : (
        <div className="divide-y divide-slate-100">
          {files.map((file) => (
            <div key={file.file_id || file.path} className="flex items-center gap-4 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-[10px] text-slate-700">{safeDisplayPath(file.path)}</p>
                <p className="mt-1 text-[9px] text-slate-400">{formatBytes(file.size_bytes)} · {file.source}</p>
              </div>
              {file.sha256 ? <span className="hidden max-w-56 truncate font-mono text-[9px] text-slate-400 md:block">sha256 {file.sha256}</span> : null}
              {output && file.file_id ? (
                <button
                  type="button"
                  onClick={() => void copyText(file.file_id)}
                  className="inline-flex items-center gap-1 rounded-[7px] border border-slate-200 px-2 py-1 text-[9px] text-slate-500 hover:bg-slate-50"
                >
                  <Copy size={10} />
                  Copy file id
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function ActivityRow({ activity }: { activity: SandboxActivityEvent }) {
  const decisionClass = activity.decision === "allowed"
    ? "bg-emerald-50 text-emerald-700"
    : activity.decision === "denied"
      ? "bg-rose-50 text-rose-700"
      : "bg-slate-100 text-slate-600"

  return (
    <tr className="border-b border-slate-100 text-[10px] text-slate-600 last:border-b-0">
      <td className="whitespace-nowrap px-5 py-3 text-slate-400">{formatTime(activity.timestamp)}</td>
      <td className="px-3 py-3 uppercase text-slate-500">{activity.kind}</td>
      <td className="max-w-[360px] truncate px-3 py-3 font-mono" title={safeDisplayPath(activity.target)}>{safeDisplayPath(activity.target)}</td>
      <td className="px-3 py-3 uppercase">{activity.action}</td>
      <td className="px-5 py-3">
        <span className={`inline-flex rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase ${decisionClass}`}>
          {activity.decision}
        </span>
        {activity.reason ? <p className="mt-1 font-mono text-[8px] text-slate-400">{activity.reason}</p> : null}
      </td>
    </tr>
  )
}

function safeDisplayPath(value: string): string {
  const path = value.trim()
  if (!path) return "—"

  const knownContainerPath = SAFE_CONTAINER_PATH_ROOTS.some(
    (root) => path === root || path.startsWith(`${root}/`),
  )
  const windowsHostPath = /^[a-zA-Z]:[\\/]/.test(path)
  const uncHostPath = /^\\\\/.test(path)
  const fileUri = /^file:\/\//i.test(path)
  const unknownPosixAbsolutePath = path.startsWith("/") && !knownContainerPath

  if (windowsHostPath || uncHostPath || fileUri || unknownPosixAbsolutePath) {
    const filename = path.split(/[\\/]/).filter(Boolean).at(-1) ?? "path"
    return `[host path redacted]/${filename}`
  }
  return path
}

function formatTime(value: string): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

async function copyText(value: string): Promise<void> {
  if (typeof navigator === "undefined" || !navigator.clipboard) return
  await navigator.clipboard.writeText(value)
}
