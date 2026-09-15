import { AlertCircle, CheckCircle2, Cpu, Download, HardDrive, LoaderCircle, RefreshCw, ShieldCheck, Trash2 } from "lucide-react"
import { useState } from "react"

import type { RagModelId, RagModelStatus } from "../../api/rag-models"
import { Badge, type BadgeTone } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import { useLocalModels } from "./useLocalModels"

export function LocalModelManager() {
  const models = useLocalModels()
  const [confirmRemove, setConfirmRemove] = useState<RagModelId | null>(null)
  const error = models.modelsQuery.error ?? models.downloadMutation.error ?? models.verifyMutation.error ?? models.removeMutation.error

  return (
    <section className="ait-surface overflow-hidden">
      <header className="border-b border-slate-100 p-6 lg:p-7">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Local AI</p>
        <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">Local AI models</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">Manage the embedding and reranker models used by the on-device Knowledge index. Downloads are verified before they become active.</p>
      </header>

      {error && <div role="alert" className="m-5 flex items-start gap-2 rounded-[14px] border border-rose-100 bg-rose-50 px-4 py-3 text-xs text-rose-700 lg:mx-7"><AlertCircle size={15} className="mt-0.5 shrink-0" />{error instanceof Error ? error.message : "Local model operation failed."}</div>}

      {models.modelsQuery.isPending ? (
        <div className="p-7" aria-busy="true"><div className="ait-skeleton h-24 rounded-[17px]" /><div className="ait-skeleton mt-3 h-24 rounded-[17px]" /></div>
      ) : models.modelsQuery.isError ? (
        <div className="p-7"><p className="text-sm text-slate-600">Local model status is unavailable.</p><Button className="mt-3" size="xs" onClick={() => void models.modelsQuery.refetch()}><RefreshCw size={13} />Retry</Button></div>
      ) : (
        <div className="divide-y divide-slate-100">
          {models.modelsQuery.data?.models.map((model) => (
            <ModelRow
              key={model.model_id}
              model={model}
              downloading={models.downloadMutation.isPending && models.downloadMutation.variables === model.model_id}
              verifying={models.verifyMutation.isPending && models.verifyMutation.variables === model.model_id}
              removing={models.removeMutation.isPending && models.removeMutation.variables === model.model_id}
              confirmRemove={confirmRemove === model.model_id}
              onDownload={() => models.downloadMutation.mutate(model.model_id)}
              onVerify={() => models.verifyMutation.mutate(model.model_id)}
              onRemove={() => {
                if (confirmRemove === model.model_id) {
                  models.removeMutation.mutate(model.model_id, { onSettled: () => setConfirmRemove(null) })
                } else {
                  setConfirmRemove(model.model_id)
                }
              }}
            />
          ))}
          <details className="px-6 py-4 lg:px-7"><summary className="cursor-pointer text-xs font-medium text-slate-500">Advanced storage detail</summary><p className="mt-2 break-all font-mono text-[10px] text-slate-400">{models.modelsQuery.data?.models_root}</p></details>
        </div>
      )}
    </section>
  )
}

function ModelRow({ model, downloading, verifying, removing, confirmRemove, onDownload, onVerify, onRemove }: { model: RagModelStatus; downloading: boolean; verifying: boolean; removing: boolean; confirmRemove: boolean; onDownload: () => void; onVerify: () => void; onRemove: () => void }) {
  const busy = downloading || verifying || removing || model.state === "downloading"
  const managedInvalid = model.state === "invalid" && model.source === "managed"
  return (
    <article className="px-6 py-5 lg:px-7">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 gap-3.5"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[13px] border border-slate-200 bg-slate-50 text-slate-500">{model.model_id.includes("embedding") ? <Cpu size={18} /> : <ShieldCheck size={18} />}</span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-slate-900">{model.display_name}</h3><Badge tone={modelTone(model)}>{modelLabel(model, busy)}</Badge></div><p className="mt-1 text-xs text-slate-500">{model.model_id.includes("embedding") ? "Embedding" : "Reranker"} · {model.repository_id}</p>{model.installed && <p className="mt-1 flex items-center gap-1 text-[10px] text-slate-400"><HardDrive size={11} />{formatBytes(model.disk_usage_bytes)} · {model.source === "huggingface_cache" ? "Hugging Face cache" : "AITrans storage"}</p>}</div></div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {!model.installed ? <Button variant="primary" size="xs" disabled={busy || managedInvalid} onClick={onDownload}>{busy ? <LoaderCircle size={13} className="animate-spin" /> : <Download size={13} />}{busy ? "Downloading…" : "Download"}</Button> : <Button size="xs" disabled={busy} onClick={onVerify}>{verifying ? <LoaderCircle size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}{verifying ? "Verifying…" : "Verify"}</Button>}
          {model.removable && <Button variant={confirmRemove ? "danger" : "ghost"} size="xs" disabled={busy} onClick={onRemove}><Trash2 size={13} />{removing ? "Removing…" : confirmRemove ? "Confirm remove" : "Remove"}</Button>}
        </div>
      </div>
      {busy && <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100" aria-label={`Downloading ${model.display_name}`}><span className="block h-full w-1/2 animate-pulse rounded-full bg-cyan-500" /></div>}
      {model.state === "invalid" && <p className="mt-3 rounded-[12px] bg-amber-50 px-3 py-2 text-xs text-amber-700">{model.source === "huggingface_cache" ? "The Hugging Face cache is incomplete. Download a verified AITrans copy to continue." : "The managed files failed verification. Remove the invalid directory before downloading again."} {model.error}</p>}
      {model.installed && !model.runtime_ready && model.runtime_error && <p className="mt-3 rounded-[12px] bg-amber-50 px-3 py-2 text-xs text-amber-700">Files are present, but the backend runtime probe failed: {model.runtime_error}</p>}
    </article>
  )
}

function modelTone(model: RagModelStatus): BadgeTone {
  if (model.state === "installed" && model.verified && model.runtime_ready) return "success"
  if (model.state === "downloading") return "info"
  if (model.state === "invalid") return "danger"
  return "neutral"
}

function modelLabel(model: RagModelStatus, busy: boolean): string {
  if (busy) return "Downloading"
  if (model.state === "installed" && model.verified && model.runtime_ready) return "Runtime ready"
  if (model.state === "installed" && model.verified) return "Files ready"
  if (model.state === "invalid") return "Invalid"
  return "Not installed"
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 MB"
  const gib = bytes / 1024 ** 3
  return gib >= 1 ? `${gib.toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`
}
