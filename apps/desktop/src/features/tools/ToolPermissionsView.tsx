import { Shield } from "lucide-react"
import type { ToolDetail } from "../../api/tools"

export function ToolPermissionsView({ tool }: { tool: ToolDetail }) {
  return <section><h3>Permissions & security</h3><p className="tools-note">Authority comes from the executor and runtime policy.</p><dl className="tools-property-list">
    <dt>Effect</dt><dd>{tool.effect}</dd><dt>Risk level</dt><dd>{tool.risk_level.replaceAll("_", " ")}</dd>
    {Object.entries(tool.permissions).map(([key, value]) => <div className="tools-property-row" key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}</dd></div>)}
  </dl><div className="tools-permission-note"><Shield size={15} />Test calls use the same scope and confirmation rules as Agent calls.</div></section>
}
