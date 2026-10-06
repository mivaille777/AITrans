// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import * as api from "../../api/skills"
import type { SkillDetail, SkillFileContent } from "../../api/skills"
import SkillWorkspace from "./SkillWorkspace"

vi.mock("../../api/skills")

const record: SkillDetail = {
  id: "paper-review",
  name: "paper-review",
  description: "审阅学术论文",
  enabled: false,
  valid: true,
  diagnostics: [],
  metadata: { name: "paper-review", description: "审阅学术论文" },
  file_count: 2,
  updated_at: "2026-10-06T00:00:00Z",
  files: [
    { path: "SKILL.md", size: 120 },
    { path: "references/guide.md", size: 25 },
  ],
}
const source =
  "---\nname: paper-review\ndescription: 审阅学术论文\n---\n\n# 阅读流程\n\n先提取论点。\n\n[查看指南](references/guide.md)"
const manifest: SkillFileContent = {
  path: "SKILL.md",
  size: 120,
  content: source,
  revision: "a".repeat(64),
  previewable: true,
  language: "markdown",
}

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  render(
    <QueryClientProvider client={client}>
      <SkillWorkspace />
    </QueryClientProvider>,
  )
  return client
}

beforeEach(() => {
  vi.mocked(api.listSkills).mockResolvedValue({
    skills: [record],
    storage_root: "D:/AITrans/data/skills",
  })
  vi.mocked(api.getSkill).mockResolvedValue(record)
  vi.mocked(api.readSkillFile).mockImplementation(async (_id, path) =>
    path === "SKILL.md"
      ? manifest
      : {
          ...manifest,
          path,
          content: "# 指南\n\n证据优先。",
          revision: "b".repeat(64),
        },
  )
  vi.mocked(api.setSkillEnabled).mockResolvedValue({ ...record, enabled: true })
  vi.mocked(api.removeSkill).mockResolvedValue({
    removed: true,
    archived_path: "D:/AITrans/data/skills/.trash/paper-review",
  })
  vi.mocked(api.writeSkillFile).mockImplementation(
    async (_id, path, content) => ({
      ...manifest,
      path,
      content,
      revision: "c".repeat(64),
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe("Skill workspace", () => {
  it("inspects metadata routes without loading files or losing editor drafts", async () => {
    vi.mocked(api.previewSkillRoute).mockResolvedValue({
      catalog: {
        domains: [{ id: "research", description: "研究", count: 1 }],
        eligible_count: 1,
        revision: "a",
        disclosure_level: "domains",
      },
      candidates: [
        {
          id: "paper-review",
          description: "审阅学术论文",
          category: "research",
          invocation: "auto",
          score: 4,
          reason: "元数据匹配：论文",
          revision: "a",
          triggers: [],
          context_modes: ["general", "reading"],
        },
      ],
      explicit_ids: [],
      selected_domains: ["research"],
      diagnostics: [],
      disclosure_level: "metadata",
      body_loaded: false,
    })
    renderWorkspace()
    await screen.findByRole("heading", { name: "阅读流程" })
    await userEvent.click(screen.getByRole("tab", { name: "源码 / 编辑" }))
    const editor = screen.getByRole("textbox", { name: "编辑文件内容" })
    await userEvent.clear(editor)
    await userEvent.type(editor, "未保存草稿")
    const reads = vi.mocked(api.readSkillFile).mock.calls.length
    await userEvent.click(screen.getByRole("button", { name: "路由检查" }))
    await userEvent.type(
      screen.getByRole("textbox", { name: "路由任务描述" }),
      "审阅论文",
    )
    await userEvent.click(screen.getByRole("button", { name: "检查路由" }))
    await screen.findByText("元数据匹配：论文 · 自动候选")
    expect(api.previewSkillRoute).toHaveBeenCalledWith(
      { query: "审阅论文", context_mode: "general" },
      expect.anything(),
    )
    expect(api.readSkillFile).toHaveBeenCalledTimes(reads)
    await userEvent.keyboard("{Escape}")
    expect((editor as HTMLTextAreaElement).value).toBe("未保存草稿")
  })

  it("previews Markdown body and navigates local file links", async () => {
    renderWorkspace()
    expect(
      await screen.findByRole("heading", { name: "阅读流程" }),
    ).not.toBeNull()
    expect(screen.queryByText("name: paper-review")).toBeNull()
    await userEvent.click(screen.getByRole("button", { name: "查看指南" }))
    expect(await screen.findByRole("heading", { name: "指南" })).not.toBeNull()
    expect(api.readSkillFile).toHaveBeenCalledWith(
      "paper-review",
      "references/guide.md",
    )
  })

  it("saves the draft with the revision originally read", async () => {
    renderWorkspace()
    await screen.findByRole("heading", { name: "阅读流程" })
    await userEvent.click(screen.getByRole("tab", { name: "源码 / 编辑" }))
    const editor = screen.getByRole("textbox", { name: "编辑文件内容" })
    await userEvent.clear(editor)
    await userEvent.type(editor, "# 新流程")
    await userEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(api.writeSkillFile).toHaveBeenCalledWith(
        "paper-review",
        "SKILL.md",
        "# 新流程",
        manifest.revision,
      ),
    )
    expect(await screen.findByText("文件已保存。")).not.toBeNull()
  })

  it("keeps the draft when a conflicting save is rejected", async () => {
    vi.mocked(api.writeSkillFile).mockRejectedValue(
      new Error("文件已更改，请重新加载后再保存。"),
    )
    renderWorkspace()
    await screen.findByRole("heading", { name: "阅读流程" })
    await userEvent.click(screen.getByRole("tab", { name: "源码 / 编辑" }))
    const editor = screen.getByRole("textbox", {
      name: "编辑文件内容",
    }) as HTMLTextAreaElement
    await userEvent.clear(editor)
    await userEvent.type(editor, "draft kept")
    await userEvent.click(screen.getByRole("button", { name: "保存" }))
    expect(
      await screen.findByText("文件已更改，请重新加载后再保存。"),
    ).not.toBeNull()
    expect(editor.value).toBe("draft kept")
  })

  it("requires a discard decision before switching files and resets a discarded editor", async () => {
    renderWorkspace()
    await screen.findByRole("heading", { name: "阅读流程" })
    await userEvent.click(screen.getByRole("tab", { name: "源码 / 编辑" }))
    const editor = screen.getByRole("textbox", {
      name: "编辑文件内容",
    }) as HTMLTextAreaElement
    await userEvent.clear(editor)
    await userEvent.type(editor, "unsaved")
    await userEvent.click(
      screen.getByRole("button", { name: "references/guide.md" }),
    )
    const dialog = screen.getByRole("dialog", { name: "放弃未保存的修改？" })
    await userEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    expect(editor.value).toBe("unsaved")
    await userEvent.click(screen.getByRole("button", { name: "新建技能" }))
    await userEvent.click(screen.getByRole("button", { name: "放弃修改" }))
    await userEvent.click(
      within(screen.getByRole("dialog", { name: "新建技能" })).getByRole(
        "button",
        { name: "取消" },
      ),
    )
    await userEvent.click(screen.getByRole("tab", { name: "源码 / 编辑" }))
    expect(
      (
        screen.getByRole("textbox", {
          name: "编辑文件内容",
        }) as HTMLTextAreaElement
      ).value,
    ).toBe(source)
    await userEvent.click(
      screen.getByRole("button", { name: "references/guide.md" }),
    )
    expect(await screen.findByRole("heading", { name: "指南" })).not.toBeNull()
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("keeps current edits when a background file refresh completes", async () => {
    const client = renderWorkspace()
    await screen.findByRole("heading", { name: "阅读流程" })
    await userEvent.click(screen.getByRole("tab", { name: "源码 / 编辑" }))
    const editor = screen.getByRole("textbox", {
      name: "编辑文件内容",
    }) as HTMLTextAreaElement
    await userEvent.clear(editor)
    await userEvent.type(editor, "my draft")
    vi.mocked(api.readSkillFile).mockResolvedValue({
      ...manifest,
      content: "changed externally",
      revision: "d".repeat(64),
    })
    await client.invalidateQueries({ queryKey: ["skills", "file"] })
    expect(await screen.findByText(/磁盘文件已更新/)).not.toBeNull()
    expect(editor.value).toBe("my draft")
  })

  it("keeps the editor mounted when a background refresh fails", async () => {
    const client = renderWorkspace()
    await screen.findByRole("heading", { name: "阅读流程" })
    await userEvent.click(screen.getByRole("tab", { name: "源码 / 编辑" }))
    const editor = screen.getByRole("textbox", {
      name: "编辑文件内容",
    }) as HTMLTextAreaElement
    await userEvent.clear(editor)
    await userEvent.type(editor, "keep this draft")
    vi.mocked(api.readSkillFile).mockRejectedValue(
      new Error("暂时无法读取文件"),
    )
    await client.invalidateQueries({ queryKey: ["skills", "file"] })
    expect(await screen.findByText("暂时无法读取文件")).not.toBeNull()
    expect(editor.value).toBe("keep this draft")
    expect(screen.getByRole("textbox", { name: "编辑文件内容" })).toBe(editor)
  })

  it("does not switch an edited default selection when the library order changes", async () => {
    const client = renderWorkspace()
    await screen.findByRole("heading", { name: "阅读流程" })
    await userEvent.click(screen.getByRole("tab", { name: "源码 / 编辑" }))
    const editor = screen.getByRole("textbox", {
      name: "编辑文件内容",
    }) as HTMLTextAreaElement
    await userEvent.clear(editor)
    await userEvent.type(editor, "unsaved draft")
    vi.mocked(api.listSkills).mockResolvedValue({
      skills: [{ ...record, id: "a-new", name: "a-new" }, record],
      storage_root: "local",
    })
    await client.invalidateQueries({ queryKey: ["skills", "library"] })
    expect(editor.value).toBe("unsaved draft")
    expect(screen.getByRole("textbox", { name: "编辑文件内容" })).toBe(editor)
    expect(api.getSkill).not.toHaveBeenCalledWith("a-new")
  })

  it("disables activation for an invalid skill and surfaces diagnostics", async () => {
    const invalid = {
      ...record,
      valid: false,
      diagnostics: ["description 必须是字符串。"],
    }
    vi.mocked(api.getSkill).mockResolvedValue(invalid)
    renderWorkspace()
    expect(await screen.findByText("description 必须是字符串。")).not.toBeNull()
    expect(
      (screen.getByRole("switch", { name: "启用技能" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it("creates a new skill from its name and purpose", async () => {
    vi.mocked(api.listSkills).mockResolvedValue({
      skills: [],
      storage_root: "local",
    })
    vi.mocked(api.createSkill).mockResolvedValue(record)
    renderWorkspace()
    await userEvent.click(
      await screen.findByRole("button", { name: "创建第一个技能" }),
    )
    await userEvent.type(
      screen.getByLabelText("技能名称", { exact: false }),
      "paper-review",
    )
    await userEvent.type(
      screen.getByLabelText("用途与触发场景"),
      "审阅学术论文",
    )
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "创建" }),
    )
    await waitFor(() =>
      expect(api.createSkill).toHaveBeenCalledWith(
        "paper-review",
        "审阅学术论文",
      ),
    )
  })

  it("imports a selected SKILL.md without reading other local files", async () => {
    vi.mocked(api.importSkill).mockResolvedValue(record)
    renderWorkspace()
    await userEvent.click(screen.getByRole("button", { name: "导入技能" }))
    const file = new File([source], "SKILL.md", { type: "text/markdown" })
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode(source).buffer,
    })
    await userEvent.upload(screen.getByLabelText("选择 SKILL.md 文件"), file)
    await screen.findByText("SKILL.md 已读取")
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "导入" }),
    )
    await waitFor(() =>
      expect(api.importSkill).toHaveBeenCalledWith({ content: source }),
    )
  })

  it("does not submit a previously selected file after the next upload fails", async () => {
    renderWorkspace()
    await userEvent.click(screen.getByRole("button", { name: "导入技能" }))
    const input = screen.getByLabelText("选择 SKILL.md 文件")
    const good = new File([source], "SKILL.md", { type: "text/markdown" })
    Object.defineProperty(good, "arrayBuffer", {
      value: async () => new TextEncoder().encode(source).buffer,
    })
    await userEvent.upload(input, good)
    await screen.findByText("SKILL.md 已读取")
    const bad = new File(["bad"], "oversize.md", { type: "text/markdown" })
    Object.defineProperty(bad, "size", { value: 3 * 1024 ** 2 })
    await userEvent.upload(input, bad)
    expect(await screen.findByText("文件超过 2 MB。")).not.toBeNull()
    expect(
      (
        within(screen.getByRole("dialog")).getByRole("button", {
          name: "导入",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true)
    expect(api.importSkill).not.toHaveBeenCalled()
  })

  it("requires a confirmation before archiving a skill", async () => {
    renderWorkspace()
    await userEvent.click(
      await screen.findByRole("button", { name: "移除技能" }),
    )
    expect(api.removeSkill).not.toHaveBeenCalled()
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "移除技能",
      }),
    )
    await waitFor(() =>
      expect(api.removeSkill).toHaveBeenCalledWith("paper-review"),
    )
  })

  it("filters the library by name and purpose", async () => {
    renderWorkspace()
    await screen.findByRole("heading", { name: "阅读流程" })
    await userEvent.type(
      screen.getByRole("textbox", { name: "搜索技能" }),
      "missing",
    )
    expect(screen.getByText("没有匹配的技能。")).not.toBeNull()
  })
  it("renders BOM/CRLF frontmatter without exposing it as body text", async () => {
    vi.mocked(api.readSkillFile).mockResolvedValue({
      ...manifest,
      content: "\uFEFF---\r\nname: sample\r\n---\r\n# body",
    })
    renderWorkspace()
    expect(await screen.findByRole("heading", { name: "body" })).not.toBeNull()
    expect(screen.queryByText("name: sample")).toBeNull()
  })

  it("shows a retry action when the library cannot be read", async () => {
    vi.mocked(api.listSkills).mockRejectedValue(new Error("技能状态文件损坏"))
    renderWorkspace()
    expect(await screen.findByText("技能状态文件损坏")).not.toBeNull()
    expect(screen.getByRole("button", { name: "重试" })).not.toBeNull()
  })
})
