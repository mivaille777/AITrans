export interface MarkdownDocument {
  filename: string
  markdown: string
  mime_type: string
}

export function downloadMarkdown(document: MarkdownDocument): void {
  const blob = new Blob([document.markdown], { type: document.mime_type })
  const url = URL.createObjectURL(blob)
  const anchor = window.document.createElement("a")
  anchor.href = url
  anchor.download = document.filename
  window.document.body.appendChild(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
