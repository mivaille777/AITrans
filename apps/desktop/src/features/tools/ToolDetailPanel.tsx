import { useState } from "react"
import { Box, Shield } from "lucide-react"
import type { ToolDetail } from "../../api/tools"
import { ToolSchemaView } from "./ToolSchemaView"
import { ToolPermissionsView } from "./ToolPermissionsView"
import { ToolExamplesView } from "./ToolExamplesView"
import { CopyButton } from "./CopyButton"

const tabs = ["Overview", "Parameters", "Returns", "Permissions", "Examples"] as const
export function ToolDetailPanel({ tool, onExample, actions }: { tool: ToolDetail; onExample: (value: string) => void; actions?: React.ReactNode }) {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Parameters")
  return <>
    <div className="tools-detail-header"><div className="tools-title"><div className="tools-tool-icon"><Box size={25} /></div><div><h2>{tool.name}<span className={`tools-badge ${tool.enabled ? "is-green" : ""}`}>{tool.enabled ? "Enabled" : "Disabled"}</span></h2><div className="tools-meta"><code>{tool.namespace}.{tool.name}</code><span>{tool.category}</span><span>{tool.origin}</span></div></div>{actions}</div><p>{tool.description}</p>{tool.unavailable_reason && <p className="tools-notice">{tool.unavailable_reason}</p>}<div className="tools-meta"><span>{tool.effect}</span><span>{String(tool.limits.timeout_seconds)}s timeout</span><span>{tool.risk_level.replaceAll("_", " ")}</span></div></div>
    <div className="tools-tabs" role="tablist" aria-label="Tool details">{tabs.map((name) => <button role="tab" aria-selected={tab === name} tabIndex={tab === name ? 0 : -1} key={name} onClick={() => setTab(name)} onKeyDown={(event) => {
      const offset = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0
      if (offset) { event.preventDefault(); const next = tabs[(tabs.indexOf(tab) + offset + tabs.length) % tabs.length]; setTab(next); (event.currentTarget.parentElement?.children[tabs.indexOf(next)] as HTMLButtonElement)?.focus() }
    }}>{name}</button>)}</div>
    <div className="tools-detail-content" role="tabpanel" aria-label={tab}>
      {tab === "Overview" && <><h3>Tool information</h3><dl className="tools-property-list">{Object.entries({ Name: tool.name, Namespace: tool.namespace, Provider: tool.origin, Version: tool.tool_version, Status: tool.archived ? "Archived" : tool.enabled ? "Enabled" : "Disabled", Availability: tool.available ? "Available; required context still applies" : tool.unavailable_reason, Context: tool.context_requirements.join(", ") || "None", Effect: tool.effect }).map(([key, value]) => <div className="tools-property-row" key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><p className="tools-note">{tool.description}</p>{tool.origin === "custom" && <><p className="tools-notice">Agent execution supported. Native Chat does not expose custom presets.</p><h4>Preset configuration</h4><pre className="tools-code">{JSON.stringify(tool.configuration, null, 2)}</pre></>}</>}
      {tab === "Parameters" && <><ToolSchemaView schema={tool.input_schema} title="Input parameters" />{Object.entries(tool.input_profiles).map(([name, schema]) => <details className="tools-native-profile" key={name}><summary>{name.replaceAll("_", " ")} input profile</summary><p className="tools-note">This input belongs to a separate calling entry point. The test panel uses the Agent schema above.</p><pre className="tools-code">{JSON.stringify(schema, null, 2)}</pre></details>)}<div className="tools-permission-note"><Shield size={15} /><span>Required context: {tool.context_requirements.join(", ") || "none"}.</span><button onClick={() => setTab("Permissions")}>View permissions →</button></div>{tool.examples[0] && <><div className="tools-section-heading"><h4>Quick example</h4><CopyButton text={JSON.stringify(tool.examples[0].arguments, null, 2)} /></div><pre className="tools-code">{JSON.stringify(tool.examples[0].arguments, null, 2)}</pre></>}</>}
      {tab === "Returns" && <><p className="tools-note">Structured data returned by the executor. Execution status and output_text are separate envelope fields.</p><ToolSchemaView schema={tool.output_schema} title="Output schema" /></>}
      {tab === "Permissions" && <ToolPermissionsView tool={tool} />}
      {tab === "Examples" && <ToolExamplesView tool={tool} onUse={onExample} />}
      <footer className="tools-detail-footer">{tool.origin} tool · Version {tool.tool_version}{tool.updated_at ? " · Updated " + new Date(tool.updated_at).toLocaleString() : ""}</footer>
    </div>
  </>
}
