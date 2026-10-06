import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./client"

export interface SkillRecord {
  id: string
  name: string
  description: string
  enabled: boolean
  valid: boolean
  diagnostics: string[]
  metadata: Record<string, unknown>
  file_count: number
  updated_at: string
}

export interface SkillFile {
  path: string
  size: number
}
export interface SkillDetail extends SkillRecord {
  files: SkillFile[]
}
export interface SkillLibrary {
  skills: SkillRecord[]
  storage_root: string
}
export interface SkillFileContent extends SkillFile {
  content: string | null
  revision: string
  language: string
  previewable: boolean
}

export interface SkillCatalog {
  domains: { id: string; description: string; count: number }[]
  eligible_count: number
  revision: string
  disclosure_level: "domains"
}
export interface SkillRoutePreview {
  catalog: SkillCatalog
  selected_domains: string[]
  candidates: {
    id: string
    description: string
    category: string
    invocation: "auto" | "manual"
    score: number
    reason: string
    revision: string
    triggers: string[]
    context_modes: string[]
  }[]
  explicit_ids: string[]
  diagnostics: string[]
  disclosure_level: "metadata"
  body_loaded: boolean
}
export const previewSkillRoute = (request: {
  query: string
  context_mode: "general" | "reading"
  category?: string
}) => apiPost<SkillRoutePreview, typeof request>("/api/skills/route", request)

const skillUrl = (id: string) => `/api/skills/${encodeURIComponent(id)}`
const fileUrl = (id: string, path: string) =>
  `${skillUrl(id)}/file?${new URLSearchParams({ path })}`

export const listSkills = () => apiGet<SkillLibrary>("/api/skills")
export const getSkill = (id: string) => apiGet<SkillDetail>(skillUrl(id))
export const createSkill = (name: string, description: string) =>
  apiPost<SkillDetail, { name: string; description: string }>("/api/skills", {
    name,
    description,
  })
export const importSkill = (source: { path: string } | { content: string }) =>
  apiPost<SkillDetail, typeof source>("/api/skills/import", source)
export const setSkillEnabled = (id: string, enabled: boolean) =>
  apiPatch<SkillDetail, { enabled: boolean }>(skillUrl(id), { enabled })
export const removeSkill = (id: string) =>
  apiDelete<{ removed: boolean; archived_path: string }>(skillUrl(id))
export const readSkillFile = (id: string, path: string) =>
  apiGet<SkillFileContent>(fileUrl(id, path))
export const writeSkillFile = (
  id: string,
  path: string,
  content: string,
  revision: string | null,
) =>
  apiPut<
    SkillFileContent,
    { path: string; content: string; revision: string | null }
  >(`${skillUrl(id)}/file`, { path, content, revision })
export const deleteSkillFile = (id: string, path: string, revision: string) =>
  apiDelete<{ removed: boolean }>(
    `${fileUrl(id, path)}&${new URLSearchParams({ revision })}`,
  )
