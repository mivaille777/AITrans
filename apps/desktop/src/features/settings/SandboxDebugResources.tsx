import type { ReactNode } from "react"

import type { SandboxDebugTrace, SandboxResourceSample } from "../../api/sandbox-debug"

export default function SandboxDebugResources({ trace }: { trace: SandboxDebugTrace | null }) {
  const samples = trace?.resources ?? []
  const policy = trace?.policy

  const peaks = {
    cpu: max(samples, (sample) => sample.cpu_percent),
    memory: max(samples, (sample) => sample.memory_bytes),
    pids: max(samples, (sample) => sample.pids),
    stdout: max(samples, (sample) => sample.stdout_bytes),
    stderr: max(samples, (sample) => sample.stderr_bytes),
    output: max(samples, (sample) => sample.output_bytes),
  }

  if (!trace) {
    return <ResourcesEmpty />
  }

  const memoryLimit = policy?.memory_limit_bytes ?? 0
  const pidsLimit = policy?.pids_limit ?? 0
  const timeoutMs = (policy?.timeout_seconds ?? 0) * 1000
  const stdoutLimit = policy?.stdout_limit_bytes ?? 0
  const stderrLimit = policy?.stderr_limit_bytes ?? 0
  const outputLimit = Math.max(stdoutLimit + stderrLimit, peaks.output)

  return (
    <div className="h-full overflow-auto bg-slate-50/40 px-8 py-6">
      <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="CPU Peak" value={formatPercent(peaks.cpu)} ratio={Math.min(peaks.cpu / 100, 1)} />
          <MetricCard label="Memory Peak" value={formatPair(peaks.memory, memoryLimit, formatBytes)} ratio={ratio(peaks.memory, memoryLimit)} />
          <MetricCard label="PID Peak" value={formatPair(peaks.pids, pidsLimit, (value) => String(Math.round(value)))} ratio={ratio(peaks.pids, pidsLimit)} />
          <MetricCard label="Runtime" value={formatPair(trace.run.duration_ms, timeoutMs, formatDuration)} ratio={ratio(trace.run.duration_ms, timeoutMs)} />
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <MetricCard label="stdout" value={formatPair(peaks.stdout, stdoutLimit, formatBytes)} ratio={ratio(peaks.stdout, stdoutLimit)} />
          <MetricCard label="stderr" value={formatPair(peaks.stderr, stderrLimit, formatBytes)} ratio={ratio(peaks.stderr, stderrLimit)} />
          <MetricCard label="outputs" value={formatPair(peaks.output, outputLimit, formatBytes)} ratio={ratio(peaks.output, outputLimit)} />
        </div>

        {trace.run.status === "oom_killed" ? (
          <div className="rounded-[10px] border border-rose-200 bg-rose-50 px-4 py-3 text-[11px] text-rose-700">
            Sandbox was terminated for memory use.
          </div>
        ) : null}

        {samples.length === 0 ? (
          <ResourcesEmpty compact />
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Memory usage over time">
              <MiniChart samples={samples} value={(sample) => sample.memory_bytes} limit={memoryLimit} />
            </ChartCard>
            <ChartCard title="CPU usage over time">
              <MiniChart samples={samples} value={(sample) => sample.cpu_percent} limit={100} />
            </ChartCard>
          </div>
        )}
      </div>
    </div>
  )
}

function MetricCard({
  label,
  value,
  ratio: usageRatio,
}: {
  label: string
  value: string
  ratio: number
}) {
  const tone = usageRatio >= 1
    ? "border-rose-200 bg-rose-50/60"
    : usageRatio >= 0.8
      ? "border-amber-200 bg-amber-50/60"
      : "border-slate-200 bg-white"

  return (
    <div className={`rounded-[10px] border px-4 py-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.03)] ${tone}`}>
      <p className="text-[10px] font-medium uppercase tracking-[0.11em] text-slate-400">{label}</p>
      <p className="mt-1 text-[12px] font-semibold text-slate-800">{value}</p>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full ${usageRatio >= 1 ? "bg-rose-400" : usageRatio >= 0.8 ? "bg-amber-400" : "bg-slate-500"}`}
          style={{ width: `${Math.max(0, Math.min(100, usageRatio * 100))}%` }}
        />
      </div>
    </div>
  )
}

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-[10px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
      <h2 className="text-[12px] font-semibold text-slate-800">{title}</h2>
      <div className="mt-4 h-40">{children}</div>
    </section>
  )
}

function MiniChart({
  samples,
  value,
  limit,
}: {
  samples: SandboxResourceSample[]
  value: (sample: SandboxResourceSample) => number
  limit: number
}) {
  const reduced = downsample(samples, 800)
  const values = reduced.map(value)
  const maxValue = Math.max(limit, ...values, 1)
  const points = reduced.map((sample, index) => {
    const x = reduced.length <= 1 ? 0 : (index / (reduced.length - 1)) * 100
    const y = 34 - (value(sample) / maxValue) * 30
    return `${x.toFixed(2)},${Math.max(2, Math.min(34, y)).toFixed(2)}`
  }).join(" ")

  return (
    <svg viewBox="0 0 100 36" preserveAspectRatio="none" className="h-full w-full overflow-visible text-slate-700" role="img" aria-label="Resource usage chart">
      <line x1="0" x2="100" y1="34" y2="34" stroke="currentColor" strokeOpacity="0.12" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
      <line x1="0" x2="100" y1="4" y2="4" stroke="currentColor" strokeOpacity="0.08" strokeWidth="0.5" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
      <polyline fill="none" stroke="currentColor" strokeWidth="1.3" vectorEffect="non-scaling-stroke" points={points} />
    </svg>
  )
}

function ResourcesEmpty({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`rounded-[10px] border border-slate-200 bg-white text-center shadow-[0_1px_2px_rgba(15,23,42,0.03)] ${compact ? "px-6 py-8" : "mx-auto mt-10 max-w-3xl px-8 py-10"}`}>
      <h2 className="text-[15px] font-semibold text-slate-900">No resource samples recorded</h2>
      <p className="mx-auto mt-2 max-w-xl text-[12px] leading-5 text-slate-500">
        CPU, memory, PID and output usage will appear here for the selected Sandbox run.
      </p>
    </div>
  )
}

function max(samples: SandboxResourceSample[], value: (sample: SandboxResourceSample) => number): number {
  return samples.reduce((current, sample) => Math.max(current, value(sample)), 0)
}

function ratio(value: number, limit: number): number {
  if (limit <= 0) return 0
  return value / limit
}

function formatPair(value: number, limit: number, formatter: (value: number) => string): string {
  if (limit <= 0) return formatter(value)
  return `${formatter(value)} / ${formatter(limit)}`
}

function formatPercent(value: number): string {
  return `${value.toFixed(value >= 10 ? 0 : 1)} %`
}

function formatBytes(value: number): string {
  if (value < 1024) return `${Math.round(value)} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function formatDuration(value: number): string {
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(1)} s`
}

function downsample<T>(items: T[], limit: number): T[] {
  if (items.length <= limit) return items
  const step = items.length / limit
  return Array.from({ length: limit }, (_, index) => items[Math.min(items.length - 1, Math.floor(index * step))])
}
