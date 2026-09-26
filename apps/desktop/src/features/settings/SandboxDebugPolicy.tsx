import { AlertTriangle, CheckCircle2, ShieldCheck } from "lucide-react"

import type { SandboxDebugTrace, SandboxEffectivePolicy } from "../../api/sandbox-debug"

export default function SandboxDebugPolicy({ trace }: { trace: SandboxDebugTrace | null }) {
  if (!trace) {
    return (
      <div className="flex h-full items-center justify-center overflow-auto px-8 py-10">
        <div className="w-full max-w-3xl rounded-[10px] border border-slate-200 bg-white px-8 py-10 text-center shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <h2 className="text-[16px] font-semibold text-slate-900">No effective policy recorded</h2>
          <p className="mx-auto mt-2 max-w-xl text-[12px] leading-5 text-slate-500">
            The security policy enforced for a Sandbox run will appear here once runtime data is available.
          </p>
        </div>
      </div>
    )
  }

  const policy = trace.policy
  const warnings = policyWarnings(policy)
  const rows = buildRows(policy)

  return (
    <div className="h-full overflow-auto bg-slate-50/40 px-8 py-6">
      <div className="mx-auto flex w-full max-w-[980px] flex-col gap-5">
        <section className="rounded-[10px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="flex items-start justify-between gap-5">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Effective Policy</p>
              <h2 className="mt-1 text-[15px] font-semibold text-slate-900">Runtime-enforced sandbox boundary</h2>
              <p className="mt-1 text-[11px] leading-5 text-slate-500">
                This view is read-only. Display warnings do not replace backend or Docker enforcement.
              </p>
            </div>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold ${
              warnings.length === 0 ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
            }`}>
              {warnings.length === 0 ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
              {warnings.length === 0 ? "Policy enforced" : `${warnings.length} warning${warnings.length === 1 ? "" : "s"}`}
            </span>
          </div>
        </section>

        {warnings.length > 0 ? (
          <section className="rounded-[10px] border border-rose-200 bg-rose-50/60 px-4 py-3">
            <div className="flex gap-2">
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-rose-600" />
              <div>
                <h3 className="text-[11px] font-semibold text-rose-800">Unsafe policy conditions detected</h3>
                <ul className="mt-1 space-y-1 text-[10px] leading-4 text-rose-700">
                  {warnings.map((warning) => <li key={warning}>• {warning}</li>)}
                </ul>
              </div>
            </div>
          </section>
        ) : null}

        <section className="overflow-hidden rounded-[10px] border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="flex items-center gap-2">
              <ShieldCheck size={14} className="text-slate-500" />
              <h2 className="text-[12px] font-semibold text-slate-800">Policy snapshot for {trace.run.sandbox_id}</h2>
            </div>
          </div>
          <div className="divide-y divide-slate-100">
            {rows.map((row) => (
              <div key={row.label} className="grid gap-3 px-5 py-3.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_120px] sm:items-center">
                <p className="text-[10px] font-medium text-slate-500">{row.label}</p>
                <p className="break-words font-mono text-[10px] text-slate-800">{row.value}</p>
                <span className={`inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-semibold ${
                  row.safe ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
                }`}>
                  {row.safe ? <CheckCircle2 size={10} /> : <AlertTriangle size={10} />}
                  {row.safe ? "Enforced" : "Unsafe"}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

export function policyWarnings(policy: SandboxEffectivePolicy): string[] {
  const warnings: string[] = []
  if (policy.network.trim().toLowerCase() !== "none") warnings.push("Network is not disabled.")
  if (!policy.root_filesystem_read_only) warnings.push("Root filesystem is writable.")
  if (["0", "0:0", "root"].includes(policy.user.trim().toLowerCase())) warnings.push("Sandbox is running as root.")
  if (!policy.cap_drop.map((item) => item.toUpperCase()).includes("ALL")) warnings.push("Linux capabilities are not fully dropped.")
  if (!policy.no_new_privileges) warnings.push("New privileges are allowed.")
  if (!policy.seccomp.trim() || policy.seccomp.trim().toLowerCase() === "unconfined") warnings.push("Seccomp is unconfined.")
  if (policy.docker_socket_mounted) warnings.push("Docker socket is mounted.")
  if (policy.cpu_limit <= 0) warnings.push("CPU limit is not enforced.")
  if (policy.memory_limit_bytes <= 0) warnings.push("Memory limit is not enforced.")
  if (policy.pids_limit <= 0) warnings.push("PID limit is not enforced.")
  if (policy.timeout_seconds <= 0) warnings.push("Execution timeout is not enforced.")
  return warnings
}

function buildRows(policy: SandboxEffectivePolicy) {
  const capabilitiesSafe = policy.cap_drop.map((item) => item.toUpperCase()).includes("ALL")
  const seccompSafe = Boolean(policy.seccomp.trim()) && policy.seccomp.trim().toLowerCase() !== "unconfined"
  const userSafe = !["0", "0:0", "root"].includes(policy.user.trim().toLowerCase())
  return [
    { label: "Network", value: policy.network || "—", safe: policy.network.trim().toLowerCase() === "none" },
    { label: "Root filesystem", value: policy.root_filesystem_read_only ? "read-only" : "read / write", safe: policy.root_filesystem_read_only },
    { label: "User", value: policy.user || "—", safe: userSafe },
    { label: "Capabilities", value: policy.cap_drop.length ? `DROP ${policy.cap_drop.join(", ")}` : "—", safe: capabilitiesSafe },
    { label: "New privileges", value: policy.no_new_privileges ? "disabled" : "allowed", safe: policy.no_new_privileges },
    { label: "Seccomp", value: policy.seccomp || "—", safe: seccompSafe },
    { label: "CPU", value: policy.cpu_limit > 0 ? `${policy.cpu_limit} core${policy.cpu_limit === 1 ? "" : "s"}` : "unlimited", safe: policy.cpu_limit > 0 },
    { label: "Memory", value: policy.memory_limit_bytes > 0 ? formatBytes(policy.memory_limit_bytes) : "unlimited", safe: policy.memory_limit_bytes > 0 },
    { label: "PIDs", value: policy.pids_limit > 0 ? String(policy.pids_limit) : "unlimited", safe: policy.pids_limit > 0 },
    { label: "Timeout", value: policy.timeout_seconds > 0 ? `${policy.timeout_seconds} s` : "none", safe: policy.timeout_seconds > 0 },
    { label: "stdout", value: formatBytes(policy.stdout_limit_bytes), safe: policy.stdout_limit_bytes > 0 },
    { label: "stderr", value: formatBytes(policy.stderr_limit_bytes), safe: policy.stderr_limit_bytes > 0 },
    { label: "Docker socket", value: policy.docker_socket_mounted ? "mounted" : "not mounted", safe: !policy.docker_socket_mounted },
  ]
}

function formatBytes(value: number): string {
  if (value <= 0) return "none"
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`
}
