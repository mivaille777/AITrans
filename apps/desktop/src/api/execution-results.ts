import { API_BASE_URL } from "./client"

export interface ExecutionFile {
  file_id: string
  relative_path: string
  size_bytes: number
  sha256: string
}

export interface ExecutionResult {
  sandbox_id: string
  tool_call_id?: string
  status: string
  exit_code: number | null
  duration_ms: number
  stdout: string
  stderr: string
  logs_truncated?: boolean
  source_file_id?: string
  output_files: ExecutionFile[]
}

export function conversationArtifactUrl(conversationId: string, messageId: string, sandboxId: string, fileId: string, inline = false): string {
  const parts = [conversationId, messageId, sandboxId, fileId].map(encodeURIComponent)
  return `${API_BASE_URL}/api/conversations/${parts[0]}/messages/${parts[1]}/executions/${parts[2]}/files/${parts[3]}${inline ? "?inline=true" : ""}`
}

export function wantsPlotExecution(text: string): boolean {
  if (/^(?:请问)?(?:如何|怎么|怎样|是否|有没有)|^\s*(?:how\b|explain\b)/i.test(text)) return false
  if (/(?:不要|不需要|无需|别).{0,6}(?:执行|运行)|(?:仅|只).{0,6}(?:代码|脚本)|\b(?:do not|don't)\s+(?:run|execute)|\bcode\s+only\b/i.test(text)) return false
  return /(?:画|绘制|绘图|生成).{0,24}(?:爱心|心形|曲线|图表|折线图|柱状图|散点图|饼图|函数图|图像)|(?:绘图|画图|画爱心|画心形).{0,12}(?:脚本|代码|程序)|\b(?:draw|plot|render|generate)\b.{0,40}\b(?:heart|chart|graph|plot)\b/i.test(text)
}
