import type { ToolDetail } from "../../api/tools"
import { CopyButton } from "./CopyButton"

export function ToolExamplesView({ tool, onUse }: { tool: ToolDetail; onUse: (value: string) => void }) {
  return <section><h3>Usage examples</h3><p className="tools-note">Provide the required context before executing an example.</p>
    {!tool.examples.length && <p className="tools-notice">This tool requires context-specific arguments. Use its parameter schema to prepare a call.</p>}
    {tool.examples.map((example) => <article key={example.id}><div className="tools-section-heading"><strong>{example.title}</strong><div className="tools-actions"><CopyButton text={JSON.stringify(example.arguments, null, 2)} /><button className="tools-text-button" onClick={() => onUse(JSON.stringify(example.arguments, null, 2))}>Use in test →</button></div></div><p className="tools-note">{example.description}</p><pre className="tools-code">{JSON.stringify(example.arguments, null, 2)}</pre></article>)}
  </section>
}
