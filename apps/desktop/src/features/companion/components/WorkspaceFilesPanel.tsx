import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileText, Folder, RefreshCw } from "lucide-react"
import {
  applyChatWorkspaceUndo, browseChatWorkspace, getChatWorkspaceChanges, getChatWorkspaceLocation,
  previewChatWorkspaceText, previewChatWorkspaceUndo,
  type WorkspaceUndoPreview,
} from "../../../api/chat-sessions"
import { desktop } from "../../../desktop"

export function WorkspaceFilesPanel({sessionId, workspaceId, readOnly, busy, refreshKey}: {
  sessionId: string; workspaceId: string; readOnly: boolean; busy: boolean; refreshKey: string
}) {
  const client = useQueryClient()
  const [directory, setDirectory] = useState("")
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState("")
  const [line, setLine] = useState(1)
  const [undo, setUndo] = useState<WorkspaceUndoPreview | null>(null)
  const [error, setError] = useState("")
  const prefix = ["chat-workspace-files", sessionId, workspaceId]
  const enabled = Boolean(sessionId && workspaceId)
  const listing = useQuery({queryKey: [...prefix, "list", directory, offset],
    queryFn: () => browseChatWorkspace(sessionId, directory, offset), enabled, retry: 0})
  const changes = useQuery({queryKey: [...prefix, "changes"],
    queryFn: () => getChatWorkspaceChanges(sessionId), enabled, retry: 0})
  const preview = useQuery({queryKey: [...prefix, "preview", selected, line],
    queryFn: () => previewChatWorkspaceText(sessionId, selected, line), enabled: enabled && Boolean(selected), retry: 0})
  const mutation = useMutation({mutationFn: async (action: {kind: "preview"; id: string} | {kind: "apply"; token: string}) => {
    if (action.kind === "preview") {
      setUndo(await previewChatWorkspaceUndo(sessionId, action.id))
    } else {
      await applyChatWorkspaceUndo(sessionId, action.token)
      setUndo(null)
      setSelected("")
      await client.invalidateQueries({queryKey: prefix})
    }
  }})
  useEffect(() => {
    setDirectory(""); setOffset(0); setSelected(""); setUndo(null); setError("")
  }, [sessionId, workspaceId])
  useEffect(() => {
    void client.invalidateQueries({queryKey: ["chat-workspace-files", sessionId, workspaceId]})
  }, [refreshKey, client, sessionId, workspaceId])
  const show = (path: string) => {setSelected(path); setLine(1); setError("")}
  const enter = (path: string) => {setDirectory(path); setOffset(0); setSelected("")}
  async function open(path: string, reveal: boolean) {
    try {
      setError("")
      const location = await getChatWorkspaceLocation(sessionId, path)
      if (reveal || location.kind === "directory") {
        if (!desktop.files.revealWorkspaceLocation) throw new Error("请重启桌面程序以使用文件定位。")
        await desktop.files.revealWorkspaceLocation(location.resource_url)
      } else {
        await desktop.files.openEvidenceSource(location.resource_url)
      }
    } catch (cause) {setError(cause instanceof Error ? cause.message : "打开文件失败。")}
  }
  return <section className="ait-chat-reading-context-section" aria-label="工作区文件">
    <div className="ait-chat-inspector-section-heading">
      <div className="ait-chat-inspector-section-title"><Folder size={18}/><div><h3>工作区文件</h3>
        <p>{workspaceId ? (readOnly ? "仅允许读取" : "允许读取和写入") : "请在输入框上方选择工作区"}</p></div></div>
      {enabled && <button type="button" className="ait-chat-message-action" aria-label="刷新工作区文件" onClick={() => void client.invalidateQueries({queryKey: prefix})}><RefreshCw size={15}/></button>}
    </div>
    {listing.data && <>
      <p className="my-2 break-all text-xs text-slate-500">{listing.data.display_path}</p>
      <div className="my-2 flex items-center gap-3 text-xs">
        <button type="button" className="ait-chat-message-action" onClick={() => enter("")}>根目录</button>
        {directory && <button type="button" className="ait-chat-message-action" onClick={() => enter(directory.split("/").slice(0, -1).join("/"))}>上一级</button>}
        <span className="break-all">{directory || "/"}</span>
      </div>
      <div className="max-h-64 overflow-y-auto">
        {listing.data.entries.map(entry => <button type="button" key={entry.relative_path} className="ait-chat-context-picker-option w-full" onClick={() => entry.kind === "directory" ? enter(entry.relative_path) : show(entry.relative_path)}>
          {entry.kind === "directory" ? <Folder size={15}/> : <FileText size={15}/>}
          <span className="min-w-0"><strong className="break-all">{entry.name}</strong><small>{entry.kind === "directory" ? "文件夹" : `${entry.size_bytes} 字节`}</small></span>
        </button>)}
        {!listing.data.entries.length && <p className="ait-chat-inspector-empty">此目录没有可访问的文件。</p>}
      </div>
      <div className="flex gap-3 text-xs">
        {offset > 0 && <button type="button" onClick={() => setOffset(Math.max(0, offset - 100))}>上一页</button>}
        {listing.data.has_more && <button type="button" onClick={() => setOffset(listing.data.next_offset)}>下一页</button>}
      </div>
    </>}
    {listing.isError && <p role="alert" className="ait-chat-model-menu-message is-error">{listing.error.message}</p>}
    {selected && <div className="ait-chat-context-empty my-3">
      <strong className="break-all">{selected}</strong>
      {preview.data && <>
        <p className="text-xs">{preview.data.size_bytes} 字节 · {preview.data.encoding}</p>
        <pre className="my-2 max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{preview.data.text}</pre>
        <div className="flex flex-wrap gap-3 text-xs">
          {line > 1 && <button type="button" onClick={() => setLine(Math.max(1, line - 200))}>上一段</button>}
          {preview.data.has_more && <button type="button" onClick={() => setLine(preview.data.next_line)}>继续读取</button>}
          {desktop.runtime === "electron" && /\.(?:md|txt|json|csv|pdf|docx)$/i.test(selected) && <button type="button" onClick={() => void open(selected, false)}>打开文件</button>}
          {desktop.runtime === "electron" && <button type="button" onClick={() => void open(selected, true)}>打开所在文件夹</button>}
        </div>
      </>}
      {preview.isError && <p role="alert">{preview.error.message}</p>}
    </div>}
    {!!changes.data?.length && <div className="mt-4">
      <p className="ait-chat-card-eyebrow">本会话的文件变更</p>
      {changes.data.slice(0, 8).map(change => <div key={change.change_id} className="ait-chat-context-empty my-2">
        <strong className="break-all">{change.relative_path}</strong>
        <p className="text-xs">{({create: "已创建", edit: "已编辑", write: "已重写", mkdir: "已创建文件夹", undo: "已撤销变更"} as Record<string, string>)[change.operation] || change.operation} · {change.kind === "file" ? `${change.size_bytes} 字节` : "文件夹"}{change.undone_by ? " · 已撤销" : ""}</p>
        <div className="mt-2 flex flex-wrap gap-3 text-xs">
          {change.exists && !change.undone_by && change.kind === "file" && <button type="button" onClick={() => show(change.relative_path)}>查看内容</button>}
          {change.exists && !change.undone_by && desktop.runtime === "electron" && <button type="button" onClick={() => void open(change.relative_path, true)}>打开所在文件夹</button>}
          {change.exists && !change.undone_by && desktop.runtime === "electron" && /\.(?:md|txt|json|csv)$/i.test(change.relative_path) && <button type="button" onClick={() => void open(change.relative_path, false)}>打开文件</button>}
          {!change.undone_by && change.operation !== "undo" && <button type="button" disabled={readOnly || busy || mutation.isPending} onClick={() => mutation.mutate({kind: "preview", id: change.change_id})}>查看撤销差异</button>}
        </div>
      </div>)}
    </div>}
    {undo && <div className="ait-chat-run-confirmation my-3" role="region" aria-label="撤销变更确认">
      <div><strong>撤销：{undo.relative_path}</strong><p>{undo.size_before} → {undo.size_after} 字节</p>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs">{undo.diff || "恢复此前的文件或文件夹状态。"}</pre>
        {undo.diff_truncated && <p>差异过长，仅显示部分内容。</p>}
        <button type="button" disabled={readOnly || busy || mutation.isPending} onClick={() => mutation.mutate({kind: "apply", token: undo.approval_token})}>确认撤销</button>
        <button type="button" disabled={mutation.isPending} onClick={() => {setUndo(null); mutation.reset()}}>取消</button>
      </div>
    </div>}
    {(error || mutation.error) && <p role="alert" className="ait-chat-model-menu-message is-error">{error || mutation.error?.message}</p>}
  </section>
}
