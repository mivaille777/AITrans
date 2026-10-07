import { useState } from "react"
import type { JsonSchema } from "../../api/tools"

interface Row { name: string; schema: JsonSchema; required: boolean; depth: number }
function resolve(schema: JsonSchema, root: JsonSchema): JsonSchema {
  const target = schema.$ref?.startsWith("#/$defs/") ? root.$defs?.[schema.$ref.slice(8)] : undefined
  return target ? { ...target, ...schema, $ref: undefined } : schema
}
function rows(schema: JsonSchema, root: JsonSchema, depth = 0, prefix = ""): Row[] {
  const value = resolve(schema, root)
  const result: Row[] = []
  for (const [name, raw] of Object.entries(value.properties ?? {})) {
    const child = resolve(raw, root)
    const path = prefix ? prefix + "." + name : name
    result.push({ name: path, schema: child, required: value.required?.includes(name) ?? false, depth })
    if (depth < 3) {
      if (child.properties) result.push(...rows(child, root, depth + 1, path))
      if (child.items?.$ref || child.items?.properties) result.push(...rows(child.items, root, depth + 1, path + "[]"))
    }
  }
  return result
}
function typeLabel(schema: JsonSchema, root: JsonSchema): string {
  const value = resolve(schema, root)
  if (value.anyOf) return value.anyOf.map((item) => typeLabel(item, root)).join(" | ")
  if (value.type === "array") return typeLabel(value.items ?? {}, root) + "[]"
  if (Array.isArray(value.type)) return value.type.join(" | ")
  return value.type ?? (value.$ref ? value.$ref.split("/").at(-1) ?? "reference" : "schema")
}
function constraints(schema: JsonSchema): string {
  return [schema.description, schema.enum ? "Allowed: " + JSON.stringify(schema.enum) : "",
    ...["minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"].filter((key) => schema[key] !== undefined).map((key) => key + ": " + String(schema[key])),
    schema.anyOf ? "See JSON for alternative schemas and their constraints." : "",
    schema.properties || schema.items ? "Nested structure; see JSON for the complete schema." : "",
  ].filter(Boolean).join(" ")
}
export function ToolSchemaView({ schema, title }: { schema: JsonSchema; title: string }) {
  const [mode, setMode] = useState("visual")
  const fields = rows(schema, schema)
  return <section>
    <div className="tools-section-heading"><div><h3>{title}</h3><p className="tools-note">{Object.keys(schema.properties ?? {}).length} fields · {schema.required?.length ?? 0} required</p></div><div className="tools-segment">{["visual", "json"].map((tab) => <button key={tab} aria-pressed={mode === tab} onClick={() => setMode(tab)}>{tab === "visual" ? "Visual schema" : "JSON"}</button>)}</div></div>
    {mode === "json" ? <pre className="tools-code">{JSON.stringify(schema, null, 2)}</pre> : <div className="tools-table-wrap"><table className="tools-schema-table"><thead><tr><th>Parameter</th><th>Type</th><th>Required</th><th>Default</th><th>Description</th></tr></thead><tbody>
      {fields.map((row) => <tr key={row.name}><td style={{ paddingLeft: 12 + row.depth * 14 }}><code>{row.name}</code></td><td><code>{typeLabel(row.schema, schema)}</code></td><td><span className={`tools-required ${row.required ? "is-required" : ""}`}>{row.required ? "Required" : "Optional"}</span></td><td><code>{row.schema.default === undefined ? "—" : JSON.stringify(row.schema.default)}</code></td><td>{constraints(row.schema) || "—"}</td></tr>)}
      {fields.length === 0 && <tr><td colSpan={5}>{schema.type === "object" ? "No business parameters." : "View JSON for this schema."}</td></tr>}
    </tbody></table></div>}
    <p className="tools-note tools-schema-note">JSON preserves all references, alternatives and validation rules.</p>
  </section>
}
