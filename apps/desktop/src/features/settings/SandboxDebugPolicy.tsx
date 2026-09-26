import { AlertTriangle, CheckCircle2, ShieldCheck } from "lucide-react"

import type {
  SandboxActivityEvent,
  SandboxDebugTrace,
  SandboxEffectivePolicy,
} from "../../api/sandbox-debug"

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
  const permissionDecisions = trace.activities.filter(
    (activity) => activity.kind === "policy" && activity.action.startsWith("permission."),
  )
  const approvals = latestApprovalEvents(trace.activities)

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
          <div className="flex items-center gap-2 border-b border-slate-200 px-5 py-4">
            <ShieldCheck size={14} className="text-slate-500" />
            <div>
              <h2 className="text-[12px] font-semibold text-slate-800">Permission Decision</h2>
              <p className="mt-1 text-[10px] text-slate-400">Recorded policy decisions for this run.</p>
            </div>
          </div>
          {permissionDecisions.length === 0 ? (
            <p className="px-5 py-7 text-center text-[11px] text-slate-400">No permission decisions recorded.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-slate-100 text-[9px] uppercase tracking-[0.09em] text-slate-400">
                    <th className="px-5 py-2.5 font-medium">Action</th>
                    <th className="px-3 py-2.5 font-medium">Target</th>
                    <th className="px-3 py-2.5 font-medium">Decision</th>
                    <th className="px-3 py-2.5 font-medium">Reason</th>
                    <th className="px-5 py-2.5 font-medium">Rule</th>
                  </tr>
                </thead>
                <tbody>
                  {permissionDecisions.map((activity) => (
                    <PermissionRow key={activity.sequence} activity={activity} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-[10px] border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="flex items-center gap-2 border-b border-slate-200 px-5 py-4">
            <ShieldCheck size={14} className="text-slate-500" />
            <div>
              <h2 className="text-[12px] font-semibold text-slate-800">Approval</h2>
              <p className="mt-1 text-[10px] text-slate-400">Latest status for each approval request.</p>
            </div>
          </div>
          {approvals.length === 0 ? (
            <p className="px-5 py-7 text-center text-[11px] text-slate-400">No approval was requested for this run.</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {approvals.map((activity) => (
                <div key={activity.approval_id} className="grid gap-2 px-5 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                  <div className="min-w-0">
                    <p className="truncate font-mono text-[10px] text-slate-700" title={safeDisplayTarget(activity.target)}>
                      {safeDisplayTarget(activity.target) || activity.permission_action || "Sandbox permission"}
                    </p>
                    <p className="mt-1 truncate font-mono text-[9px] text-slate-400" title={activity.approval_id}>
                      {activity.approval_id}
                      {activity.grant_id ? ` · grant ${activity.grant_id}` : ""}
                    </p>
                  </div>
                  <DecisionBadge decision={activity.decision} />
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-[10px] border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="flex items-center gap-2">
              <ShieldCheck size={14} className="text-slate-500" />
              <h2 className="text-[12px] font-semibold text-slate-800">Policy snapshot for {trace.run.sandbox_id}</h2>
            </div>
          </div>
          <div className="divide-y divide-slate-100">
            {rows.map((row) => {
              const safe = row.state === "safe"
              const unknown = row.state === "unknown"
              return (
                <div key={row.label} className="grid gap-3 px-5 py-3.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_120px] sm:items-center">
                  <p className="text-[10px] font-medium text-slate-500">{row.label}</p>
                  <p className="break-words font-mono text-[10px] text-slate-800">{row.value}</p>
                  <span className={`inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-semibold ${
                    safe
                      ? "bg-emerald-50 text-emerald-700"
                      : unknown
                        ? "bg-amber-50 text-amber-800"
                        : "bg-rose-50 text-rose-700"
                  }`}>
                    {safe ? <CheckCircle2 size={10} /> : <AlertTriangle size={10} />}
                    {safe ? "Enforced" : unknown ? "Unknown" : "Unsafe"}
                  </span>
                </div>
              )
            })}
          </div>
        </section>
      </div>
    </div>
  )
}

export function policyWarnings(policy: SandboxEffectivePolicy): string[] {
  const warnings: string[] = []
  const networkMode = policy.network.trim().toLowerCase()
  if (networkMode !== "none" && networkMode !== "restricted") warnings.push("Network is not disabled or approval-gated.")
  if (!policy.root_filesystem_read_only) warnings.push("Root filesystem is writable.")
  if (!policy.user.trim()) warnings.push("Sandbox user is not reported.")
  else if (["0", "0:0", "root"].includes(policy.user.trim().toLowerCase())) warnings.push("Sandbox is running as root.")
  if (!policy.cap_drop.map((item) => item.toUpperCase()).includes("ALL")) warnings.push("Linux capabilities are not fully dropped.")
  if (!policy.no_new_privileges) warnings.push("New privileges are allowed.")
  if (!policy.seccomp.trim() || policy.seccomp.trim().toLowerCase() === "unconfined") warnings.push("Seccomp is unconfined.")
  if (policy.docker_socket_mounted === true) warnings.push("Docker socket is mounted.")
  if (policy.docker_socket_mounted === null) warnings.push("Docker socket mount status is unknown.")
  if (policy.cpu_limit <= 0) warnings.push("CPU limit is not enforced.")
  if (policy.memory_limit_bytes <= 0) warnings.push("Memory limit is not enforced.")
  if (policy.pids_limit <= 0) warnings.push("PID limit is not enforced.")
  if (policy.timeout_seconds <= 0) warnings.push("Execution timeout is not enforced.")
  return warnings
}

function buildRows(policy: SandboxEffectivePolicy) {
  const capabilitiesSafe = policy.cap_drop.map((item) => item.toUpperCase()).includes("ALL")
  const seccompSafe = Boolean(policy.seccomp.trim()) && policy.seccomp.trim().toLowerCase() !== "unconfined"
  const user = policy.user.trim()
  const userSafe = Boolean(user) && !["0", "0:0", "root"].includes(user.toLowerCase())
  const socketState = policy.docker_socket_mounted === null
    ? "unknown"
    : policy.docker_socket_mounted
      ? "unsafe"
      : "safe"
  const network = policy.network.trim().toLowerCase()
  return [
    { label: "Network", value: network === "restricted" ? "restricted · exact-host approval" : policy.network || "—", state: network === "none" || network === "restricted" ? "safe" : network ? "unsafe" : "unknown" },
    { label: "Root filesystem", value: policy.root_filesystem_read_only ? "read-only" : "read / write", state: policy.root_filesystem_read_only ? "safe" : "unsafe" },
    { label: "User", value: policy.user || "—", state: user ? (userSafe ? "safe" : "unsafe") : "unknown" },
    { label: "Capabilities", value: policy.cap_drop.length ? `DROP ${policy.cap_drop.join(", ")}` : "—", state: capabilitiesSafe ? "safe" : "unsafe" },
    { label: "New privileges", value: policy.no_new_privileges ? "disabled" : "allowed", state: policy.no_new_privileges ? "safe" : "unsafe" },
    { label: "Seccomp", value: policy.seccomp || "—", state: policy.seccomp.trim() ? (seccompSafe ? "safe" : "unsafe") : "unknown" },
    { label: "CPU", value: policy.cpu_limit > 0 ? `${policy.cpu_limit} core${policy.cpu_limit === 1 ? "" : "s"}` : "unlimited", state: policy.cpu_limit > 0 ? "safe" : "unsafe" },
    { label: "Memory", value: policy.memory_limit_bytes > 0 ? formatBytes(policy.memory_limit_bytes) : "unlimited", state: policy.memory_limit_bytes > 0 ? "safe" : "unsafe" },
    { label: "PIDs", value: policy.pids_limit > 0 ? String(policy.pids_limit) : "unlimited", state: policy.pids_limit > 0 ? "safe" : "unsafe" },
    { label: "Timeout", value: policy.timeout_seconds > 0 ? `${policy.timeout_seconds} s` : "none", state: policy.timeout_seconds > 0 ? "safe" : "unsafe" },
    { label: "stdout", value: formatBytes(policy.stdout_limit_bytes), state: policy.stdout_limit_bytes > 0 ? "safe" : "unsafe" },
    { label: "stderr", value: formatBytes(policy.stderr_limit_bytes), state: policy.stderr_limit_bytes > 0 ? "safe" : "unsafe" },
    { label: "Output files", value: formatBytes(policy.output_limit_bytes ?? 0), state: (policy.output_limit_bytes ?? 0) > 0 ? "safe" : "unknown" },
    { label: "Docker socket", value: policy.docker_socket_mounted === null ? "unknown" : policy.docker_socket_mounted ? "mounted" : "not mounted", state: socketState },
  ] as Array<{ label: string; value: string; state: "safe" | "unsafe" | "unknown" }>
}

function PermissionRow({ activity }: { activity: SandboxActivityEvent }) {
  const action = activity.permission_action || activity.action.replace(/^permission\./, "")
  return (
    <tr className="border-b border-slate-100 text-[10px] text-slate-600 last:border-b-0">
      <td className="px-5 py-3 font-mono text-slate-700">{action}</td>
      <td className="max-w-[220px] truncate px-3 py-3 font-mono" title={safeDisplayTarget(activity.target)}>{safeDisplayTarget(activity.target) || "—"}</td>
      <td className="px-3 py-3"><DecisionBadge decision={activity.decision} /></td>
      <td className="max-w-[260px] px-3 py-3 text-slate-500">{activity.reason || "—"}</td>
      <td className="max-w-[220px] truncate px-5 py-3 font-mono text-slate-500" title={activity.policy_rule}>{activity.policy_rule || "—"}</td>
    </tr>
  )
}

function DecisionBadge({ decision }: { decision: SandboxActivityEvent["decision"] }) {
  const label = decision === "approval_required"
    ? "Approval Required"
    : decision === "observed"
      ? "Requested"
      : decision.charAt(0).toUpperCase() + decision.slice(1).replaceAll("_", " ")
  const className = decision === "allowed" || decision === "approved"
    ? "bg-emerald-50 text-emerald-700"
    : decision === "denied"
      ? "bg-rose-50 text-rose-700"
      : decision === "approval_required" || decision === "pending"
        ? "bg-amber-50 text-amber-800"
        : "bg-slate-100 text-slate-600"
  return <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[9px] font-semibold ${className}`}>{label}</span>
}

function latestApprovalEvents(activities: SandboxActivityEvent[]): SandboxActivityEvent[] {
  const latest = new Map<string, SandboxActivityEvent>()
  for (const activity of activities) {
    if (activity.kind !== "approval" || !activity.approval_id) continue
    latest.set(activity.approval_id, activity)
  }
  return [...latest.values()].sort((left, right) => left.sequence - right.sequence)
}

function safeDisplayTarget(value: string): string {
  const target = value.trim()
  if (!target) return ""
  const containerPath = target === "/input"
    || target.startsWith("/input/")
    || target === "/workspace"
    || target.startsWith("/workspace/")
  if (/^[a-z]:[\\/]/i.test(target) || /^\\\\/.test(target) || /^file:\/\//i.test(target) || (target.startsWith("/") && !containerPath)) {
    return "[host path redacted]"
  }
  return target
}

function formatBytes(value: number): string {
  if (value <= 0) return "none"
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`
}
