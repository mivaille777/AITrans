import { useEffect, useRef, useState } from "react"
import type { ExecutionFile, ExecutionResult } from "../../api/execution-results"

type ArtifactUrl = (fileId: string, inline?: boolean) => string

function OutputImage({ file, url }: { file: ExecutionFile; url: string }) {
  const [failed, setFailed] = useState(false)
  return <figure className="my-3 rounded-xl border border-slate-200 bg-white p-3">
    {failed ? <p role="alert" className="text-sm text-slate-500">图片不可用：可能已过期或未通过校验。</p>
      : <img src={url} alt={`运行结果：${file.relative_path}`} loading="lazy" onError={() => setFailed(true)} className="mx-auto max-h-[min(480px,35vh)] max-w-full rounded-lg object-contain" />}
    <figcaption className="mt-2 truncate text-xs text-slate-500">{file.relative_path}</figcaption>
  </figure>
}

export function ExecutionResultCard({ result, artifactUrl }: { result: ExecutionResult; artifactUrl: ArtifactUrl }) {
  const [source, setSource] = useState("")
  const [sourceOpen, setSourceOpen] = useState(false)
  const [sourceError, setSourceError] = useState("")
  const [loadingSource, setLoadingSource] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  useEffect(() => () => controllerRef.current?.abort(), [])
  const succeeded = ["succeeded", "completed"].includes(result.status) && result.exit_code === 0
  const active = ["pending", "queued", "preparing", "running", "cancelling"].includes(result.status)
  const images = result.output_files.filter(file => /\.(png|jpe?g)$/i.test(file.relative_path))
  async function showSource() {
    setSourceOpen(value => !value)
    if (source || !result.source_file_id || loadingSource) return
    const controller = new AbortController()
    controllerRef.current = controller
    setLoadingSource(true)
    setSourceError("")
    try {
      const response = await fetch(artifactUrl(result.source_file_id), { signal: controller.signal })
      if (!response.ok) throw new Error("Source unavailable")
      const text = await response.text()
      if (!controller.signal.aborted) setSource(text.slice(0, 50000))
    } catch {
      if (!controller.signal.aborted) setSourceError("脚本不可用：可能已过期或未通过校验。")
    } finally {
      if (!controller.signal.aborted) setLoadingSource(false)
    }
  }
  return <section aria-label="脚本运行结果" className="my-3 rounded-xl border border-slate-200 bg-slate-50/70 p-4 text-sm text-slate-700">
    <div className="flex flex-wrap items-center gap-3">
      <strong>{active ? "正在运行 Python…" : succeeded ? "✓ 运行完成" : "运行未成功"}</strong>
      <span className="text-xs text-slate-500">{result.status} · {(result.duration_ms / 1000).toFixed(2)} s · 退出码 {result.exit_code ?? "—"}</span>
    </div>
    {images.map(file => <OutputImage key={`${file.file_id}:${artifactUrl(file.file_id, true)}`} file={file} url={artifactUrl(file.file_id, true)} />)}
    <div className="mt-3 flex flex-wrap gap-4 text-xs">
      {result.source_file_id && <button type="button" onClick={() => void showSource()} className="underline">{sourceOpen ? "收起代码" : "查看代码"}</button>}
      {result.output_files.map(file => <a key={file.file_id} href={artifactUrl(file.file_id)} download className="underline">
        {file.file_id === result.source_file_id ? "下载脚本" : /\.(png|jpe?g)$/i.test(file.relative_path) ? "下载图片" : `下载 ${file.relative_path}`}
      </a>)}
    </div>
    {sourceOpen && <div className="mt-3">{loadingSource ? "正在读取脚本…" : sourceError ? <p role="alert">{sourceError}</p> : <pre className="max-h-80 overflow-auto whitespace-pre rounded-lg bg-slate-950 p-3 text-xs text-slate-100"><code>{source}</code></pre>}</div>}
    <details className="mt-3" open={!succeeded && !active}>
      <summary className="cursor-pointer text-xs">运行日志</summary>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <div><p className="mb-1 text-xs">stdout</p><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{result.stdout || "No output"}</pre></div>
        <div><p className="mb-1 text-xs">stderr</p><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{result.stderr || "No output"}</pre></div>
      </div>
      {result.logs_truncated && <p className="mt-2 text-xs">日志较长，已截断展示。</p>}
    </details>
  </section>
}
