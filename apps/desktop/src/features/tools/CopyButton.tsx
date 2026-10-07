import { useState } from "react"
import { Copy } from "lucide-react"

export function CopyButton({ text }: { text: string }) {
  const [status, setStatus] = useState("Copy")
  return <button className="tools-text-button" onClick={() => {
    navigator.clipboard.writeText(text).then(() => setStatus("Copied"), () => setStatus("Copy failed"))
  }}><Copy size={12} />{status}</button>
}
